from datetime import UTC, date, datetime
from decimal import Decimal

from curtailess.data_access import ExposureRepository


class FakeTable:
    def __init__(self, items, pages=None):
        self.items = items
        self.pages = pages
        self.scan_calls = []
        self.query_calls = []

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        values = kwargs["ExpressionAttributeValues"]
        items = [item for item in self.items if item["asset_id"] == values[":asset_id"]]
        if ":period_start" in values:
            items = [
                item
                for item in items
                if values[":period_start"] <= item["period"] <= values[":period_end"]
            ]
        items.sort(key=lambda item: item["period"], reverse=not kwargs["ScanIndexForward"])
        return {"Items": items}

    def get_item(self, **kwargs):
        key = kwargs["Key"]
        item = next(
            (
                item
                for item in self.items
                if item["asset_id"] == key["asset_id"] and item["period"] == key["period"]
            ),
            None,
        )
        return {"Item": item} if item is not None else {}

    def scan(self, **kwargs):
        self.scan_calls.append(kwargs)
        if self.pages is None:
            return {"Items": self.items}
        index = int(kwargs.get("ExclusiveStartKey", {}).get("page", 0))
        response = {"Items": self.pages[index]}
        if index + 1 < len(self.pages):
            response["LastEvaluatedKey"] = {"page": index + 1}
        return response


def test_list_assets_uses_latest_monthly_materialization_per_asset() -> None:
    table = FakeTable(
        [
            {
                "asset_id": "CJU_A",
                "period": "2026-07",
                "asset_name": "Conj. Antigo",
                "point_id": "POINT-A",
                "point_name": "Ponto A",
                "state": "BA",
            },
            {
                "asset_id": "CJU_A",
                "period": "2026-08",
                "asset_name": "Conj. Atual",
                "point_id": "POINT-A",
                "point_name": "Ponto A",
                "state": "BA",
            },
            {
                "asset_id": "CJU_B",
                "period": "2026-08#WINDOW#2026-08-01T00:00:00",
                "asset_name": "Conj. B",
                "point_id": "POINT-B",
                "point_name": "Ponto B",
                "state": "RN",
            },
            {
                "asset_id": "CJU_B",
                "period": "2026-08",
                "asset_name": "Conj. B",
                "point_id": "POINT-B",
                "point_name": "Ponto B",
                "state": "RN",
                "curtailed_mwh": Decimal("10.5"),
            },
        ]
    )

    assets = ExposureRepository(table).list_assets()

    assert assets == [
        {
            "asset_id": "CJU_A",
            "asset_name": "Conj. Atual",
            "point_id": "POINT-A",
            "point_name": "Ponto A",
            "state": "BA",
            "period": "2026-08",
        },
        {
            "asset_id": "CJU_B",
            "asset_name": "Conj. B",
            "point_id": "POINT-B",
            "point_name": "Ponto B",
            "state": "RN",
            "period": "2026-08",
            "curtailed_mwh": Decimal("10.5"),
        },
    ]


def test_get_exposure_sums_overlapping_materialized_months() -> None:
    table = FakeTable(
        [
            {
                "asset_id": "CJU_A",
                "period": "2026-07",
                "period_start": "2026-07-01T00:00:00",
                "period_end": "2026-07-31T23:30:00",
                "curtailed_mwh": Decimal("10.25"),
                "source_sha256": "hash-jul",
            },
            {
                "asset_id": "CJU_A",
                "period": "2026-08",
                "period_start": "2026-08-01T00:00:00",
                "period_end": "2026-08-31T23:30:00",
                "curtailed_mwh": Decimal("20.75"),
                "source_sha256": "hash-aug",
            },
            {
                "asset_id": "CJU_A",
                "period": "2026-09",
                "period_start": "2026-09-01T00:00:00",
                "period_end": "2026-09-30T23:30:00",
                "curtailed_mwh": Decimal("99"),
                "source_sha256": "hash-sep",
            },
        ]
    )

    exposure = ExposureRepository(table).get_exposure("CJU_A", date(2026, 7, 1), date(2026, 8, 31))

    assert exposure["curtailed_mwh"] == Decimal("31.00")
    assert exposure["periods"] == ["2026-07", "2026-08"]
    assert exposure["source_sha256s"] == ["hash-jul", "hash-aug"]
    assert len(table.query_calls) == 1
    assert table.scan_calls == []


def test_historical_windows_supports_dynamodb_decimal_interval_count() -> None:
    table = FakeTable(
        [
            {
                "asset_id": "CJU_BAOUR",
                "period": "2026-08",
                "asset_name": "Conj. Ourolândia II",
                "point_id": "BAOUR-500-A",
                "period_start": "2026-08-01T00:00:00",
                "period_end": "2026-08-31T23:30:00",
                "interval_count": Decimal("1488"),
                "limited_interval_count": Decimal("296"),
                "curtailed_mwh": Decimal("23968.0945"),
                "source_key": "raw/ons/2026/08/source.parquet",
                "source_sha256": "abc123",
                "method": "monthly materialization",
            }
        ]
    )

    windows = ExposureRepository(table).get_historical_windows(
        "CJU_BAOUR", date(2026, 8, 1), date(2026, 8, 31), 72
    )

    assert windows[0]["curtailed_mwh"] == 2319.493016
    assert windows[0]["source_key"] == "raw/ons/2026/08/source.parquet"
    assert windows[0]["source_record"] is table.items[0]


def test_scan_paginates_until_evidence_beyond_first_megabyte_page() -> None:
    target = {
        "asset_id": "TARGET",
        "period": "2026-08",
        "period_start": "2026-08-01T00:00:00",
        "period_end": "2026-08-31T23:30:00",
        "curtailed_mwh": Decimal("1"),
        "source_sha256": "f" * 64,
    }
    # The first page models a full 1 MB DynamoDB scan page; the target is only on page 2.
    filler = [
        {"asset_id": f"FILLER-{index}", "period": "2026-08", "payload": "x" * 1024}
        for index in range(1024)
    ]
    table = FakeTable([], pages=[filler, [target]])

    found = ExposureRepository(table).get_provenance("f" * 64)

    assert found is not None
    assert found["asset_id"] == "TARGET"
    assert table.scan_calls == [{}, {"ExclusiveStartKey": {"page": 1}}]


def test_get_asset_uses_partition_query_without_scan() -> None:
    table = FakeTable(
        [
            {"asset_id": "A", "period": "2026-07"},
            {"asset_id": "A", "period": "2026-08"},
            {"asset_id": "B", "period": "2026-09"},
        ]
    )

    found = ExposureRepository(table).get_asset("A")

    assert found == {"asset_id": "A", "period": "2026-08"}
    assert len(table.query_calls) == 1
    assert table.scan_calls == []


def test_point_context_reuses_asset_and_returns_exact_latest_mixed_source_records() -> None:
    wind = {
        "asset_id": "A",
        "period": "2026-08",
        "point_id": "POINT",
        "period_start": "2026-08-01T00:00:00",
        "period_end": "2026-08-31T23:30:00",
        "limited_interval_count": 0,
        "source_key": "dataset/restricao_coff_eolica_tm/wind.parquet",
        "source_sha256": "a" * 64,
    }
    old_solar = {
        **wind,
        "asset_id": "B",
        "period": "2026-07",
        "source_key": "dataset/restricao_coff_fotovoltaica_tm/solar-old.parquet",
        "source_sha256": "c" * 64,
    }
    solar = {
        **old_solar,
        "period": "2026-08",
        "limited_interval_count": 1,
        "source_key": "dataset/restricao_coff_fotovoltaica_tm/solar.parquet",
        "source_sha256": "b" * 64,
    }
    table = FakeTable([], pages=[[wind, old_solar], [solar]])

    context = ExposureRepository(table).get_point_context("A", wind)

    assert context is not None
    assert context["entity_count"] == 2
    assert context["limited_entity_count"] == 1
    assert context["items"] == [wind, solar]
    assert context["source_sha256s"] == ["a" * 64, "b" * 64]
    assert table.query_calls == []
    assert table.scan_calls == [{}, {"ExclusiveStartKey": {"page": 1}}]


def test_source_hash_lookup_batches_one_fully_paginated_scan() -> None:
    first = {
        "asset_id": "A",
        "period": "2026-07",
        "source_sha256": "a" * 64,
    }
    second = {
        "asset_id": "B",
        "period": "2026-08",
        "source_sha256": "b" * 64,
    }
    table = FakeTable([], pages=[[first], [second]])

    found = ExposureRepository(table).get_provenances({"a" * 64, "b" * 64})

    assert set(found) == {"a" * 64, "b" * 64}
    assert table.scan_calls == [{}, {"ExclusiveStartKey": {"page": 1}}]


def test_forecast_selection_uses_latest_publication_for_valid_instant() -> None:
    base = {
        "asset_id": "program:SOL",
        "fact_type": "forecast_program_daily",
        "program_entity_id": "SOL",
        "program_entity_name": "Solar",
        "intervals": [
            {
                "valid_at": "2026-09-27T00:30:00-03:00",
                "forecast_mw": Decimal("10"),
                "programmed_mw": Decimal("9"),
            }
        ],
        "source_key": "older.parquet",
        "source_sha256": "a" * 64,
        "source_fingerprint": "b" * 64,
    }
    newer = {
        **base,
        "period": "forecast#2026-09-27-new",
        "publication_timestamp": "2026-09-27T01:00:00+00:00",
        "source_key": "newer.parquet",
        "source_sha256": "c" * 64,
        "source_fingerprint": "d" * 64,
        "intervals": [{**base["intervals"][0], "forecast_mw": Decimal("12")}],
    }
    older = {
        **base,
        "period": "forecast#2026-09-27-old",
        "publication_timestamp": "2026-09-27T00:00:00+00:00",
    }
    repository = ExposureRepository(FakeTable([newer, older]))

    result = repository.get_forecast("SOL", datetime(2026, 9, 27, 3, 30, tzinfo=UTC))

    assert result["forecast_mw"] == Decimal("12")
    assert result["source_key"] == "newer.parquet"


def test_generation_profile_query_filters_periods() -> None:
    table = FakeTable(
        [
            {
                "asset_id": "A",
                "period": "generation#2026-07",
                "fact_type": "observed_generation_profile",
            },
            {
                "asset_id": "A",
                "period": "generation#2026-08",
                "fact_type": "observed_generation_profile",
            },
            {"asset_id": "A", "period": "2026-08", "fact_type": "constrained_off_monthly"},
        ]
    )

    result = ExposureRepository(table).get_generation_profiles("A", "2026-08", "2026-08")

    assert [item["period"] for item in result] == ["generation#2026-08"]


def test_identity_query_resolves_effective_relationship_and_capacity() -> None:
    capacity = {
        "asset_id": "ceg:CEG-1",
        "period": "identity#capacity#snapshot",
        "active_capacity_mw": Decimal("30"),
    }
    old = {
        "asset_id": "A",
        "period": "identity#relationship#2020-01-01#OLD",
        "fact_type": "asset_group_relationship",
        "ons_group_id": "OLD",
        "ceg": "CEG-1",
        "valid_from": "2020-01-01",
        "valid_to": "2021-12-31",
    }
    current = {
        **old,
        "period": "identity#relationship#2022-01-01#CURRENT",
        "ons_group_id": "CURRENT",
        "valid_from": "2022-01-01",
        "valid_to": None,
    }
    repository = ExposureRepository(FakeTable([capacity, old, current]))

    result = repository.get_identity("A", date(2026, 9, 27))

    assert result["ons_group_id"] == "CURRENT"
    assert result["capacity"]["active_capacity_mw"] == Decimal("30")
