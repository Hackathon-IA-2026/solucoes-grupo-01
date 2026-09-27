from botocore.exceptions import ClientError

from curtailess.bedrock import explain_maintenance_decision, optimize_with_bedrock
from curtailess.config import Settings
from curtailess.schemas import CurtailmentScenario


def _scenario() -> CurtailmentScenario:
    return CurtailmentScenario.model_validate(
        {
            "regiao_subsistema": "Nordeste",
            "timestamp": "2026-09-26T15:00:00Z",
            "demanda_prevista_mw": 120,
            "geracao_renovavel_prevista_mw": 150,
            "geracao_convencional_disponivel_mw": 20,
            "restricoes_transmissao": ["Limite de exportação: 140 MW"],
            "limite_corte_permitido_mw": 15,
            "prioridade_operacional": "alta",
        }
    )


def test_bedrock_uses_fallback_after_primary_failure() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.models: list[str] = []

        def converse(self, **kwargs):
            model_id = kwargs["modelId"]
            self.models.append(model_id)
            if model_id == "primary-model":
                raise ClientError(
                    {"Error": {"Code": "ThrottlingException", "Message": "try again"}},
                    "Converse",
                )
            return {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": """{
                                    "recomendacao": "Aplicar corte controlado.",
                                    "justificativa_tecnica": "Há restrição de escoamento.",
                                    "nivel_risco": "alto",
                                    "acoes_sugeridas": ["Monitorar a restrição"],
                                    "premissas_usadas": ["Limite informado pelo operador"]
                                }"""
                            }
                        ]
                    }
                }
            }

    fake_client = FakeClient()
    settings = Settings(
        aws_region="us-west-2",
        bedrock_model_id="primary-model",
        bedrock_fallback_model_id="fallback-model",
        bedrock_emergency_model_id="emergency-model",
    )

    result = optimize_with_bedrock(
        _scenario(),
        settings=settings,
        client_factory=lambda *_args, **_kwargs: fake_client,
    )

    assert fake_client.models == ["primary-model", "fallback-model"]
    assert result.modelo_bedrock_utilizado == "fallback-model"
    assert result.nivel_risco == "alto"


def test_decision_explanation_is_bounded_to_supplied_evidence_and_explicit_tokens() -> None:
    class FakeClient:
        def __init__(self):
            self.requests = []

        def converse(self, **kwargs):
            self.requests.append(kwargs)
            return {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": (
                                    '{"summary":"A janela tem a menor energia residual.",'
                                    '"evidence_ids":["mw1.'
                                    + "1" * 64
                                    + '"],"limitations":["Candidata sem aprovação do ONS."]}'
                                )
                            }
                        ]
                    }
                }
            }

    client = FakeClient()
    evidence_ids = ("mw1." + "1" * 64, "pst1." + "2" * 64)
    result = explain_maintenance_decision(
        {
            "selected_window": {
                "start": "2026-02-01T00:00:00-03:00",
                "end": "2026-02-03T00:00:00-03:00",
                "residual_saleable_mwh": 10,
                "uncertainty_penalty_mwh": 1,
            }
        },
        evidence_ids,
        settings=Settings(
            bedrock_model_id="primary-model",
            bedrock_fallback_model_id="fallback-model",
            bedrock_emergency_model_id="emergency-model",
        ),
        client_factory=lambda *_args, **_kwargs: client,
    )

    assert result.generation_mode == "bedrock"
    assert result.evidence_ids == (evidence_ids[0],)
    assert client.requests[0]["inferenceConfig"] == {"maxTokens": 800}


def test_invalid_bedrock_evidence_uses_deterministic_fallback() -> None:
    class FakeClient:
        def __init__(self):
            self.models = []

        def converse(self, **kwargs):
            self.models.append(kwargs["modelId"])
            return {
                "output": {
                    "message": {
                        "content": [
                            {
                                "text": (
                                    '{"summary":"O ONS aprovou a janela.",'
                                    '"evidence_ids":["inventado"],'
                                    '"limitations":["Nenhuma."]}'
                                )
                            }
                        ]
                    }
                }
            }

    client = FakeClient()
    evidence_ids = ("mw1." + "1" * 64,)
    result = explain_maintenance_decision(
        {
            "selected_window": {
                "start": "2026-02-01T00:00:00-03:00",
                "end": "2026-02-03T00:00:00-03:00",
                "residual_saleable_mwh": 10,
                "uncertainty_penalty_mwh": 1,
            }
        },
        evidence_ids,
        settings=Settings(
            bedrock_model_id="primary-model",
            bedrock_fallback_model_id="fallback-model",
            bedrock_emergency_model_id="emergency-model",
        ),
        client_factory=lambda *_args, **_kwargs: client,
    )

    assert client.models == ["primary-model", "fallback-model", "emergency-model"]
    assert result.generation_mode == "deterministic_fallback"
    assert result.model_id is None
    assert result.evidence_ids == evidence_ids


def test_unavailable_bedrock_uses_deterministic_fallback() -> None:
    class UnavailableClient:
        def converse(self, **kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "ServiceUnavailableException",
                        "Message": kwargs["modelId"],
                    }
                },
                "Converse",
            )

    evidence_ids = ("mw1." + "1" * 64,)
    result = explain_maintenance_decision(
        {
            "selected_window": {
                "start": "2026-02-01T00:00:00-03:00",
                "end": "2026-02-03T00:00:00-03:00",
                "residual_saleable_mwh": 10,
                "uncertainty_penalty_mwh": 1,
            }
        },
        evidence_ids,
        settings=Settings(
            bedrock_model_id="primary-model",
            bedrock_fallback_model_id="fallback-model",
            bedrock_emergency_model_id="emergency-model",
        ),
        client_factory=lambda *_args, **_kwargs: UnavailableClient(),
    )

    assert result.generation_mode == "deterministic_fallback"
    assert result.evidence_ids == evidence_ids
