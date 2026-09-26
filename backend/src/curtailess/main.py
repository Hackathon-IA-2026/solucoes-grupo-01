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
    DataQualityResponse,
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
)

settings = get_settings()
repository = create_exposure_repository(settings.exposure_table, settings.aws_region)
artifact_repository = create_artifact_repository(
    settings.scenarios_table, settings.data_bucket, settings.aws_region
)

DEMO_ASSET = Asset(
    asset_id="demo-wind-ne-001",
    name="Ativo eólico de demonstração",
    technology="wind",
    capacity_mw=100.0,
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
    return Asset(
        asset_id=item["asset_id"],
        name=item["asset_name"],
        technology="wind",
        capacity_mw=None,
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
    if not provenance_id.startswith("sha256:"):
        raise HTTPException(status_code=422, detail="provenance_id deve usar o prefixo sha256:.")
    source_sha256 = provenance_id.removeprefix("sha256:")
    item = repository.get_provenance(source_sha256)
    if item is None:
        raise HTTPException(status_code=404, detail="Proveniência não encontrada.")
    limitation = "Linhagem da materialização mensal; o manifesto bruto permanece privado no S3."
    return ProvenanceResponse(
        provenance_id=provenance_id,
        classification="calculado",
        source="ONS/restricao_coff_eolica_tm",
        source_bucket=item.get("source_bucket"),
        source_key=item["source_key"],
        source_sha256=source_sha256,
        data_version=item["period"],
        method=item["method"],
        asset_ids=item.get("asset_ids", [item["asset_id"]]),
        limitations=[limitation],
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
    provenance_id = "sha256:" + ",".join(exposure["source_sha256s"])
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
            limitations=[limitation],
            provenance_id=provenance_id,
        ),
        limitations=[limitation],
    )


@app.get(
    "/v1/assets/{asset_id}/point-context",
    response_model=PointContextResponse,
    tags=["exposure"],
)
def get_asset_point_context(asset_id: str) -> PointContextResponse:
    if repository.get_asset(asset_id) is None:
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
    provenance_id = "sha256:" + ",".join(context["source_sha256s"])
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
            limitations=[limitation],
            provenance_id=provenance_id,
        ),
        simultaneity_rate=NumericEvidence(
            value=simultaneity_rate,
            unit="%",
            period=period,
            source="ONS/restricao_coff_eolica_tm",
            data_version=context["data_version"],
            method="historical_simultaneity_v1",
            value_status="calculado",
            limitations=[limitation],
            provenance_id=provenance_id,
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
    if repository.get_asset(asset_id) is None:
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
    return HistoricalWindowsResponse(
        asset_id=asset_id,
        perspective_type="historical_seasonal",
        validation_status="historical_signal",
        data_mode="ons_materialized",
        duration_hours=duration_hours,
        reason=reason,
        windows=[
            HistoricalWindow(
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
                    limitations=[limitation],
                    provenance_id=f"sha256:{window['source_sha256']}",
                ),
            )
            for window in materialized_windows
        ],
        limitations=[limitation],
    )


@app.post(
    "/v1/maintenance/rank",
    response_model=MaintenanceRankResponse,
    tags=["maintenance"],
)
def rank_maintenance(request: MaintenanceRankRequest) -> MaintenanceRankResponse:
    if repository.get_asset(request.asset_id) is None:
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
                    limitations=[limitation],
                    provenance_id=f"sha256:{candidate['source_sha256']}",
                ),
                opportunity_cost=MonetaryEvidence(
                    value=energy * request.energy_price.value,
                    unit="BRL",
                    source=request.energy_price.source,
                    value_status="calculado",
                ),
                difference_from_baseline_mwh=energy - baseline_energy,
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
