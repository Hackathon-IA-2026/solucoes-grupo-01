import hashlib
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
    observed_at: datetime | None = None,
    effective_at: datetime | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> EvidenceProvenance:
    hashes = tuple(sorted(set(source_hashes)))
    identities = list(hashes) or [source_uri or "curtailess://unspecified"]
    evidence_id = build_evidence_id(identities, field_name, method_version, context)
    observed_at = observed_at or (_aware(source_item["period_end"]) if source_item else None)
    valid_from = valid_from or (_aware(source_item["period_start"]) if source_item else None)
    valid_to = valid_to or (_aware(source_item["period_end"]) if source_item else None)
    return EvidenceProvenance(
        evidence_id=evidence_id,
        field_name=field_name,
        origin=origin,
        source_uri=source_uri,
        source_key=source_item.get("source_key") if source_item else None,
        source_sha256=hashes[0] if hashes else None,
        source_sha256s=hashes,
        observed_at=observed_at,
        effective_at=effective_at
        or (observed_at if origin is not DataOrigin.ONS_PUBLICO else None),
        valid_from=valid_from,
        valid_to=valid_to,
        method_version=method_version,
        limitations=limitations,
    )


_DEMO_CAPACITY_URI = "curtailess://demo/assets/demo-wind-ne-001/capacity_mw"
DEMO_ASSET = Asset(
    asset_id="demo-wind-ne-001",
    name="Ativo eólico de demonstração",
    technology="wind",
    capacity_mw=100.0,
    capacity_provenance=_field_provenance(
        field_name="capacity_mw",
        method_version="demo_fixture_v1",
        context="demo-wind-ne-001",
        origin=DataOrigin.SIMULADO,
        limitations=["Capacidade fictícia usada somente na demonstração."],
        source_uri=_DEMO_CAPACITY_URI,
        effective_at=datetime(2026, 1, 1, tzinfo=UTC),
    ),
    ons_group="Conjunto anonimizado NE-001",
    connection_point="Ponto cadastral anonimizado NE-001",
    data_mode="demo",
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


def materialized_asset(item: dict) -> Asset:
    capacity = item.get("capacity_mw")
    capacity_provenance = None
    if capacity is not None:
        capacity_provenance = _field_provenance(
            field_name="capacity_mw",
            method_version=item.get("capacity_method_version", "ons_capacity_source_v1"),
            context=item["asset_id"],
            origin=DataOrigin.ONS_PUBLICO,
            limitations=item.get("capacity_limitations", []),
            source_hashes=[item["capacity_source_sha256"]],
            source_item={
                **item,
                "source_key": item["capacity_source_key"],
                "source_sha256": item["capacity_source_sha256"],
            },
            source_uri="s3://ons-aws-prod-opendata/dataset/capacidade-geracao/",
        )
    return Asset(
        asset_id=item["asset_id"],
        name=item["asset_name"],
        technology="wind",
        capacity_mw=capacity,
        capacity_provenance=capacity_provenance,
        ons_group=item["asset_id"],
        connection_point=item["point_id"],
        data_mode="ons_materialized",
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
    try:
        identity = parse_evidence_id(provenance_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    source_hashes = identity["sources"]
    if any(len(value) != 64 for value in source_hashes):
        raise HTTPException(status_code=404, detail="Proveniência externa não materializada.")
    source_items = [repository.get_provenance(value) for value in source_hashes]
    if any(item is None for item in source_items):
        raise HTTPException(status_code=404, detail="Proveniência não encontrada.")
    items = [item for item in source_items if item is not None]
    item = items[0]
    limitation = "Linhagem de campo da materialização; o manifesto bruto permanece privado no S3."
    simulated_fields = {
        "residual_exposure_mwh",
        "technically_absorbable_mwh",
        "annual_benefit_brl",
        "annual_net_benefit_brl",
        "preliminary_viable",
    }
    public_fields = {"capacity_mw", "residual_exposure_source"}
    if identity["field"] in simulated_fields:
        origin = DataOrigin.SIMULADO
        classification = "simulado"
    elif identity["field"] in public_fields:
        origin = DataOrigin.ONS_PUBLICO
        classification = "medido"
    else:
        origin = DataOrigin.PROXY_CALCULADO
        classification = "calculado"
    provenance = _field_provenance(
        field_name=identity["field"],
        method_version=identity["method"],
        context=identity["context"],
        origin=origin,
        limitations=[limitation],
        source_hashes=source_hashes,
        source_item=item,
        source_uri=f"curtailess://evidence/{provenance_id}",
    )
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
        source="ONS/restricao_coff_eolica_tm",
        source_bucket=item.get("source_bucket"),
        source_key=item["source_key"],
        source_sha256=source_hashes[0],
        source_sha256s=source_hashes,
        data_version=",".join(sorted({source_item["period"] for source_item in items})),
        method=item["method"],
        method_version=identity["method"],
        field_name=identity["field"],
        observed_at=provenance.observed_at,
        effective_at=provenance.effective_at,
        valid_from=provenance.valid_from,
        valid_to=provenance.valid_to,
        asset_ids=asset_ids,
        limitations=[limitation],
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
            context=f"{asset_id}:{window['start'].isoformat()}:{window['end'].isoformat()}",
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

    ranked_windows = []
    for rank, candidate in enumerate(candidates, start=1):
        energy = candidate["curtailed_mwh"]
        context = (
            f"{request.asset_id}:{candidate['start'].isoformat()}:"
            f"{candidate['end'].isoformat()}:{baseline.isoformat()}"
        )
        energy_provenance = _field_provenance(
            field_name="expected_curtailed_energy",
            method_version=candidate["method"],
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
        )
        cost_provenance = _field_provenance(
            field_name="opportunity_cost",
            method_version="opportunity_cost_v1",
            context=f"{context}:{request.energy_price.provenance.evidence_id}",
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
        )
        difference_provenance = _field_provenance(
            field_name="difference_from_baseline_mwh",
            method_version="maintenance_difference_v1",
            context=context,
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=[limitation],
            source_hashes=[candidate["source_sha256"], baseline_candidate["source_sha256"]],
            source_item=asset_item,
            source_uri=f"curtailess://maintenance/{request.asset_id}/rank",
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
            )
        )

    return MaintenanceRankResponse(
        asset_id=request.asset_id,
        ranking_mode="historical_prototype",
        data_mode="ons_materialized",
        baseline_window_start=baseline,
        ranked_windows=ranked_windows,
        limitations=[limitation],
    )


@app.post(
    "/v1/bess/screen",
    response_model=BessScreenResponse,
    tags=["bess"],
)
def screen_bess(request: BessScreenRequest) -> BessScreenResponse:
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
    source_observation = _field_provenance(
        field_name="residual_exposure_source",
        method_version="ons_materialized_observation_v1",
        context=f"{request.asset_id}:{item['period']}",
        origin=DataOrigin.ONS_PUBLICO,
        limitations=["Observação pública materializada usada como entrada da simulação."],
        source_hashes=[item["source_sha256"]],
        source_item=item,
        source_uri=f"curtailess://assets/{request.asset_id}/materialized-exposure",
    )
    simulation_inputs = [
        request.maintenance_result_id,
        *(provenance.evidence_id for provenance in request.input_provenance.values()),
    ]
    input_fingerprint = hashlib.sha256("|".join(sorted(simulation_inputs)).encode()).hexdigest()
    period = Period(
        start=date.fromisoformat(item["period_start"][:10]),
        end=date.fromisoformat(item["period_end"][:10]),
    )

    def simulation_provenance(field_name: str, method_version: str) -> EvidenceProvenance:
        return _field_provenance(
            field_name=field_name,
            method_version=method_version,
            context=(f"{request.asset_id}:{request.maintenance_result_id}:{input_fingerprint}"),
            origin=DataOrigin.SIMULADO,
            limitations=[limitation],
            source_hashes=[item["source_sha256"]],
            source_item=item,
            source_uri=f"curtailess://bess/{request.asset_id}/screen",
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
                value_status="simulado",
                origin=DataOrigin.SIMULADO,
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
                value_status="simulado",
                origin=DataOrigin.SIMULADO,
                limitations=[limitation],
                provenance_id=provenance.evidence_id,
                provenance=provenance,
            )
    return BessScreenResponse(
        asset_id=request.asset_id,
        maintenance_result_id=request.maintenance_result_id,
        screening_mode="historical_deterministic",
        data_mode="ons_materialized",
        residual_exposure_mwh=round(residual_exposure, 6),
        technically_absorbable_mwh=round(absorbable, 6),
        annual_benefit_brl=round(annual_benefit, 2),
        annual_net_benefit_brl=round(annual_net_benefit, 2),
        preliminary_viable=annual_net_benefit > 0,
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
        limitations=[limitation],
    )


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
