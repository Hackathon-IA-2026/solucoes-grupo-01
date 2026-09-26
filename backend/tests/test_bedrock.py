from botocore.exceptions import ClientError

from curtailess.bedrock import optimize_with_bedrock
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
