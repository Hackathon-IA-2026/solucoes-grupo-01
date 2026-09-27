import calendar
import re
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

PeriodGranularity = Literal["day", "month", "year", "snapshot"]
IngestionMode = Literal["backfill", "incremental"]
Technology = Literal["wind", "solar", "wind_and_solar", "all"]
DatasetGrain = Literal[
    "plant_half_hour",
    "program_entity_half_hour",
    "plant_hour",
    "plant_group_relationship",
    "generating_unit",
]
Materializer = Literal["constrained_off", "forecast", "generation", "assets"]


class DatasetPeriod(BaseModel):
    """Period encoded by an ONS object name; snapshots intentionally have no dates."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    label: str = Field(min_length=1)
    start: date | None
    end: date | None
    granularity: PeriodGranularity

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.granularity == "snapshot":
            if self.start is not None or self.end is not None or self.label != "snapshot":
                raise ValueError("snapshot periods must use label='snapshot' without date bounds")
            return self
        if self.start is None or self.end is None:
            raise ValueError("dated periods require start and end")
        if self.end < self.start:
            raise ValueError("period end cannot precede start")
        return self


class DatasetSpec(BaseModel):
    """Strict metadata contract for one verified public ONS dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    dataset_id: str = Field(min_length=1)
    source_bucket: Literal["ons-aws-prod-opendata"]
    s3_prefix: str = Field(min_length=1)
    technology: Technology
    grain: DatasetGrain
    filename_pattern: str = Field(min_length=1)
    period_parser: Callable[[str], DatasetPeriod]
    required_columns: tuple[str, ...] = Field(min_length=1)
    aliases: dict[str, tuple[str, ...]]
    source_timezone: Literal["America/Sao_Paulo"]
    materializer: Materializer
    schema_version: Literal["1"]
    enabled_modes: frozenset[IngestionMode] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.s3_prefix != f"dataset/{self.dataset_id}/":
            raise ValueError("s3_prefix must be the exact public ONS dataset prefix")
        if not self.aliases:
            raise ValueError("aliases cannot be empty")
        return self


def _dated_parser(
    filename_pattern: str,
    granularity: Literal["day", "month", "year"],
) -> Callable[[str], DatasetPeriod]:
    compiled = re.compile(filename_pattern)

    def parse(source_key: str) -> DatasetPeriod:
        filename = PurePosixPath(source_key).name
        match = compiled.fullmatch(filename)
        if match is None:
            raise ValueError(f"{filename!r} não corresponde ao padrão ONS {filename_pattern!r}")
        year = int(match.group("year"))
        if granularity == "year":
            return DatasetPeriod(
                label=f"{year:04d}",
                start=date(year, 1, 1),
                end=date(year, 12, 31),
                granularity="year",
            )
        month = int(match.group("month"))
        if granularity == "month":
            last_day = calendar.monthrange(year, month)[1]
            return DatasetPeriod(
                label=f"{year:04d}-{month:02d}",
                start=date(year, month, 1),
                end=date(year, month, last_day),
                granularity="month",
            )
        day = int(match.group("day"))
        parsed_date = date(year, month, day)
        return DatasetPeriod(
            label=parsed_date.isoformat(),
            start=parsed_date,
            end=parsed_date,
            granularity="day",
        )

    return parse


def _generation_period_parser(source_key: str) -> DatasetPeriod:
    filename_pattern = r"GERACAO_USINA-2_(?P<year>\d{4})(?:_(?P<month>\d{2}))?\.parquet"
    match = re.fullmatch(filename_pattern, PurePosixPath(source_key).name)
    if match is None:
        raise ValueError(
            f"{PurePosixPath(source_key).name!r} não corresponde ao padrão ONS {filename_pattern!r}"
        )
    year = int(match.group("year"))
    month_text = match.group("month")
    if month_text is None and year > 2021:
        raise ValueError("arquivos anuais de geração foram verificados somente até 2021")
    if month_text is not None and year < 2022:
        raise ValueError("arquivos mensais de geração foram verificados somente desde 2022")
    if month_text is None:
        return DatasetPeriod(
            label=f"{year:04d}",
            start=date(year, 1, 1),
            end=date(year, 12, 31),
            granularity="year",
        )
    month = int(month_text)
    return DatasetPeriod(
        label=f"{year:04d}-{month:02d}",
        start=date(year, month, 1),
        end=date(year, month, calendar.monthrange(year, month)[1]),
        granularity="month",
    )


def _snapshot_parser(expected_filename: str) -> Callable[[str], DatasetPeriod]:
    def parse(source_key: str) -> DatasetPeriod:
        filename = PurePosixPath(source_key).name
        if filename != expected_filename:
            raise ValueError(
                f"{filename!r} não corresponde ao padrão ONS estático {expected_filename!r}"
            )
        return DatasetPeriod(label="snapshot", start=None, end=None, granularity="snapshot")

    return parse


_CONSTRAINED_OFF_COLUMNS = (
    "id_ons",
    "nom_usina",
    "id_estado",
    "din_instante",
    "val_geracao",
    "val_disponibilidade",
    "val_geracaolimitada",
    "val_geracaoreferencia",
    "val_geracaonaorealizadaapurada",
    "cod_razaorestricao",
    "cod_origemrestricao",
    "id_pontoconexao",
)
_CONSTRAINED_OFF_ALIASES = {
    "asset_id": ("id_ons",),
    "asset_name": ("nom_usina",),
    "observed_at": ("din_instante",),
    "state": ("id_estado",),
    "connection_point_id": ("id_pontoconexao",),
}

_DATASETS = (
    DatasetSpec(
        dataset_id="restricao_coff_eolica_tm",
        source_bucket="ons-aws-prod-opendata",
        s3_prefix="dataset/restricao_coff_eolica_tm/",
        technology="wind",
        grain="plant_half_hour",
        filename_pattern=r"RESTRICAO_COFF_EOLICA_(?P<year>\d{4})_(?P<month>\d{2})\.parquet",
        period_parser=_dated_parser(
            r"RESTRICAO_COFF_EOLICA_(?P<year>\d{4})_(?P<month>\d{2})\.parquet",
            "month",
        ),
        required_columns=_CONSTRAINED_OFF_COLUMNS,
        aliases=_CONSTRAINED_OFF_ALIASES,
        source_timezone="America/Sao_Paulo",
        materializer="constrained_off",
        schema_version="1",
        enabled_modes=frozenset({"backfill", "incremental"}),
    ),
    DatasetSpec(
        dataset_id="restricao_coff_fotovoltaica_tm",
        source_bucket="ons-aws-prod-opendata",
        s3_prefix="dataset/restricao_coff_fotovoltaica_tm/",
        technology="solar",
        grain="plant_half_hour",
        filename_pattern=(r"RESTRICAO_COFF_FOTOVOLTAICA_(?P<year>\d{4})_(?P<month>\d{2})\.parquet"),
        period_parser=_dated_parser(
            r"RESTRICAO_COFF_FOTOVOLTAICA_(?P<year>\d{4})_(?P<month>\d{2})\.parquet",
            "month",
        ),
        required_columns=_CONSTRAINED_OFF_COLUMNS,
        aliases=_CONSTRAINED_OFF_ALIASES,
        source_timezone="America/Sao_Paulo",
        materializer="constrained_off",
        schema_version="1",
        enabled_modes=frozenset({"backfill", "incremental"}),
    ),
    DatasetSpec(
        dataset_id="programacao_x_previsao",
        source_bucket="ons-aws-prod-opendata",
        s3_prefix="dataset/programacao_x_previsao/",
        technology="wind_and_solar",
        grain="program_entity_half_hour",
        filename_pattern=(
            r"PROGRAMACAO_X_PREVISAO_(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})\.parquet"
        ),
        period_parser=_dated_parser(
            r"PROGRAMACAO_X_PREVISAO_(?P<year>\d{4})_(?P<month>\d{2})_"
            r"(?P<day>\d{2})\.parquet",
            "day",
        ),
        required_columns=(
            "dat_programacao",
            "num_patamar",
            "cod_usinapdp",
            "nom_usinapdp",
            "val_previsao",
            "val_programado",
        ),
        aliases={
            "program_date": ("dat_programacao",),
            "interval_number": ("num_patamar",),
            "program_entity_id": ("cod_usinapdp",),
            "program_entity_name": ("nom_usinapdp",),
        },
        source_timezone="America/Sao_Paulo",
        materializer="forecast",
        schema_version="1",
        enabled_modes=frozenset({"backfill", "incremental"}),
    ),
    DatasetSpec(
        dataset_id="geracao_usina_2_ho",
        source_bucket="ons-aws-prod-opendata",
        s3_prefix="dataset/geracao_usina_2_ho/",
        technology="all",
        grain="plant_hour",
        filename_pattern=(r"GERACAO_USINA-2_(?P<year>\d{4})(?:_(?P<month>\d{2}))?\.parquet"),
        period_parser=_generation_period_parser,
        required_columns=("din_instante", "id_ons", "nom_usina", "nom_tipousina", "val_geracao"),
        aliases={
            "observed_at": ("din_instante",),
            "asset_id": ("id_ons",),
            "asset_name": ("nom_usina",),
            "technology_name": ("nom_tipousina",),
        },
        source_timezone="America/Sao_Paulo",
        materializer="generation",
        schema_version="1",
        enabled_modes=frozenset({"backfill", "incremental"}),
    ),
    DatasetSpec(
        dataset_id="usina_conjunto",
        source_bucket="ons-aws-prod-opendata",
        s3_prefix="dataset/usina_conjunto/",
        technology="all",
        grain="plant_group_relationship",
        filename_pattern=r"RELACIONAMENTO_USINA_CONJUNTO\.parquet",
        period_parser=_snapshot_parser("RELACIONAMENTO_USINA_CONJUNTO.parquet"),
        required_columns=(
            "id_ons_conjunto",
            "id_ons_usina",
            "nom_conjunto",
            "nom_usina",
            "ceg",
            "dat_iniciorelacionamento",
            "dat_fimrelacionamento",
        ),
        aliases={
            "group_id": ("id_ons_conjunto",),
            "asset_id": ("id_ons_usina",),
            "valid_from": ("dat_iniciorelacionamento",),
            "valid_to": ("dat_fimrelacionamento",),
        },
        source_timezone="America/Sao_Paulo",
        materializer="assets",
        schema_version="1",
        enabled_modes=frozenset({"incremental"}),
    ),
    DatasetSpec(
        dataset_id="capacidade-geracao",
        source_bucket="ons-aws-prod-opendata",
        s3_prefix="dataset/capacidade-geracao/",
        technology="all",
        grain="generating_unit",
        filename_pattern=r"CAPACIDADE_GERACAO\.parquet",
        period_parser=_snapshot_parser("CAPACIDADE_GERACAO.parquet"),
        required_columns=(
            "ceg",
            "nom_usina",
            "nom_tipousina",
            "cod_equipamento",
            "dat_entradateste",
            "dat_entradaoperacao",
            "dat_desativacao",
            "val_potenciaefetiva",
        ),
        aliases={
            "asset_external_id": ("ceg",),
            "asset_name": ("nom_usina",),
            "technology_name": ("nom_tipousina",),
            "capacity_mw": ("val_potenciaefetiva",),
            "valid_from": ("dat_entradaoperacao", "dat_entradateste"),
            "valid_to": ("dat_desativacao",),
        },
        source_timezone="America/Sao_Paulo",
        materializer="assets",
        schema_version="1",
        enabled_modes=frozenset({"incremental"}),
    ),
)

DATASET_REGISTRY: Mapping[str, DatasetSpec] = MappingProxyType(
    {spec.dataset_id: spec for spec in _DATASETS}
)


def get_dataset_spec(dataset_id: str) -> DatasetSpec:
    try:
        return DATASET_REGISTRY[dataset_id]
    except KeyError as exc:
        raise ValueError(f"Dataset ONS não registrado: {dataset_id}") from exc
