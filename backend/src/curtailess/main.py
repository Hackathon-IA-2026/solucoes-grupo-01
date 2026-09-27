import hashlib
import json
import re
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from . import __version__
from .artifacts import create_artifact_repository, serialize_report_body
from .bedrock import BedrockOptimizationError, optimize_with_bedrock
from .config import get_settings
from .data_access import create_exposure_repository
from .provenance import create_issued_provenance_repository
from .schemas import (
    ApiInfo,
    Asset,
    AssetList,
    BessScreenRequest,
    BessScreenResponse,
    CurtailmentRecommendation,
    CurtailmentScenario,
    DataOrigin,
    DataQualityResponse,
    EvidenceProvenance,
    ExposureResponse,
    HealthResponse,
    HistoricalWindow,
    HistoricalWindowsResponse,
    MaintenanceRankRequest,
    MaintenanceRankResponse,
    ModelRunResponse,
    MonetaryEvidence,
    NumericEvidence,
    Period,
    PointContextResponse,
    ProvenanceResponse,
    RankedMaintenanceWindow,
    ReportCreateRequest,
    ReportFileResponse,
    ReportResponse,
    build_evidence_id,
    parse_evidence_id,
)

settings = get_settings()
repository = create_exposure_repository(settings.exposure_table, settings.aws_region)
artifact_repository = create_artifact_repository(
    settings.scenarios_table, settings.data_bucket, settings.aws_region
)
issued_provenance_repository = create_issued_provenance_repository(
    settings.scenarios_table, settings.aws_region
)


def _aware(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _field_provenance(
    *,
    field_name: str,
    method_version: str,
    context: str,
    origin: DataOrigin,
    limitations: list[str],
    source_hashes: list[str] | tuple[str, ...] = (),
    source_item: dict | None = None,
    source_uri: str | None = None,
    source_key: str | None = None,
    use_source_period: bool = True,
    observed_at: datetime | None = None,
    effective_at: datetime | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    parent_evidence_ids: list[str] | tuple[str, ...] = (),
) -> EvidenceProvenance:
    hashes = tuple(sorted(set(source_hashes)))
    identities = list(hashes) or [source_uri or "curtailess://unspecified"]
    evidence_id = build_evidence_id(identities, field_name, method_version, context)
    period_item = source_item if source_item and use_source_period else None
    observed_at = observed_at or (_aware(period_item["period_end"]) if period_item else None)
    valid_from = valid_from or (_aware(period_item["period_start"]) if period_item else None)
    valid_to = valid_to or (_aware(period_item["period_end"]) if period_item else None)
    return EvidenceProvenance(
        evidence_id=evidence_id,
        field_name=field_name,
        origin=origin,
        source_uri=source_uri,
        source_key=source_key or (source_item.get("source_key") if source_item else None),
        source_sha256=hashes[0] if hashes else None,
        source_sha256s=hashes,
        parent_evidence_ids=tuple(sorted(set(parent_evidence_ids))),
        observed_at=observed_at,
        effective_at=effective_at
        or (observed_at if origin is not DataOrigin.ONS_PUBLICO else None),
        valid_from=valid_from,
        valid_to=valid_to,
        method_version=method_version,
        limitations=limitations,
    )


# Only these server-emitted field/method pairs are resolvable through the public audit API.
# The ID payload is an index into this registry, never authority for origin or classification.
_SERVER_PROVENANCE_CONTRACTS: dict[
    tuple[str, str], tuple[DataOrigin, Literal["medido", "calculado"]]
] = {
    ("capacity_mw", "ons_capacity_source_v1"): (DataOrigin.ONS_PUBLICO, "medido"),
    ("capacity_mw", "asset_capacity_unavailable_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    **{
        (field_name, "ons_materialized_asset_v1"): (DataOrigin.ONS_PUBLICO, "medido")
        for field_name in ("asset_id", "name", "technology", "ons_group", "connection_point")
    },
    ("total_curtailed_energy", "curtailed_energy_sum_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("anonymized_entity_count", "point_context_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("simultaneity_rate", "historical_simultaneity_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("expected_curtailed_energy", "monthly_observed_rate_prorated_to_window_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("expected_curtailed_energy", "monthly_observed_reason_rate_prorated_to_window_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("rank", "maintenance_rank_v1"): (DataOrigin.PROXY_CALCULADO, "calculado"),
    ("start", "maintenance_window_boundary_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("end", "maintenance_window_boundary_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("opportunity_cost", "opportunity_cost_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("difference_from_baseline_mwh", "maintenance_difference_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("difference_from_baseline", "maintenance_difference_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("residual_exposure_source", "curtailed_energy_sum_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    **{
        (field_name, "bess_screen_v1"): (DataOrigin.PROXY_CALCULADO, "calculado")
        for field_name in (
            "residual_exposure_mwh",
            "technically_absorbable_mwh",
            "annual_benefit_brl",
            "annual_net_benefit_brl",
            "preliminary_viable",
        )
    },
}


def _json_context(kind: str, **values: object) -> str:
    return json.dumps({"kind": kind, **values}, sort_keys=True, separators=(",", ":"))


def _candidate_from_repository(identity: dict, items: list[dict]) -> EvidenceProvenance | None:
    """Regenerate a canonical emitted fact from current repository rows."""

    field = identity["field"]
    method = identity["method"]
    context = identity["context"]
    hashes = identity["sources"]
    if _requires_issued_record(identity):
        return None
    limitation = "Linhagem de campo da materialização; o manifesto bruto permanece privado no S3."

    if method in {
        "ons_materialized_asset_v1",
        "ons_capacity_source_v1",
        "asset_capacity_unavailable_v1",
    }:
        item = repository.get_asset(context)
        if item is None:
            return None
        asset = materialized_asset(item)
        return asset.field_provenance.get(field)

    exposure_match = re.fullmatch(
        r"(?P<asset>[^:]+):(?P<start>\d{4}-\d{2}-\d{2}):"
        r"(?P<end>\d{4}-\d{2}-\d{2}):(?P<reason>all|ENE|REL|CNF)",
        context,
    )
    if field == "total_curtailed_energy" and method == "curtailed_energy_sum_v1":
        if exposure_match is None:
            return None
        start = date.fromisoformat(exposure_match["start"])
        end = date.fromisoformat(exposure_match["end"])
        reason = exposure_match["reason"]
        exposure = repository.get_exposure(
            exposure_match["asset"], start, end, None if reason == "all" else reason
        )
        if exposure is None:
            return None
        return _field_provenance(
            field_name=field,
            method_version=method,
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[
                "Agregado mensal materializado de dados públicos do ONS; períodos mensais "
                "sobrepostos são incluídos integralmente."
            ],
            source_hashes=exposure["source_sha256s"],
            source_item=exposure["items"][0],
            source_uri=f"curtailess://assets/{exposure_match['asset']}/exposure",
            observed_at=max(_aware(item["period_end"]) for item in exposure["items"]),
            valid_from=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
            valid_to=datetime.combine(end, datetime.max.time(), tzinfo=UTC),
        )

    if field == "residual_exposure_source" and method == "curtailed_energy_sum_v1":
        item = items[0]
        expected_context = f"{item['asset_id']}:{item['period']}"
        if context != expected_context:
            return None
        return _field_provenance(
            field_name=field,
            method_version=method,
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=["Agregado mensal curado e calculado a partir de observações públicas."],
            source_hashes=hashes,
            source_item=item,
            source_uri=f"curtailess://assets/{item['asset_id']}/materialized-exposure",
        )

    try:
        structured = json.loads(context)
    except (TypeError, json.JSONDecodeError):
        structured = None
    if isinstance(structured, dict) and structured.get("kind") == "historical_window":
        try:
            asset_id = structured["asset_id"]
            start = datetime.fromisoformat(structured["start"])
            end = datetime.fromisoformat(structured["end"])
            reason = structured["reason"]
            duration = int((end - start).total_seconds() / 3600)
        except (KeyError, TypeError, ValueError):
            return None
        if reason not in {None, "ENE", "REL", "CNF"} or duration <= 0:
            return None
        asset_item = repository.get_asset(asset_id)
        if asset_item is None:
            return None
        windows = repository.get_historical_windows(
            asset_id, start.date(), end.date(), duration, reason
        )
        window = next(
            (
                value
                for value in windows
                if value["start"] == start
                and value["end"] == end
                and value["method"] == method
                and value["source_sha256"] in hashes
            ),
            None,
        )
        if window is None:
            return None
        return _field_provenance(
            field_name=field,
            method_version=method,
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[
                "Sinal derivado da taxa mensal histórica materializada; não é previsão "
                "operacional ex ante nem preserva a distribuição intramensal."
            ],
            source_hashes=[window["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://assets/{asset_id}/windows",
        )

    if isinstance(structured, dict) and structured.get("kind") == "maintenance_rank":
        try:
            asset_id = structured["asset_id"]
            candidate_start = datetime.fromisoformat(structured["candidate_start"])
            candidate_end = datetime.fromisoformat(structured["candidate_end"])
            baseline_start = datetime.fromisoformat(structured["baseline_start"])
            request_start = date.fromisoformat(structured["request_start"])
            request_end = date.fromisoformat(structured["request_end"])
            input_ids = structured["input_evidence_ids"]
            duration = int((candidate_end - candidate_start).total_seconds() / 3600)
        except (KeyError, TypeError, ValueError):
            return None
        if not isinstance(input_ids, dict) or duration <= 0:
            return None
        asset_item = repository.get_asset(asset_id)
        if asset_item is None:
            return None
        candidates = repository.get_historical_windows(
            asset_id, request_start, request_end, duration
        )
        candidate = next(
            (
                value
                for value in candidates
                if value["start"] == candidate_start and value["end"] == candidate_end
            ),
            None,
        )
        if candidate is None:
            return None
        baseline_candidate = min(candidates, key=lambda value: abs(value["start"] - baseline_start))
        rank_limitation = (
            "Ranking baseado em taxa mensal histórica materializada do ONS: não é previsão "
            "operacional e não preserva a distribuição intramensal; não coordena nem revela "
            "manutenções de terceiros."
        )

        def energy_provenance(value: dict) -> EvidenceProvenance:
            return _field_provenance(
                field_name="expected_curtailed_energy",
                method_version=value["method"],
                context=_json_context(
                    "maintenance_rank",
                    asset_id=asset_id,
                    candidate_start=value["start"].isoformat(),
                    candidate_end=value["end"].isoformat(),
                    baseline_start=baseline_start.isoformat(),
                    request_start=request_start.isoformat(),
                    request_end=request_end.isoformat(),
                    input_evidence_ids=input_ids,
                ),
                origin=DataOrigin.PROXY_CALCULADO,
                limitations=[rank_limitation],
                source_hashes=[value["source_sha256"]],
                source_item=asset_item,
                source_uri=f"curtailess://maintenance/{asset_id}/rank",
            )

        energy = energy_provenance(candidate)
        baseline_energy = energy_provenance(baseline_candidate)
        if method.startswith("monthly_observed_") and field == "expected_curtailed_energy":
            return energy
        if method == "opportunity_cost_v1" and field == "opportunity_cost":
            parents = [energy.evidence_id, input_ids.get("energy_price", "")]
            source_hashes = [candidate["source_sha256"]]
        elif method == "maintenance_difference_v1" and field in {
            "difference_from_baseline",
            "difference_from_baseline_mwh",
        }:
            parents = [energy.evidence_id, baseline_energy.evidence_id]
            source_hashes = [candidate["source_sha256"], baseline_candidate["source_sha256"]]
        elif method in {"maintenance_rank_v1", "maintenance_window_boundary_v1"}:
            parents = [energy.evidence_id, *input_ids.values()]
            source_hashes = [candidate["source_sha256"]]
        else:
            return None
        if any(not parent for parent in parents):
            return None
        return _field_provenance(
            field_name=field,
            method_version=method,
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[rank_limitation],
            source_hashes=source_hashes,
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{asset_id}/rank",
            parent_evidence_ids=parents,
        )

    if isinstance(structured, dict) and structured.get("kind") == "bess_screen":
        asset_id = structured.get("asset_id")
        parent_ids = structured.get("parent_evidence_ids")
        if not isinstance(asset_id, str) or not isinstance(parent_ids, list):
            return None
        item = repository.get_asset(asset_id)
        if item is None or [item["source_sha256"]] != hashes:
            return None
        source_observation = _field_provenance(
            field_name="residual_exposure_source",
            method_version="curtailed_energy_sum_v1",
            context=f"{asset_id}:{item['period']}",
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=["Agregado mensal curado e calculado a partir de observações públicas."],
            source_hashes=hashes,
            source_item=item,
            source_uri=f"curtailess://assets/{asset_id}/materialized-exposure",
        )
        if source_observation.evidence_id not in parent_ids:
            return None
        return _field_provenance(
            field_name=field,
            method_version=method,
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[
                "Triagem determinística sobre exposição histórica: não é dimensionamento, "
                "previsão de despacho ou garantia de corte evitado."
            ],
            source_hashes=hashes,
            source_item=item,
            source_uri=f"curtailess://bess/{asset_id}/screen",
            parent_evidence_ids=parent_ids,
        )

    # Point-context facts can be regenerated from the current point aggregation.
    if method in {"point_context_v1", "historical_simultaneity_v1"}:
        asset_id = context.split(":", 1)[0]
        item = repository.get_asset(asset_id)
        point = repository.get_point_context(asset_id)
        if item is None or point is None:
            return None
        expected_context = (
            f"{asset_id}:{point['connection_point']}:{point['period_start']}:{point['period_end']}"
        )
        if context != expected_context:
            return None
        return _field_provenance(
            field_name=field,
            method_version=method,
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[
                "Agregado materializado sem nomes ou planos de terceiros; conexões cadastrais "
                "não comprovam limite, folga ou causalidade elétrica."
            ],
            source_hashes=point["source_sha256s"],
            source_item=item,
            source_uri=f"curtailess://assets/{asset_id}/point-context",
        )

    # Window facts must map to a real row start and a positive duration.
    if method.startswith("monthly_observed_"):
        item = items[0]
        asset_id = item["asset_id"]
        prefix = f"{asset_id}:"
        if not context.startswith(prefix):
            return None
        remainder = context[len(prefix) :]
        timestamps = re.fullmatch(r"(.+?\+00:00):(.+?\+00:00)", remainder)
        if timestamps is None:
            return None
        start = datetime.fromisoformat(timestamps[1])
        end = datetime.fromisoformat(timestamps[2])
        duration = int((end - start).total_seconds() / 3600)
        if duration <= 0:
            return None
        windows = repository.get_historical_windows(
            asset_id,
            start.date(),
            end.date(),
            duration,
            "ENE" if method.endswith("reason_rate_prorated_to_window_v1") else None,
        )
        if not any(
            window["start"] == start
            and window["end"] == end
            and window["source_sha256"] in hashes
            and window["method"] == method
            for window in windows
        ):
            return None
        return _field_provenance(
            field_name=field,
            method_version=method,
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=hashes,
            source_item=item,
            source_uri=f"curtailess://assets/{asset_id}/windows",
        )
    return None


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _issued_record(
    *,
    operation: str,
    request: MaintenanceRankRequest | BessScreenRequest,
    output: dict[str, object],
    provenance: EvidenceProvenance,
    source_item: dict,
) -> dict[str, object]:
    evidence_digest = hashlib.sha256(provenance.evidence_id.encode("utf-8")).hexdigest()
    return {
        "plant_id": "PROVENANCE",
        "scenario_id": f"evidence#{evidence_digest}",
        "evidence_id": provenance.evidence_id,
        "record_type": "issued_provenance",
        "operation": operation,
        "request_json": _canonical_json(request.model_dump(mode="json")),
        "output_json": _canonical_json(output),
        "provenance": provenance.model_dump(mode="json"),
        "source_item": {
            "asset_id": source_item["asset_id"],
            "asset_ids": [source_item["asset_id"]],
            "period": source_item["period"],
            "source_bucket": source_item.get("source_bucket", "ons-aws-prod-opendata"),
            "source_key": source_item["source_key"],
            "method": source_item.get("method", provenance.method_version),
        },
    }


def _requires_issued_record(identity: dict) -> bool:
    if identity["field"] == "residual_exposure_source" or identity["method"] == "bess_screen_v1":
        return True
    if identity["method"] in {
        "maintenance_rank_v1",
        "maintenance_window_boundary_v1",
        "opportunity_cost_v1",
        "maintenance_difference_v1",
    }:
        return True
    try:
        context = json.loads(identity["context"])
    except (TypeError, json.JSONDecodeError):
        return False
    return isinstance(context, dict) and context.get("kind") in {"maintenance_rank", "bess_screen"}


def _resolve_issued_evidence(
    evidence_id: str,
    identity: dict,
    contract: tuple[DataOrigin, Literal["medido", "calculado"]],
) -> tuple[dict, DataOrigin, Literal["medido", "calculado"], list[dict], EvidenceProvenance]:
    record = issued_provenance_repository.get(evidence_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Fato derivado não emitido.")
    try:
        candidate = EvidenceProvenance.model_validate(record["provenance"])
        candidate_identity = parse_evidence_id(candidate.evidence_id)
        source_item = record["source_item"]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Registro de proveniência inválido.") from exc
    origin, classification = contract
    if (
        candidate.evidence_id != evidence_id
        or candidate_identity != identity
        or candidate.origin is not origin
        or not isinstance(source_item, dict)
    ):
        raise HTTPException(status_code=404, detail="Registro de proveniência inconsistente.")
    return identity, origin, classification, [source_item], candidate


def _resolve_server_evidence(
    evidence_id: str,
) -> tuple[
    dict,
    DataOrigin,
    Literal["medido", "calculado"],
    list[dict],
    EvidenceProvenance,
]:
    try:
        identity = parse_evidence_id(evidence_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Proveniência não reconhecida.") from exc
    contract = _SERVER_PROVENANCE_CONTRACTS.get((identity["field"], identity["method"]))
    if contract is None:
        raise HTTPException(status_code=404, detail="Contrato de proveniência não reconhecido.")
    source_hashes = identity["sources"]
    if any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in source_hashes
    ):
        raise HTTPException(status_code=404, detail="Proveniência externa não materializada.")
    if _requires_issued_record(identity):
        return _resolve_issued_evidence(evidence_id, identity, contract)
    source_items = [repository.get_provenance(value) for value in source_hashes]
    if any(item is None for item in source_items):
        raise HTTPException(status_code=404, detail="Proveniência não encontrada.")
    materialized_items = [item for item in source_items if item is not None]
    candidate = _candidate_from_repository(identity, materialized_items)
    if candidate is None or candidate.evidence_id != evidence_id:
        raise HTTPException(status_code=404, detail="Fato de proveniência não materializado.")
    origin, classification = contract
    if candidate.origin is not origin:
        raise HTTPException(status_code=404, detail="Origem de proveniência inconsistente.")
    return identity, origin, classification, materialized_items, candidate


def _validate_caller_provenance(provenances: dict[str, EvidenceProvenance]) -> None:
    for provenance in provenances.values():
        if provenance.origin is DataOrigin.CLIENTE_INFORMADO:
            continue
        if provenance.origin is DataOrigin.SIMULADO:
            raise HTTPException(
                status_code=422, detail="Proveniência simulada não é entrada confiável."
            )
        try:
            identity, origin, _, _, candidate = _resolve_server_evidence(provenance.evidence_id)
        except HTTPException as exc:
            raise HTTPException(
                status_code=422,
                detail="Alegação de proveniência pública/calculada não pôde ser resolvida.",
            ) from exc
        if (
            provenance.origin is not origin
            or provenance.field_name != identity["field"]
            or provenance.method_version != identity["method"]
            or tuple(identity["sources"]) != provenance.source_sha256s
            or provenance != candidate
        ):
            raise HTTPException(
                status_code=422,
                detail="Metadados de proveniência não correspondem ao contrato do servidor.",
            )


_DEMO_FIELDS = {
    field_name: _field_provenance(
        field_name=field_name,
        method_version="demo_fixture_v1",
        context="demo-wind-ne-001",
        origin=DataOrigin.SIMULADO,
        limitations=["Campo fictício usado somente na demonstração."],
        source_uri=f"curtailess://demo/assets/demo-wind-ne-001/{field_name}",
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    for field_name in (
        "asset_id",
        "name",
        "technology",
        "capacity_mw",
        "ons_group",
        "connection_point",
    )
}
DEMO_ASSET = Asset(
    asset_id="demo-wind-ne-001",
    name="Ativo eólico de demonstração",
    technology="wind",
    capacity_mw=100.0,
    capacity_provenance=_DEMO_FIELDS["capacity_mw"],
    ons_group="Conjunto anonimizado NE-001",
    connection_point="Ponto cadastral anonimizado NE-001",
    data_mode="demo",
    field_provenance=_DEMO_FIELDS,
)

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="API para previsao de curtailment e planejamento de manutencao.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=ApiInfo, tags=["system"])
def api_info() -> ApiInfo:
    return ApiInfo(
        name=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        docs="/docs",
    )


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(
        service=settings.app_name,
        version=__version__,
        environment=settings.app_env,
    )


def get_demo_asset(asset_id: str) -> Asset:
    if asset_id != DEMO_ASSET.asset_id:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    return DEMO_ASSET


def _optional_aware(item: dict, key: str) -> datetime | None:
    value = item.get(key)
    return _aware(value) if value else None


def materialized_asset(item: dict) -> Asset:
    asset_id = item["asset_id"]
    capacity = item.get("capacity_mw")
    common_limitations = ["Campo cadastral materializado de fonte pública do ONS."]
    field_provenance = {
        field_name: _field_provenance(
            field_name=field_name,
            method_version="ons_materialized_asset_v1",
            context=asset_id,
            origin=DataOrigin.ONS_PUBLICO,
            limitations=common_limitations,
            source_hashes=[item["source_sha256"]],
            source_item=item,
            source_uri="s3://ons-aws-prod-opendata/dataset/restricao_coff_eolica_tm/",
        )
        for field_name in ("asset_id", "name", "technology", "ons_group", "connection_point")
    }
    capacity_provenance = None
    if capacity is not None:
        capacity_limitations = list(item.get("capacity_limitations", []))
        capacity_valid_from = _optional_aware(item, "capacity_valid_from")
        capacity_valid_to = _optional_aware(item, "capacity_valid_to")
        capacity_observed_at = _optional_aware(item, "capacity_observed_at")
        capacity_effective_at = _optional_aware(item, "capacity_effective_at")
        if not capacity_observed_at and not capacity_effective_at:
            capacity_limitations.append(
                "Metadados de validade temporal da fonte de capacidade indisponíveis; "
                "validade aberta/desconhecida."
            )
        if bool(capacity_valid_from) != bool(capacity_valid_to):
            capacity_limitations.append(
                "Intervalo temporal da capacidade incompleto; validade tratada como "
                "aberta/desconhecida."
            )
            capacity_valid_from = capacity_valid_to = None
        capacity_provenance = _field_provenance(
            field_name="capacity_mw",
            method_version="ons_capacity_source_v1",
            context=asset_id,
            origin=DataOrigin.ONS_PUBLICO,
            limitations=capacity_limitations,
            source_hashes=[item["capacity_source_sha256"]],
            source_uri="s3://ons-aws-prod-opendata/dataset/capacidade-geracao/",
            source_key=item["capacity_source_key"],
            use_source_period=False,
            observed_at=capacity_observed_at,
            effective_at=capacity_effective_at,
            valid_from=capacity_valid_from,
            valid_to=capacity_valid_to,
        )
        field_provenance["capacity_mw"] = capacity_provenance
    else:
        field_provenance["capacity_mw"] = _field_provenance(
            field_name="capacity_mw",
            method_version="asset_capacity_unavailable_v1",
            context=asset_id,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=["Capacidade não materializada para este ativo."],
            source_hashes=[item["source_sha256"]],
            source_item=item,
            source_uri=f"curtailess://assets/{asset_id}",
        )
    return Asset(
        asset_id=asset_id,
        name=item["asset_name"],
        technology="wind",
        capacity_mw=capacity,
        capacity_provenance=capacity_provenance,
        ons_group=asset_id,
        connection_point=item["point_id"],
        data_mode="ons_materialized",
        field_provenance=field_provenance,
    )


@app.get("/v1/assets", response_model=AssetList, tags=["assets"])
def list_assets() -> AssetList:
    return AssetList(items=[materialized_asset(item) for item in repository.list_assets()])


@app.get("/v1/assets/{asset_id}", response_model=Asset, tags=["assets"])
def get_asset(asset_id: str) -> Asset:
    item = repository.get_asset(asset_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    return materialized_asset(item)


@app.get(
    "/v1/data-quality/{asset_id}",
    response_model=DataQualityResponse,
    tags=["audit"],
)
def get_data_quality(asset_id: str) -> DataQualityResponse:
    item = repository.get_data_quality(asset_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Qualidade de dados não encontrada.")
    start = date.fromisoformat(item["period_start"][:10])
    end = date.fromisoformat(item["period_end"][:10])
    expected = ((end - start).days + 1) * 48
    observed = int(item["interval_count"])
    limitation = (
        "Contagens de nulos e duplicatas ainda não materializadas; cobertura calculada "
        "sobre intervalos esperados de 30 minutos no período."
    )
    return DataQualityResponse(
        asset_id=asset_id,
        validation_status="valid",
        period=Period(start=start, end=end),
        observed_interval_count=observed,
        expected_interval_count=expected,
        coverage_percent=round(min(observed / expected * 100, 100.0), 6),
        null_count=None,
        duplicate_count=None,
        source="ONS/restricao_coff_eolica_tm",
        source_sha256=item["source_sha256"],
        limitations=[limitation],
    )


@app.get(
    "/v1/provenances/{provenance_id}",
    response_model=ProvenanceResponse,
    tags=["audit"],
)
def get_provenance(provenance_id: str) -> ProvenanceResponse:
    identity, origin, classification, items, provenance = _resolve_server_evidence(provenance_id)
    source_hashes = identity["sources"]
    item = items[0]
    source_key = provenance.source_key or item["source_key"]
    dataset = next(
        (
            dataset_id
            for dataset_id in (
                "capacidade-geracao",
                "usina_conjunto",
                "restricao_coff_eolica_tm",
                "restricao_coff_fotovoltaica_tm",
                "programacao_x_previsao",
                "geracao_usina_2_ho",
            )
            if f"/{dataset_id}/" in f"/{source_key}"
        ),
        "restricao_coff_eolica_tm",
    )
    limitation = "Linhagem de campo da materialização; o manifesto bruto permanece privado no S3."
    asset_ids = sorted(
        {
            asset_id
            for source_item in items
            for asset_id in source_item.get("asset_ids", [source_item["asset_id"]])
        }
    )
    return ProvenanceResponse(
        provenance_id=provenance_id,
        evidence_id=provenance_id,
        classification=classification,
        origin=provenance.origin,
        dataset=dataset,
        source=f"ONS/{dataset}",
        source_bucket=item.get("source_bucket", "ons-aws-prod-opendata"),
        source_key=source_key,
        source_sha256=source_hashes[0],
        source_sha256s=source_hashes,
        data_version=(
            item.get("capacity_data_version", "snapshot")
            if dataset == "capacidade-geracao"
            else ",".join(sorted({source_item["period"] for source_item in items}))
        ),
        method=item.get("capacity_method", item.get("method", identity["method"])),
        method_version=identity["method"],
        field_name=identity["field"],
        observed_at=provenance.observed_at,
        effective_at=provenance.effective_at,
        valid_from=provenance.valid_from,
        valid_to=provenance.valid_to,
        asset_ids=asset_ids,
        parent_evidence_ids=list(provenance.parent_evidence_ids),
        limitations=provenance.limitations or [limitation],
        provenance=provenance,
    )


@app.get(
    "/v1/assets/{asset_id}/exposure",
    response_model=ExposureResponse,
    tags=["exposure"],
)
def get_asset_exposure(
    asset_id: str,
    start: Annotated[date, "query"],
    end: Annotated[date, "query"],
    granularity: Literal["period", "day", "hour", "30min"] = "period",
    reason: Literal["ENE", "REL", "CNF"] | None = None,
    technology: Literal["wind", "solar"] = "wind",
) -> ExposureResponse:
    if start > end:
        raise HTTPException(status_code=422, detail="start deve ser anterior ou igual a end.")
    if repository.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    if granularity != "period":
        raise HTTPException(status_code=422, detail="Apenas granularity=period está materializada.")
    if technology != "wind":
        raise HTTPException(status_code=422, detail="Apenas technology=wind está materializada.")
    exposure = repository.get_exposure(asset_id, start, end, reason)
    if exposure is None:
        raise HTTPException(status_code=404, detail="Sem dados materializados para o período.")

    limitation = (
        "Agregado mensal materializado de dados públicos do ONS; períodos mensais "
        "sobrepostos são incluídos integralmente."
    )
    first_item = exposure["items"][0]
    data_version = ",".join(exposure["periods"])
    method_version = "curtailed_energy_sum_v1"
    provenance = _field_provenance(
        field_name="total_curtailed_energy",
        method_version=method_version,
        context=f"{asset_id}:{start}:{end}:{reason or 'all'}",
        origin=DataOrigin.PROXY_CALCULADO,
        limitations=[limitation],
        source_hashes=exposure["source_sha256s"],
        source_item=first_item,
        source_uri=f"curtailess://assets/{asset_id}/exposure",
        observed_at=max(_aware(item["period_end"]) for item in exposure["items"]),
        valid_from=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        valid_to=datetime.combine(end, datetime.max.time(), tzinfo=UTC),
    )
    return ExposureResponse(
        asset_id=asset_id,
        perspective_type="historical_observed",
        data_mode="ons_materialized",
        granularity="period",
        reason=reason,
        technology="wind",
        total_curtailed_energy=NumericEvidence(
            value=float(exposure["curtailed_mwh"]),
            unit="MWh",
            period=Period(start=start, end=end),
            source="ONS/restricao_coff_eolica_tm",
            data_version=data_version,
            method=first_item["method"],
            value_status="calculado",
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            provenance_id=provenance.evidence_id,
            provenance=provenance,
        ),
        limitations=[limitation],
    )


@app.get(
    "/v1/assets/{asset_id}/point-context",
    response_model=PointContextResponse,
    tags=["exposure"],
)
def get_asset_point_context(asset_id: str) -> PointContextResponse:
    asset_item = repository.get_asset(asset_id)
    if asset_item is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    context = repository.get_point_context(asset_id)
    if context is None:
        raise HTTPException(status_code=404, detail="Contexto materializado não encontrado.")
    period = Period(
        start=date.fromisoformat(context["period_start"]),
        end=date.fromisoformat(context["period_end"]),
    )
    limitation = (
        "Agregado materializado sem nomes ou planos de terceiros; conexões cadastrais não "
        "comprovam limite, folga ou causalidade elétrica."
    )
    simultaneity_rate = (
        round(context["limited_entity_count"] / context["entity_count"] * 100, 6)
        if context["entity_count"]
        else 0
    )
    entity_provenance = _field_provenance(
        field_name="anonymized_entity_count",
        method_version="point_context_v1",
        context=f"{asset_id}:{context['connection_point']}:{period.start}:{period.end}",
        origin=DataOrigin.PROXY_CALCULADO,
        limitations=[limitation],
        source_hashes=context["source_sha256s"],
        source_item=asset_item,
        source_uri=f"curtailess://assets/{asset_id}/point-context",
    )
    simultaneity_provenance = _field_provenance(
        field_name="simultaneity_rate",
        method_version="historical_simultaneity_v1",
        context=f"{asset_id}:{context['connection_point']}:{period.start}:{period.end}",
        origin=DataOrigin.PROXY_CALCULADO,
        limitations=[limitation],
        source_hashes=context["source_sha256s"],
        source_item=asset_item,
        source_uri=f"curtailess://assets/{asset_id}/point-context",
    )
    return PointContextResponse(
        asset_id=asset_id,
        connection_point=context["connection_point"],
        data_mode="ons_materialized",
        anonymized_entity_count=NumericEvidence(
            value=context["entity_count"],
            unit="entities",
            period=period,
            source="ONS/usina_conjunto",
            data_version=context["data_version"],
            method="point_context_v1",
            value_status="calculado",
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            provenance_id=entity_provenance.evidence_id,
            provenance=entity_provenance,
        ),
        simultaneity_rate=NumericEvidence(
            value=simultaneity_rate,
            unit="%",
            period=period,
            source="ONS/restricao_coff_eolica_tm",
            data_version=context["data_version"],
            method="historical_simultaneity_v1",
            value_status="calculado",
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            provenance_id=simultaneity_provenance.evidence_id,
            provenance=simultaneity_provenance,
        ),
        physical_limit_available=False,
        limitations=[limitation],
    )


@app.get(
    "/v1/assets/{asset_id}/windows",
    response_model=HistoricalWindowsResponse,
    tags=["exposure"],
)
def get_asset_windows(
    asset_id: str,
    start: Annotated[date, "query"],
    end: Annotated[date, "query"],
    duration_hours: Annotated[int, "query"] = 72,
    reason: Literal["ENE", "REL", "CNF"] | None = None,
) -> HistoricalWindowsResponse:
    if start > end:
        raise HTTPException(status_code=422, detail="start deve ser anterior ou igual a end.")
    if duration_hours <= 0:
        raise HTTPException(status_code=422, detail="duration_hours deve ser positivo.")
    asset_item = repository.get_asset(asset_id)
    if asset_item is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    materialized_windows = repository.get_historical_windows(
        asset_id, start, end, duration_hours, reason
    )
    if not materialized_windows:
        raise HTTPException(status_code=404, detail="Sem sinal histórico materializado.")
    limitation = (
        "Sinal derivado da taxa mensal histórica materializada; não é previsão "
        "operacional ex ante nem preserva a distribuição intramensal."
    )

    def historical_window(window: dict) -> HistoricalWindow:
        provenance = _field_provenance(
            field_name="expected_curtailed_energy",
            method_version=window["method"],
            context=_json_context(
                "historical_window",
                asset_id=asset_id,
                start=window["start"].isoformat(),
                end=window["end"].isoformat(),
                reason=reason,
            ),
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[window["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://assets/{asset_id}/windows",
        )
        return HistoricalWindow(
            start=window["start"],
            end=window["end"],
            expected_curtailed_energy=NumericEvidence(
                value=window["curtailed_mwh"],
                unit="MWh",
                period=Period(start=window["start"].date(), end=window["end"].date()),
                source="ONS/restricao_coff_eolica_tm",
                data_version=window["period"],
                method=window["method"],
                value_status="calculado",
                origin=DataOrigin.PROXY_CALCULADO,
                limitations=[limitation],
                provenance_id=provenance.evidence_id,
                provenance=provenance,
            ),
        )

    return HistoricalWindowsResponse(
        asset_id=asset_id,
        perspective_type="historical_seasonal",
        validation_status="historical_signal",
        data_mode="ons_materialized",
        duration_hours=duration_hours,
        reason=reason,
        windows=[historical_window(window) for window in materialized_windows],
        limitations=[limitation],
    )


@app.post(
    "/v1/maintenance/rank",
    response_model=MaintenanceRankResponse,
    tags=["maintenance"],
)
def rank_maintenance(request: MaintenanceRankRequest) -> MaintenanceRankResponse:
    input_provenance = request.input_provenance or {}
    _validate_caller_provenance(input_provenance)
    asset_item = repository.get_asset(request.asset_id)
    if asset_item is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    if request.start > request.end:
        raise HTTPException(status_code=422, detail="start deve ser anterior ou igual a end.")

    baseline = request.baseline_window_start
    if baseline.tzinfo is None:
        baseline = baseline.replace(tzinfo=UTC)
    period_start = datetime.combine(request.start, datetime.min.time(), tzinfo=UTC)
    period_end = datetime.combine(request.end, datetime.max.time(), tzinfo=UTC)
    if not period_start <= baseline <= period_end:
        raise HTTPException(status_code=422, detail="Janela-base fora do período informado.")

    candidates = repository.get_historical_windows(
        request.asset_id,
        request.start,
        request.end,
        request.duration_hours,
    )
    if not candidates:
        raise HTTPException(status_code=404, detail="Sem sinal histórico materializado.")

    limitation = (
        "Ranking baseado em taxa mensal histórica materializada do ONS: não é previsão "
        "operacional e não preserva a distribuição intramensal; não coordena nem revela "
        "manutenções de terceiros."
    )
    candidates.sort(key=lambda item: item["curtailed_mwh"], reverse=True)
    baseline_candidate = min(
        candidates,
        key=lambda item: abs(item["start"] - baseline),
    )
    baseline_energy = baseline_candidate["curtailed_mwh"]
    decision_parent_ids = [item.evidence_id for item in input_provenance.values()]

    input_evidence_ids = {
        field_name: provenance.evidence_id for field_name, provenance in input_provenance.items()
    }
    decision_input_sha256 = _canonical_digest(
        {
            "request": request.model_dump(mode="json"),
            "candidates": [
                {
                    "start": candidate["start"].isoformat(),
                    "end": candidate["end"].isoformat(),
                    "curtailed_mwh": candidate["curtailed_mwh"],
                    "period": candidate["period"],
                    "source_sha256": candidate["source_sha256"],
                    "method": candidate["method"],
                }
                for candidate in candidates
            ],
        }
    )

    def candidate_context(candidate: dict) -> str:
        return _json_context(
            "maintenance_rank",
            asset_id=request.asset_id,
            candidate_start=candidate["start"].isoformat(),
            candidate_end=candidate["end"].isoformat(),
            baseline_start=baseline.isoformat(),
            request_start=request.start.isoformat(),
            request_end=request.end.isoformat(),
            input_evidence_ids=input_evidence_ids,
            decision_input_sha256=decision_input_sha256,
        )

    def candidate_energy_provenance(candidate: dict) -> EvidenceProvenance:
        context = candidate_context(candidate)
        return _field_provenance(
            field_name="expected_curtailed_energy",
            method_version=candidate["method"],
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
        )

    baseline_energy_provenance = candidate_energy_provenance(baseline_candidate)
    ranked_windows = []
    for rank, candidate in enumerate(candidates, start=1):
        energy = candidate["curtailed_mwh"]
        context = candidate_context(candidate)
        energy_provenance = candidate_energy_provenance(candidate)
        cost_provenance = _field_provenance(
            field_name="opportunity_cost",
            method_version="opportunity_cost_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[
                energy_provenance.evidence_id,
                request.energy_price.provenance.evidence_id,
            ],
        )
        difference_mwh_provenance = _field_provenance(
            field_name="difference_from_baseline_mwh",
            method_version="maintenance_difference_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"], baseline_candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[
                energy_provenance.evidence_id,
                baseline_energy_provenance.evidence_id,
            ],
        )
        difference_provenance = _field_provenance(
            field_name="difference_from_baseline",
            method_version="maintenance_difference_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"], baseline_candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[
                energy_provenance.evidence_id,
                baseline_energy_provenance.evidence_id,
            ],
        )
        rank_provenance = _field_provenance(
            field_name="rank",
            method_version="maintenance_rank_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[energy_provenance.evidence_id, *decision_parent_ids],
        )
        start_provenance = _field_provenance(
            field_name="start",
            method_version="maintenance_window_boundary_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[energy_provenance.evidence_id, *decision_parent_ids],
        )
        end_provenance = _field_provenance(
            field_name="end",
            method_version="maintenance_window_boundary_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
            parent_evidence_ids=[energy_provenance.evidence_id, *decision_parent_ids],
        )
        ranked_windows.append(
            RankedMaintenanceWindow(
                rank=rank,
                start=candidate["start"],
                end=candidate["end"],
                expected_curtailed_energy=NumericEvidence(
                    value=energy,
                    unit="MWh",
                    period=Period(
                        start=candidate["start"].date(),
                        end=candidate["end"].date(),
                    ),
                    source="ONS/restricao_coff_eolica_tm",
                    data_version=candidate["period"],
                    method=candidate["method"],
                    value_status="calculado",
                    origin=DataOrigin.PROXY_CALCULADO,
                    limitations=[limitation],
                    provenance_id=energy_provenance.evidence_id,
                    provenance=energy_provenance,
                ),
                opportunity_cost=MonetaryEvidence(
                    value=energy * request.energy_price.value,
                    unit="BRL",
                    source=request.energy_price.source,
                    value_status="calculado",
                    origin=DataOrigin.PROXY_CALCULADO,
                    provenance_id=cost_provenance.evidence_id,
                    provenance=cost_provenance,
                ),
                difference_from_baseline_mwh=energy - baseline_energy,
                difference_from_baseline=NumericEvidence(
                    value=energy - baseline_energy,
                    unit="MWh",
                    period=Period(
                        start=candidate["start"].date(),
                        end=candidate["end"].date(),
                    ),
                    source="ONS/restricao_coff_eolica_tm",
                    data_version=candidate["period"],
                    method="candidate minus baseline expected curtailed energy",
                    value_status="calculado",
                    origin=DataOrigin.PROXY_CALCULADO,
                    limitations=[limitation],
                    provenance_id=difference_provenance.evidence_id,
                    provenance=difference_provenance,
                ),
                field_provenance={
                    "rank": rank_provenance,
                    "start": start_provenance,
                    "end": end_provenance,
                    "expected_curtailed_energy": energy_provenance,
                    "opportunity_cost": cost_provenance,
                    "difference_from_baseline_mwh": difference_mwh_provenance,
                    "difference_from_baseline": difference_provenance,
                },
            )
        )

    response = MaintenanceRankResponse(
        asset_id=request.asset_id,
        ranking_mode="historical_prototype",
        data_mode="ons_materialized",
        baseline_window_start=baseline,
        input_provenance=input_provenance,
        ranked_windows=ranked_windows,
        limitations=[limitation],
    )
    for window in response.ranked_windows:
        canonical_output = window.model_dump(mode="json")
        for field_name, provenance in window.field_provenance.items():
            issued_provenance_repository.put(
                _issued_record(
                    operation="maintenance_rank",
                    request=request,
                    output={"evidence_field": field_name, "ranked_window": canonical_output},
                    provenance=provenance,
                    source_item=asset_item,
                )
            )
    return response


@app.post(
    "/v1/bess/screen",
    response_model=BessScreenResponse,
    tags=["bess"],
)
def screen_bess(request: BessScreenRequest) -> BessScreenResponse:
    input_provenance = request.input_provenance or {}
    _validate_caller_provenance(input_provenance)
    item = repository.get_asset(request.asset_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    residual_exposure = float(item["curtailed_mwh"])
    annual_energy_capacity = (
        request.energy_mwh * request.cycles_per_year * request.round_trip_efficiency
    )
    absorbable = min(residual_exposure, annual_energy_capacity)
    annual_benefit = absorbable * request.energy_price_brl_mwh
    annual_net_benefit = annual_benefit - request.annualized_cost_brl
    limitation = (
        "Triagem determinística sobre exposição histórica: não é dimensionamento, previsão "
        "de despacho ou garantia de corte evitado."
    )
    decision_input_sha256 = _canonical_digest(
        {
            "request": request.model_dump(mode="json"),
            "materialized_source": {
                "asset_id": item["asset_id"],
                "period": item["period"],
                "period_start": item["period_start"],
                "period_end": item["period_end"],
                "curtailed_mwh": residual_exposure,
                "source_key": item["source_key"],
                "source_sha256": item["source_sha256"],
                "method": item["method"],
            },
        }
    )
    source_observation = _field_provenance(
        field_name="residual_exposure_source",
        method_version="curtailed_energy_sum_v1",
        context=_json_context(
            "bess_screen_source",
            asset_id=request.asset_id,
            period=item["period"],
            decision_input_sha256=decision_input_sha256,
        ),
        origin=DataOrigin.PROXY_CALCULADO,
        limitations=["Agregado mensal curado e calculado a partir de observações públicas."],
        source_hashes=[item["source_sha256"]],
        source_item=item,
        source_uri=f"curtailess://assets/{request.asset_id}/materialized-exposure",
    )
    output_parent_ids = sorted(
        {
            source_observation.evidence_id,
            *(provenance.evidence_id for provenance in input_provenance.values()),
        }
    )
    output_context = _json_context(
        "bess_screen",
        asset_id=request.asset_id,
        maintenance_result_id=request.maintenance_result_id,
        parent_evidence_ids=output_parent_ids,
        decision_input_sha256=decision_input_sha256,
        inputs={
            field_name: getattr(request, field_name)
            for field_name in (
                "power_mw",
                "energy_mwh",
                "capex_brl",
                "annualized_cost_brl",
                "round_trip_efficiency",
                "cycles_per_year",
                "energy_price_brl_mwh",
            )
        },
    )
    period = Period(
        start=date.fromisoformat(item["period_start"][:10]),
        end=date.fromisoformat(item["period_end"][:10]),
    )

    def simulation_provenance(field_name: str, method_version: str) -> EvidenceProvenance:
        return _field_provenance(
            field_name=field_name,
            method_version=method_version,
            context=output_context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[item["source_sha256"]],
            source_item=item,
            source_uri=f"curtailess://bess/{request.asset_id}/screen",
            parent_evidence_ids=output_parent_ids,
        )

    output_values = {
        "residual_exposure_mwh": round(residual_exposure, 6),
        "technically_absorbable_mwh": round(absorbable, 6),
        "annual_benefit_brl": round(annual_benefit, 2),
        "annual_net_benefit_brl": round(annual_net_benefit, 2),
        "preliminary_viable": float(annual_net_benefit > 0),
    }
    output_evidence: dict[str, NumericEvidence | MonetaryEvidence] = {}
    for field_name, value in output_values.items():
        provenance = simulation_provenance(field_name, "bess_screen_v1")
        if field_name.endswith("_brl"):
            output_evidence[field_name] = MonetaryEvidence(
                value=value,
                unit="BRL",
                source="historical exposure and client-informed BESS assumptions",
                value_status="calculado",
                origin=DataOrigin.PROXY_CALCULADO,
                provenance_id=provenance.evidence_id,
                provenance=provenance,
            )
        else:
            output_evidence[field_name] = NumericEvidence(
                value=value,
                unit="boolean" if field_name == "preliminary_viable" else "MWh",
                period=period,
                source="historical exposure and client-informed BESS assumptions",
                data_version=item["period"],
                method="deterministic BESS screening",
                value_status="calculado",
                origin=DataOrigin.PROXY_CALCULADO,
                limitations=[limitation],
                provenance_id=provenance.evidence_id,
                provenance=provenance,
            )
    response = BessScreenResponse(
        asset_id=request.asset_id,
        maintenance_result_id=request.maintenance_result_id,
        screening_mode="historical_deterministic",
        data_mode="ons_materialized",
        residual_exposure_mwh=round(residual_exposure, 6),
        technically_absorbable_mwh=round(absorbable, 6),
        annual_benefit_brl=round(annual_benefit, 2),
        annual_net_benefit_brl=round(annual_net_benefit, 2),
        preliminary_viable=annual_net_benefit > 0,
        input_provenance=input_provenance,
        source_observation=source_observation,
        output_evidence=output_evidence,
        missing_data=[
            "soc_cronológico",
            "degradação",
            "disponibilidade",
            "limite_de_conexão",
            "preço_horário",
            "fronteira_de_medição",
        ],
        limitations=[
            limitation,
            *(
                ["Proveniência de entradas legadas inferida como CLIENTE_INFORMADO."]
                if any(
                    provenance.method_version == "client_input_inferred_v1"
                    for provenance in input_provenance.values()
                )
                else []
            ),
        ],
    )
    screening_output = {
        field_name: getattr(response, field_name)
        for field_name in (
            "residual_exposure_mwh",
            "technically_absorbable_mwh",
            "annual_benefit_brl",
            "annual_net_benefit_brl",
            "preliminary_viable",
        )
    }
    issued_provenance_repository.put(
        _issued_record(
            operation="bess_screen",
            request=request,
            output={
                "evidence_field": "residual_exposure_source",
                "screening_output": screening_output,
            },
            provenance=source_observation,
            source_item=item,
        )
    )
    for field_name, evidence in response.output_evidence.items():
        issued_provenance_repository.put(
            _issued_record(
                operation="bess_screen",
                request=request,
                output={"evidence_field": field_name, "screening_output": screening_output},
                provenance=evidence.provenance,
                source_item=item,
            )
        )
    return response


@app.get(
    "/v1/model-runs/{model_run_id}",
    response_model=ModelRunResponse,
    tags=["audit"],
)
def get_model_run(model_run_id: str) -> ModelRunResponse:
    if not model_run_id.startswith("materialization:"):
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    period = model_run_id.removeprefix("materialization:")
    run = repository.get_materialization_run(period)
    if run is None:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    return ModelRunResponse(
        model_run_id=model_run_id,
        run_type="historical_replay",
        model_used=False,
        validation_status="materialized_historical_data",
        dataset="ONS/restricao_coff_eolica_tm",
        period=period,
        asset_count=run["asset_count"],
        source_sha256s=run["source_sha256s"],
        metrics=None,
        limitations=["Registro derivado da materialização; nenhum modelo preditivo foi executado."],
    )


def report_response(item: dict) -> ReportResponse:
    return ReportResponse(
        report_id=item["scenario_id"],
        asset_id=item["asset_id"],
        evidence_ids=item["evidence_ids"],
        report_type=item["report_type"],
        format=item["format"],
        execution_status=item["execution_status"],
        generation_mode=item["generation_mode"],
        hash_sha256=item["hash_sha256"],
        created_at=item["created_at"],
        limitations=item["limitations"],
    )


@app.post("/v1/reports", response_model=ReportResponse, status_code=202, tags=["reports"])
def create_report(request: ReportCreateRequest) -> ReportResponse:
    asset = repository.get_asset(request.asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    report_id = str(uuid.uuid4())
    created_at = datetime.now(UTC)
    limitations = [
        "Relatório determinístico de evidência histórica; não contém previsão "
        "nem orientação regulatória."
    ]
    body = serialize_report_body(
        {
            "report_id": report_id,
            "asset_id": request.asset_id,
            "asset_name": asset["asset_name"],
            "data_mode": "ons_materialized",
            "evidence_ids": request.evidence_ids,
            "source_sha256": asset["source_sha256"],
            "period": asset["period"],
            "limitations": limitations,
        }
    )
    item = {
        "plant_id": "REPORT",
        "scenario_id": report_id,
        "asset_id": request.asset_id,
        "evidence_ids": request.evidence_ids,
        "report_type": request.report_type,
        "format": request.format,
        "execution_status": "completed",
        "generation_mode": "deterministic_fallback",
        "hash_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "created_at": created_at.isoformat(),
        "artifact_key": f"reports/{report_id}.json",
        "limitations": limitations,
        "body": body,
    }
    stored = artifact_repository.create_report(item)
    return report_response(stored)


@app.get("/v1/reports/{report_id}", response_model=ReportResponse, tags=["reports"])
def get_report(report_id: str) -> ReportResponse:
    item = artifact_repository.get_report(report_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Relatório não encontrado.")
    return report_response(item)


@app.get(
    "/v1/reports/{report_id}/file",
    response_model=ReportFileResponse,
    tags=["reports"],
)
def get_report_file(report_id: str) -> ReportFileResponse:
    item = artifact_repository.get_report(report_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Relatório não encontrado.")
    return ReportFileResponse(
        report_id=report_id,
        url=artifact_repository.get_report_file_url(item),
        expires_in_seconds=300,
    )


@app.post(
    "/optimize-curtailment",
    response_model=CurtailmentRecommendation,
    tags=["curtailment"],
)
def optimize_curtailment(scenario: CurtailmentScenario) -> CurtailmentRecommendation:
    try:
        return optimize_with_bedrock(scenario)
    except BedrockOptimizationError as exc:
        raise HTTPException(
            status_code=503,
            detail="Serviço de otimização temporariamente indisponível.",
        ) from exc


handler = Mangum(
    app,
    lifespan="off",
    api_gateway_base_path=settings.api_gateway_base_path,
)
