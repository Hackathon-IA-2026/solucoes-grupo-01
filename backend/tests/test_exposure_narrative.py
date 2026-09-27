import json
from typing import Any

import pytest
from botocore.exceptions import ClientError

from curtailess.canonical import canonical_json
from curtailess.config import Settings
from curtailess.exposure_narrative import (
    _MAX_TOKENS,
    _SECTION_FIELDS,
    SECTION_IDS,
    _evidence_payload,
    _section_evidence_payloads,
    deterministic_exposure_narrative,
    generate_exposure_narrative,
    validate_exposure_narrative,
    validate_section_narrative,
)
from curtailess.exposure_view import build_exposure_view
from curtailess.schemas import ExposureNarrative, ExposureNarrativeSection

WIND_ASSET = "BAEA52"
SOLAR_ASSET = "PBLZ3"

_NEUTRAL = "A leitura desta seção usa somente os fatos fornecidos para ela."


def _valid_payload() -> dict[str, dict[str, list[str]]]:
    return {section_id: {"paragraphs": [_NEUTRAL]} for section_id in SECTION_IDS}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        item = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        if isinstance(item, Exception):
            raise item
        return {
            "output": {"message": {"content": [{"text": json.dumps(item, ensure_ascii=False)}]}}
        }


class Factory:
    def __init__(self, client):
        self.client = client
        self.args: tuple[Any, ...] = ()
        self.kwargs: dict[str, Any] = {}

    def __call__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        return self.client


def _settings() -> Settings:
    return Settings(
        bedrock_model_id="model-primary",
        bedrock_fallback_model_id="model-fallback",
        bedrock_emergency_model_id="model-emergency",
    )


def _generate(view, client):
    factory = Factory(client)
    narrative, model_id = generate_exposure_narrative(
        view, settings=_settings(), client_factory=factory
    )
    return narrative, model_id, factory


def _transport_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "throttled"}}, "Converse"
    )


@pytest.fixture(scope="module")
def view():
    return build_exposure_view(WIND_ASSET)


@pytest.fixture(scope="module")
def evidence(view):
    return _section_evidence_payloads(view)


def test_section_evidence_payloads_are_scoped_and_free_of_provenance(view, evidence):
    assert set(evidence) == set(SECTION_IDS)
    serialized = canonical_json(evidence)
    for label in ("SIMULADO", "ONS_PUBLICO", "PROXY_CALCULADO", "simulation_method"):
        assert label not in serialized
    for payload in evidence.values():
        assert '"origin":' not in json.dumps(payload)
    # A fact that only section 1 owns is not visible to the quality section.
    capacity = view.asset.capacity_mw
    assert capacity is not None
    assert str(capacity) not in canonical_json(evidence["secao-qualidade"])
    assert str(capacity) in canonical_json(evidence["secao-ativo"])


def test_valid_six_section_json_is_accepted_with_one_converse_call(view):
    client = FakeClient([_valid_payload()])
    narrative, model_id, factory = _generate(view, client)

    assert model_id == "model-primary"
    assert set(narrative.model_dump(by_alias=True)) == set(SECTION_IDS)
    for section_id in SECTION_IDS:
        section = getattr(narrative, _SECTION_FIELDS[section_id])
        assert section.generation_mode == "bedrock"
        assert section.paragraphs == (_NEUTRAL,)

    assert len(client.calls) == 1
    assert client.calls[0]["inferenceConfig"] == {"maxTokens": _MAX_TOKENS}
    assert "temperature" not in client.calls[0]["inferenceConfig"]
    assert factory.args[0] == "bedrock-runtime"
    assert factory.kwargs["config"].retries == {"max_attempts": 5, "mode": "adaptive"}


def test_section_arrays_are_accepted_and_marked_bedrock(view):
    payload = {section_id: [_NEUTRAL] for section_id in SECTION_IDS}
    narrative, model_id, _ = _generate(view, FakeClient([payload]))

    assert model_id == "model-primary"
    assert all(
        getattr(narrative, _SECTION_FIELDS[section_id]).generation_mode == "bedrock"
        for section_id in SECTION_IDS
    )


def test_partial_and_missing_sections_fall_back_individually(view):
    payload = _valid_payload()
    payload.pop("secao-previsao")
    payload.pop("secao-qualidade")
    narrative, model_id, factory = _generate(view, FakeClient([payload]))

    assert model_id == "model-primary"
    assert getattr(narrative, _SECTION_FIELDS["secao-ativo"]).generation_mode == "bedrock"
    assert getattr(narrative, _SECTION_FIELDS["secao-previsao"]).generation_mode == (
        "deterministic_fallback"
    )
    assert getattr(narrative, _SECTION_FIELDS["secao-qualidade"]).generation_mode == (
        "deterministic_fallback"
    )
    assert getattr(narrative, _SECTION_FIELDS["secao-previsao"]).paragraphs
    assert len(factory.client.calls) == 1


def test_oversized_paragraph_falls_back_for_its_section_only(view, evidence):
    payload = _valid_payload()
    payload["secao-resumo"] = {"paragraphs": ["x" * 600]}
    narrative, model_id, _ = _generate(view, FakeClient([payload]))

    assert model_id == "model-primary"
    assert getattr(narrative, _SECTION_FIELDS["secao-resumo"]).generation_mode == (
        "deterministic_fallback"
    )
    assert getattr(narrative, _SECTION_FIELDS["secao-ativo"]).generation_mode == "bedrock"
    with pytest.raises(ValueError):
        validate_section_narrative("secao-resumo", ["x" * 600], evidence["secao-resumo"])


def test_invented_number_is_rejected_for_its_section(view, evidence):
    payload = _valid_payload()
    payload["secao-resumo"] = {"paragraphs": ["O histórico registra 123456789 MWh."]}
    narrative, model_id, _ = _generate(view, FakeClient([payload]))

    assert model_id == "model-primary"
    assert getattr(narrative, _SECTION_FIELDS["secao-resumo"]).generation_mode == (
        "deterministic_fallback"
    )
    assert getattr(narrative, _SECTION_FIELDS["secao-previsao"]).generation_mode == "bedrock"
    with pytest.raises(ValueError, match="numbers outside its section evidence"):
        validate_section_narrative(
            "secao-resumo", ["O histórico registra 123456789 MWh."], evidence["secao-resumo"]
        )


def test_cross_section_number_is_rejected(view, evidence):
    payload = _valid_payload()
    capacity = view.asset.capacity_mw
    assert capacity is not None
    payload["secao-qualidade"] = {"paragraphs": [f"A capacidade cadastrada é de {capacity} MW."]}
    narrative, model_id, _ = _generate(view, FakeClient([payload]))

    assert model_id == "model-primary"
    assert getattr(narrative, _SECTION_FIELDS["secao-qualidade"]).generation_mode == (
        "deterministic_fallback"
    )
    assert getattr(narrative, _SECTION_FIELDS["secao-recorrencia"]).generation_mode == "bedrock"
    with pytest.raises(ValueError, match="numbers outside its section evidence"):
        validate_section_narrative(
            "secao-qualidade",
            [f"A capacidade cadastrada é de {capacity} MW."],
            evidence["secao-qualidade"],
        )


def test_truncated_or_rounded_number_is_rejected(view, evidence):
    # Evidence exposes 81.2775 (restricted-day share) and 46.4 (capacity); 81 and 46 are
    # truncations/roundings and must not pass as if they were the same fact.
    for text in (
        "A fração de dias restritos é de 81%.",
        "A capacidade cadastrada é de 46 MW.",
    ):
        with pytest.raises(ValueError, match="numbers outside its section evidence"):
            validate_section_narrative("secao-resumo", [text], evidence["secao-resumo"])


def test_exact_number_with_comma_separator_is_accepted(view, evidence):
    for text in (
        "A fração de dias restritos é de 81,2775%.",
        "A capacidade cadastrada é de 46.4 MW.",
    ):
        section = validate_section_narrative("secao-resumo", [text], evidence["secao-resumo"])
        assert section.generation_mode == "bedrock"


def test_unit_alteration_is_rejected(view, evidence):
    with pytest.raises(ValueError, match="alters a unit"):
        validate_section_narrative(
            "secao-qualidade", ["A cobertura calculada é de 100 kWh."], evidence["secao-qualidade"]
        )


def test_mwh_evidence_does_not_authorize_mw_by_substring():
    # Evidence that only contains MWh must not authorize MW through the "mw" substring.
    evidence = {"forecast_60d": {"total_expected_mwh": 10.0}}
    with pytest.raises(ValueError, match="alters a unit"):
        validate_section_narrative("secao-previsao", ["A energia esperada é de 10 MW."], evidence)
    section = validate_section_narrative(
        "secao-previsao", ["A energia esperada é de 10 MWh."], evidence
    )
    assert section.generation_mode == "bedrock"


@pytest.mark.parametrize(
    "text",
    [
        "SIMULADO: a série veio do histórico público.",
        "O rótulo ONS_PUBLICO identifica esta seção.",
        "A procedência PROXY_CALCULADO sustenta o número.",
        "O campo simulation_method define a origem técnica.",
    ],
)
def test_provenance_and_technical_labels_are_rejected(view, evidence, text):
    payload = _valid_payload()
    payload["secao-qualidade"] = {"paragraphs": [text]}
    narrative, _, _ = _generate(view, FakeClient([payload]))

    assert getattr(narrative, _SECTION_FIELDS["secao-qualidade"]).generation_mode == (
        "deterministic_fallback"
    )
    with pytest.raises(ValueError):
        validate_section_narrative("secao-qualidade", [text], evidence["secao-qualidade"])


@pytest.mark.parametrize(
    "text",
    [
        "O ONS aprovou a previsão de restrição.",
        "A coordenação do ONS confirma o resultado.",
        "A usina mede telemetria SCADA em tempo real.",
        "A capacidade física confirmada é de 46 MW.",
        "O corte ocorrerá com certeza na próxima semana.",
        "Recomenda-se manutenção preventiva durante a janela.",
        "A razão do conjunto é a causa comprovada do corte da usina.",
        "A operação real confirmada consta do registro.",
    ],
)
def test_forbidden_claims_are_rejected(view, evidence, text):
    payload = _valid_payload()
    payload["secao-previsao"] = {"paragraphs": [text]}
    narrative, _, _ = _generate(view, FakeClient([payload]))

    assert getattr(narrative, _SECTION_FIELDS["secao-previsao"]).generation_mode == (
        "deterministic_fallback"
    )
    with pytest.raises(ValueError):
        validate_section_narrative("secao-previsao", [text], evidence["secao-previsao"])


def test_negated_claims_remain_acceptable(view, evidence):
    text = "O estado apresentado é uma estimativa simulada e não de telemetria privada da usina."
    section = validate_section_narrative("secao-ativo", [text], evidence["secao-ativo"])
    assert section.generation_mode == "bedrock"


def test_section_generation_mode_literal():
    for mode in ("bedrock", "cached_bedrock", "deterministic_fallback"):
        section = ExposureNarrativeSection(paragraphs=(_NEUTRAL,), generation_mode=mode)
        assert section.generation_mode == mode
    with pytest.raises(ValueError):
        ExposureNarrativeSection.model_validate(
            {"paragraphs": [_NEUTRAL], "generation_mode": "bedrock_cached"}
        )


def test_narrative_schema_requires_exactly_six_sections():
    payload = {section_id: {"paragraphs": [_NEUTRAL]} for section_id in SECTION_IDS}
    payload.pop("secao-qualidade")
    with pytest.raises(ValueError):
        ExposureNarrative.model_validate(payload)

    payload["secao-extra"] = {"paragraphs": [_NEUTRAL]}
    payload["secao-qualidade"] = {"paragraphs": [_NEUTRAL]}
    with pytest.raises(ValueError):
        ExposureNarrative.model_validate(payload)


def test_strict_validation_rejects_a_stored_narrative_with_one_bad_section(view):
    narrative = deterministic_exposure_narrative(view)
    payload = narrative.model_dump(mode="json", by_alias=True)
    payload["secao-resumo"]["paragraphs"] = ["O histórico registra 123456789 MWh."]
    with pytest.raises(ValueError, match="numbers outside its section evidence"):
        validate_exposure_narrative(payload, _evidence_payload(view))


def test_validation_failure_does_not_retry_other_models(view):
    payload = _valid_payload()
    payload["secao-resumo"] = {"paragraphs": ["O histórico registra 123456789 MWh."]}
    client = FakeClient([payload, _valid_payload(), _valid_payload()])
    narrative, model_id, _ = _generate(view, client)

    assert model_id == "model-primary"
    assert len(client.calls) == 1
    assert getattr(narrative, _SECTION_FIELDS["secao-resumo"]).generation_mode == (
        "deterministic_fallback"
    )


def test_transport_error_uses_the_next_model(view):
    client = FakeClient([_transport_error(), _valid_payload()])
    narrative, model_id, _ = _generate(view, client)

    assert model_id == "model-fallback"
    assert len(client.calls) == 2
    assert getattr(narrative, _SECTION_FIELDS["secao-ativo"]).generation_mode == "bedrock"


def test_all_models_failing_returns_the_deterministic_narrative(view):
    client = FakeClient([_transport_error()])
    narrative, model_id, _ = _generate(view, client)

    assert model_id is None
    assert len(client.calls) == 3
    assert all(
        getattr(narrative, _SECTION_FIELDS[section_id]).generation_mode == "deterministic_fallback"
        for section_id in SECTION_IDS
    )


def test_unparseable_response_returns_deterministic_narrative_without_next_model(view):
    client = FakeClient(["not-json", _valid_payload()])
    narrative, model_id, _ = _generate(view, client)

    assert model_id is None
    assert len(client.calls) == 1
    assert all(
        getattr(narrative, _SECTION_FIELDS[section_id]).generation_mode == "deterministic_fallback"
        for section_id in SECTION_IDS
    )


@pytest.mark.parametrize("asset_id", [WIND_ASSET, SOLAR_ASSET])
def test_deterministic_fallback_is_self_consistent(asset_id):
    view = build_exposure_view(asset_id)
    evidence = _section_evidence_payloads(view)
    narrative = deterministic_exposure_narrative(view)

    for section_id in SECTION_IDS:
        section = getattr(narrative, _SECTION_FIELDS[section_id])
        assert section.generation_mode == "deterministic_fallback"
        assert section.paragraphs
        # The deterministic text must satisfy the same section-scoped rules.
        validate_section_narrative(
            section_id,
            section.paragraphs,
            evidence[section_id],
            generation_mode="deterministic_fallback",
        )
    serialized = canonical_json(narrative.model_dump(by_alias=True))
    for label in ("ONS_PUBLICO", "PROXY_CALCULADO", "SIMULADO", "simulation_method"):
        assert label not in serialized
