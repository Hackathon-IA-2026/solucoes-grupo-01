from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from curtailess.datasets import DatasetSpec


@dataclass(frozen=True)
class MaterializationContext:
    spec: DatasetSpec
    period: str
    source_path: Path
    curated_path: Path
    source_fingerprint: str
    source_sha256: str
    source_bucket: str
    source_key: str
    source_last_modified: str | None


@dataclass(frozen=True)
class MaterializationOutput:
    dynamodb_items: list[dict[str, Any]]
    row_count: int
    fact_count: int
    metrics: dict[str, Any]

    @property
    def dynamodb_keys(self) -> list[dict[str, str]]:
        return sorted(
            (
                {"asset_id": str(item["asset_id"]), "period": str(item["period"])}
                for item in self.dynamodb_items
            ),
            key=lambda item: (item["asset_id"], item["period"]),
        )


Materializer = Callable[[duckdb.DuckDBPyConnection, MaterializationContext], MaterializationOutput]


def source_columns(connection: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in connection.execute("DESCRIBE source_rows").fetchall()}


def require_columns(connection: duckdb.DuckDBPyConnection, required: tuple[str, ...]) -> None:
    missing = set(required) - source_columns(connection)
    if missing:
        raise ValueError(f"Colunas obrigatórias ausentes: {sorted(missing)}")


def create_curated_copy(
    connection: duckdb.DuckDBPyConnection,
    context: MaterializationContext,
    select_sql: str,
    parameters: list[Any] | None = None,
) -> None:
    connection.execute("DROP TABLE IF EXISTS curated_rows")
    connection.execute(f"CREATE TEMP TABLE curated_rows AS {select_sql}", parameters or [])
    connection.execute(
        "COPY curated_rows TO ? (FORMAT PARQUET, COMPRESSION ZSTD)",
        [str(context.curated_path)],
    )


def resolve_materializer(name: str) -> Materializer:
    if name == "constrained_off":
        from curtailess.materializers.constrained_off import materialize

        return materialize
    if name == "forecast":
        from curtailess.materializers.forecast import materialize

        return materialize
    if name == "generation":
        from curtailess.materializers.generation import materialize

        return materialize
    if name == "assets":
        from curtailess.materializers.assets import materialize

        return materialize
    raise ValueError(f"Materializador não registrado: {name}")
