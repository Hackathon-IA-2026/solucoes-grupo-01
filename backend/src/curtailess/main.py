from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from . import __version__
from .bedrock import BedrockOptimizationError, optimize_with_bedrock
from .config import get_settings
from .schemas import (
    ApiInfo,
    Asset,
    AssetList,
    CurtailmentRecommendation,
    CurtailmentScenario,
    ExposureResponse,
    HealthResponse,
    NumericEvidence,
    Period,
)

settings = get_settings()

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


@app.get("/v1/assets", response_model=AssetList, tags=["assets"])
def list_assets() -> AssetList:
    return AssetList(items=[DEMO_ASSET])


@app.get("/v1/assets/{asset_id}", response_model=Asset, tags=["assets"])
def get_asset(asset_id: str) -> Asset:
    return get_demo_asset(asset_id)


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
    get_demo_asset(asset_id)
    if start > end:
        raise HTTPException(status_code=422, detail="start deve ser anterior ou igual a end.")

    demo_limitation = (
        "Valores numéricos simulados para validar o contrato; a materialização dos "
        "dados públicos do ONS ainda não está conectada a esta rota."
    )
    return ExposureResponse(
        asset_id=asset_id,
        perspective_type="historical_observed",
        data_mode="demo",
        total_curtailed_energy=NumericEvidence(
            value=0.0,
            unit="MWh",
            period=Period(start=start, end=end),
            source="ONS/restricao_coff_eolica_tm",
            data_version="demo-not-materialized",
            method="settlement_energy_v1",
            value_status="calculado",
            limitations=[demo_limitation],
            provenance_id=(f"prov-demo-{asset_id}-{start.isoformat()}-{end.isoformat()}"),
        ),
        limitations=[demo_limitation],
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
