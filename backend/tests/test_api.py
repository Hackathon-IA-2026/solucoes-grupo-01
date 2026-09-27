import hashlib
import json

from fastapi.testclient import TestClient

import curtailess.main as main
from curtailess.main import app

client = TestClient(app)


def client_provenance(field_name: str) -> dict:
    return {
        "evidence_id": f"client:{field_name}:v1",
        "field_name": field_name,
        "origin": "CLIENTE_INFORMADO",
        "source_uri": f"client://scenario/{field_name}",
        "source_key": None,
        "source_sha256": None,
        "source_sha256s": [],
        "observed_at": None,
        "effective_at": "2026-08-01T00:00:00Z",
        "valid_from": None,
        "valid_to": None,
        "method_version": "client_input_v1",
        "limitations": ["Valor informado pelo cliente para o cenário."],
    }


def energy_price_payload(value: float = 250) -> dict:
    return {
        "value": value,
        "unit": "BRL/MWh",
        "source": "client_scenario",
        "value_status": "informado",
        "origin": "CLIENTE_INFORMADO",
        "provenance": client_provenance("energy_price"),
    }


def bess_input_provenance() -> dict:
    return {
        field_name: client_provenance(field_name)
        for field_name in (
            "power_mw",
            "energy_mwh",
            "capex_brl",
            "annualized_cost_brl",
            "round_trip_efficiency",
            "cycles_per_year",
            "energy_price_brl_mwh",
        )
    }


MATERIALIZED_ITEM = {
    "asset_id": "CJU_BAOUR",
    "period": "2026-08",
    "asset_name": "Conj. Ourolândia II",
    "point_id": "BAOUR-500-A",
    "point_name": "OUROLANDIA II500kVA",
    "state": "BA",
    "period_start": "2026-08-01T00:00:00",
    "period_end": "2026-08-31T23:30:00",
    "curtailed_mwh": 23968.0945,
    "source_key": "raw/ons/restricao_coff_eolica_tm/source_year=2026/source_month=08/file.parquet",
    "source_sha256": "45fa63e984245c17862bf8cc028437311ee7e1ca8a7cd0a6550226432ccbe2fa",
    "method": "sum(apurada * 0.5) when val_geracaolimitada is not null",
}


def test_api_info() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "CurtaiLess API",
        "version": "0.1.0",
        "environment": "local",
        "docs": "/docs",
    }


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "CurtaiLess API",
        "version": "0.1.0",
        "environment": "local",
    }


def test_cors_preflight() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_list_assets_returns_materialized_ons_assets(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "list_assets", lambda: [MATERIALIZED_ITEM])

    response = client.get("/v1/assets")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "asset_id": "CJU_BAOUR",
                "name": "Conj. Ourolândia II",
                "technology": "wind",
                "capacity_mw": None,
                "capacity_provenance": None,
                "ons_group": "CJU_BAOUR",
                "connection_point": "BAOUR-500-A",
                "data_mode": "ons_materialized",
            }
        ]
    }


def test_get_asset_returns_materialized_ons_asset(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)

    response = client.get("/v1/assets/CJU_BAOUR")

    assert response.status_code == 200
    assert response.json()["asset_id"] == "CJU_BAOUR"
    assert response.json()["data_mode"] == "ons_materialized"


def test_get_asset_capacity_has_public_field_level_provenance(monkeypatch) -> None:
    capacity_hash = "b" * 64
    item = {
        **MATERIALIZED_ITEM,
        "capacity_mw": 87.5,
        "capacity_source_key": "dataset/capacidade-geracao/CAPACIDADE_GERACAO.parquet",
        "capacity_source_sha256": capacity_hash,
        "capacity_method_version": "ons_capacity_source_v1",
    }
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: item)

    response = client.get("/v1/assets/CJU_BAOUR")

    assert response.status_code == 200
    payload = response.json()
    assert payload["capacity_mw"] == 87.5
    provenance = payload["capacity_provenance"]
    assert provenance["origin"] == "ONS_PUBLICO"
    assert provenance["field_name"] == "capacity_mw"
    assert provenance["source_sha256"] == capacity_hash
    assert provenance["source_key"].endswith("CAPACIDADE_GERACAO.parquet")


def test_get_asset_exposure_returns_materialized_ons_values(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_exposure",
        lambda asset_id, start, end, reason=None: {
            "curtailed_mwh": 23968.0945,
            "periods": ["2026-08"],
            "source_sha256s": [MATERIALIZED_ITEM["source_sha256"]],
            "items": [MATERIALIZED_ITEM],
        },
    )

    response = client.get(
        "/v1/assets/CJU_BAOUR/exposure",
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["perspective_type"] == "historical_observed"
    assert payload["data_mode"] == "ons_materialized"
    assert payload["total_curtailed_energy"]["value"] == 23968.0945
    assert payload["total_curtailed_energy"]["unit"] == "MWh"
    assert payload["total_curtailed_energy"]["value_status"] == "calculado"
    assert payload["total_curtailed_energy"]["origin"] == "PROXY_CALCULADO"
    assert payload["total_curtailed_energy"]["data_version"] == "2026-08"
    evidence = payload["total_curtailed_energy"]
    assert evidence["source"] == "ONS/restricao_coff_eolica_tm"
    assert evidence["provenance_id"].startswith("ev1.")
    assert evidence["provenance_id"] == evidence["provenance"]["evidence_id"]
    assert evidence["provenance"]["field_name"] == "total_curtailed_energy"
    assert evidence["provenance"]["source_sha256s"] == [MATERIALIZED_ITEM["source_sha256"]]
    assert evidence["provenance"]["observed_at"] == "2026-08-31T23:30:00Z"
    assert evidence["provenance"]["effective_at"] == "2026-08-31T23:30:00Z"
    assert evidence["provenance"]["valid_from"] == "2026-08-01T00:00:00Z"
    assert evidence["provenance"]["valid_to"] == "2026-08-31T23:59:59.999999Z"
    assert evidence["provenance"]["method_version"] == "curtailed_energy_sum_v1"
    assert evidence["provenance"]["limitations"]
    assert "materializado" in " ".join(payload["limitations"]).lower()


def test_get_asset_exposure_filters_materialized_reason(monkeypatch) -> None:
    item = {
        **MATERIALIZED_ITEM,
        "curtailed_mwh_by_reason": {"ENE": 120.5, "REL": 80.0, "CNF": 10.0, "NC": 2.0},
    }
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: item)
    monkeypatch.setattr(
        main.repository,
        "get_exposure",
        lambda asset_id, start, end, reason=None: {
            "curtailed_mwh": 120.5,
            "periods": ["2026-08"],
            "source_sha256s": [MATERIALIZED_ITEM["source_sha256"]],
            "items": [item],
        },
    )

    response = client.get(
        "/v1/assets/CJU_BAOUR/exposure",
        params={
            "start": "2026-08-01",
            "end": "2026-08-31",
            "granularity": "period",
            "reason": "ENE",
            "technology": "wind",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reason"] == "ENE"
    assert payload["granularity"] == "period"
    assert payload["total_curtailed_energy"]["value"] == 120.5


def test_get_asset_exposure_rejects_unmaterialized_granularity(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)

    response = client.get(
        "/v1/assets/CJU_BAOUR/exposure",
        params={"start": "2026-08-01", "end": "2026-08-31", "granularity": "hour"},
    )

    assert response.status_code == 422
    assert "granularity=period" in response.json()["detail"]


def test_get_asset_exposure_rejects_inverted_period() -> None:
    response = client.get(
        "/v1/assets/demo-wind-ne-001/exposure",
        params={"start": "2026-09-01", "end": "2026-08-01"},
    )

    assert response.status_code == 422


def test_get_unknown_asset_returns_not_found() -> None:
    response = client.get("/v1/assets/unknown")

    assert response.status_code == 404


def test_get_data_quality_returns_materialized_coverage(monkeypatch) -> None:
    item = {**MATERIALIZED_ITEM, "interval_count": 1488, "limited_interval_count": 296}
    monkeypatch.setattr(main.repository, "get_data_quality", lambda asset_id: item)

    response = client.get("/v1/data-quality/CJU_BAOUR")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["validation_status"] == "valid"
    assert payload["coverage_percent"] == 100.0
    assert payload["observed_interval_count"] == 1488
    assert payload["expected_interval_count"] == 1488
    assert payload["null_count"] is None
    assert payload["duplicate_count"] is None
    assert payload["source_sha256"] == MATERIALIZED_ITEM["source_sha256"]
    assert "não materializadas" in " ".join(payload["limitations"]).lower()


def test_get_provenance_returns_source_lineage(monkeypatch) -> None:
    monkeypatch.setattr(
        main.repository,
        "get_provenance",
        lambda source_sha256: MATERIALIZED_ITEM,
    )

    evidence_id = main.build_evidence_id(
        MATERIALIZED_ITEM["source_sha256"],
        "total_curtailed_energy",
        "curtailed_energy_sum_v1",
        "CJU_BAOUR:2026-08-01:2026-08-31:all",
    )
    response = client.get(f"/v1/provenances/{evidence_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provenance_id"] == evidence_id
    assert payload["classification"] == "calculado"
    assert payload["source"] == "ONS/restricao_coff_eolica_tm"
    assert payload["source_key"] == MATERIALIZED_ITEM["source_key"]
    assert payload["source_sha256"] == MATERIALIZED_ITEM["source_sha256"]
    assert payload["source_sha256s"] == [MATERIALIZED_ITEM["source_sha256"]]
    assert payload["method"] == MATERIALIZED_ITEM["method"]
    assert payload["origin"] == "PROXY_CALCULADO"
    assert payload["evidence_id"] == payload["provenance_id"]
    assert payload["method_version"] == "curtailed_energy_sum_v1"
    assert payload["field_name"] == "total_curtailed_energy"
    assert payload["provenance"]["evidence_id"] == evidence_id
    assert payload["valid_from"] == "2026-08-01T00:00:00Z"
    assert payload["valid_to"] == "2026-08-31T23:30:00Z"
    assert payload["asset_ids"] == ["CJU_BAOUR"]


def test_get_point_context_returns_materialized_anonymized_aggregates(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_point_context",
        lambda asset_id: {
            "connection_point": "point-" + MATERIALIZED_ITEM["source_sha256"][:12],
            "entity_count": 3,
            "limited_entity_count": 2,
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "data_version": "2026-08",
            "source_sha256s": [MATERIALIZED_ITEM["source_sha256"]],
        },
    )

    response = client.get("/v1/assets/CJU_BAOUR/point-context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["data_mode"] == "ons_materialized"
    assert payload["connection_point"].startswith("point-")
    assert payload["anonymized_entity_count"]["value"] == 3
    assert payload["anonymized_entity_count"]["unit"] == "entities"
    assert payload["simultaneity_rate"]["value"] == 66.666667
    assert payload["simultaneity_rate"]["unit"] == "%"
    assert payload["physical_limit_available"] is False
    entity_evidence = payload["anonymized_entity_count"]
    rate_evidence = payload["simultaneity_rate"]
    assert entity_evidence["provenance_id"] != rate_evidence["provenance_id"]
    assert entity_evidence["provenance"]["field_name"] == "anonymized_entity_count"
    assert rate_evidence["provenance"]["field_name"] == "simultaneity_rate"
    monkeypatch.setattr(main.repository, "get_provenance", lambda source_sha256: MATERIALIZED_ITEM)
    assert client.get(f"/v1/provenances/{entity_evidence['provenance_id']}").status_code == 200
    assert client.get(f"/v1/provenances/{rate_evidence['provenance_id']}").status_code == 200
    assert "nomes" in " ".join(payload["limitations"]).lower()
    assert "entities" not in payload


def test_get_historical_windows_uses_materialized_monthly_signal(monkeypatch) -> None:
    item = {**MATERIALIZED_ITEM, "interval_count": 1488}
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: item)
    monkeypatch.setattr(
        main.repository,
        "get_historical_windows",
        lambda asset_id, start, end, duration_hours, reason=None: [
            {
                "start": main.datetime(2026, 8, 1, tzinfo=main.UTC),
                "end": main.datetime(2026, 8, 4, tzinfo=main.UTC),
                "curtailed_mwh": 2319.493016,
                "period": "2026-08",
                "source_sha256": item["source_sha256"],
                "method": "monthly_observed_rate_prorated_to_window_v1",
            }
        ],
    )

    response = client.get(
        "/v1/assets/CJU_BAOUR/windows",
        params={
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["perspective_type"] == "historical_seasonal"
    assert payload["validation_status"] == "historical_signal"
    assert payload["data_mode"] == "ons_materialized"
    assert payload["duration_hours"] == 72
    assert len(payload["windows"]) == 1
    assert payload["windows"][0]["expected_curtailed_energy"]["value"] == 2319.493016
    assert payload["windows"][0]["expected_curtailed_energy"]["value_status"] == "calculado"
    assert "não é previsão" in " ".join(payload["limitations"]).lower()


def test_get_asset_windows_passes_reason_filter(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    captured = {}

    def fake_windows(asset_id, start, end, duration_hours, reason=None):
        captured["reason"] = reason
        return [
            {
                "start": main.datetime(2026, 8, 1, tzinfo=main.UTC),
                "end": main.datetime(2026, 8, 4, tzinfo=main.UTC),
                "curtailed_mwh": 12.5,
                "period": "2026-08",
                "source_sha256": MATERIALIZED_ITEM["source_sha256"],
                "method": "monthly_observed_reason_rate_prorated_to_window_v1",
            }
        ]

    monkeypatch.setattr(main.repository, "get_historical_windows", fake_windows)

    response = client.get(
        "/v1/assets/CJU_BAOUR/windows",
        params={
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
            "reason": "REL",
        },
    )

    assert response.status_code == 200
    assert captured["reason"] == "REL"
    assert response.json()["reason"] == "REL"


def test_get_historical_windows_rejects_non_positive_duration() -> None:
    response = client.get(
        "/v1/assets/demo-wind-ne-001/windows",
        params={
            "start": "2026-10-01",
            "end": "2026-10-30",
            "duration_hours": 0,
        },
    )

    assert response.status_code == 422


def test_get_historical_windows_rejects_inverted_period() -> None:
    response = client.get(
        "/v1/assets/demo-wind-ne-001/windows",
        params={
            "start": "2026-10-30",
            "end": "2026-10-01",
            "duration_hours": 72,
        },
    )

    assert response.status_code == 422


def test_rank_maintenance_uses_materialized_ons_historical_windows(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_historical_windows",
        lambda asset_id, start, end, duration_hours: [
            {
                "start": main.datetime(2026, 8, 1, tzinfo=main.UTC),
                "end": main.datetime(2026, 8, 4, tzinfo=main.UTC),
                "curtailed_mwh": 20.0,
                "period": "2026-08",
                "source_sha256": MATERIALIZED_ITEM["source_sha256"],
                "method": "monthly_observed_rate_prorated_to_window_v1",
            },
            {
                "start": main.datetime(2026, 8, 15, tzinfo=main.UTC),
                "end": main.datetime(2026, 8, 18, tzinfo=main.UTC),
                "curtailed_mwh": 8.0,
                "period": "2026-08",
                "source_sha256": MATERIALIZED_ITEM["source_sha256"],
                "method": "monthly_observed_rate_prorated_to_window_v1",
            },
        ],
    )

    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "CJU_BAOUR",
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-08-15T00:00:00Z",
            "constraints": {
                "weekdays_only": False,
                "unavailable_periods": [],
            },
            "energy_price": energy_price_payload(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["ranking_mode"] == "historical_prototype"
    assert payload["data_mode"] == "ons_materialized"
    assert payload["baseline_window_start"] == "2026-08-15T00:00:00Z"
    assert [item["expected_curtailed_energy"]["value"] for item in payload["ranked_windows"]] == [
        20.0,
        8.0,
    ]
    assert payload["ranked_windows"][0]["opportunity_cost"]["value"] == 5000.0
    evidence = payload["ranked_windows"][0]["expected_curtailed_energy"]
    assert evidence["value_status"] == "calculado"
    assert evidence["origin"] == "PROXY_CALCULADO"
    window = payload["ranked_windows"][0]
    assert window["opportunity_cost"]["origin"] == "PROXY_CALCULADO"
    assert evidence["source"] == "ONS/restricao_coff_eolica_tm"
    assert evidence["provenance_id"].startswith("ev1.")
    assert window["difference_from_baseline"]["value"] == 12.0
    assert window["difference_from_baseline"]["provenance"]["field_name"] == (
        "difference_from_baseline_mwh"
    )
    ids = {
        evidence["provenance_id"],
        window["opportunity_cost"]["provenance_id"],
        window["difference_from_baseline"]["provenance_id"],
    }
    assert len(ids) == 3
    assert "não é previsão" in " ".join(payload["limitations"]).lower()


def test_rank_maintenance_rejects_baseline_outside_period(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)

    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "demo-wind-ne-001",
            "start": "2026-10-01",
            "end": "2026-10-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-11-15T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(),
        },
    )

    assert response.status_code == 422


def test_rank_maintenance_rejects_non_positive_price() -> None:
    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "demo-wind-ne-001",
            "start": "2026-10-01",
            "end": "2026-10-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-10-15T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(-1),
        },
    )

    assert response.status_code == 422


def test_rank_maintenance_rejects_unknown_asset() -> None:
    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "unknown",
            "start": "2026-10-01",
            "end": "2026-10-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-10-15T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(),
        },
    )

    assert response.status_code == 404


def test_bess_screen_uses_materialized_residual_and_explicit_assumptions(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)

    response = client.post(
        "/v1/bess/screen",
        json={
            "asset_id": "CJU_BAOUR",
            "maintenance_result_id": "historical:CJU_BAOUR:2026-08",
            "power_mw": 20,
            "energy_mwh": 80,
            "capex_brl": 1000000,
            "annualized_cost_brl": 100000,
            "round_trip_efficiency": 0.85,
            "cycles_per_year": 200,
            "energy_price_brl_mwh": 250,
            "input_provenance": bess_input_provenance(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["screening_mode"] == "historical_deterministic"
    assert payload["data_mode"] == "ons_materialized"
    assert payload["residual_exposure_mwh"] == 23968.0945
    assert payload["technically_absorbable_mwh"] == 13600.0
    assert payload["annual_benefit_brl"] == 3400000.0
    assert payload["annual_net_benefit_brl"] == 3300000.0
    assert payload["preliminary_viable"] is True
    assert payload["source_observation"]["origin"] == "ONS_PUBLICO"
    output_evidence = payload["output_evidence"]
    assert set(output_evidence) == {
        "residual_exposure_mwh",
        "technically_absorbable_mwh",
        "annual_benefit_brl",
        "annual_net_benefit_brl",
        "preliminary_viable",
    }
    assert {item["origin"] for item in output_evidence.values()} == {"SIMULADO"}
    assert len({item["provenance_id"] for item in output_evidence.values()}) == 5
    assert all(
        item["provenance"]["method_version"] == "bess_screen_v1"
        for item in output_evidence.values()
    )
    monkeypatch.setattr(main.repository, "get_provenance", lambda source_sha256: MATERIALIZED_ITEM)
    for field_name, evidence in output_evidence.items():
        provenance_response = client.get(f"/v1/provenances/{evidence['provenance_id']}")
        assert provenance_response.status_code == 200
        assert provenance_response.json()["field_name"] == field_name
        assert provenance_response.json()["origin"] == "SIMULADO"
    assert "soc_cronológico" in payload["missing_data"]
    assert "não é dimensionamento" in " ".join(payload["limitations"]).lower()


def test_get_materialization_model_run_is_explicitly_historical(monkeypatch) -> None:
    monkeypatch.setattr(
        main.repository,
        "get_materialization_run",
        lambda period: {
            "period": period,
            "asset_count": 153,
            "source_sha256s": [MATERIALIZED_ITEM["source_sha256"]],
        },
    )

    response = client.get("/v1/model-runs/materialization:2026-08")

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_run_id"] == "materialization:2026-08"
    assert payload["run_type"] == "historical_replay"
    assert payload["model_used"] is False
    assert payload["validation_status"] == "materialized_historical_data"
    assert payload["asset_count"] == 153
    assert payload["metrics"] is None


def test_report_lifecycle_uses_frozen_materialized_evidence(monkeypatch) -> None:
    stored = {}

    def fake_create(report):
        stored.update(report)
        return report

    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(main.artifact_repository, "create_report", fake_create)
    monkeypatch.setattr(main.artifact_repository, "get_report", lambda report_id: stored or None)
    monkeypatch.setattr(
        main.artifact_repository,
        "get_report_file_url",
        lambda report: "https://example.invalid/temporary-report-url",
    )

    create_response = client.post(
        "/v1/reports",
        json={
            "asset_id": "CJU_BAOUR",
            "evidence_ids": [f"sha256:{MATERIALIZED_ITEM['source_sha256']}"],
            "report_type": "decision_support",
            "format": "json",
        },
    )

    assert create_response.status_code == 202
    created = create_response.json()
    assert created["execution_status"] == "completed"
    assert created["generation_mode"] == "deterministic_fallback"
    assert created["hash_sha256"] == hashlib.sha256(stored["body"].encode()).hexdigest()
    assert json.loads(stored["body"])["data_mode"] == "ons_materialized"

    get_response = client.get(f"/v1/reports/{created['report_id']}")
    assert get_response.status_code == 200
    assert get_response.json()["hash_sha256"] == created["hash_sha256"]

    file_response = client.get(f"/v1/reports/{created['report_id']}/file")
    assert file_response.status_code == 200
    assert file_response.json()["expires_in_seconds"] == 300
    assert file_response.json()["url"].startswith("https://")


def test_optimize_curtailment_returns_explainable_recommendation(monkeypatch) -> None:
    def fake_optimize(_scenario):
        return {
            "recomendacao": "Reduzir 8 MW de geração renovável por 30 minutos.",
            "justificativa_tecnica": "A restrição de transmissão limita o escoamento.",
            "nivel_risco": "medio",
            "acoes_sugeridas": ["Monitorar o intercâmbio", "Reavaliar em 15 minutos"],
            "premissas_usadas": ["Demanda prevista de 120 MW"],
            "modelo_bedrock_utilizado": "us.anthropic.claude-opus-5",
        }

    monkeypatch.setattr(main, "optimize_with_bedrock", fake_optimize, raising=False)

    response = client.post(
        "/optimize-curtailment",
        json={
            "regiao_subsistema": "Nordeste",
            "timestamp": "2026-09-26T15:00:00Z",
            "demanda_prevista_mw": 120,
            "geracao_renovavel_prevista_mw": 150,
            "geracao_convencional_disponivel_mw": 20,
            "restricoes_transmissao": ["Limite de exportação: 140 MW"],
            "limite_corte_permitido_mw": 15,
            "prioridade_operacional": "alta",
            "observacoes": "Preservar estabilidade do sistema.",
        },
    )

    assert response.status_code == 200
    assert response.json()["nivel_risco"] == "medio"
    assert response.json()["modelo_bedrock_utilizado"] == "us.anthropic.claude-opus-5"
    assert len(response.json()["acoes_sugeridas"]) == 2


def test_optimize_curtailment_rejects_invalid_generation() -> None:
    response = client.post(
        "/optimize-curtailment",
        json={
            "regiao_subsistema": "Nordeste",
            "timestamp": "2026-09-26T15:00:00Z",
            "demanda_prevista_mw": 120,
            "geracao_renovavel_prevista_mw": -1,
            "geracao_convencional_disponivel_mw": 20,
            "restricoes_transmissao": [],
            "limite_corte_permitido_mw": 15,
            "prioridade_operacional": "alta",
        },
    )

    assert response.status_code == 422


def test_optimize_curtailment_returns_controlled_error(monkeypatch) -> None:
    def fake_optimize(_scenario):
        raise main.BedrockOptimizationError("all models failed")

    monkeypatch.setattr(main, "optimize_with_bedrock", fake_optimize)

    response = client.post(
        "/optimize-curtailment",
        json={
            "regiao_subsistema": "Nordeste",
            "timestamp": "2026-09-26T15:00:00Z",
            "demanda_prevista_mw": 120,
            "geracao_renovavel_prevista_mw": 150,
            "geracao_convencional_disponivel_mw": 20,
            "restricoes_transmissao": [],
            "limite_corte_permitido_mw": 15,
            "prioridade_operacional": "alta",
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Serviço de otimização temporariamente indisponível."}
