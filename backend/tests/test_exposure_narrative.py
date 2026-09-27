import json

import pytest

from curtailess.config import Settings
from curtailess.exposure_narrative import (
    generate_exposure_narrative,
    validate_exposure_narrative,
)
from curtailess.exposure_view import build_exposure_view

VALID = {
    "secao-ativo": ["O conjunto está ligado ao ponto indicado nos dados."],
    "secao-resumo": ["O histórico materializado resume a exposição observada."],
    "secao-previsao": ["A projeção é demonstrativa e expressa uma possibilidade estimada."],
    "secao-razao-origem": ["As categorias disponíveis descrevem condições associadas."],
    "secao-recorrencia": ["A granularidade atual limita a leitura temporal."],
    "secao-qualidade": ["Os indicadores apresentados qualificam a leitura da série."],
}


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.payload, Exception):
            raise self.payload
        return {
            "output": {
                "message": {"content": [{"text": json.dumps(self.payload, ensure_ascii=False)}]}
            }
        }


def test_validate_narrative_rejects_unsupported_numbers_and_claims():
    view = build_exposure_view("CJU_RNRDV")
    evidence = view.model_dump(mode="json", by_alias=True)
    evidence.pop("narrative")
    evidence.pop("input_digest")

    invalid_number = {**VALID, "secao-resumo": ["O histórico registra 999 MWh."]}
    with pytest.raises(ValueError, match="unsupported numbers"):
        validate_exposure_narrative(invalid_number, evidence)

    invalid_claim = {**VALID, "secao-previsao": ["O ONS aprovou a previsão."]}
    with pytest.raises(ValueError, match="unsupported"):
        validate_exposure_narrative(invalid_claim, evidence)


def test_generate_narrative_uses_converse_without_temperature():
    view = build_exposure_view("CJU_RNRDV")
    client = FakeClient(VALID)

    narrative, model_id = generate_exposure_narrative(
        view,
        settings=Settings(
            bedrock_model_id="model-primary",
            bedrock_fallback_model_id="model-fallback",
            bedrock_emergency_model_id="model-emergency",
        ),
        client_factory=lambda *args, **kwargs: client,
    )

    assert model_id == "model-primary"
    assert narrative.secao_ativo == tuple(VALID["secao-ativo"])
    assert client.calls[0]["inferenceConfig"] == {"maxTokens": 800}
    assert "temperature" not in client.calls[0]["inferenceConfig"]


def test_generate_narrative_falls_back_deterministically_after_invalid_models():
    view = build_exposure_view("CJU_RNRDV")
    client = FakeClient({**VALID, "secao-resumo": ["O histórico registra 999 MWh."]})

    narrative, model_id = generate_exposure_narrative(
        view,
        settings=Settings(
            bedrock_model_id="model-primary",
            bedrock_fallback_model_id="model-fallback",
            bedrock_emergency_model_id="model-emergency",
        ),
        client_factory=lambda *args, **kwargs: client,
    )

    assert model_id is None
    assert narrative.secao_previsao
    assert len(client.calls) == 3
