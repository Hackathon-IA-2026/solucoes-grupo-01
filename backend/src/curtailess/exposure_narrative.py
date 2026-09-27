"""Section-scoped Bedrock interpretation for the Exposure screen.

The model may only interpret facts that the deterministic view already exposes. Each
section receives its own evidence subset, so a number that exists only in another
section is rejected for the section that cited it. One Bedrock Converse call covers the
six sections; a section that fails validation falls back deterministically on its own
without discarding the valid sibling sections.

Storage, caching and the public response projection are out of scope here: they belong to
the persistence and API tasks. Internal provenance labels never reach the model and are
rejected if a model echoes them.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from curtailess.bedrock import _extract_text, _parse_json_text
from curtailess.canonical import canonical_json
from curtailess.config import Settings, get_settings
from curtailess.schemas import (
    ExposureNarrative,
    ExposureNarrativeGenerationMode,
    ExposureNarrativeSection,
    ExposureViewResponse,
)

logger = logging.getLogger(__name__)

SECTION_IDS: tuple[str, ...] = (
    "secao-ativo",
    "secao-resumo",
    "secao-previsao",
    "secao-razao-origem",
    "secao-recorrencia",
    "secao-qualidade",
)

_SECTION_FIELDS: dict[str, str] = {
    "secao-ativo": "secao_ativo",
    "secao-resumo": "secao_resumo",
    "secao-previsao": "secao_previsao",
    "secao-razao-origem": "secao_razao_origem",
    "secao-recorrencia": "secao_recorrencia",
    "secao-qualidade": "secao_qualidade",
}

_MAX_TOKENS = 1600

# Provenance and lineage keys never belong to the interpretation facts, so they are
# stripped before the bundle reaches the model.
_PROVENANCE_KEYS = frozenset(
    {
        "origin",
        "simulation_method",
        "probability_source",
        "probability_status",
        "window_definition",
        "schema_version",
        "model_id",
        "input_digest",
        "source_sha256",
        "history_sha256",
        "input_manifest_digest",
        "source_artifact_schema",
        "envelope",
    }
)

# Technical labels that must never appear in customer-facing interpretation text.
_FORBIDDEN_LABELS_UPPER = (
    "ONS_PUBLICO",
    "PROXY_CALCULADO",
    "SIMULADO",
    "SIMULADO_FROM_ONS_HISTORY",
    "CLIENTE_INFORMADO",
)
_FORBIDDEN_TERMS = (
    "simulation_method",
    "input_digest",
    "source_sha",
    "hash",
    "prompt",
    "schema",
    "bucket",
    "método de rateio",
    "método de alocação",
    "origem técnica",
    "procedência",
)

# Claims that the deterministic view never supports.
_FORBIDDEN_CLAIMS = (
    "ons aprovou",
    "ons validou",
    "ons autorizou",
    "aprovação do ons",
    "validação do ons",
    "coordenação do ons",
    "coordenado pelo ons",
    "autorizado pelo ons",
    "telemetria scada",
    "telemetria privada",
    "dados scada",
    "scada",
    "limite físico confirmado",
    "capacidade física confirmada",
    "capacidade confirmada",
    "limite operacional confirmado",
    "capacidade instalada confirmada",
    "curtailment ocorrerá",
    "corte ocorrerá",
    "vai ocorrer",
    "irá ocorrer",
    "com certeza",
    "certamente",
    "sem dúvida",
    "garantia de",
    "garante que",
    "causa comprovada",
    "causa confirmada",
    "o ons causou",
    "causado pelo ons",
    "provocou o corte",
    "causou o corte",
    "recomenda-se manutenção",
    "recomenda-se bateria",
    "recomendamos manutenção",
    "recomendamos bateria",
    "manutenção recomendada",
    "acionar a bateria",
    "carregar a bateria",
    "operação real confirmada",
)

# Strong, unambiguous units. Prose words such as "dias" are intentionally excluded to
# avoid rejecting ordinary sentences; only a real unit substitution is rejected. Units are
# matched on alphanumeric boundaries so that "MWh" never authorizes "MW" by substring.
_KNOWN_UNITS = ("GWh", "MWh/dia", "MWh", "kWh", "MW", "kW", "m/s", "%", "pontos percentuais")


def _unit_pattern(unit: str) -> re.Pattern[str]:
    """Match a unit as a token, not as a substring of a longer unit or identifier."""

    if unit == "%":
        return re.compile(re.escape(unit))
    return re.compile(rf"(?<![0-9A-Za-z]){re.escape(unit)}(?![0-9A-Za-z])", re.IGNORECASE)


_UNIT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (unit, _unit_pattern(unit)) for unit in _KNOWN_UNITS
)


def _units_in(text: str) -> set[str]:
    return {unit for unit, pattern in _UNIT_PATTERNS if pattern.search(text)}


_NUMBER = re.compile(r"(?<![\w#])\d+(?:[.,]\d+)?")
_IDENTIFIER = re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b")

_SYSTEM_PROMPT = """Você escreve interpretações concisas em português para a aba Exposição.
Retorne somente um objeto JSON com estas seis chaves exatas: secao-ativo, secao-resumo,
secao-previsao, secao-razao-origem, secao-recorrencia e secao-qualidade. Cada chave deve
ser um objeto com a lista "paragraphs" contendo de 1 a 3 parágrafos curtos.
Cada seção recebe apenas as evidências dela; use somente esses fatos e não cite números,
unidades, nomes ou códigos que não apareçam na evidência da própria seção.
Não crie, arredonde ou altere números nem unidades. Não afirme causalidade, aprovação,
validação ou coordenação do ONS, telemetria privada ou SCADA, limite físico confirmado,
capacidade confirmada ou certeza sobre o futuro. Não recomende manutenção ou bateria.
Não mencione prompts, hashes, buckets, esquemas, métodos internos ou rótulos técnicos.
A previsão de 60 dias e a telemetria são possibilidades simuladas e demonstrativas, não
operações reais confirmadas. As razões publicadas pertencem ao conjunto e não devem ser
atribuídas à usina selecionada como causa comprovada."""


def _as_payload(view: ExposureViewResponse | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(view, ExposureViewResponse):
        payload = view.model_dump(mode="json", by_alias=True)
    else:
        payload = dict(view)
    payload.pop("narrative", None)
    payload.pop("input_digest", None)
    return payload


def _strip_provenance(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _strip_provenance(item)
            for key, item in value.items()
            if str(key) not in _PROVENANCE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_strip_provenance(item) for item in value]
    return value


def _evidence_payload(view: ExposureViewResponse | Mapping[str, Any]) -> dict[str, Any]:
    """Full deterministic evidence bundle, excluding the narrative and its digest."""

    return _as_payload(view)


def _section_evidence_payloads(
    view: ExposureViewResponse | Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Facts each Exposure section is allowed to cite, keyed by section id."""

    payload = _as_payload(view)
    asset = _strip_provenance(payload.get("asset") or {})
    observed = _strip_provenance(payload.get("observed_impact") or {})
    conditions = _strip_provenance(payload.get("associated_conditions") or {})
    recurrence = _strip_provenance(payload.get("recurrence") or {})
    quality = _strip_provenance(payload.get("quality") or {})
    point = _strip_provenance(payload.get("point_context") or {})
    telemetry = _strip_provenance(payload.get("simulated_telemetry") or {})
    forecast = _strip_provenance(payload.get("forecast_60d") or {})

    points = forecast.get("points") or []
    windows = forecast.get("critical_windows_72h") or []
    forecast_facts = {
        "status": forecast.get("status"),
        "start": forecast.get("start"),
        "end": forecast.get("end"),
        "point_count": len(points),
        "total_expected_mwh": forecast.get("total_expected_mwh"),
        "total_lower_mwh": forecast.get("total_lower_mwh"),
        "total_upper_mwh": forecast.get("total_upper_mwh"),
        "curtailment_probability_unit": "%",
        "critical_window_count": len(windows),
        "critical_windows_72h": windows,
        "points": points,
    }

    return {
        "secao-ativo": {
            "asset": asset,
            "last_data_update": payload.get("last_data_update"),
            "simulated_telemetry": telemetry,
        },
        "secao-resumo": {
            "asset": {
                key: asset.get(key)
                for key in ("asset_id", "name", "capacity_mw", "allocation_coverage")
            },
            "observed_impact": observed,
            "simulated_telemetry": {
                key: telemetry.get(key)
                for key in (
                    "operational_capacity_mw",
                    "potential_generation_mw",
                    "availability_mw",
                )
            },
        },
        "secao-previsao": {
            "forecast_60d": forecast_facts,
            "simulated_telemetry": {
                key: telemetry.get(key)
                for key in (
                    "potential_generation_mw",
                    "accepted_generation_limit_mw",
                    "weather_value",
                    "weather_unit",
                )
            },
            "point_context": {
                key: point.get(key)
                for key in (
                    "point_id",
                    "entity_count",
                    "installed_capacity_mw",
                    "potential_generation_mw",
                    "accepted_generation_envelope_mw",
                    "estimated_excess_mw",
                    "scheduled_maintenance_relief_mw",
                )
            },
        },
        "secao-razao-origem": {
            "associated_conditions": conditions,
            "observed_impact": {
                key: observed.get(key)
                for key in ("characterized_share", "simultaneous_share", "exclusive_share")
            },
            "point_context": {
                key: point.get(key)
                for key in (
                    "point_id",
                    "entity_count",
                    "scheduled_maintenance_relief_mw",
                    "scheduled_maintenance_window_count",
                    "simulated_entities",
                )
            },
        },
        "secao-recorrencia": {
            "recurrence": recurrence,
            "observed_impact": {
                key: observed.get(key)
                for key in ("curtailed_day_share", "period_start", "period_end")
            },
            "simulated_telemetry": {
                key: telemetry.get(key) for key in ("weather_value", "weather_unit")
            },
        },
        "secao-qualidade": {
            "quality": quality,
            "asset": {"allocation_coverage": asset.get("allocation_coverage")},
            "forecast_60d": {
                "status": forecast.get("status"),
                "point_count": len(points),
            },
            "limitations": payload.get("limitations"),
        },
    }


def _decimal(token: str) -> Decimal:
    try:
        return Decimal(token.replace(",", "."))
    except InvalidOperation:  # pragma: no cover - regex guarantees a numeric token
        raise ValueError(f"token numérico inválido: {token}") from None


def _evidence_numbers(evidence: Mapping[str, Any]) -> tuple[Decimal, ...]:
    serialized = canonical_json(evidence)
    return tuple(_decimal(token) for token in _NUMBER.findall(serialized))


def _reject_numbers(text: str, evidence: Mapping[str, Any]) -> None:
    """Reject any number that is not exactly a number the section evidence exposes.

    Comparison is numeric and exact after decimal-comma normalization: a truncated or
    rounded token such as ``81`` for evidence ``81.2775`` is not the same value and is
    rejected, so the narrative can never silently restate a fact at a different precision.
    """

    allowed = set(_evidence_numbers(evidence))
    unsupported = sorted(
        {token for token in _NUMBER.findall(text) if _decimal(token) not in allowed}
    )
    if unsupported:
        raise ValueError(
            "narrative cites numbers outside its section evidence: " + ", ".join(unsupported)
        )


def _reject_units(text: str, evidence: Mapping[str, Any]) -> None:
    allowed = _units_in(canonical_json(evidence))
    altered = sorted(_units_in(text) - allowed)
    if altered:
        raise ValueError("narrative alters a unit: " + ", ".join(altered))


def _reject_identifiers(text: str, evidence: Mapping[str, Any]) -> None:
    serialized = canonical_json(evidence)
    unknown = sorted({token for token in _IDENTIFIER.findall(text) if token not in serialized})
    if unknown:
        raise ValueError("narrative cites unknown identifiers: " + ", ".join(unknown))


def _reject_labels(text: str) -> None:
    for label in _FORBIDDEN_LABELS_UPPER:
        if label in text:
            raise ValueError(f"narrative exposes an internal label: {label}")
    folded = text.casefold()
    for term in _FORBIDDEN_TERMS:
        if term in folded:
            raise ValueError(f"narrative exposes an internal term: {term}")


_NEGATIONS = ("não", "nunca", "jamais", "sem", "tampouco", "nenhum", "nenhuma", "longe de")


def _reject_claims(text: str) -> None:
    folded = " ".join(text.casefold().split())
    for claim in _FORBIDDEN_CLAIMS:
        start = folded.find(claim)
        while start != -1:
            window = folded[max(0, start - 32) : start]
            if not any(cue in window.split() for cue in _NEGATIONS):
                raise ValueError(f"narrative asserts an unsupported claim: {claim}")
            start = folded.find(claim, start + 1)


def _validate_section_text(
    section_id: str, paragraphs: Sequence[str], evidence: Mapping[str, Any]
) -> tuple[str, ...]:
    """Validate one section only against its own evidence; raises ``ValueError``."""

    try:
        section = ExposureNarrativeSection(paragraphs=tuple(paragraphs), generation_mode="bedrock")
    except ValueError as exc:
        raise ValueError(f"seção {section_id} inválida: {exc}") from exc
    text = " ".join(section.paragraphs)
    _reject_labels(text)
    _reject_claims(text)
    _reject_numbers(text, evidence)
    _reject_units(text, evidence)
    _reject_identifiers(text, evidence)
    return section.paragraphs


def validate_section_narrative(
    section_id: str,
    paragraphs: Sequence[str],
    evidence: Mapping[str, Any],
    *,
    generation_mode: ExposureNarrativeGenerationMode = "bedrock",
) -> ExposureNarrativeSection:
    """Validate and normalize one section of model output."""

    if section_id not in SECTION_IDS:
        raise ValueError(f"seção desconhecida: {section_id}")
    normalized = _validate_section_text(section_id, paragraphs, evidence)
    return ExposureNarrativeSection(paragraphs=normalized, generation_mode=generation_mode)


def validate_exposure_narrative(
    value: Mapping[str, Any],
    evidence: ExposureViewResponse | Mapping[str, Any],
) -> ExposureNarrative:
    """Strictly validate a complete six-section narrative against the view evidence.

    Kept signature-compatible with the API layer, which re-validates a persisted
    narrative before serving it.
    """

    section_evidence = _section_evidence_payloads(evidence)
    narrative = ExposureNarrative.model_validate(value)
    for section_id, field in _SECTION_FIELDS.items():
        section = getattr(narrative, field)
        _validate_section_text(section_id, section.paragraphs, section_evidence[section_id])
    return narrative


def _extract_paragraphs(raw: Any) -> tuple[str, ...] | None:
    if isinstance(raw, (list, tuple)) and all(isinstance(item, str) for item in raw):
        return tuple(raw)
    if isinstance(raw, Mapping):
        paragraphs = raw.get("paragraphs")
        if isinstance(paragraphs, (list, tuple)) and all(
            isinstance(item, str) for item in paragraphs
        ):
            return tuple(paragraphs)
    return None


def _accepted_bedrock_sections(
    payload: Mapping[str, Any], section_evidence: Mapping[str, Mapping[str, Any]]
) -> dict[str, ExposureNarrativeSection]:
    accepted: dict[str, ExposureNarrativeSection] = {}
    for section_id in SECTION_IDS:
        paragraphs = _extract_paragraphs(payload.get(section_id))
        if paragraphs is None:
            logger.warning("Seção %s ausente ou malformada na resposta Bedrock", section_id)
            continue
        try:
            accepted[section_id] = validate_section_narrative(
                section_id, paragraphs, section_evidence[section_id]
            )
        except ValueError as exc:
            logger.warning("Seção %s rejeitada: %s", section_id, exc)
    return accepted


def _fmt(value: Any) -> str:
    """Render an evidence value exactly as canonical JSON serializes it.

    Exact number validation compares Decimal values, so the deterministic text must not
    round: a rounded token such as ``94987.3`` is not the evidence value ``94987.325407``.
    """

    if isinstance(value, float):
        return repr(value)
    return str(value)


def deterministic_exposure_narrative(
    view: ExposureViewResponse | Mapping[str, Any],
) -> ExposureNarrative:
    """Deterministic per-section fallback that consumes the same evidence bundle."""

    evidence = _section_evidence_payloads(view)
    return ExposureNarrative.model_validate(
        {
            section_id: _deterministic_section(section_id, evidence[section_id])
            for section_id in SECTION_IDS
        }
    )


def _deterministic_section(section_id: str, evidence: Mapping[str, Any]) -> dict[str, Any]:
    paragraphs = _deterministic_paragraphs(section_id, evidence)
    return {"paragraphs": list(paragraphs), "generation_mode": "deterministic_fallback"}


def _deterministic_paragraphs(section_id: str, evidence: Mapping[str, Any]) -> tuple[str, ...]:
    if section_id == "secao-ativo":
        asset = evidence["asset"]
        technology = "eólica" if asset.get("technology") == "wind" else "solar"
        group = ""
        if asset.get("ons_group_name") and asset.get("ons_group_id"):
            group = f", vinculada ao conjunto {asset['ons_group_name']} ({asset['ons_group_id']})"
        capacity = asset.get("capacity_mw")
        capacity_text = (
            f" A capacidade cadastrada é de {_fmt(capacity)} MW." if capacity is not None else ""
        )
        return (
            f"{asset.get('name')} é uma usina {technology} no estado {asset.get('state')}, "
            f"conectada ao ponto {asset.get('connection_point')}{group}." + capacity_text,
            "O estado operacional apresentado é uma estimativa construída a partir de dados "
            "públicos e de simulação demonstrativa, não de telemetria privada da usina.",
        )
    if section_id == "secao-resumo":
        observed = evidence["observed_impact"]
        total = (observed.get("total_curtailed_energy") or {}).get("value")
        start = observed.get("period_start")
        end = observed.get("period_end")
        if total is not None:
            first = (
                f"O histórico materializado registra {_fmt(total)} MWh de energia restringida "
                f"da própria usina entre {start} e {end}."
            )
        else:
            first = "O histórico detalhado ainda não está materializado neste ambiente."
        mean_30 = _fmt((observed.get("trailing_30_day_mean") or {}).get("value"))
        mean_7 = _fmt((observed.get("trailing_7_day_mean") or {}).get("value"))
        trailing = (
            f"A média recente é de {mean_30} MWh/dia nos últimos trinta dias e de "
            f"{mean_7} MWh/dia nos últimos sete dias."
        )
        return (
            first,
            trailing,
            "A frequência histórica de dias restritos é uma estimativa calculada a partir do "
            "histórico público da própria usina.",
        )
    if section_id == "secao-previsao":
        forecast = evidence["forecast_60d"]
        return (
            f"A projeção demonstrativa cobre {forecast.get('point_count')} dias, de "
            f"{forecast.get('start')} a {forecast.get('end')}.",
            f"A energia esperada total é de {_fmt(forecast.get('total_expected_mwh'))} MWh, com "
            f"faixa estimada entre {_fmt(forecast.get('total_lower_mwh'))} e "
            f"{_fmt(forecast.get('total_upper_mwh'))} MWh.",
            "As três janelas críticas de 72 horas concentram a maior exposição estimada; a "
            "previsão representa apenas uma possibilidade demonstrativa estimada e não uma "
            "ordem operacional futura.",
        )
    if section_id == "secao-razao-origem":
        conditions = evidence["associated_conditions"]
        if conditions.get("reasons"):
            first = (
                "As categorias publicadas pelo Operador Nacional do Sistema Elétrico descrevem "
                "as condições associadas aos cortes observados no conjunto."
            )
        else:
            first = (
                "A distribuição por razão ficará disponível após a materialização do histórico "
                "público do conjunto."
            )
        return (
            first,
            "As razões publicadas pertencem ao conjunto e não são atribuídas à usina "
            "selecionada como causa do corte.",
        )
    if section_id == "secao-recorrencia":
        recurrence = evidence["recurrence"]
        if recurrence.get("weekdays"):
            first = (
                "A distribuição por dia da semana usa a estimativa diária calculada a partir do "
                "histórico público da usina."
            )
        else:
            first = "A série disponível não sustenta uma distribuição temporal."
        return (
            first,
            "A leitura temporal disponível é por dia da semana e não por horário.",
        )
    quality = evidence["quality"]
    coverage = (quality.get("coverage") or {}).get("value")
    delay = (quality.get("update_delay") or {}).get("value")
    return (
        f"A cobertura calculada da série materializada é de {_fmt(coverage)}%.",
        f"A defasagem de atualização é de {_fmt(delay)} dias.",
        "A taxa de registros ausentes e a contagem de registros duplicados qualificam a "
        "leitura da série.",
    )


def _merge_sections(
    view: ExposureViewResponse | Mapping[str, Any],
    accepted: Mapping[str, ExposureNarrativeSection],
) -> ExposureNarrative:
    fallback = deterministic_exposure_narrative(view)
    merged: dict[str, ExposureNarrativeSection] = {}
    for section_id, field in _SECTION_FIELDS.items():
        merged[section_id] = accepted.get(section_id) or getattr(fallback, field)
    return ExposureNarrative.model_validate(merged)


def generate_exposure_narrative(
    view: ExposureViewResponse,
    *,
    settings: Settings | None = None,
    client_factory: Callable[..., Any] = boto3.client,
) -> tuple[ExposureNarrative, str | None]:
    """Interpret the six sections with one Converse call and validate each in isolation.

    Returns the narrative and the model that produced at least one accepted section, or
    ``None`` when every section fell back to the deterministic text.
    """

    current_settings = settings or get_settings()
    section_evidence = _section_evidence_payloads(view)
    client = client_factory(
        "bedrock-runtime",
        region_name=current_settings.aws_region,
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
    )
    prompt = canonical_json({"sections": section_evidence})
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
                inferenceConfig={"maxTokens": _MAX_TOKENS},
            )
        except (BotoCoreError, ClientError) as exc:
            logger.warning(
                "Transporte Bedrock falhou no modelo %s (%s): %s",
                model_id,
                type(exc).__name__,
                exc,
            )
            continue
        try:
            payload = _parse_json_text(_extract_text(response))
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "Resposta ilegível do modelo %s (%s): %s", model_id, type(exc).__name__, exc
            )
            # An unreadable response is a model-quality problem, not a transport failure:
            # retrying another model cannot fix it, so fall back deterministically now.
            return deterministic_exposure_narrative(view), None
        accepted = _accepted_bedrock_sections(payload, section_evidence)
        narrative = _merge_sections(view, accepted)
        return narrative, (model_id if accepted else None)
    return deterministic_exposure_narrative(view), None
