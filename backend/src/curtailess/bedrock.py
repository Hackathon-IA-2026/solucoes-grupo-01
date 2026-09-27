import json
import logging
from collections.abc import Callable
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import BaseModel, ConfigDict, Field

from .canonical import canonical_json
from .config import Settings, get_settings
from .schemas import (
    CurtailmentRecommendation,
    CurtailmentScenario,
    DecisionExplanation,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é especialista em operação do sistema elétrico brasileiro.
Analise sem inventar dados. Retorne SOMENTE um objeto JSON válido, sem markdown, com:
recomendacao (string), justificativa_tecnica (string), nivel_risco
(baixo|medio|alto|critico), acoes_sugeridas (lista de strings) e
premissas_usadas (lista de strings). Seja conciso: no máximo 700 caracteres.
A resposta apoia decisão humana e não substitui procedimentos operacionais, normas
ou validação do operador responsável."""


class BedrockOptimizationError(RuntimeError):
    """Raised when every configured Bedrock model fails."""


class _DecisionExplanationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=512)
    evidence_ids: list[str] = Field(min_length=1, max_length=32)
    limitations: list[str] = Field(min_length=1, max_length=16)


def _extract_text(response: dict[str, Any]) -> str:
    blocks = response.get("output", {}).get("message", {}).get("content", [])
    text = "".join(block.get("text", "") for block in blocks if isinstance(block, dict))
    if not text.strip():
        raise ValueError("Bedrock retornou uma resposta sem texto")
    return text.strip()


def _parse_recommendation(text: str, model_id: str) -> CurtailmentRecommendation:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1])
        if candidate.lstrip().startswith("json"):
            candidate = candidate.lstrip()[4:].lstrip()

    payload = json.loads(candidate)
    payload["modelo_bedrock_utilizado"] = model_id
    return CurtailmentRecommendation.model_validate(payload)


def optimize_with_bedrock(
    scenario: CurtailmentScenario,
    *,
    settings: Settings | None = None,
    client_factory: Callable[..., Any] = boto3.client,
) -> CurtailmentRecommendation:
    current_settings = settings or get_settings()
    client = client_factory("bedrock-runtime", region_name=current_settings.aws_region)
    model_ids = dict.fromkeys(
        (
            current_settings.bedrock_model_id,
            current_settings.bedrock_fallback_model_id,
            current_settings.bedrock_emergency_model_id,
        )
    )
    prompt = (
        "Analise o cenário a seguir e proponha a mitigação mais segura e explicável:\n"
        f"{scenario.model_dump_json()}"
    )

    failures: list[str] = []
    for model_id in model_ids:
        try:
            response = client.converse(
                modelId=model_id,
                system=[{"text": SYSTEM_PROMPT}],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 1000},
            )
            return _parse_recommendation(_extract_text(response), model_id)
        except (BotoCoreError, ClientError, ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "Falha ao usar modelo Bedrock %s (%s): %s",
                model_id,
                type(exc).__name__,
                exc,
            )
            failures.append(f"{model_id}: {type(exc).__name__}")

    raise BedrockOptimizationError(
        "Nenhum modelo Bedrock conseguiu gerar uma recomendação válida ("
        + "; ".join(failures)
        + ")"
    )


def _parse_json_text(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        candidate = "\n".join(lines[1:-1])
        if candidate.lstrip().startswith("json"):
            candidate = candidate.lstrip()[4:].lstrip()
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise ValueError("Bedrock decision explanation must be a JSON object")
    return value


def _validate_decision_explanation(
    text: str, model_id: str, allowed_evidence_ids: tuple[str, ...]
) -> DecisionExplanation:
    payload = _DecisionExplanationPayload.model_validate(_parse_json_text(text))
    evidence_ids = tuple(dict.fromkeys(payload.evidence_ids))
    if not set(evidence_ids).issubset(allowed_evidence_ids):
        raise ValueError("Bedrock cited evidence outside the supplied decision bundle")
    normalized_text = " ".join([payload.summary, *payload.limitations]).casefold()
    forbidden_claims = (
        "ons aprovou",
        "ons validou",
        "coordenação confirmada",
        "garante que",
        "garantia de",
    )
    if any(claim in normalized_text for claim in forbidden_claims):
        raise ValueError("Bedrock explanation asserted unsupported operational validation")
    return DecisionExplanation(
        summary=payload.summary,
        evidence_ids=evidence_ids,
        limitations=tuple(payload.limitations),
        generation_mode="bedrock",
        model_id=model_id,
    )


def deterministic_decision_explanation(
    decision_payload: dict[str, Any], evidence_ids: tuple[str, ...]
) -> DecisionExplanation:
    selected = decision_payload.get("selected_window")
    if selected:
        summary = (
            f"A janela {selected['start']} a {selected['end']} ficou em primeiro lugar "
            f"por minimizar a energia residual vendável estimada "
            f"({selected['residual_saleable_mwh']:.6f} MWh), incluindo a penalidade "
            f"de incerteza de {selected['uncertainty_penalty_mwh']:.6f} MWh."
        )
    else:
        summary = (
            "Nenhuma janela foi recomendada porque o estado público requer revisão "
            "ou porque todas as candidatas violaram critérios de elegibilidade."
        )
    return DecisionExplanation(
        summary=summary,
        evidence_ids=evidence_ids,
        limitations=(
            "Explicação determinística usada porque nenhuma resposta Bedrock válida foi obtida.",
            "As janelas são candidatas e não representam aprovação ou coordenação do ONS.",
        ),
        generation_mode="deterministic_fallback",
    )


def explain_maintenance_decision(
    decision_payload: dict[str, Any],
    evidence_ids: tuple[str, ...],
    *,
    settings: Settings | None = None,
    client_factory: Callable[..., Any] = boto3.client,
) -> DecisionExplanation:
    current_settings = settings or get_settings()
    client = client_factory(
        "bedrock-runtime",
        region_name=current_settings.aws_region,
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
    )
    model_ids = dict.fromkeys(
        (
            current_settings.bedrock_model_id,
            current_settings.bedrock_fallback_model_id,
            current_settings.bedrock_emergency_model_id,
        )
    )
    system_prompt = (
        "Explique em português a decisão determinística recebida. Não escolha nem altere "
        "a janela. Use somente os evidence_ids fornecidos. Não afirme aprovação, validação "
        "ou coordenação do ONS. Retorne somente JSON com summary, evidence_ids e limitations. "
        "O summary deve ter no máximo 350 caracteres e cada limitation no máximo 200."
    )
    prompt = canonical_json(
        {
            "decision": decision_payload,
            "allowed_evidence_ids": evidence_ids,
        }
    )
    for model_id in model_ids:
        try:
            response = client.converse(
                modelId=model_id,
                system=[{"text": system_prompt}],
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 800},
            )
            return _validate_decision_explanation(_extract_text(response), model_id, evidence_ids)
        except (BotoCoreError, ClientError, ValueError, KeyError, TypeError) as exc:
            logger.warning(
                "Falha na explicação de decisão com modelo %s (%s): %s",
                model_id,
                type(exc).__name__,
                exc,
            )
    return deterministic_decision_explanation(decision_payload, evidence_ids)
