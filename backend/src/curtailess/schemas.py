import base64
import hashlib
import json
import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def build_evidence_id(
    source_identities: str | list[str] | tuple[str, ...],
    field_name: str,
    method_version: str,
    context: str,
) -> str:
    """Build a deterministic, self-describing field-level evidence identifier."""

    sources = (
        [source_identities] if isinstance(source_identities, str) else sorted(source_identities)
    )
    payload = {
        "context": context,
        "field": field_name,
        "method": method_version,
        "sources": sources,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    digest = hashlib.sha256(raw).hexdigest()[:24]
    return f"ev1.{encoded}.{digest}"


def parse_evidence_id(evidence_id: str) -> dict[str, Any]:
    """Decode and integrity-check an identifier produced by :func:`build_evidence_id`."""

    try:
        prefix, encoded, digest = evidence_id.split(".")
        if prefix != "ev1":
            raise ValueError
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if hashlib.sha256(raw).hexdigest()[:24] != digest:
            raise ValueError
        payload = json.loads(raw)
        if set(payload) != {"context", "field", "method", "sources"}:
            raise ValueError
        if not payload["field"] or not payload["method"] or not payload["sources"]:
            raise ValueError
        return payload
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("evidence_id inválido ou corrompido") from exc


def inferred_client_provenance(field_name: str, value: Any, context: str) -> "EvidenceProvenance":
    """Create deterministic, explicitly inferred provenance for a legacy caller input."""

    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
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


class EvidenceProvenance(BaseModel):
    """Authoritative source, temporal validity, and method metadata for one field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    origin: DataOrigin
    source_uri: str | None = Field(default=None, min_length=1)
    source_key: str | None = Field(default=None, min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_sha256s: tuple[str, ...] = ()
    parent_evidence_ids: tuple[str, ...] = ()
    observed_at: datetime | None = None
    effective_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    method_version: str = Field(min_length=1)
    limitations: list[str]

    @field_validator("source_sha256s")
    @classmethod
    def validate_source_hashes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not _SHA256_PATTERN.fullmatch(value) for value in values):
            raise ValueError("source_sha256s must contain SHA-256 hex digests")
        if tuple(sorted(set(values))) != values:
            raise ValueError("source_sha256s must be sorted and unique")
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
        if self.source_uri is None and self.source_key is None:
            raise ValueError("source_uri ou source_key é obrigatório")
        unknown_capacity_time = (
            self.origin is DataOrigin.ONS_PUBLICO
            and self.field_name == "capacity_mw"
            and self.method_version == "ons_capacity_source_v1"
            and any("temporal" in limitation.lower() for limitation in self.limitations)
        )
        if self.observed_at is None and self.effective_at is None and not unknown_capacity_time:
            raise ValueError(
                "observed_at ou effective_at é obrigatório, salvo limitação temporal explícita"
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
    value: float
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
    coverage_percent: float
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
    unavailable_periods: list[Period] = Field(default_factory=list)


class EnergyPrice(BaseModel):
    value: float = Field(ge=0)
    unit: Literal["BRL/MWh"]
    source: str = Field(min_length=1)
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
    asset_id: str
    start: date
    end: date
    duration_hours: int = Field(gt=0)
    minimum_notice_hours: int = Field(ge=0)
    baseline_window_start: datetime
    constraints: MaintenanceConstraints = Field(default_factory=MaintenanceConstraints)
    energy_price: EnergyPrice
    input_provenance: dict[str, EvidenceProvenance] | None = None

    @model_validator(mode="after")
    def validate_input_provenance(self) -> Self:
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
    value: float
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


class RankedMaintenanceWindow(BaseModel):
    rank: int
    start: datetime
    end: datetime
    expected_curtailed_energy: NumericEvidence
    opportunity_cost: MonetaryEvidence
    difference_from_baseline_mwh: float
    difference_from_baseline: NumericEvidence
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
        nested = {
            "expected_curtailed_energy": self.expected_curtailed_energy.provenance,
            "opportunity_cost": self.opportunity_cost.provenance,
            "difference_from_baseline": self.difference_from_baseline.provenance,
        }
        if any(
            self.field_provenance[field_name].evidence_id != provenance.evidence_id
            for field_name, provenance in nested.items()
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
    asset_id: str
    maintenance_result_id: str
    power_mw: float = Field(gt=0)
    energy_mwh: float = Field(gt=0)
    capex_brl: float = Field(ge=0)
    annualized_cost_brl: float = Field(ge=0)
    round_trip_efficiency: float = Field(gt=0, le=1)
    cycles_per_year: int = Field(gt=0)
    energy_price_brl_mwh: float = Field(ge=0)
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
    residual_exposure_mwh: float
    technically_absorbable_mwh: float
    annual_benefit_brl: float
    annual_net_benefit_brl: float
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
