import base64
import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from botocore.exceptions import ClientError

from curtailess.datasets import get_dataset_spec
from curtailess.ingestion import copy_handler, discover_dataset_objects, discovery_handler
from curtailess.ingestion_state import IngestionLedger, SourceIdentity, source_fingerprint


def source_object(
    key: str,
    *,
    size: int = 100,
    etag: str | None = None,
    last_modified: datetime | None = None,
) -> dict:
    return {
        "Key": key,
        "Size": size,
        "ETag": f'"{etag or key}"',
        "LastModified": last_modified or datetime(2026, 9, 1, tzinfo=UTC),
    }


class FakePaginator:
    def __init__(self, owner, pages_by_prefix):
        self.owner = owner
        self.pages_by_prefix = pages_by_prefix

    def paginate(self, **kwargs):
        self.owner.pagination_calls.append(kwargs)
        start_after = kwargs.get("StartAfter")
        for page in self.pages_by_prefix.get(kwargs["Prefix"], [{"Contents": []}]):
            contents = page.get("Contents", [])
            if start_after is not None:
                contents = [item for item in contents if item["Key"] > start_after]
            self.owner.page_visits += 1
            self.owner.object_visits += len(contents)
            yield {**page, "Contents": contents}


class FakeS3:
    def __init__(self, pages_by_prefix):
        self.pages_by_prefix = pages_by_prefix
        self.pagination_calls = []
        self.boundary_calls = []
        self.page_visits = 0
        self.object_visits = 0

    def get_paginator(self, operation_name):
        assert operation_name == "list_objects_v2"
        return FakePaginator(self, self.pages_by_prefix)

    def list_objects_v2(self, **kwargs):
        self.boundary_calls.append(kwargs)
        key = kwargs["Prefix"]
        matches = [
            item
            for pages in self.pages_by_prefix.values()
            for page in pages
            for item in page.get("Contents", [])
            if item["Key"].startswith(key)
        ]
        return {"Contents": matches[: kwargs["MaxKeys"]]}


class InstrumentedPagedS3:
    """Generate a large lexicographic inventory without retaining it in the fake."""

    def __init__(self, spec, *, total: int, page_size: int = 1_000):
        self.spec = spec
        self.total = total
        self.page_size = page_size
        self.pagination_calls = []
        self.boundary_calls = []
        self.page_visits = 0
        self.object_visits = 0
        self.objects_materialized = 0
        self.returned_ranges = []

    def _key(self, index: int) -> str:
        year, month_index = divmod(index, 12)
        return (
            f"{self.spec.s3_prefix}RESTRICAO_COFF_EOLICA_"
            f"{year + 1:04d}_{month_index + 1:02d}.parquet"
        )

    def _index(self, key: str) -> int:
        stem = key.removesuffix(".parquet")
        year_text, month_text = stem.rsplit("_", 2)[-2:]
        return (int(year_text) - 1) * 12 + int(month_text) - 1

    def get_paginator(self, operation_name):
        assert operation_name == "list_objects_v2"
        return self

    def paginate(self, **kwargs):
        self.pagination_calls.append(kwargs)
        start = self._index(kwargs["StartAfter"]) + 1 if "StartAfter" in kwargs else 0
        requested_page_size = kwargs.get("PaginationConfig", {}).get("PageSize", self.page_size)
        effective_page_size = min(self.page_size, requested_page_size)
        while start < self.total:
            stop = min(start + effective_page_size, self.total)
            contents = [source_object(self._key(index)) for index in range(start, stop)]
            self.page_visits += 1
            self.object_visits += len(contents)
            self.objects_materialized += len(contents)
            self.returned_ranges.append((start, stop))
            yield {"Contents": contents}
            start = stop

    def list_objects_v2(self, **kwargs):
        self.boundary_calls.append(kwargs)
        index = self._index(kwargs["Prefix"])
        contents = [source_object(self._key(index))] if 0 <= index < self.total else []
        return {"Contents": contents}


class FakeSQS:
    def __init__(self):
        self.messages = []

    def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"MessageId": f"message-{len(self.messages)}"}


def environment(*, cap: int = 100) -> dict[str, str]:
    return {
        "INGESTION_QUEUE_URL": "https://sqs.example/ingestion",
        "DISCOVERY_MAX_MESSAGES": str(cap),
    }


def continuation_token(payload: object, *, canonical: bool = True) -> str:
    if canonical:
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    else:
        encoded = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(encoded).decode()


def legacy_environment(*, cap: int = 100) -> dict[str, str]:
    return {
        **environment(cap=cap),
        "SOURCE_BUCKET": "ons-aws-prod-opendata",
        "SOURCE_PREFIX": "dataset/restricao_coff_eolica_tm/",
        "SOURCE_DATASET": "restricao_coff_eolica_tm",
    }


def test_discover_dataset_objects_paginates_through_empty_pages_and_skips_malformed_keys() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    valid_08 = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_08.parquet"
    valid_09 = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    malformed = f"{spec.s3_prefix}README.parquet"
    s3 = FakeS3(
        {
            spec.s3_prefix: [
                {"Contents": [source_object(valid_08), source_object(malformed)]},
                {},
                {"Contents": [source_object(valid_09)]},
            ]
        }
    )

    objects, malformed_keys = discover_dataset_objects(s3, spec)

    assert [item["period"] for item in objects] == ["2026-08", "2026-09"]
    assert malformed_keys == [malformed]
    assert s3.pagination_calls == [{"Bucket": spec.source_bucket, "Prefix": spec.s3_prefix}]


def test_discovery_rejects_nonmonotonic_paginator_pages() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    earlier = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_08.parquet"
    later = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"

    with pytest.raises(ValueError, match="nonmonotonic"):
        discover_dataset_objects(
            FakeS3(
                {
                    spec.s3_prefix: [
                        {"Contents": [source_object(later)]},
                        {"Contents": [source_object(earlier)]},
                    ]
                }
            ),
            spec,
        )


def test_canonical_filename_lexicographic_order_matches_period_order() -> None:
    samples = {
        "restricao_coff_eolica_tm": [
            "RESTRICAO_COFF_EOLICA_2025_12.parquet",
            "RESTRICAO_COFF_EOLICA_2026_01.parquet",
        ],
        "restricao_coff_fotovoltaica_tm": [
            "RESTRICAO_COFF_FOTOVOLTAICA_2025_12.parquet",
            "RESTRICAO_COFF_FOTOVOLTAICA_2026_01.parquet",
        ],
        "programacao_x_previsao": [
            "PROGRAMACAO_X_PREVISAO_2026_01_31.parquet",
            "PROGRAMACAO_X_PREVISAO_2026_02_01.parquet",
        ],
        "geracao_usina_2_ho": [
            "GERACAO_USINA-2_2020.parquet",
            "GERACAO_USINA-2_2021.parquet",
            "GERACAO_USINA-2_2022_01.parquet",
        ],
        "usina_conjunto": ["RELACIONAMENTO_USINA_CONJUNTO.parquet"],
        "capacidade-geracao": ["CAPACIDADE_GERACAO.parquet"],
    }

    for dataset_id, filenames in samples.items():
        spec = get_dataset_spec(dataset_id)
        keys = [f"{spec.s3_prefix}{filename}" for filename in filenames]
        labels = [spec.period_parser(key).label for key in keys]
        assert keys == sorted(keys)
        assert labels == sorted(labels)


def test_discovery_collapses_identical_duplicate_keys_on_the_same_page() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    key = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    duplicate = source_object(key, size=321, etag="same-version")

    objects, malformed_keys = discover_dataset_objects(
        FakeS3({spec.s3_prefix: [{"Contents": [duplicate, duplicate.copy()]}]}), spec
    )

    assert len(objects) == 1
    assert objects[0]["key"] == key
    assert objects[0]["size"] == 321
    assert objects[0]["etag"] == "same-version"
    assert malformed_keys == []


def test_discovery_collapses_cross_page_duplicates_and_selects_newest_metadata() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    key = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    older = datetime(2026, 9, 1, tzinfo=UTC)
    newer = datetime(2026, 9, 2, tzinfo=UTC)

    objects, _ = discover_dataset_objects(
        FakeS3(
            {
                spec.s3_prefix: [
                    {
                        "Contents": [
                            source_object(key, size=100, etag="old-a", last_modified=older),
                            source_object(key, size=101, etag="old-b", last_modified=older),
                        ]
                    },
                    {"Contents": [source_object(key, size=200, etag="new", last_modified=newer)]},
                ]
            }
        ),
        spec,
    )

    assert len(objects) == 1
    assert objects[0]["size"] == 200
    assert objects[0]["etag"] == "new"
    assert objects[0]["last_modified"] == newer.isoformat()


def test_discovery_rejects_conflicting_metadata_at_the_same_latest_timestamp() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    key = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    timestamp = datetime(2026, 9, 2, tzinfo=UTC)
    s3 = FakeS3(
        {
            spec.s3_prefix: [
                {
                    "Contents": [
                        source_object(key, size=100, etag="version-a", last_modified=timestamp),
                        source_object(key, size=200, etag="version-b", last_modified=timestamp),
                    ]
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="conflicting metadata.*RESTRICAO_COFF_EOLICA_2026_09"):
        discover_dataset_objects(s3, spec)


def test_duplicate_straddling_cap_boundary_does_not_create_spurious_continuation() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    keys = [
        f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_{month:02d}.parquet" for month in range(7, 9)
    ]
    pages = {
        spec.s3_prefix: [
            {"Contents": [source_object(keys[0]), source_object(keys[1])]},
            {"Contents": [source_object(keys[1])]},
        ]
    }
    sqs = FakeSQS()

    result = discovery_handler(
        {"mode": "incremental"},
        None,
        s3_client=FakeS3(pages),
        sqs_client=sqs,
        environment=environment(cap=2),
    )

    emitted_keys = [json.loads(call["MessageBody"])["source_key"] for call in sqs.messages]
    assert emitted_keys == keys
    assert result["enqueued"] == 2
    assert result["has_more"] is False
    assert result["continuation"] is None


def test_empty_event_preserves_deployed_single_prefix_latest_object_contract() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    older = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_08.parquet"
    latest = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    s3 = FakeS3(
        {
            spec.s3_prefix: [
                {
                    "Contents": [
                        source_object(latest, last_modified=datetime(2026, 9, 2, tzinfo=UTC)),
                        source_object(older, last_modified=datetime(2026, 9, 1, tzinfo=UTC)),
                    ]
                }
            ]
        }
    )
    sqs = FakeSQS()

    result = discovery_handler(
        {},
        None,
        s3_client=s3,
        sqs_client=sqs,
        environment=legacy_environment(),
    )

    assert s3.pagination_calls == [{"Bucket": "ons-aws-prod-opendata", "Prefix": spec.s3_prefix}]
    assert len(sqs.messages) == 1
    assert json.loads(sqs.messages[0]["MessageBody"]) == {
        "dataset": "restricao_coff_eolica_tm",
        "source_bucket": "ons-aws-prod-opendata",
        "source_key": latest,
        "source_size": 100,
        "source_etag": latest,
        "source_last_modified": "2026-09-02T00:00:00+00:00",
        "source_fingerprint": source_fingerprint(
            SourceIdentity(
                dataset="restricao_coff_eolica_tm",
                source_bucket="ons-aws-prod-opendata",
                source_key=latest,
                source_etag=latest,
                source_size=100,
                source_last_modified="2026-09-02T00:00:00+00:00",
            )
        ),
    }
    assert result == {
        "mode": "incremental",
        "dataset": "restricao_coff_eolica_tm",
        "source_key": latest,
        "message_id": "message-1",
        "enqueued": 1,
        "message_ids": ["message-1"],
        "has_more": False,
        "continuation": None,
        "malformed_count": 0,
        "malformed_keys": [],
        "malformed_keys_truncated": False,
    }


@pytest.mark.parametrize(
    ("object_count", "legacy_values", "legacy_types"),
    [
        (0, (None, None, None), (type(None), type(None), type(None))),
        (1, ("restricao_coff_eolica_tm", "SOURCE_KEY", "message-1"), (str, str, str)),
        (2, (None, None, None), (type(None), type(None), type(None))),
    ],
)
def test_response_preserves_exact_legacy_keys_for_every_discovery_cardinality(
    object_count: int,
    legacy_values: tuple[str | None, str | None, str | None],
    legacy_types: tuple[type, type, type],
) -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    keys = [
        f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_{month:02d}.parquet"
        for month in range(1, object_count + 1)
    ]

    result = discovery_handler(
        {"mode": "incremental"},
        None,
        s3_client=FakeS3({spec.s3_prefix: [{"Contents": [source_object(key) for key in keys]}]}),
        sqs_client=FakeSQS(),
        environment=environment(),
    )

    expected_values = (
        legacy_values[0],
        keys[0] if object_count == 1 else legacy_values[1],
        legacy_values[2],
    )
    actual_values = (result["dataset"], result["source_key"], result["message_id"])
    assert actual_values == expected_values
    assert tuple(type(value) for value in actual_values) == legacy_types
    assert result["enqueued"] == object_count
    assert result["message_ids"] == [f"message-{index}" for index in range(1, object_count + 1)]


def test_incremental_enumerates_enabled_datasets_and_sorts_messages_deterministically() -> None:
    wind = get_dataset_spec("restricao_coff_eolica_tm")
    solar = get_dataset_spec("restricao_coff_fotovoltaica_tm")
    wind_08 = f"{wind.s3_prefix}RESTRICAO_COFF_EOLICA_2026_08.parquet"
    wind_09 = f"{wind.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    solar_09 = f"{solar.s3_prefix}RESTRICAO_COFF_FOTOVOLTAICA_2026_09.parquet"
    s3 = FakeS3(
        {
            wind.s3_prefix: [{"Contents": [source_object(wind_09), source_object(wind_08)]}],
            solar.s3_prefix: [{"Contents": [source_object(solar_09)]}],
        }
    )
    sqs = FakeSQS()

    result = discovery_handler(
        {"mode": "incremental"},
        None,
        s3_client=s3,
        sqs_client=sqs,
        environment=environment(),
    )

    bodies = [json.loads(call["MessageBody"]) for call in sqs.messages]
    assert [(body["dataset"], body["source_period"], body["source_key"]) for body in bodies] == [
        ("restricao_coff_eolica_tm", "2026-08", wind_08),
        ("restricao_coff_eolica_tm", "2026-09", wind_09),
        ("restricao_coff_fotovoltaica_tm", "2026-09", solar_09),
    ]
    assert result["enqueued"] == 3
    assert result["has_more"] is False
    assert result["continuation"] is None
    # Every incremental-enabled registry entry gets its own fully paginated listing.
    assert len(s3.pagination_calls) == 6


def test_backfill_requires_one_dataset_and_applies_inclusive_period_bounds() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    keys = [
        f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_{month:02d}.parquet" for month in range(7, 11)
    ]
    s3 = FakeS3({spec.s3_prefix: [{"Contents": [source_object(key) for key in reversed(keys)]}]})
    sqs = FakeSQS()

    result = discovery_handler(
        {
            "mode": "backfill",
            "dataset": spec.dataset_id,
            "start_period": "2026-08",
            "end_period": "2026-09",
        },
        None,
        s3_client=s3,
        sqs_client=sqs,
        environment=environment(),
    )

    assert [json.loads(call["MessageBody"])["source_period"] for call in sqs.messages] == [
        "2026-08",
        "2026-09",
    ]
    assert result["enqueued"] == 2


@pytest.mark.parametrize(
    ("event", "match"),
    [
        ({"mode": "everything"}, "mode"),
        ({"mode": "incremental", "dataset": "restricao_coff_eolica_tm"}, "incremental"),
        ({"mode": "backfill"}, "dataset"),
        (
            {
                "mode": "backfill",
                "dataset": "missing",
                "start_period": "2026-01",
                "end_period": "2026-02",
            },
            "não registrado",
        ),
        (
            {
                "mode": "backfill",
                "dataset": "usina_conjunto",
                "start_period": "2026-01",
                "end_period": "2026-02",
            },
            "backfill",
        ),
        (
            {"mode": "backfill", "dataset": "restricao_coff_eolica_tm", "start_period": "2026-02"},
            "end_period",
        ),
        (
            {
                "mode": "backfill",
                "dataset": "restricao_coff_eolica_tm",
                "start_period": "2026-03",
                "end_period": "2026-02",
            },
            "bounds",
        ),
        (
            {
                "mode": "backfill",
                "dataset": "restricao_coff_eolica_tm",
                "start_period": "2026-13",
                "end_period": "2026-14",
            },
            "period",
        ),
    ],
)
def test_discovery_rejects_invalid_mode_dataset_and_bounds(event: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        discovery_handler(
            event,
            None,
            s3_client=FakeS3({}),
            sqs_client=FakeSQS(),
            environment=environment(),
        )


def test_malformed_keys_are_reported_without_hiding_valid_objects() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    valid = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    malformed = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_latest.parquet"
    sqs = FakeSQS()

    result = discovery_handler(
        {"mode": "incremental"},
        None,
        s3_client=FakeS3(
            {spec.s3_prefix: [{"Contents": [source_object(malformed), source_object(valid)]}]}
        ),
        sqs_client=sqs,
        environment=environment(),
    )

    assert result["malformed_keys"] == [malformed]
    assert result["malformed_count"] == 1
    assert result["malformed_keys_truncated"] is False
    assert [json.loads(call["MessageBody"])["source_key"] for call in sqs.messages] == [valid]


def test_malformed_key_report_is_bounded_during_large_enumeration() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    malformed = [f"{spec.s3_prefix}invalid-{index:04d}.parquet" for index in range(2_500)]
    pages = [
        {"Contents": [source_object(key) for key in malformed[offset : offset + 1_000]]}
        for offset in range(0, len(malformed), 1_000)
    ]
    result = discovery_handler(
        {"mode": "incremental"},
        None,
        s3_client=FakeS3({spec.s3_prefix: pages}),
        sqs_client=FakeSQS(),
        environment=environment(cap=2),
    )

    assert result["malformed_count"] == 2_500
    assert result["malformed_keys"] == malformed[:2]
    assert result["malformed_keys_truncated"] is True


def test_cap_returns_deterministic_continuation_and_next_invocation_resumes() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    keys = [
        f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_{month:02d}.parquet" for month in range(7, 11)
    ]
    pages = {spec.s3_prefix: [{"Contents": [source_object(key) for key in reversed(keys)]}]}
    first_sqs = FakeSQS()
    first = discovery_handler(
        {"mode": "incremental"},
        None,
        s3_client=FakeS3(pages),
        sqs_client=first_sqs,
        environment=environment(cap=2),
    )

    assert first["enqueued"] == 2
    assert first["has_more"] is True
    assert isinstance(first["continuation"], str)
    assert [json.loads(call["MessageBody"])["source_period"] for call in first_sqs.messages] == [
        "2026-07",
        "2026-08",
    ]

    second_sqs = FakeSQS()
    second = discovery_handler(
        {"mode": "incremental", "continuation": first["continuation"]},
        None,
        s3_client=FakeS3(pages),
        sqs_client=second_sqs,
        environment=environment(cap=2),
    )
    assert second["has_more"] is False
    assert second["continuation"] is None
    assert [json.loads(call["MessageBody"])["source_period"] for call in second_sqs.messages] == [
        "2026-09",
        "2026-10",
    ]


def test_large_inventory_uses_bounded_pages_and_start_after_without_full_rescan() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    s3 = InstrumentedPagedS3(spec, total=100_000)

    first = discovery_handler(
        {
            "mode": "backfill",
            "dataset": spec.dataset_id,
            "start_period": "0001-01",
            "end_period": "9999-12",
        },
        None,
        s3_client=s3,
        sqs_client=FakeSQS(),
        environment=environment(cap=25),
    )
    boundary_key = s3._key(24)
    assert first["enqueued"] == 25
    assert first["has_more"] is True
    assert s3.page_visits == 1
    assert s3.object_visits == 27
    assert s3.objects_materialized == 27
    assert s3.returned_ranges == [(0, 27)]
    assert s3.pagination_calls[0]["PaginationConfig"] == {"PageSize": 27}

    second = discovery_handler(
        {
            "mode": "backfill",
            "dataset": spec.dataset_id,
            "start_period": "0001-01",
            "end_period": "9999-12",
            "continuation": first["continuation"],
        },
        None,
        s3_client=s3,
        sqs_client=FakeSQS(),
        environment=environment(cap=25),
    )

    assert second["enqueued"] == 25
    assert second["has_more"] is True
    assert s3.page_visits == 2
    assert s3.object_visits == 54
    assert s3.objects_materialized == 54
    assert s3.returned_ranges == [(0, 27), (25, 52)]
    assert s3.pagination_calls[1]["StartAfter"] == boundary_key
    assert s3.pagination_calls[1]["PaginationConfig"] == {"PageSize": 27}
    assert s3.boundary_calls == [
        {"Bucket": spec.source_bucket, "Prefix": boundary_key, "MaxKeys": 1}
    ]


def test_continuation_crosses_dataset_boundary_without_relisting_earlier_datasets() -> None:
    wind = get_dataset_spec("restricao_coff_eolica_tm")
    solar = get_dataset_spec("restricao_coff_fotovoltaica_tm")
    wind_key = f"{wind.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    solar_key = f"{solar.s3_prefix}RESTRICAO_COFF_FOTOVOLTAICA_2026_09.parquet"
    pages = {
        wind.s3_prefix: [{"Contents": [source_object(wind_key)]}],
        solar.s3_prefix: [{"Contents": [source_object(solar_key)]}],
    }
    first = discovery_handler(
        {"mode": "incremental"},
        None,
        s3_client=FakeS3(pages),
        sqs_client=FakeSQS(),
        environment=environment(cap=1),
    )
    resumed_s3 = FakeS3(pages)
    resumed_sqs = FakeSQS()

    second = discovery_handler(
        {"mode": "incremental", "continuation": first["continuation"]},
        None,
        s3_client=resumed_s3,
        sqs_client=resumed_sqs,
        environment=environment(cap=1),
    )

    assert [call["Prefix"] for call in resumed_s3.pagination_calls] == [
        wind.s3_prefix,
        solar.s3_prefix,
        get_dataset_spec("usina_conjunto").s3_prefix,
    ]
    assert resumed_s3.pagination_calls[0]["StartAfter"] == wind_key
    assert [json.loads(call["MessageBody"])["source_key"] for call in resumed_sqs.messages] == [
        solar_key
    ]
    assert second["has_more"] is False


def test_resume_boundary_is_stable_when_objects_are_inserted_before_and_after_it() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    original = [
        f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_{month:02d}.parquet" for month in (7, 8, 10)
    ]
    first_sqs = FakeSQS()
    first = discovery_handler(
        {"mode": "incremental"},
        None,
        s3_client=FakeS3(
            {spec.s3_prefix: [{"Contents": [source_object(key) for key in original]}]}
        ),
        sqs_client=first_sqs,
        environment=environment(cap=2),
    )

    inserted_before = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_06.parquet"
    inserted_after = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    changed = [inserted_after, original[2], inserted_before, original[0], original[1]]
    resumed_sqs = FakeSQS()
    resumed = discovery_handler(
        {"mode": "incremental", "continuation": first["continuation"]},
        None,
        s3_client=FakeS3({spec.s3_prefix: [{"Contents": [source_object(key) for key in changed]}]}),
        sqs_client=resumed_sqs,
        environment=environment(cap=2),
    )

    assert [json.loads(call["MessageBody"])["source_period"] for call in first_sqs.messages] == [
        "2026-07",
        "2026-08",
    ]
    assert [json.loads(call["MessageBody"])["source_period"] for call in resumed_sqs.messages] == [
        "2026-09",
        "2026-10",
    ]
    assert resumed["has_more"] is False


def test_resume_rejects_boundary_that_no_longer_exists() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    keys = [
        f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_{month:02d}.parquet" for month in (7, 8, 9)
    ]
    first = discovery_handler(
        {"mode": "incremental"},
        None,
        s3_client=FakeS3({spec.s3_prefix: [{"Contents": [source_object(key) for key in keys]}]}),
        sqs_client=FakeSQS(),
        environment=environment(cap=2),
    )

    with pytest.raises(ValueError, match="invalid continuation"):
        discovery_handler(
            {"mode": "incremental", "continuation": first["continuation"]},
            None,
            s3_client=FakeS3(
                {spec.s3_prefix: [{"Contents": [source_object(keys[0]), source_object(keys[2])]}]}
            ),
            sqs_client=FakeSQS(),
            environment=environment(cap=2),
        )


def test_resume_rejects_forged_high_boundary_instead_of_silently_skipping_work() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    key = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    forged = continuation_token(
        {
            "context": {"mode": "incremental"},
            "cursor": [spec.dataset_id, "9999-12", "forged-key"],
            "version": 1,
        }
    )

    with pytest.raises(ValueError, match="invalid continuation"):
        discovery_handler(
            {"mode": "incremental", "continuation": forged},
            None,
            s3_client=FakeS3({spec.s3_prefix: [{"Contents": [source_object(key)]}]}),
            sqs_client=FakeSQS(),
            environment=environment(),
        )


@pytest.mark.parametrize(
    "cursor",
    [-1, True, 1.5, 10**100, ["dataset", "period", False]],
)
def test_resume_rejects_wrong_cursor_types(cursor: object) -> None:
    token = continuation_token({"context": {"mode": "incremental"}, "cursor": cursor, "version": 1})
    with pytest.raises(ValueError, match="invalid continuation"):
        discovery_handler(
            {"mode": "incremental", "continuation": token},
            None,
            s3_client=FakeS3({}),
            sqs_client=FakeSQS(),
            environment=environment(),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "context": {"mode": "incremental"},
            "cursor": ["dataset", "period", "key"],
            "version": 2,
        },
        {
            "context": {"mode": "incremental"},
            "cursor": ["dataset", "period", "key"],
            "version": 1,
            "unexpected": "field",
        },
    ],
)
def test_resume_rejects_unknown_version_and_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="invalid continuation"):
        discovery_handler(
            {"mode": "incremental", "continuation": continuation_token(payload)},
            None,
            s3_client=FakeS3({}),
            sqs_client=FakeSQS(),
            environment=environment(),
        )


@pytest.mark.parametrize(
    "token",
    [
        "not-base64!",
        base64.urlsafe_b64encode(b"not-json").decode(),
        "A" * 5_000,
        continuation_token(
            {
                "context": {"mode": "incremental"},
                "cursor": ["dataset", "period", "key"],
                "version": 1,
            }
        )
        + "=",
        continuation_token(
            {
                "context": {"mode": "incremental"},
                "cursor": ["dataset", "period", "key"],
                "version": 1,
            },
            canonical=False,
        ),
    ],
)
def test_resume_rejects_malformed_oversized_and_noncanonical_tokens(token: str) -> None:
    with pytest.raises(ValueError, match="invalid continuation"):
        discovery_handler(
            {"mode": "incremental", "continuation": token},
            None,
            s3_client=FakeS3({}),
            sqs_client=FakeSQS(),
            environment=environment(),
        )


def test_resume_rejects_token_from_another_request_scope() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    keys = [
        f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_{month:02d}.parquet" for month in (7, 8, 9)
    ]
    pages = {spec.s3_prefix: [{"Contents": [source_object(key) for key in keys]}]}
    first = discovery_handler(
        {
            "mode": "backfill",
            "dataset": spec.dataset_id,
            "start_period": "2026-07",
            "end_period": "2026-09",
        },
        None,
        s3_client=FakeS3(pages),
        sqs_client=FakeSQS(),
        environment=environment(cap=2),
    )

    with pytest.raises(ValueError, match="invalid continuation"):
        discovery_handler(
            {
                "mode": "backfill",
                "dataset": spec.dataset_id,
                "start_period": "2026-08",
                "end_period": "2026-09",
                "continuation": first["continuation"],
            },
            None,
            s3_client=FakeS3(pages),
            sqs_client=FakeSQS(),
            environment=environment(cap=2),
        )


class StreamingBody:
    def __init__(self, chunks):
        self.chunks = chunks

    def iter_chunks(self, chunk_size):
        assert chunk_size > 0
        yield from self.chunks


class FakeDestinationS3:
    def __init__(self):
        self.uploads = []
        self.objects = []
        self.head_calls = []
        self.destination_objects = {}

    def get_object(self, **kwargs):
        assert kwargs == {
            "Bucket": "ons-aws-prod-opendata",
            "Key": "dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet",
            "IfMatch": '"source-etag"',
        }
        return {
            "Body": StreamingBody([b"parquet-", b"bytes"]),
            "ContentLength": 13,
            "ETag": '"source-etag"',
            "LastModified": datetime(2026, 9, 3, tzinfo=UTC),
        }

    def head_object(self, **kwargs):
        self.head_calls.append(kwargs)
        item = self.destination_objects.get((kwargs["Bucket"], kwargs["Key"]))
        if item is None:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "not found"}},
                "HeadObject",
            )
        return deepcopy(item)

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs):
        body = fileobj.read()
        self.uploads.append(
            {
                "bucket": bucket,
                "key": key,
                "body": body,
                "extra_args": ExtraArgs,
            }
        )
        self.destination_objects[(bucket, key)] = {
            "ContentLength": len(body),
            "ContentType": ExtraArgs["ContentType"],
            "Metadata": deepcopy(ExtraArgs["Metadata"]),
        }

    def put_object(self, **kwargs):
        self.objects.append(kwargs)


class FakeLambda:
    def __init__(self):
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"StatusCode": 202}


def test_copy_handler_writes_verified_content_addressed_raw_object() -> None:
    s3 = FakeDestinationS3()
    event = {
        "Records": [
            {
                "messageId": "message-1",
                "body": json.dumps(
                    {
                        "dataset": "restricao_coff_eolica_tm",
                        "source_bucket": "ons-aws-prod-opendata",
                        "source_key": (
                            "dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet"
                        ),
                        "source_size": 13,
                        "source_etag": "source-etag",
                        "source_last_modified": "2026-09-03T00:00:00+00:00",
                    }
                ),
            }
        ]
    }

    result = copy_handler(
        event,
        None,
        s3_client=s3,
        environment={"DATA_BUCKET": "curtailess-data"},
        now=lambda: datetime(2026, 9, 26, 18, 30, tzinfo=UTC),
    )

    assert result == {"batchItemFailures": []}
    digest = "fba56374a33fa9ac89f203b90e6c34687cbd6721bfa94e78af45580a132641e0"
    assert s3.uploads[0]["key"] == (
        f"raw/ons/restricao_coff_eolica_tm/source_year=2026/source_month=09/sha256={digest[:2]}/{digest}.parquet"
    )
    assert s3.uploads[0]["body"] == b"parquet-bytes"
    assert s3.uploads[0]["extra_args"]["Metadata"] == {
        "content-length": "13",
        "sha256": digest,
    }
    assert len(s3.head_calls) == 2
    assert s3.objects == []


def test_copy_handler_reuses_existing_verified_content_addressed_object() -> None:
    digest = "fba56374a33fa9ac89f203b90e6c34687cbd6721bfa94e78af45580a132641e0"
    key = (
        "raw/ons/restricao_coff_eolica_tm/source_year=2026/source_month=09/"
        f"sha256={digest[:2]}/{digest}.parquet"
    )
    s3 = FakeDestinationS3()
    s3.destination_objects[("curtailess-data", key)] = {
        "ContentLength": 13,
        "ContentType": "application/vnd.apache.parquet",
        "Metadata": {"content-length": "13", "sha256": digest},
    }

    result = copy_handler(
        {"Records": [{"messageId": "reuse", "body": json.dumps(copy_message())}]},
        RequestContext("reuse"),
        s3_client=s3,
        environment={"DATA_BUCKET": "curtailess-data"},
        now=lambda: datetime(2026, 9, 27, tzinfo=UTC),
    )

    assert result == {"batchItemFailures": []}
    assert s3.uploads == []
    assert s3.head_calls == [{"Bucket": "curtailess-data", "Key": key}]
    assert s3.objects == []


def test_copy_handler_rejects_existing_object_with_mismatched_sha_metadata() -> None:
    digest = "fba56374a33fa9ac89f203b90e6c34687cbd6721bfa94e78af45580a132641e0"
    key = (
        "raw/ons/restricao_coff_eolica_tm/source_year=2026/source_month=09/"
        f"sha256={digest[:2]}/{digest}.parquet"
    )
    s3 = FakeDestinationS3()
    s3.destination_objects[("curtailess-data", key)] = {
        "ContentLength": 13,
        "ContentType": "application/vnd.apache.parquet",
        "Metadata": {"content-length": "13", "sha256": "0" * 64},
    }
    table = MemoryLedgerTable()
    ledger = IngestionLedger(table)
    message = copy_message()

    result = copy_handler(
        {"Records": [{"messageId": "mismatch", "body": json.dumps(message)}]},
        RequestContext("mismatch"),
        s3_client=s3,
        environment={"DATA_BUCKET": "curtailess-data"},
        now=lambda: datetime(2026, 9, 27, tzinfo=UTC),
        ledger=ledger,
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "mismatch"}]}
    assert s3.uploads == []
    assert table.items[message["source_fingerprint"]]["state"] == "FAILED"
    assert (
        "mismatched SHA-256 metadata" in table.items[message["source_fingerprint"]]["failure_error"]
    )


def test_copy_handler_rejects_downloaded_size_mismatch_before_upload() -> None:
    message = copy_message()
    message["source_size"] = 12
    message["source_fingerprint"] = source_fingerprint(
        SourceIdentity(
            dataset=message["dataset"],
            source_bucket=message["source_bucket"],
            source_key=message["source_key"],
            source_etag=message["source_etag"],
            source_size=message["source_size"],
            source_last_modified=message["source_last_modified"],
        )
    )
    s3 = FakeDestinationS3()

    result = copy_handler(
        {"Records": [{"messageId": "short", "body": json.dumps(message)}]},
        RequestContext("short"),
        s3_client=s3,
        environment={"DATA_BUCKET": "curtailess-data"},
        now=lambda: datetime(2026, 9, 27, tzinfo=UTC),
    )

    assert result == {"batchItemFailures": [{"itemIdentifier": "short"}]}
    assert s3.uploads == []
    assert s3.head_calls == []


def test_copy_handler_starts_materialization_with_provenance() -> None:
    s3 = FakeDestinationS3()
    lambda_client = FakeLambda()
    event = {
        "Records": [
            {
                "messageId": "message-2",
                "body": json.dumps(
                    {
                        "dataset": "restricao_coff_eolica_tm",
                        "source_bucket": "ons-aws-prod-opendata",
                        "source_key": (
                            "dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet"
                        ),
                        "source_size": 13,
                        "source_etag": "source-etag",
                        "source_last_modified": "2026-09-03T00:00:00+00:00",
                    }
                ),
            }
        ]
    }
    result = copy_handler(
        event,
        None,
        s3_client=s3,
        lambda_client=lambda_client,
        environment={
            "DATA_BUCKET": "curtailess-data",
            "MATERIALIZATION_FUNCTION": "materialize-function",
        },
        now=lambda: datetime(2026, 9, 26, 18, 30, tzinfo=UTC),
    )
    assert result == {"batchItemFailures": []}
    call = lambda_client.calls[0]
    assert call["FunctionName"] == "materialize-function"
    assert call["InvocationType"] == "Event"
    payload = json.loads(call["Payload"])
    assert payload["bucket"] == "curtailess-data"
    assert payload["key"] == (
        f"raw/ons/restricao_coff_eolica_tm/source_year=2026/source_month=09/sha256={payload['sha256'][:2]}/"
        f"{payload['sha256']}.parquet"
    )
    assert len(payload["sha256"]) == 64
    assert payload["manifest_key"].endswith(
        f"source_fingerprint={payload['source_fingerprint']}.json"
    )
    assert s3.objects == []


class MemoryLedgerTable:
    def __init__(self):
        self.items = {}

    def get_item(self, **kwargs):
        item = self.items.get(kwargs["Key"]["source_fingerprint"])
        return {"Item": deepcopy(item)} if item is not None else {}

    def put_item(self, **kwargs):
        item = deepcopy(kwargs["Item"])
        fingerprint = item["source_fingerprint"]
        existing = self.items.get(fingerprint)
        condition = kwargs["ConditionExpression"]
        conflict = condition == "attribute_not_exists(source_fingerprint)" and existing is not None
        if condition == "#version = :expected_version":
            expected = kwargs["ExpressionAttributeValues"][":expected_version"]
            conflict = existing is None or existing["version"] != expected
        if conflict:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}},
                "PutItem",
            )
        self.items[fingerprint] = item
        return {}


class RequestContext:
    def __init__(self, request_id):
        self.aws_request_id = request_id


class FailSecondSQS(FakeSQS):
    def send_message(self, **kwargs):
        if len(self.messages) == 1:
            raise RuntimeError("SQS unavailable")
        return super().send_message(**kwargs)


class FailFirstDownloadS3(FakeDestinationS3):
    def __init__(self):
        super().__init__()
        self.failures_remaining = 1

    def get_object(self, **kwargs):
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("download failed")
        return super().get_object(**kwargs)


def copy_message() -> dict:
    message = {
        "dataset": "restricao_coff_eolica_tm",
        "source_bucket": "ons-aws-prod-opendata",
        "source_key": ("dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet"),
        "source_size": 13,
        "source_etag": "source-etag",
        "source_last_modified": "2026-09-03T00:00:00+00:00",
    }
    message["source_fingerprint"] = source_fingerprint(
        SourceIdentity(
            dataset=message["dataset"],
            source_bucket=message["source_bucket"],
            source_key=message["source_key"],
            source_etag=message["source_etag"],
            source_size=message["source_size"],
            source_last_modified=message["source_last_modified"],
        )
    )
    return message


def test_discovery_ledger_suppresses_replayed_completed_dispatch() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    key = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    pages = {spec.s3_prefix: [{"Contents": [source_object(key)]}]}
    ledger = IngestionLedger(MemoryLedgerTable())
    first_sqs = FakeSQS()
    event = {
        "mode": "backfill",
        "dataset": spec.dataset_id,
        "start_period": "2026-09",
        "end_period": "2026-09",
    }
    first = discovery_handler(
        event,
        RequestContext("first"),
        s3_client=FakeS3(pages),
        sqs_client=first_sqs,
        environment=environment(),
        ledger=ledger,
        now=lambda: datetime(2026, 9, 27, tzinfo=UTC),
    )
    replay = discovery_handler(
        event,
        RequestContext("replay"),
        s3_client=FakeS3(pages),
        sqs_client=FakeSQS(),
        environment=environment(),
        ledger=ledger,
        now=lambda: datetime(2026, 9, 27, 0, 1, tzinfo=UTC),
    )
    assert first["enqueued"] == 1
    assert replay["enqueued"] == 0


def test_partial_discovery_failure_retries_only_unsent_fingerprint() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    keys = [f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_{month:02d}.parquet" for month in (8, 9)]
    pages = {spec.s3_prefix: [{"Contents": [source_object(key) for key in keys]}]}
    ledger = IngestionLedger(MemoryLedgerTable())
    event = {
        "mode": "backfill",
        "dataset": spec.dataset_id,
        "start_period": "2026-08",
        "end_period": "2026-09",
    }
    failing_sqs = FailSecondSQS()
    with pytest.raises(RuntimeError, match="SQS unavailable"):
        discovery_handler(
            event,
            RequestContext("first"),
            s3_client=FakeS3(pages),
            sqs_client=failing_sqs,
            environment=environment(),
            ledger=ledger,
            now=lambda: datetime(2026, 9, 27, tzinfo=UTC),
        )
    retry_sqs = FakeSQS()
    retried = discovery_handler(
        event,
        RequestContext("retry"),
        s3_client=FakeS3(pages),
        sqs_client=retry_sqs,
        environment=environment(),
        ledger=ledger,
        now=lambda: datetime(2026, 9, 27, 0, 1, tzinfo=UTC),
    )
    assert retried["enqueued"] == 1
    assert json.loads(retry_sqs.messages[0]["MessageBody"])["source_key"] == keys[1]


def test_duplicate_sqs_delivery_copies_once_with_ledger() -> None:
    table = MemoryLedgerTable()
    ledger = IngestionLedger(table)
    message = copy_message()
    event = {
        "Records": [
            {"messageId": "first", "body": json.dumps(message)},
            {"messageId": "duplicate", "body": json.dumps(message)},
        ]
    }
    s3 = FakeDestinationS3()
    result = copy_handler(
        event,
        RequestContext("copy"),
        s3_client=s3,
        environment={"DATA_BUCKET": "curtailess-data"},
        now=lambda: datetime(2026, 9, 27, tzinfo=UTC),
        ledger=ledger,
    )
    assert result == {"batchItemFailures": []}
    assert len(s3.uploads) == 1
    assert s3.objects == []
    item = table.items[message["source_fingerprint"]]
    assert item["state"] == "COPIED"


def test_failed_copy_is_retried_then_succeeds() -> None:
    table = MemoryLedgerTable()
    ledger = IngestionLedger(table)
    message = copy_message()
    s3 = FailFirstDownloadS3()
    first = copy_handler(
        {"Records": [{"messageId": "first", "body": json.dumps(message)}]},
        RequestContext("copy-1"),
        s3_client=s3,
        environment={"DATA_BUCKET": "curtailess-data"},
        now=lambda: datetime(2026, 9, 27, tzinfo=UTC),
        ledger=ledger,
    )
    assert first == {"batchItemFailures": [{"itemIdentifier": "first"}]}
    assert table.items[message["source_fingerprint"]]["state"] == "FAILED"
    second = copy_handler(
        {"Records": [{"messageId": "second", "body": json.dumps(message)}]},
        RequestContext("copy-2"),
        s3_client=s3,
        environment={"DATA_BUCKET": "curtailess-data"},
        now=lambda: datetime(2026, 9, 27, 0, 1, tzinfo=UTC),
        ledger=ledger,
    )
    assert second == {"batchItemFailures": []}
    assert table.items[message["source_fingerprint"]]["state"] == "COPIED"
    assert len(s3.uploads) == 1


def test_copy_rejects_mismatched_fingerprint_before_ledger_write() -> None:
    table = MemoryLedgerTable()
    ledger = IngestionLedger(table)
    message = copy_message()
    message["source_fingerprint"] = "0" * 64
    s3 = FakeDestinationS3()
    result = copy_handler(
        {"Records": [{"messageId": "bad", "body": json.dumps(message)}]},
        RequestContext("copy"),
        s3_client=s3,
        environment={"DATA_BUCKET": "curtailess-data"},
        now=lambda: datetime(2026, 9, 27, tzinfo=UTC),
        ledger=ledger,
    )
    assert result == {"batchItemFailures": [{"itemIdentifier": "bad"}]}
    assert table.items == {}
    assert s3.uploads == []


def test_active_copy_lease_suppresses_duplicate_delivery_until_expiry() -> None:
    table = MemoryLedgerTable()
    ledger = IngestionLedger(table)
    message = copy_message()
    identity = SourceIdentity(
        dataset=message["dataset"],
        source_bucket=message["source_bucket"],
        source_key=message["source_key"],
        source_etag=message["source_etag"],
        source_size=message["source_size"],
        source_last_modified=message["source_last_modified"],
    )
    ledger.ensure_discovered(identity, now=datetime(2026, 9, 27, tzinfo=UTC))
    ledger.claim_copy(
        message["source_fingerprint"],
        owner="other",
        now=datetime(2026, 9, 27, tzinfo=UTC),
        lease_seconds=300,
    )
    s3 = FakeDestinationS3()
    result = copy_handler(
        {"Records": [{"messageId": "duplicate", "body": json.dumps(message)}]},
        RequestContext("copy"),
        s3_client=s3,
        environment={"DATA_BUCKET": "curtailess-data"},
        now=lambda: datetime(2026, 9, 27, 0, 1, tzinfo=UTC),
        ledger=ledger,
    )
    assert result == {"batchItemFailures": []}
    assert s3.uploads == []
