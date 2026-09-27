from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DataOrigin(StrEnum):
    ONS_PUBLICO = "ONS_PUBLICO"
    PROXY_CALCULADO = "PROXY_CALCULADO"
    SIMULADO = "SIMULADO"
    CLIENTE_INFORMADO = "CLIENTE_INFORMADO"


class EvidenceProvenance(BaseModel):
    """Auditable source and method metadata for one evidence value."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    evidence_id: str = Field(min_length=1)
    origin: DataOrigin
    source_uri: str | None = Field(default=None, min_length=1)
    source_key: str | None = Field(default=None, min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime | None = None
    effective_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    method_version: str = Field(min_length=1)
    limitations: list[str]

    @field_validator("observed_at", "effective_at", "valid_from", "valid_to")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("evidence timestamps require timezone information")
        return value

    @model_validator(mode="after")
    def validate_source_and_interval(self) -> Self:
        if self.source_uri is None and self.source_key is None:
            raise ValueError("source_uri ou source_key é obrigatório")
        if (self.valid_from is None) != (self.valid_to is None):
            raise ValueError("valid_from e valid_to devem ser informados juntos")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to <= self.valid_from
        ):
            raise ValueError("valid_to deve ser posterior a valid_from")
        return self


def validate_public_and_simulated_evidence(
    public_observation: EvidenceProvenance,
    simulated_output: EvidenceProvenance,
) -> None:
    """Guard the provenance boundary between ONS observations and simulations."""

    if public_observation.evidence_id == simulated_output.evidence_id:
        raise ValueError("public observation and simulation cannot share evidence_id")
    if public_observation.origin is not DataOrigin.ONS_PUBLICO:
        raise ValueError("public observation must use ONS_PUBLICO origin")
    if simulated_output.origin is not DataOrigin.SIMULADO:
        raise ValueError("simulated output must use SIMULADO origin")
    if public_observation.origin is simulated_output.origin:
        raise ValueError("public observation and simulation cannot share origin")


class ApiInfo(BaseModel):
    name: str
    version: str
    environment: str
    docs: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str
    version: str
    environment: str


class CurtailmentScenario(BaseModel):
    regiao_subsistema: str = Field(min_length=1, max_length=100)
    timestamp: datetime
    demanda_prevista_mw: float = Field(ge=0)
    geracao_renovavel_prevista_mw: float = Field(ge=0)
    geracao_convencional_disponivel_mw: float = Field(ge=0)
    restricoes_transmissao: list[str] = Field(default_factory=list)
    limite_corte_permitido_mw: float = Field(ge=0)
    prioridade_operacional: Literal["baixa", "media", "alta", "critica"]
    observacoes: str | None = Field(default=None, max_length=4000)


class CurtailmentRecommendation(BaseModel):
    recomendacao: str
    justificativa_tecnica: str
    nivel_risco: Literal["baixo", "medio", "alto", "critico"]
    acoes_sugeridas: list[str]
    premissas_usadas: list[str]
    modelo_bedrock_utilizado: str


class Asset(BaseModel):
    asset_id: str
    name: str
    technology: Literal["wind", "solar"]
    capacity_mw: float | None
    ons_group: str
    connection_point: str
    data_mode: Literal["demo", "ons_materialized"]


class AssetList(BaseModel):
    items: list[Asset]


class Period(BaseModel):
    start: date
    end: date


class NumericEvidence(BaseModel):
    value: float
    unit: str
    period: Period
    source: str
    data_version: str
    method: str
    value_status: Literal["medido", "calculado", "previsto", "simulado", "informado"]
    origin: DataOrigin = DataOrigin.PROXY_CALCULADO
    limitations: list[str]
    provenance_id: str


class ExposureResponse(BaseModel):
    asset_id: str
    perspective_type: Literal["historical_observed"]
    data_mode: Literal["demo", "ons_materialized"]
    granularity: Literal["period"]
    reason: Literal["ENE", "REL", "CNF"] | None
    technology: Literal["wind"]
    total_curtailed_energy: NumericEvidence
    limitations: list[str]


class DataQualityResponse(BaseModel):
    asset_id: str
    validation_status: Literal["valid"]
    period: Period
    observed_interval_count: int
    expected_interval_count: int
    coverage_percent: float
    null_count: int | None
    duplicate_count: int | None
    source: str
    source_sha256: str
    limitations: list[str]


class ProvenanceResponse(BaseModel):
    provenance_id: str
    evidence_id: str
    classification: Literal["calculado"]
    origin: DataOrigin
    source: str
    source_bucket: str | None
    source_key: str
    source_sha256: str
    data_version: str
    method: str
    method_version: str
    asset_ids: list[str]
    limitations: list[str]


class PointContextResponse(BaseModel):
    asset_id: str
    connection_point: str
    data_mode: Literal["demo", "ons_materialized"]
    anonymized_entity_count: NumericEvidence
    simultaneity_rate: NumericEvidence
    physical_limit_available: bool
    limitations: list[str]


class HistoricalWindow(BaseModel):
    start: datetime
    end: datetime
    expected_curtailed_energy: NumericEvidence


class HistoricalWindowsResponse(BaseModel):
    asset_id: str
    perspective_type: Literal["historical_seasonal"]
    validation_status: Literal["historical_signal"]
    data_mode: Literal["demo", "ons_materialized"]
    duration_hours: int
    reason: Literal["ENE", "REL", "CNF"] | None
    windows: list[HistoricalWindow]
    limitations: list[str]


class MaintenanceConstraints(BaseModel):
    weekdays_only: bool = False
    unavailable_periods: list[Period] = Field(default_factory=list)


class EnergyPrice(BaseModel):
    value: float = Field(ge=0)
    unit: Literal["BRL/MWh"]
    source: str = Field(min_length=1)
    value_status: Literal["informado"]
    origin: DataOrigin = DataOrigin.CLIENTE_INFORMADO


class MaintenanceRankRequest(BaseModel):
    asset_id: str
    start: date
    end: date
    duration_hours: int = Field(gt=0)
    minimum_notice_hours: int = Field(ge=0)
    baseline_window_start: datetime
    constraints: MaintenanceConstraints = Field(default_factory=MaintenanceConstraints)
    energy_price: EnergyPrice


class MonetaryEvidence(BaseModel):
    value: float
    unit: Literal["BRL"]
    source: str
    value_status: Literal["calculado", "simulado"]
    origin: DataOrigin = DataOrigin.PROXY_CALCULADO


class RankedMaintenanceWindow(BaseModel):
    rank: int
    start: datetime
    end: datetime
    expected_curtailed_energy: NumericEvidence
    opportunity_cost: MonetaryEvidence
    difference_from_baseline_mwh: float


class MaintenanceRankResponse(BaseModel):
    asset_id: str
    ranking_mode: Literal["historical_prototype"]
    data_mode: Literal["ons_materialized"]
    baseline_window_start: datetime
    ranked_windows: list[RankedMaintenanceWindow]
    limitations: list[str]


class BessScreenRequest(BaseModel):
    asset_id: str
    maintenance_result_id: str
    power_mw: float = Field(gt=0)
    energy_mwh: float = Field(gt=0)
    capex_brl: float = Field(ge=0)
    annualized_cost_brl: float = Field(ge=0)
    round_trip_efficiency: float = Field(gt=0, le=1)
    cycles_per_year: int = Field(gt=0)
    energy_price_brl_mwh: float = Field(ge=0)


class BessScreenResponse(BaseModel):
    asset_id: str
    maintenance_result_id: str
    screening_mode: Literal["historical_deterministic"]
    data_mode: Literal["ons_materialized"]
    residual_exposure_mwh: float
    technically_absorbable_mwh: float
    annual_benefit_brl: float
    annual_net_benefit_brl: float
    preliminary_viable: bool
    missing_data: list[str]
    limitations: list[str]


class ModelRunResponse(BaseModel):
    model_run_id: str
    run_type: Literal["historical_replay"]
    model_used: Literal[False]
    validation_status: Literal["materialized_historical_data"]
    dataset: str
    period: str
    asset_count: int
    source_sha256s: list[str]
    metrics: dict[str, float] | None
    limitations: list[str]


class ReportCreateRequest(BaseModel):
    asset_id: str
    evidence_ids: list[str] = Field(min_length=1)
    report_type: Literal["decision_support"]
    format: Literal["json"]


class ReportResponse(BaseModel):
    report_id: str
    asset_id: str
    evidence_ids: list[str]
    report_type: Literal["decision_support"]
    format: Literal["json"]
    execution_status: Literal["completed"]
    generation_mode: Literal["deterministic_fallback"]
    hash_sha256: str
    created_at: datetime
    limitations: list[str]


class ReportFileResponse(BaseModel):
    report_id: str
    url: str
    expires_in_seconds: Literal[300]
