from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from . import __version__
from .bedrock import BedrockOptimizationError, optimize_with_bedrock
from .config import get_settings
from .data_access import create_exposure_repository
from .schemas import (
    ApiInfo,
    Asset,
    AssetList,
    CurtailmentRecommendation,
    CurtailmentScenario,
    ExposureResponse,
    HealthResponse,
    HistoricalWindow,
    HistoricalWindowsResponse,
    MaintenanceRankRequest,
    MaintenanceRankResponse,
    MonetaryEvidence,
    NumericEvidence,
    Period,
    PointContextResponse,
    RankedMaintenanceWindow,
)

settings = get_settings()
repository = create_exposure_repository(settings.exposure_table, settings.aws_region)

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
    "/v1/assets/{asset_id}/exposure",
    response_model=ExposureResponse,
    tags=["exposure"],
)
def get_asset_exposure(
    asset_id: str,
    start: Annotated[date, "query"],
    end: Annotated[date, "query"],
) -> ExposureResponse:
    if start > end:
        raise HTTPException(status_code=422, detail="start deve ser anterior ou igual a end.")
    if repository.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    exposure = repository.get_exposure(asset_id, start, end)
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
) -> HistoricalWindowsResponse:
    if start > end:
        raise HTTPException(status_code=422, detail="start deve ser anterior ou igual a end.")
    if duration_hours <= 0:
        raise HTTPException(status_code=422, detail="duration_hours deve ser positivo.")
    if repository.get_asset(asset_id) is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    materialized_windows = repository.get_historical_windows(asset_id, start, end, duration_hours)
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
