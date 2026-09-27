import hashlib
import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StringConstraints,
    field_validator,
    model_validator,
)

from .canonical import canonical_json
from .provenance import EVIDENCE_ID_MAX_LENGTH, build_evidence_id
from .provenance import parse_evidence_id as parse_evidence_id

BoundedText = Annotated[str, StringConstraints(min_length=1, max_length=512)]
EvidenceId = Annotated[
    str,
    StringConstraints(
        min_length=EVIDENCE_ID_MAX_LENGTH,
        max_length=EVIDENCE_ID_MAX_LENGTH,
        pattern=r"^(?:evd1|evp1)\.[0-9a-f]{64}$",
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

MAX_DECISION_INPUT = 1e100
MAX_PLANNING_DAYS = 60
MAX_PLANNING_RESULTS = 32


class DataOrigin(StrEnum):
    ONS_PUBLICO = "ONS_PUBLICO"
    PROXY_CALCULADO = "PROXY_CALCULADO"
    SIMULADO = "SIMULADO"
    CLIENTE_INFORMADO = "CLIENTE_INFORMADO"


ValueStatus = Literal["medido", "calculado", "previsto", "simulado", "informado"]
STATUS_ORIGIN: dict[str, DataOrigin] = {
    "medido": DataOrigin.ONS_PUBLICO,
    "previsto": DataOrigin.ONS_PUBLICO,
    "calculado": DataOrigin.PROXY_CALCULADO,
    "simulado": DataOrigin.SIMULADO,
    "informado": DataOrigin.CLIENTE_INFORMADO,
}
ORIGIN_EVIDENCE_ID_FAMILY: dict[DataOrigin, str] = {
    DataOrigin.ONS_PUBLICO: "evp1",
    DataOrigin.PROXY_CALCULADO: "evd1",
    DataOrigin.SIMULADO: "evd1",
    DataOrigin.CLIENTE_INFORMADO: "evd1",
}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def inferred_client_provenance(field_name: str, value: Any, context: str) -> "EvidenceProvenance":
    """Create deterministic, explicitly inferred provenance for a legacy caller input."""

    serialized = canonical_json(value)
    value_digest = hashlib.sha256(serialized.encode()).hexdigest()
    source_uri = f"client://inferred/{context}/{field_name}"
    return EvidenceProvenance(
        evidence_id=build_evidence_id(
            source_uri,
            field_name,
            "client_input_inferred_v1",
            f"{context}:{value_digest}",
        ),
        field_name=field_name,
        origin=DataOrigin.CLIENTE_INFORMADO,
        source_uri=source_uri,
        effective_at=datetime(1970, 1, 1, tzinfo=UTC),
        method_version="client_input_inferred_v1",
        limitations=[
            "Proveniência inferida por compatibilidade: valor informado pelo cliente sem "
            "metadados de origem explícitos."
        ],
    )


class SourceArtifact(BaseModel):
    """One immutable source location paired with the digest of its contents."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_key: Annotated[str, StringConstraints(min_length=1, max_length=1024)]
    source_sha256: Sha256


class EvidenceProvenance(BaseModel):
    """Authoritative, bounded source and method metadata for one field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: EvidenceId
    field_name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    origin: DataOrigin
    source_uri: BoundedText | None = None
    source_key: Annotated[str, StringConstraints(min_length=1, max_length=1024)] | None = None
    source_sha256: Sha256 | None = None
    source_sha256s: tuple[Sha256, ...] = Field(default=(), max_length=32)
    source_artifacts: tuple[SourceArtifact, ...] = Field(default=(), max_length=32)
    parent_evidence_ids: tuple[EvidenceId, ...] = Field(default=(), max_length=32)
    observed_at: datetime | None = None
    effective_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    temporal_coverage: Literal["known", "unknown", "partial"] = "known"
    method_version: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    limitations: tuple[BoundedText, ...] = Field(max_length=16)

    @field_validator("source_sha256s")
    @classmethod
    def validate_source_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _SHA256_PATTERN.fullmatch(value) for value in values):
            raise ValueError("source_sha256s must contain SHA-256 hex digests")
        if tuple(sorted(set(values))) != values:
            raise ValueError("source_sha256s must be sorted and unique")
        return values

    @field_validator("source_artifacts")
    @classmethod
    def validate_source_artifacts(
        cls, values: tuple[SourceArtifact, ...]
    ) -> tuple[SourceArtifact, ...]:
        identities = tuple((value.source_key, value.source_sha256) for value in values)
        if tuple(sorted(set(identities))) != identities:
            raise ValueError("source_artifacts must be sorted and unique by source key and SHA-256")
        return values

    @field_validator("parent_evidence_ids")
    @classmethod
    def validate_parent_evidence_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("parent_evidence_ids cannot contain empty IDs")
        if tuple(sorted(set(values))) != values:
            raise ValueError("parent_evidence_ids must be sorted and unique")
        return values

    @field_validator("observed_at", "effective_at", "valid_from", "valid_to")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("evidence timestamps require timezone information")
        return value

    @model_validator(mode="after")
    def validate_source_and_interval(self) -> Self:
        expected_id_family = ORIGIN_EVIDENCE_ID_FAMILY[self.origin]
        actual_id_family = self.evidence_id.partition(".")[0]
        if actual_id_family != expected_id_family:
            raise ValueError(
                f"evidence_id family must be {expected_id_family} for origin {self.origin.value}"
            )
        if self.source_uri is None and self.source_key is None:
            raise ValueError("source_uri ou source_key é obrigatório")
        if (
            self.observed_at is None
            and self.effective_at is None
            and self.temporal_coverage == "known"
        ):
            raise ValueError(
                "observed_at ou effective_at é obrigatório quando temporal_coverage=known"
            )
        if (self.valid_from is None) != (self.valid_to is None):
            raise ValueError("valid_from e valid_to devem ser informados juntos")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to <= self.valid_from
        ):
            raise ValueError("valid_to deve ser posterior a valid_from")
        hashes = self.source_sha256s or (
            () if self.source_sha256 is None else (self.source_sha256,)
        )
        if self.origin is DataOrigin.ONS_PUBLICO and (self.source_key is None or not hashes):
            raise ValueError("ONS_PUBLICO requires source_key and source SHA-256")
        if self.source_sha256 is not None and hashes and self.source_sha256 not in hashes:
            raise ValueError("source_sha256 must be included in source_sha256s")
        if len(hashes) > 1 and not self.source_artifacts:
            raise ValueError("multi-source provenance requires source_artifacts")
        if self.source_artifacts:
            artifact_hashes = tuple(artifact.source_sha256 for artifact in self.source_artifacts)
            artifact_keys = tuple(artifact.source_key for artifact in self.source_artifacts)
            if tuple(sorted(artifact_hashes)) != hashes or len(set(artifact_hashes)) != len(
                artifact_hashes
            ):
                raise ValueError(
                    "source_artifacts must contain exactly one pair for every source_sha256s digest"
                )
            if len(set(artifact_keys)) != len(artifact_keys):
                raise ValueError(
                    "source_artifacts cannot pair one source key with multiple digests"
                )
            representative = self.source_artifacts[0]
            if (
                self.source_key != representative.source_key
                or self.source_sha256 != representative.source_sha256
            ):
                raise ValueError(
                    "source_key and source_sha256 must identify the first source_artifact"
                )
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
    demanda_prevista_mw: FiniteFloat = Field(ge=0)
    geracao_renovavel_prevista_mw: FiniteFloat = Field(ge=0)
    geracao_convencional_disponivel_mw: FiniteFloat = Field(ge=0)
    restricoes_transmissao: list[BoundedText] = Field(default_factory=list, max_length=64)
    limite_corte_permitido_mw: FiniteFloat = Field(ge=0)
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
    capacity_mw: FiniteFloat | None
    capacity_provenance: EvidenceProvenance | None
    ons_group: str
    connection_point: str
    data_mode: Literal["demo", "ons_materialized"]
    field_provenance: dict[str, EvidenceProvenance]

    @model_validator(mode="after")
    def require_capacity_provenance(self) -> Self:
        if (self.capacity_mw is None) != (self.capacity_provenance is None):
            raise ValueError("capacity_mw and capacity_provenance must be provided together")
        if self.capacity_provenance and self.capacity_provenance.field_name != "capacity_mw":
            raise ValueError("capacity provenance must identify capacity_mw")
        required = {
            "asset_id",
            "name",
            "technology",
            "capacity_mw",
            "ons_group",
            "connection_point",
        }
        if set(self.field_provenance) != required:
            raise ValueError("field_provenance must cover every asset field")
        if any(
            provenance.field_name != field_name
            for field_name, provenance in self.field_provenance.items()
        ):
            raise ValueError("asset field_provenance field_name mismatch")
        if self.capacity_provenance and (
            self.field_provenance["capacity_mw"].evidence_id != self.capacity_provenance.evidence_id
        ):
            raise ValueError("asset capacity provenance must match field_provenance")
        return self


class AssetList(BaseModel):
    items: list[Asset]


class Period(BaseModel):
    start: date
    end: date


class NumericEvidence(BaseModel):
    value: FiniteFloat
    unit: str
    period: Period
    source: str
    data_version: str
    method: str
    value_status: ValueStatus
    origin: DataOrigin
    limitations: list[str]
    provenance_id: str
    provenance: EvidenceProvenance

    @model_validator(mode="after")
    def validate_semantics(self) -> Self:
        expected = STATUS_ORIGIN[self.value_status]
        if self.origin is not expected:
            raise ValueError(f"origin must be {expected.value} for {self.value_status}")
        if self.provenance.origin is not self.origin:
            raise ValueError("provenance origin must match evidence origin")
        if self.provenance.evidence_id != self.provenance_id:
            raise ValueError("provenance_id must equal provenance.evidence_id")
        return self


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
    coverage_percent: FiniteFloat
    null_count: int | None
    duplicate_count: int | None
    source: str
    source_sha256: str
    limitations: list[str]


class ProvenanceResponse(BaseModel):
    provenance_id: str
    evidence_id: str
    classification: ValueStatus
    origin: DataOrigin
    dataset: str
    source: str
    source_bucket: str | None
    source_key: str
    source_sha256: str
    source_sha256s: list[str]
    data_version: str
    method: str
    method_version: str
    field_name: str
    observed_at: datetime | None
    effective_at: datetime | None
    valid_from: datetime | None
    valid_to: datetime | None
    asset_ids: list[str]
    parent_evidence_ids: list[str]
    limitations: list[str]
    provenance: EvidenceProvenance


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
    unavailable_periods: list[Period] = Field(default_factory=list, max_length=64)


class EnergyPrice(BaseModel):
    value: FiniteFloat = Field(ge=0, le=MAX_DECISION_INPUT)
    unit: Literal["BRL/MWh"]
    source: BoundedText
    value_status: Literal["informado"]
    origin: Literal[DataOrigin.CLIENTE_INFORMADO]
    provenance: EvidenceProvenance

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_provenance(cls, value: Any) -> Any:
        if isinstance(value, dict) and "provenance" not in value:
            value = dict(value)
            value["provenance"] = inferred_client_provenance(
                "energy_price",
                {key: item for key, item in value.items() if key != "provenance"},
                "maintenance-energy-price",
            )
        return value

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if self.provenance.origin is not DataOrigin.CLIENTE_INFORMADO:
            raise ValueError("energy price provenance must be CLIENTE_INFORMADO")
        if self.provenance.field_name != "energy_price":
            raise ValueError("energy price provenance must identify energy_price")
        return self


_MAINTENANCE_INPUT_FIELDS = {
    "asset_id",
    "start",
    "end",
    "duration_hours",
    "minimum_notice_hours",
    "baseline_window_start",
    "weekdays_only",
    "unavailable_periods",
    "energy_price",
}


class MaintenanceRankRequest(BaseModel):
    asset_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    start: date
    end: date
    duration_hours: int = Field(gt=0, le=MAX_PLANNING_DAYS * 24)
    minimum_notice_hours: int = Field(ge=0, le=MAX_PLANNING_DAYS * 24)
    baseline_window_start: datetime
    constraints: MaintenanceConstraints = Field(default_factory=MaintenanceConstraints)
    energy_price: EnergyPrice
    input_provenance: dict[str, EvidenceProvenance] | None = None

    @model_validator(mode="after")
    def validate_input_provenance(self) -> Self:
        if self.start > self.end:
            raise ValueError("start deve ser anterior ou igual a end")
        if (self.end - self.start).days + 1 > MAX_PLANNING_DAYS:
            raise ValueError(f"maintenance planning horizon exceeds {MAX_PLANNING_DAYS} days")
        if self.input_provenance is None:
            values = {
                "asset_id": self.asset_id,
                "start": self.start,
                "end": self.end,
                "duration_hours": self.duration_hours,
                "minimum_notice_hours": self.minimum_notice_hours,
                "baseline_window_start": self.baseline_window_start,
                "weekdays_only": self.constraints.weekdays_only,
                "unavailable_periods": [
                    period.model_dump(mode="json")
                    for period in self.constraints.unavailable_periods
                ],
            }
            self.input_provenance = {
                field_name: inferred_client_provenance(
                    field_name,
                    field_value,
                    f"maintenance:{self.asset_id}",
                )
                for field_name, field_value in values.items()
            }
            self.input_provenance["energy_price"] = self.energy_price.provenance
        if set(self.input_provenance) != _MAINTENANCE_INPUT_FIELDS:
            raise ValueError("input_provenance must cover every maintenance decision input")
        evidence_ids = set()
        for field_name, provenance in self.input_provenance.items():
            if provenance.field_name != field_name:
                raise ValueError("maintenance input provenance field_name mismatch")
            if provenance.origin is DataOrigin.SIMULADO:
                raise ValueError("maintenance caller inputs cannot claim SIMULADO provenance")
            evidence_ids.add(provenance.evidence_id)
        if len(evidence_ids) != len(_MAINTENANCE_INPUT_FIELDS):
            raise ValueError("maintenance inputs require unique field-level evidence IDs")
        if (
            self.input_provenance["energy_price"].evidence_id
            != self.energy_price.provenance.evidence_id
        ):
            raise ValueError("energy price provenance must match maintenance input_provenance")
        return self


class MonetaryEvidence(BaseModel):
    value: FiniteFloat
    unit: Literal["BRL"]
    source: str
    value_status: Literal["calculado", "simulado"]
    origin: DataOrigin
    provenance_id: str
    provenance: EvidenceProvenance

    @model_validator(mode="after")
    def validate_semantics(self) -> Self:
        expected = STATUS_ORIGIN[self.value_status]
        if self.origin is not expected:
            raise ValueError(f"origin must be {expected.value} for {self.value_status}")
        if self.provenance.origin is not self.origin:
            raise ValueError("provenance origin must match evidence origin")
        if self.provenance.evidence_id != self.provenance_id:
            raise ValueError("provenance_id must equal provenance.evidence_id")
        return self


class MaintenanceNumericEvidence(BaseModel):
    """Numeric result referencing the authoritative copy in field_provenance."""

    value: FiniteFloat
    unit: str
    period: Period
    source: str
    data_version: str
    method: str
    value_status: Literal["calculado"]
    origin: Literal[DataOrigin.PROXY_CALCULADO]
    limitations: list[str]
    provenance_id: EvidenceId


class MaintenanceMonetaryEvidence(BaseModel):
    """Monetary result referencing the authoritative copy in field_provenance."""

    value: FiniteFloat
    unit: Literal["BRL"]
    source: str
    value_status: Literal["calculado"]
    origin: Literal[DataOrigin.PROXY_CALCULADO]
    provenance_id: EvidenceId


class RankedMaintenanceWindow(BaseModel):
    rank: int
    start: datetime
    end: datetime
    expected_curtailed_energy: MaintenanceNumericEvidence
    opportunity_cost: MaintenanceMonetaryEvidence
    difference_from_baseline_mwh: FiniteFloat
    difference_from_baseline: MaintenanceNumericEvidence
    field_provenance: dict[str, EvidenceProvenance]

    @model_validator(mode="after")
    def validate_field_provenance(self) -> Self:
        required = {
            "rank",
            "start",
            "end",
            "expected_curtailed_energy",
            "opportunity_cost",
            "difference_from_baseline_mwh",
            "difference_from_baseline",
        }
        if set(self.field_provenance) != required:
            raise ValueError("field_provenance must cover every ranked window output")
        if any(
            provenance.field_name != field_name
            for field_name, provenance in self.field_provenance.items()
        ):
            raise ValueError("ranked window field_provenance field_name mismatch")
        nested_ids = {
            "expected_curtailed_energy": self.expected_curtailed_energy.provenance_id,
            "opportunity_cost": self.opportunity_cost.provenance_id,
            "difference_from_baseline": self.difference_from_baseline.provenance_id,
        }
        if any(
            self.field_provenance[field_name].evidence_id != provenance_id
            for field_name, provenance_id in nested_ids.items()
        ):
            raise ValueError("ranked window field_provenance must match nested evidence")
        if any(
            provenance.origin is not DataOrigin.PROXY_CALCULADO
            for provenance in self.field_provenance.values()
        ):
            raise ValueError("ranked window outputs must use PROXY_CALCULADO provenance")
        return self


class MaintenanceRankResponse(BaseModel):
    asset_id: str
    ranking_mode: Literal["historical_prototype"]
    data_mode: Literal["ons_materialized"]
    baseline_window_start: datetime
    input_provenance: dict[str, EvidenceProvenance]
    ranked_windows: list[RankedMaintenanceWindow]
    limitations: list[str]


class BessScreenRequest(BaseModel):
    asset_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    maintenance_result_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    power_mw: FiniteFloat = Field(gt=0, le=MAX_DECISION_INPUT)
    energy_mwh: FiniteFloat = Field(gt=0, le=MAX_DECISION_INPUT)
    capex_brl: FiniteFloat = Field(ge=0, le=MAX_DECISION_INPUT)
    annualized_cost_brl: FiniteFloat = Field(ge=0, le=MAX_DECISION_INPUT)
    round_trip_efficiency: FiniteFloat = Field(gt=0, le=1)
    cycles_per_year: int = Field(gt=0, le=1_000_000)
    energy_price_brl_mwh: FiniteFloat = Field(ge=0, le=MAX_DECISION_INPUT)
    input_provenance: dict[str, EvidenceProvenance] | None = None

    @model_validator(mode="after")
    def validate_input_provenance(self) -> Self:
        required = {
            "asset_id",
            "maintenance_result_id",
            "power_mw",
            "energy_mwh",
            "capex_brl",
            "annualized_cost_brl",
            "round_trip_efficiency",
            "cycles_per_year",
            "energy_price_brl_mwh",
        }
        if self.input_provenance is None:
            self.input_provenance = {
                field_name: inferred_client_provenance(
                    field_name,
                    getattr(self, field_name),
                    f"bess:{self.asset_id}:{self.maintenance_result_id}",
                )
                for field_name in required
            }
        if set(self.input_provenance) != required:
            raise ValueError("input_provenance must cover every decision-affecting BESS input")
        evidence_ids = set()
        for field_name, provenance in self.input_provenance.items():
            if provenance.field_name != field_name:
                raise ValueError("BESS input provenance field_name mismatch")
            if provenance.origin is DataOrigin.SIMULADO:
                raise ValueError("BESS caller inputs cannot claim SIMULADO provenance")
            evidence_ids.add(provenance.evidence_id)
        if len(evidence_ids) != len(required):
            raise ValueError("BESS inputs require unique field-level evidence IDs")
        return self


class BessScreenResponse(BaseModel):
    asset_id: str
    maintenance_result_id: str
    screening_mode: Literal["historical_deterministic"]
    data_mode: Literal["ons_materialized"]
    residual_exposure_mwh: FiniteFloat
    technically_absorbable_mwh: FiniteFloat
    annual_benefit_brl: FiniteFloat
    annual_net_benefit_brl: FiniteFloat
    preliminary_viable: bool
    input_provenance: dict[str, EvidenceProvenance]
    source_observation: EvidenceProvenance
    output_evidence: dict[str, NumericEvidence | MonetaryEvidence]
    missing_data: list[str]
    limitations: list[str]

    @model_validator(mode="after")
    def validate_calculated_lineage(self) -> Self:
        required = {
            "residual_exposure_mwh",
            "technically_absorbable_mwh",
            "annual_benefit_brl",
            "annual_net_benefit_brl",
            "preliminary_viable",
        }
        if set(self.output_evidence) != required:
            raise ValueError("output_evidence must cover every decision-affecting BESS output")
        if self.source_observation.origin is not DataOrigin.PROXY_CALCULADO:
            raise ValueError("curated BESS source aggregate must use PROXY_CALCULADO provenance")
        for field_name, evidence in self.output_evidence.items():
            if evidence.provenance.field_name != field_name:
                raise ValueError("BESS output provenance field_name mismatch")
            if evidence.origin is not DataOrigin.PROXY_CALCULADO:
                raise ValueError("deterministic BESS outputs must use PROXY_CALCULADO provenance")
            if self.source_observation.evidence_id not in evidence.provenance.parent_evidence_ids:
                raise ValueError("BESS outputs must reference their source aggregate")
        return self


class ModelRunResponse(BaseModel):
    model_run_id: str
    run_type: Literal["historical_replay"]
    model_used: Literal[False]
    validation_status: Literal["materialized_historical_data"]
    dataset: str
    period: str
    asset_count: int
    source_sha256s: list[str]
    metrics: dict[str, FiniteFloat] | None
    limitations: list[str]


class ReportCreateRequest(BaseModel):
    asset_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=64)
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
