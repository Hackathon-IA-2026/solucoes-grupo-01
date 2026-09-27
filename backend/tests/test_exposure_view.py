from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from curtailess.exposure_view import (
    APPROVED_ASSET_IDS,
    UnknownExposureAssetError,
    build_exposure_view,
    list_exposure_assets,
    load_forecast_artifact,
    load_history_summary,
)
from curtailess.main import app


class FakeRepository:
    def get_asset(self, asset_id):
        return self.get_asset_history(asset_id)[0]

    def get_asset_history(self, asset_id):
        return [
            {
                "asset_id": asset_id,
                "period": "2026-08",
                "period_start": "2026-08-01T00:00:00",
                "period_end": "2026-08-31T23:30:00",
                "curtailed_mwh": Decimal("100"),
                "curtailed_mwh_by_reason_exact": {
                    "ENE": Decimal("75"),
                    "CNF": Decimal("25"),
                },
                "limited_interval_count_by_origin": {
                    "COSR-NE": Decimal("8"),
                    "Agente": Decimal("2"),
                },
                "duplicate_interval_count": 2,
                "interval_count": 1488,
                "null_counts": {"reason": 3},
                "point_id": "RNCMM-500-A",
            }
        ]

    def get_point_context(self, asset_id, asset=None):
        return {"entity_count": 4, "limited_entity_count": 2}

    def get_identity(self, asset_id, as_of):
        return {"capacity": {"capacity_mw": Decimal("504.8")}}


def test_forecast_artifact_has_exact_approved_cohort_and_horizon():
    artifact = load_forecast_artifact()

    assert {asset["asset_id"] for asset in artifact["assets"]} == set(APPROVED_ASSET_IDS)
    assert all(len(asset["forecasts"]) == 60 for asset in artifact["assets"])


def test_local_history_summary_has_exact_approved_cohort():
    summary = load_history_summary()

    assert {asset["asset_id"] for asset in summary["assets"]} == set(APPROVED_ASSET_IDS)


def test_local_view_uses_bundled_public_history_summary():
    view = build_exposure_view("CJU_RNMVS")

    assert view.asset.technology == "solar"
    assert len(view.forecast_60d.points) == 60
    assert view.observed_impact.total_curtailed_energy.value == 266906.552
    assert view.observed_impact.event_day_share.value == 60.79
    assert view.observed_impact.latest_daily_curtailed_energy.value == 342.157
    assert len(view.recurrence.weekdays) == 7
    assert view.quality.coverage.value == 100
    assert view.quality.missing_rate.value == 0
    assert "simulação demonstrativa" in view.limitations[0]
    assert view.narrative.secao_previsao


def test_materialized_history_populates_metrics_and_digest_is_stable():
    first = build_exposure_view("CJU_RNRDV", FakeRepository())
    second = build_exposure_view("CJU_RNRDV", FakeRepository())

    assert first.input_digest == second.input_digest
    assert first.asset.capacity_mw == 504.8
    assert first.observed_impact.total_curtailed_energy.value == 100
    assert first.observed_impact.characterized_share.value == 100
    assert first.observed_impact.simultaneous_share.value == 25
    assert [point.label for point in first.associated_conditions.reasons] == ["ENE", "CNF"]
    assert first.quality.duplicate_count.value == 2


def test_catalog_contains_five_assets_in_product_order():
    catalog = list_exposure_assets()

    assert tuple(asset.asset_id for asset in catalog.items) == APPROVED_ASSET_IDS


def test_unknown_asset_is_rejected_without_cross_asset_fallback():
    with pytest.raises(UnknownExposureAssetError):
        build_exposure_view("CJU_UNKNOWN")


def test_exposure_api_serves_catalog_and_coherent_view():
    client = TestClient(app)

    catalog = client.get("/v1/exposure/assets")
    response = client.get("/v1/assets/CJU_RNRDV/exposure-view")

    assert catalog.status_code == 200
    assert len(catalog.json()["items"]) == 5
    assert response.status_code == 200
    payload = response.json()
    assert payload["asset"]["asset_id"] == "CJU_RNRDV"
    assert len(payload["forecast_60d"]["points"]) == 60
    assert set(payload["narrative"]) == {
        "secao-ativo",
        "secao-resumo",
        "secao-previsao",
        "secao-razao-origem",
        "secao-recorrencia",
        "secao-qualidade",
    }


def test_exposure_api_returns_404_for_unknown_asset():
    response = TestClient(app).get("/v1/assets/CJU_UNKNOWN/exposure-view")

    assert response.status_code == 404
