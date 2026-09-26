from fastapi.testclient import TestClient

import curtailess.main as main
from curtailess.main import app

client = TestClient(app)


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


def test_get_asset_exposure_returns_materialized_ons_values(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_exposure",
        lambda asset_id, start, end: {
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
    assert payload["total_curtailed_energy"]["data_version"] == "2026-08"
    assert payload["total_curtailed_energy"]["source"] == "ONS/restricao_coff_eolica_tm"
    assert payload["total_curtailed_energy"]["provenance_id"].startswith("sha256:")
    assert "materializado" in " ".join(payload["limitations"]).lower()


def test_get_asset_exposure_rejects_inverted_period() -> None:
    response = client.get(
        "/v1/assets/demo-wind-ne-001/exposure",
        params={"start": "2026-09-01", "end": "2026-08-01"},
    )

    assert response.status_code == 422


def test_get_unknown_asset_returns_not_found() -> None:
    response = client.get("/v1/assets/unknown")

    assert response.status_code == 404


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
    assert "nomes" in " ".join(payload["limitations"]).lower()
    assert "entities" not in payload


def test_get_historical_windows_uses_materialized_monthly_signal(monkeypatch) -> None:
    item = {**MATERIALIZED_ITEM, "interval_count": 1488}
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: item)
    monkeypatch.setattr(
        main.repository,
        "get_historical_windows",
        lambda asset_id, start, end, duration_hours: [
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


def test_rank_maintenance_returns_ranked_historical_prototype() -> None:
    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "demo-wind-ne-001",
            "start": "2026-10-01",
            "end": "2026-10-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-10-15T00:00:00Z",
            "constraints": {
                "weekdays_only": False,
                "unavailable_periods": [],
            },
            "energy_price": {
                "value": 250,
                "unit": "BRL/MWh",
                "source": "client_scenario",
                "value_status": "informado",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "demo-wind-ne-001"
    assert payload["ranking_mode"] == "historical_prototype"
    assert payload["data_mode"] == "demo"
    assert payload["baseline_window_start"] == "2026-10-15T00:00:00Z"
    assert len(payload["ranked_windows"]) >= 2
    expected_values = [
        item["expected_curtailed_energy"]["value"] for item in payload["ranked_windows"]
    ]
    assert expected_values == sorted(expected_values, reverse=True)
    assert payload["ranked_windows"][0]["rank"] == 1
    assert payload["ranked_windows"][0]["opportunity_cost"]["unit"] == "BRL"
    assert payload["ranked_windows"][0]["expected_curtailed_energy"]["value_status"] == "simulado"
    assert "não é previsão" in " ".join(payload["limitations"]).lower()


def test_rank_maintenance_rejects_baseline_outside_period() -> None:
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
            "energy_price": {
                "value": 250,
                "unit": "BRL/MWh",
                "source": "client_scenario",
                "value_status": "informado",
            },
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
            "energy_price": {
                "value": -1,
                "unit": "BRL/MWh",
                "source": "client_scenario",
                "value_status": "informado",
            },
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
            "energy_price": {
                "value": 250,
                "unit": "BRL/MWh",
                "source": "client_scenario",
                "value_status": "informado",
            },
        },
    )

    assert response.status_code == 404


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
