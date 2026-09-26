from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    capacity_mw: float
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
    limitations: list[str]
    provenance_id: str


class ExposureResponse(BaseModel):
    asset_id: str
    perspective_type: Literal["historical_observed"]
    data_mode: Literal["demo", "ons_materialized"]
    total_curtailed_energy: NumericEvidence
    limitations: list[str]
