from fastapi.testclient import TestClient

import curtailess.main as main
from curtailess.main import app

client = TestClient(app)


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


def test_list_assets_returns_demo_asset() -> None:
    response = client.get("/v1/assets")

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "asset_id": "demo-wind-ne-001",
                "name": "Ativo eólico de demonstração",
                "technology": "wind",
                "capacity_mw": 100.0,
                "ons_group": "Conjunto anonimizado NE-001",
                "connection_point": "Ponto cadastral anonimizado NE-001",
                "data_mode": "demo",
            }
        ]
    }


def test_get_asset_exposure_returns_traceable_historical_values() -> None:
    response = client.get(
        "/v1/assets/demo-wind-ne-001/exposure",
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "demo-wind-ne-001"
    assert payload["perspective_type"] == "historical_observed"
    assert payload["data_mode"] == "demo"
    assert payload["total_curtailed_energy"]["unit"] == "MWh"
    assert payload["total_curtailed_energy"]["value_status"] == "calculado"
    assert payload["total_curtailed_energy"]["source"] == ("ONS/restricao_coff_eolica_tm")
    assert payload["total_curtailed_energy"]["provenance_id"]
    assert "simulados" in " ".join(payload["limitations"]).lower()


def test_get_asset_exposure_rejects_inverted_period() -> None:
    response = client.get(
        "/v1/assets/demo-wind-ne-001/exposure",
        params={"start": "2026-09-01", "end": "2026-08-01"},
    )

    assert response.status_code == 422


def test_get_unknown_asset_returns_not_found() -> None:
    response = client.get("/v1/assets/unknown")

    assert response.status_code == 404


def test_get_point_context_returns_only_anonymized_aggregates() -> None:
    response = client.get("/v1/assets/demo-wind-ne-001/point-context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "demo-wind-ne-001"
    assert payload["data_mode"] == "demo"
    assert payload["connection_point"] == "Ponto cadastral anonimizado NE-001"
    assert payload["anonymized_entity_count"]["value"] >= 1
    assert payload["anonymized_entity_count"]["unit"] == "entities"
    assert payload["simultaneity_rate"]["unit"] == "%"
    assert payload["physical_limit_available"] is False
    assert "nomes" in " ".join(payload["limitations"]).lower()
    assert "entities" not in payload


def test_get_historical_windows_marks_result_as_non_forecast() -> None:
    response = client.get(
        "/v1/assets/demo-wind-ne-001/windows",
        params={
            "start": "2026-10-01",
            "end": "2026-10-30",
            "duration_hours": 72,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "demo-wind-ne-001"
    assert payload["perspective_type"] == "historical_seasonal"
    assert payload["validation_status"] == "historical_signal"
    assert payload["data_mode"] == "demo"
    assert payload["duration_hours"] == 72
    assert len(payload["windows"]) >= 1
    assert payload["windows"][0]["expected_curtailed_energy"]["unit"] == "MWh"
    assert payload["windows"][0]["expected_curtailed_energy"]["value_status"] == ("simulado")
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
