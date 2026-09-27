import hashlib
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum

from . import __version__
from .artifacts import create_artifact_repository, serialize_report_body
from .bedrock import BedrockOptimizationError, optimize_with_bedrock
from .canonical import canonical_json as _canonical_json
from .config import get_settings
from .data_access import create_exposure_repository
from .decision_operations import build_rank_maintenance, build_screen_bess
from .provenance import build_evidence_id as build_evidence_id
from .provenance import create_issued_provenance_repository
from .provenance_service import (
    field_provenance as _field_provenance,
)
from .provenance_service import (
    persist_operation as _persist_operation,
)
from .provenance_service import (
    resolve_server_evidence as _resolve_server_evidence_impl,
)
from .response_assembly import (
    build_exposure_response,
    build_historical_windows_response,
    materialized_asset,
)
from .schemas import (
    MAX_PLANNING_DAYS,
    ApiInfo,
    Asset,
    AssetList,
    BessScreenRequest,
    BessScreenResponse,
    CurtailmentRecommendation,
    CurtailmentScenario,
    DataOrigin,
    DataQualityResponse,
    ExposureResponse,
    HealthResponse,
    HistoricalWindowsResponse,
    MaintenanceRankRequest,
    MaintenanceRankResponse,
    ModelRunResponse,
    NumericEvidence,
    Period,
    PointContextResponse,
    ProvenanceResponse,
    ReportCreateRequest,
    ReportFileResponse,
    ReportResponse,
)

settings = get_settings()
repository = create_exposure_repository(settings.exposure_table, settings.aws_region)
artifact_repository = create_artifact_repository(
    settings.scenarios_table, settings.data_bucket, settings.aws_region
)
issued_provenance_repository = create_issued_provenance_repository(
    settings.scenarios_table, settings.aws_region
)


def _json_context(kind: str, **values: object) -> str:
    return _canonical_json({"kind": kind, **values})


_CONSTRAINED_OFF_DATASETS = (
    "restricao_coff_eolica_tm",
    "restricao_coff_fotovoltaica_tm",
)


def _point_context_datasets(records: list[dict]) -> list[str]:
    datasets = set()
    for record in records:
        source_key = record.get("source_key", "")
        dataset = next(
            (
                candidate
                for candidate in _CONSTRAINED_OFF_DATASETS
                if f"/{candidate}/" in f"/{source_key}/"
            ),
            None,
        )
        if dataset is None:
            raise HTTPException(
                status_code=422,
                detail="Contexto contém fonte que não é constrained-off eólica/fotovoltaica.",
            )
        datasets.add(dataset)
    return sorted(datasets)


def _point_context_source(records: list[dict]) -> str:
    return " + ".join(f"ONS/{dataset}" for dataset in _point_context_datasets(records))


def _resolve_server_evidence(evidence_id: str):
    return _resolve_server_evidence_impl(evidence_id, issued_provenance_repository)


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


@app.exception_handler(RequestValidationError)
async def request_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    # Starlette cannot serialize NaN/Infinity echoed in Pydantic's error `input` field.
    errors = [
        {key: value for key, value in error.items() if key != "input"} for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


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


def _persist_asset(item: dict, asset: Asset) -> None:
    _persist_operation(
        issued_provenance_repository,
        operation="materialized_asset",
        request_value={"asset_id": asset.asset_id, "period": item["period"]},
        provenances=list(asset.field_provenance.values()),
        source_records=[item],
    )


@app.get("/v1/assets", response_model=AssetList, tags=["assets"])
def list_assets() -> AssetList:
    assets = []
    for item in repository.list_assets():
        asset = materialized_asset(item)
        _persist_asset(item, asset)
        assets.append(asset)
    return AssetList(items=assets)


@app.get("/v1/assets/{asset_id}", response_model=Asset, tags=["assets"])
def get_asset(asset_id: str) -> Asset:
    item = repository.get_asset(asset_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    asset = materialized_asset(item)
    _persist_asset(item, asset)
    return asset


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
    source = f"ONS/{dataset}"
    method = item.get("capacity_method", item.get("method", identity["method"]))
    if identity["field"] in {"anonymized_entity_count", "simultaneity_rate"}:
        datasets = _point_context_datasets(items)
        dataset = " + ".join(datasets)
        source = " + ".join(f"ONS/{value}" for value in datasets)
        method = identity["method"]
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
        source=source,
        source_bucket=item.get("source_bucket", "ons-aws-prod-opendata"),
        source_key=source_key,
        source_sha256=provenance.source_sha256 or source_hashes[0],
        source_sha256s=source_hashes,
        data_version=(
            item.get("capacity_data_version", "snapshot")
            if dataset == "capacidade-geracao"
            else ",".join(sorted({source_item["period"] for source_item in items}))
        ),
        method=method,
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

    response, provenance = build_exposure_response(asset_id, start, end, reason, exposure)
    _persist_operation(
        issued_provenance_repository,
        operation="exposure",
        request_value={"asset_id": asset_id, "start": start, "end": end, "reason": reason},
        provenances=[provenance],
        source_records=exposure["items"],
    )
    return response


@app.get(
    "/v1/assets/{asset_id}/point-context",
    response_model=PointContextResponse,
    tags=["exposure"],
)
def get_asset_point_context(asset_id: str) -> PointContextResponse:
    asset_item = repository.get_asset(asset_id)
    if asset_item is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    context = repository.get_point_context(asset_id, asset_item)
    if context is None:
        raise HTTPException(status_code=404, detail="Contexto materializado não encontrado.")
    source_records = context["items"]
    if len(context["source_sha256s"]) > 32 or len(source_records) > 32:
        raise HTTPException(status_code=422, detail="Contexto excede o limite de 32 fontes.")
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
    source = _point_context_source(source_records)
    record_identities = [
        {
            "asset_id": item["asset_id"],
            "period": item["period"],
            "source_key": item["source_key"],
            "source_sha256": item["source_sha256"],
        }
        for item in source_records
    ]
    provenance_context = _json_context(
        "point_context",
        asset_id=asset_id,
        connection_point=context["connection_point"],
        period_start=period.start,
        period_end=period.end,
        records=record_identities,
    )
    entity_method = "distinct_latest_constrained_off_assets_at_point_v1"
    entity_provenance = _field_provenance(
        field_name="anonymized_entity_count",
        method_version=entity_method,
        context=provenance_context,
        origin=DataOrigin.PROXY_CALCULADO,
        limitations=[limitation],
        source_hashes=context["source_sha256s"],
        source_items=source_records,
        source_item=asset_item,
        source_uri=f"curtailess://assets/{asset_id}/point-context",
    )
    simultaneity_provenance = _field_provenance(
        field_name="simultaneity_rate",
        method_version="historical_simultaneity_v1",
        context=provenance_context,
        origin=DataOrigin.PROXY_CALCULADO,
        limitations=[limitation],
        source_hashes=context["source_sha256s"],
        source_items=source_records,
        source_item=asset_item,
        source_uri=f"curtailess://assets/{asset_id}/point-context",
    )
    response = PointContextResponse(
        asset_id=asset_id,
        connection_point=context["connection_point"],
        data_mode="ons_materialized",
        anonymized_entity_count=NumericEvidence(
            value=context["entity_count"],
            unit="entities",
            period=period,
            source=source,
            data_version=context["data_version"],
            method=entity_method,
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
            source=source,
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
    _persist_operation(
        issued_provenance_repository,
        operation="point_context",
        request_value={"asset_id": asset_id, "data_version": context["data_version"]},
        provenances=[entity_provenance, simultaneity_provenance],
        source_records=source_records,
    )
    return response


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
    if (end - start).days + 1 > MAX_PLANNING_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"Período de planejamento excede {MAX_PLANNING_DAYS} dias.",
        )
    if duration_hours <= 0 or duration_hours > MAX_PLANNING_DAYS * 24:
        raise HTTPException(
            status_code=422,
            detail=f"duration_hours deve estar entre 1 e {MAX_PLANNING_DAYS * 24}.",
        )
    asset_item = repository.get_asset(asset_id)
    if asset_item is None:
        raise HTTPException(status_code=404, detail="Ativo não encontrado.")
    materialized_windows = repository.get_historical_windows(
        asset_id, start, end, duration_hours, reason
    )
    if not materialized_windows:
        raise HTTPException(status_code=404, detail="Sem sinal histórico materializado.")
    response = build_historical_windows_response(
        asset_id, duration_hours, reason, materialized_windows
    )
    _persist_operation(
        issued_provenance_repository,
        operation="historical_windows",
        request_value={
            "asset_id": asset_id,
            "start": start,
            "end": end,
            "duration_hours": duration_hours,
            "reason": reason,
        },
        provenances=[window.expected_curtailed_energy.provenance for window in response.windows],
        source_records=[window["source_record"] for window in materialized_windows],
    )
    return response


@app.post(
    "/v1/maintenance/rank",
    response_model=MaintenanceRankResponse,
    tags=["maintenance"],
)
def rank_maintenance(request: MaintenanceRankRequest) -> MaintenanceRankResponse:
    return build_rank_maintenance(request, repository, issued_provenance_repository)


@app.post(
    "/v1/bess/screen",
    response_model=BessScreenResponse,
    tags=["bess"],
)
def screen_bess(request: BessScreenRequest) -> BessScreenResponse:
    return build_screen_bess(request, repository, issued_provenance_repository)


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
