import json
import logging
from collections.abc import Callable
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .config import Settings, get_settings
from .schemas import CurtailmentRecommendation, CurtailmentScenario

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
