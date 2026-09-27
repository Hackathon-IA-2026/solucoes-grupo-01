from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from curtailess.bedrock import _extract_text, _parse_json_text
from curtailess.canonical import canonical_json
from curtailess.config import Settings, get_settings
from curtailess.exposure_view import deterministic_narrative
from curtailess.schemas import ExposureNarrative, ExposureViewResponse

logger = logging.getLogger(__name__)
NARRATIVE_SCHEMA_VERSION = "exposure-narrative-v1"
_NUMBER = re.compile(r"(?<![\w#])\d+(?:[.,]\d+)?")
_FORBIDDEN_CLAIMS = (
    "ons aprovou",
    "ons validou",
    "operador aprovou",
    "operador validou",
    "coordenação confirmada",
    "limite físico confirmado",
    "curtailment ocorrerá",
    "corte ocorrerá",
    "garantia de",
    "telemetria scada",
    "setpoint medido",
    "recomenda-se manutenção",
    "recomenda-se bateria",
    "bucket",
    "prompt",
    "input_digest",
    "source_sha",
)
_SYSTEM_PROMPT = """Você escreve interpretações concisas em português para a aba Exposição.
Retorne somente um objeto JSON com estas seis chaves exatas: secao-ativo,
secao-resumo, secao-previsao, secao-razao-origem, secao-recorrencia e
secao-qualidade. Cada valor deve ser uma lista de 1 a 3 parágrafos curtos.
Use somente os fatos recebidos. Não crie, arredonde ou altere números. Não afirme
causalidade, aprovação ou coordenação do ONS, limite físico confirmado, telemetria
SCADA, setpoint medido ou previsão operacional validada. Não recomende manutenção
ou bateria. Não mencione prompts, hashes, buckets, modelos ou detalhes internos.
A previsão representa apenas uma possibilidade demonstrativa estimada."""


def _evidence_payload(view: ExposureViewResponse) -> dict[str, Any]:
    payload = view.model_dump(mode="json", by_alias=True)
    payload.pop("narrative", None)
    payload.pop("input_digest", None)
    return payload


def _allowed_number_tokens(payload: dict[str, Any]) -> set[str]:
    serialized = canonical_json(payload)
    tokens = set(_NUMBER.findall(serialized))
    allowed = set(tokens)
    allowed.update(token.replace(".", ",") for token in tokens)
    return allowed


def validate_exposure_narrative(
    value: dict[str, Any], evidence_payload: dict[str, Any]
) -> ExposureNarrative:
    narrative = ExposureNarrative.model_validate(value)
    text = " ".join(
        paragraph
        for paragraphs in narrative.model_dump(by_alias=True).values()
        for paragraph in paragraphs
    )
    normalized = " ".join(text.casefold().split())
    if any(claim in normalized for claim in _FORBIDDEN_CLAIMS):
        raise ValueError("narrative contains an unsupported or internal claim")
    allowed_numbers = _allowed_number_tokens(evidence_payload)
    unsupported = sorted(set(_NUMBER.findall(text)) - allowed_numbers)
    if unsupported:
        raise ValueError(f"narrative contains unsupported numbers: {unsupported}")
    return narrative


def generate_exposure_narrative(
    view: ExposureViewResponse,
    *,
    settings: Settings | None = None,
    client_factory: Callable[..., Any] = boto3.client,
) -> tuple[ExposureNarrative, str | None]:
    current_settings = settings or get_settings()
    client = client_factory(
        "bedrock-runtime",
        region_name=current_settings.aws_region,
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
    )
    evidence = _evidence_payload(view)
    prompt = canonical_json(evidence)
    model_ids = dict.fromkeys(
        (
            current_settings.bedrock_model_id,
            current_settings.bedrock_fallback_model_id,
            current_settings.bedrock_emergency_model_id,
        )
    )
    for model_id in model_ids:
        try:
            response = client.converse(
                modelId=model_id,
                system=[{"text": _SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 800},
            )
            payload = _parse_json_text(_extract_text(response))
            return validate_exposure_narrative(payload, evidence), model_id
        except (
            BotoCoreError,
            ClientError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            logger.warning(
                "Falha na narrativa de Exposição com modelo %s (%s): %s",
                model_id,
                type(exc).__name__,
                exc,
            )
    return (
        deterministic_narrative(
            view.asset,
            view.observed_impact,
            view.forecast_60d,
            view.associated_conditions,
            view.recurrence,
            view.quality,
        ),
        None,
    )
