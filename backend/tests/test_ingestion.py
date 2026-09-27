import json
from datetime import UTC, datetime

import pytest

from curtailess.datasets import get_dataset_spec
from curtailess.ingestion import copy_handler, discover_dataset_objects, discovery_handler


def source_object(key: str, *, size: int = 100, etag: str | None = None) -> dict:
    return {
        "Key": key,
        "Size": size,
        "ETag": f'"{etag or key}"',
        "LastModified": datetime(2026, 9, 1, tzinfo=UTC),
    }


class FakePaginator:
    def __init__(self, owner, pages_by_prefix):
        self.owner = owner
        self.pages_by_prefix = pages_by_prefix

    def paginate(self, **kwargs):
        self.owner.pagination_calls.append(kwargs)
        return self.pages_by_prefix.get(kwargs["Prefix"], [{"Contents": []}])


class FakeS3:
    def __init__(self, pages_by_prefix):
        self.pages_by_prefix = pages_by_prefix
        self.pagination_calls = []

    def get_paginator(self, operation_name):
        assert operation_name == "list_objects_v2"
        return FakePaginator(self, self.pages_by_prefix)

    def list_objects_v2(self, **kwargs):
        raise AssertionError("discovery must use the paginator, not assume one list page")


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


def test_discover_dataset_objects_paginates_through_empty_pages_and_skips_malformed_keys() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    valid_08 = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_08.parquet"
    valid_09 = f"{spec.s3_prefix}RESTRICAO_COFF_EOLICA_2026_09.parquet"
    malformed = f"{spec.s3_prefix}README.parquet"
    s3 = FakeS3(
        {
            spec.s3_prefix: [
                {"Contents": [source_object(valid_09)]},
                {},
                {"Contents": [source_object(malformed), source_object(valid_08)]},
            ]
        }
    )

    objects, malformed_keys = discover_dataset_objects(s3, spec)

    assert [item["period"] for item in objects] == ["2026-08", "2026-09"]
    assert malformed_keys == [malformed]
    assert s3.pagination_calls == [{"Bucket": spec.source_bucket, "Prefix": spec.s3_prefix}]


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


def test_malformed_key_report_is_bounded_and_deterministically_truncated() -> None:
    spec = get_dataset_spec("restricao_coff_eolica_tm")
    malformed = [f"{spec.s3_prefix}invalid-{index}.parquet" for index in range(3)]
    result = discovery_handler(
        {"mode": "incremental"},
        None,
        s3_client=FakeS3(
            {spec.s3_prefix: [{"Contents": [source_object(key) for key in reversed(malformed)]}]}
        ),
        sqs_client=FakeSQS(),
        environment=environment(cap=2),
    )

    assert result["malformed_count"] == 3
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

    def get_object(self, **kwargs):
        assert kwargs == {
            "Bucket": "ons-aws-prod-opendata",
            "Key": "dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet",
        }
        return {"Body": StreamingBody([b"parquet-", b"bytes"])}

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs):
        self.uploads.append(
            {
                "bucket": bucket,
                "key": key,
                "body": fileobj.read(),
                "extra_args": ExtraArgs,
            }
        )

    def put_object(self, **kwargs):
        self.objects.append(kwargs)


class FakeLambda:
    def __init__(self):
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"StatusCode": 202}


def test_copy_handler_preserves_raw_object_and_writes_traceable_manifest() -> None:
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
    assert s3.uploads[0]["key"] == (
        "raw/ons/restricao_coff_eolica_tm/source_year=2026/source_month=09/"
        "RESTRICAO_COFF_EOLICA_2026_09.parquet"
    )
    assert s3.uploads[0]["body"] == b"parquet-bytes"
    assert s3.uploads[0]["extra_args"]["Metadata"]["source-etag"] == "source-etag"
    manifest_write = s3.objects[0]
    assert manifest_write["Key"] == (
        "manifests/restricao_coff_eolica_tm/ingestion_date=2026-09-26/"
        "RESTRICAO_COFF_EOLICA_2026_09.json"
    )
    manifest = json.loads(manifest_write["Body"])
    assert manifest["source_url"].startswith("s3://ons-aws-prod-opendata/")
    assert manifest["sha256"] == (
        "fba56374a33fa9ac89f203b90e6c34687cbd6721bfa94e78af45580a132641e0"
    )
    assert manifest["validation_status"] == "pending"


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
    assert payload["key"].startswith("raw/ons/")
    assert len(payload["sha256"]) == 64
