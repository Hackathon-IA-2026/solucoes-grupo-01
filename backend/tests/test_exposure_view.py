from copy import deepcopy
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import curtailess.exposure_view as exposure_view
from curtailess.exposure_view import (
    APPROVED_ASSET_IDS,
    UnknownExposureAssetError,
    build_exposure_view,
    list_exposure_assets,
    load_forecast_artifact,
    load_plant_catalog,
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


def test_plant_catalog_exposes_exactly_five_individual_plants():
    catalog = load_plant_catalog()

    assert catalog["entity_level"] == "plant"
    identifiers = tuple(plant["asset_id"] for plant in catalog["plants"])
    assert identifiers == APPROVED_ASSET_IDS
    assert len(identifiers) == 5
    assert not any(identifier.startswith("CJU_") for identifier in identifiers)


def test_forecast_artifact_has_exact_plant_cohort_and_horizon():
    artifact = load_forecast_artifact()

    assert {asset["asset_id"] for asset in artifact["assets"]} == set(APPROVED_ASSET_IDS)
    assert all(asset["entity_level"] == "plant" for asset in artifact["assets"])
    assert all(len(asset["forecasts"]) == 60 for asset in artifact["assets"])


def test_local_view_uses_the_plant_history_and_three_critical_windows():
    view = build_exposure_view("RNEM13")

    assert view.asset.asset_id == "RNEM13"
    assert view.asset.entity_level == "plant"
    assert view.asset.technology == "wind"
    assert len(view.forecast_60d.points) == 60
    assert all(point.display_label for point in view.forecast_60d.points)
    assert all(point.expected_curtailed_mwh >= 0 for point in view.forecast_60d.points)
    assert len(view.recurrence.weekdays) == 7
    assert "simulação demonstrativa" in view.limitations[0]
    assert view.narrative.secao_previsao
    windows = view.forecast_60d.critical_windows_72h
    assert len(windows) == 3
    assert all(window.interval_count == 144 for window in windows)
    assert all(window.window_hours == 72.0 for window in windows)
    ordered = sorted(windows, key=lambda window: window.start)
    for previous, following in zip(ordered, ordered[1:], strict=False):
        assert following.start > previous.end


def test_view_exposes_group_ceg_and_allocation_coverage_as_context():
    view = build_exposure_view("RNEM13")

    assert view.asset.ons_group_id == "CJU_RNRDV"
    assert view.asset.ons_group_name == "Rio do Vento"
    assert view.asset.ceg
    assert view.asset.allocation_coverage is not None
    assert view.asset.allocation_coverage.value == 100.0


def test_simulated_telemetry_and_point_context_validate_against_the_schema():
    view = build_exposure_view("RNEM13")

    assert view.simulated_telemetry is not None
    assert view.simulated_telemetry.origin == "SIMULADO"
    assert view.simulated_telemetry.potentially_curtailed_mw >= 0
    assert view.point_context is not None
    assert view.point_context.entity_count == len(view.point_context.simulated_entities)
    assert view.point_context.envelope.slope >= 0
    assert all(entity.origin == "SIMULADO" for entity in view.point_context.simulated_entities)


def test_view_rejects_incoherent_simulated_telemetry_and_point_population(monkeypatch):
    artifact = load_forecast_artifact()
    broken_telemetry = deepcopy(artifact)
    plant = next(asset for asset in broken_telemetry["assets"] if asset["asset_id"] == "RNEM13")
    plant["simulated_telemetry"]["generation_mw"] = (
        plant["simulated_telemetry"]["potential_generation_mw"] + 1
    )
    monkeypatch.setattr(exposure_view, "load_forecast_artifact", lambda: broken_telemetry)
    with pytest.raises(ValueError, match="cannot exceed potential"):
        build_exposure_view("RNEM13")

    broken_context = deepcopy(artifact)
    plant = next(asset for asset in broken_context["assets"] if asset["asset_id"] == "RNEM13")
    plant["point_context"]["entity_count"] += 1
    monkeypatch.setattr(exposure_view, "load_forecast_artifact", lambda: broken_context)
    with pytest.raises(ValueError, match="entity count"):
        build_exposure_view("RNEM13")


def test_no_group_energy_is_attributed_to_the_selected_plant():
    artifact = load_forecast_artifact()
    payload = next(asset for asset in artifact["assets"] if asset["asset_id"] == "RNEM13")
    view = build_exposure_view("RNEM13")

    plant_total = sum(point["expected_curtailed_mwh"] for point in payload["forecasts"])
    assert view.forecast_60d.total_expected_mwh == pytest.approx(plant_total, abs=1e-3)
    assert view.point_context is not None
    assert view.simulated_telemetry is not None
    # The plant is one entity of a larger point: its capacity, mean potential and the energy
    # attributed to it are its own slice, never the aggregate of the connection point.
    assert view.asset.connected_asset_count == view.point_context.entity_count - 1
    assert view.asset.capacity_mw is not None
    assert view.asset.capacity_mw < view.point_context.installed_capacity_mw
    assert (
        view.simulated_telemetry.potential_generation_mw
        < view.point_context.potential_generation_mw
    )
    assert view.observed_impact.total_curtailed_energy.value == pytest.approx(
        payload["history_summary"]["total_curtailed_mwh"]
    )


def test_materialized_history_populates_metrics_and_digest_is_stable():
    first = build_exposure_view("RNEM13", FakeRepository())
    second = build_exposure_view("RNEM13", FakeRepository())

    assert first.input_digest == second.input_digest
    assert first.asset.capacity_mw == 504.8
    assert first.observed_impact.total_curtailed_energy.value == 100
    assert first.observed_impact.characterized_share.value == 100
    assert first.observed_impact.simultaneous_share.value == 25
    assert [point.label for point in first.associated_conditions.reasons] == ["ENE", "CNF"]
    assert first.quality.duplicate_count.value == 2


def test_input_digest_identifies_the_source_provenance(monkeypatch):
    artifact = load_forecast_artifact()
    baseline = build_exposure_view("RNEM13")
    assert len(baseline.input_digest) == 64
    assert baseline.input_digest == build_exposure_view("RNEM13").input_digest

    tampered = {**artifact, "source_sha256": "0" * 64}
    monkeypatch.setattr(exposure_view, "load_forecast_artifact", lambda path=None: tampered)
    assert build_exposure_view("RNEM13").input_digest != baseline.input_digest


def test_catalog_contains_five_plants_in_product_order():
    catalog = list_exposure_assets()

    assert tuple(asset.asset_id for asset in catalog.items) == APPROVED_ASSET_IDS
    assert all(asset.entity_level == "plant" for asset in catalog.items)


def test_generation_group_and_unknown_asset_are_rejected():
    with pytest.raises(UnknownExposureAssetError):
        build_exposure_view("CJU_RNRDV")
    with pytest.raises(UnknownExposureAssetError):
        build_exposure_view("CJU_UNKNOWN")
    with pytest.raises(UnknownExposureAssetError):
        build_exposure_view("UNKNOWN")


def test_exposure_api_serves_catalog_and_coherent_view():
    client = TestClient(app)

    catalog = client.get("/v1/exposure/assets")
    response = client.get("/v1/assets/RNEM13/exposure-view")

    assert catalog.status_code == 200
    assert len(catalog.json()["items"]) == 5
    assert response.status_code == 200
    payload = response.json()
    assert payload["asset"]["asset_id"] == "RNEM13"
    assert payload["asset"]["entity_level"] == "plant"
    assert len(payload["forecast_60d"]["points"]) == 60
    assert len(payload["forecast_60d"]["critical_windows_72h"]) == 3
    assert set(payload["narrative"]) == {
        "secao-ativo",
        "secao-resumo",
        "secao-previsao",
        "secao-razao-origem",
        "secao-recorrencia",
        "secao-qualidade",
    }


def test_exposure_api_returns_404_for_group_and_unknown_asset():
    client = TestClient(app)

    assert client.get("/v1/assets/CJU_RNRDV/exposure-view").status_code == 404
    assert client.get("/v1/assets/UNKNOWN/exposure-view").status_code == 404
