from datetime import date
from decimal import Decimal

from curtailess.data_access import ExposureRepository


class FakeTable:
    def __init__(self, items):
        self.items = items
        self.scan_calls = []

    def scan(self, **kwargs):
        self.scan_calls.append(kwargs)
        return {"Items": self.items}


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
