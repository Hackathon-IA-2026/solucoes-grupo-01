from datetime import date
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
                "source_sha256": "abc123",
            }
        ]
    )

    windows = ExposureRepository(table).get_historical_windows(
        "CJU_BAOUR", date(2026, 8, 1), date(2026, 8, 31), 72
    )

    assert windows[0]["curtailed_mwh"] == 2319.493016


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
