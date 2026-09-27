from collections import defaultdict
from decimal import Decimal
from typing import Any

import duckdb

from curtailess.materializers import (
    MaterializationContext,
    MaterializationOutput,
    create_curated_copy,
    require_columns,
)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(round(float(value or 0), 6)))


def _season(period: str) -> str:
    month = int(period[5:7]) if len(period) >= 7 else 1
    if month in {12, 1, 2}:
        return "summer"
    if month in {3, 4, 5}:
        return "autumn"
    if month in {6, 7, 8}:
        return "winter"
    return "spring"


def materialize(
    connection: duckdb.DuckDBPyConnection, context: MaterializationContext
) -> MaterializationOutput:
    require_columns(connection, context.spec.required_columns)
    create_curated_copy(
        connection,
        context,
        """
        SELECT
            *,
            ?::VARCHAR AS source_dataset,
            ?::VARCHAR AS source_period,
            ?::VARCHAR AS source_fingerprint,
            ?::VARCHAR AS source_sha256,
            ?::VARCHAR AS source_bucket,
            ?::VARCHAR AS source_key,
            'ONS_PUBLICO'::VARCHAR AS provenance_status
        FROM source_rows
        """,
        [
            context.spec.dataset_id,
            context.period,
            context.source_fingerprint,
            context.source_sha256,
            context.source_bucket,
            context.source_key,
        ],
    )
    aggregates = connection.execute(
        """
        SELECT
            id_ons,
            min(nom_usina),
            min(nom_tipousina),
            min(din_instante),
            max(din_instante),
            count(*),
            count(*) - count(DISTINCT din_instante),
            count(*) FILTER (WHERE val_geracao IS NULL),
            avg(val_geracao),
            min(val_geracao),
            max(val_geracao),
            sum(coalesce(val_geracao, 0))
        FROM source_rows
        WHERE nullif(trim(id_ons), '') IS NOT NULL
        GROUP BY id_ons
        ORDER BY id_ons
        """
    ).fetchall()
    hour_rows = connection.execute(
        """
        SELECT
            id_ons,
            extract(hour FROM din_instante)::INTEGER,
            avg(val_geracao),
            count(*) FILTER (WHERE val_geracao IS NOT NULL)
        FROM source_rows
        WHERE nullif(trim(id_ons), '') IS NOT NULL
        GROUP BY id_ons, extract(hour FROM din_instante)
        ORDER BY id_ons, extract(hour FROM din_instante)
        """
    ).fetchall()
    hour_profiles: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for asset_id, hour, mean_mw, count in hour_rows:
        hour_profiles[asset_id][f"{int(hour):02d}"] = {
            "mean_mw": _decimal(mean_mw),
            "observation_count": int(count),
        }
    items = []
    for row in aggregates:
        items.append(
            {
                "asset_id": row[0],
                "period": f"generation#{context.period}",
                "fact_type": "observed_generation_profile",
                "dataset": context.spec.dataset_id,
                "grain": context.spec.grain,
                "asset_name": row[1],
                "technology_name": row[2],
                "period_start": row[3].isoformat(),
                "period_end": row[4].isoformat(),
                "season": _season(context.period),
                "observation_count": int(row[5]),
                "duplicate_observation_count": int(row[6]),
                "null_generation_count": int(row[7]),
                "mean_generation_mw": _decimal(row[8]),
                "min_generation_mw": _decimal(row[9]),
                "max_generation_mw": _decimal(row[10]),
                "observed_generation_mwh": _decimal(row[11]),
                "hour_of_day_profile": hour_profiles[row[0]],
                "provenance_status": "ONS_PUBLICO",
                "source_bucket": context.source_bucket,
                "source_key": context.source_key,
                "source_sha256": context.source_sha256,
                "source_fingerprint": context.source_fingerprint,
            }
        )
    counts = connection.execute(
        """
        SELECT count(*), count(*) FILTER (WHERE nullif(trim(id_ons), '') IS NULL)
        FROM source_rows
        """
    ).fetchone()
    return MaterializationOutput(
        dynamodb_items=items,
        row_count=int(counts[0]),
        fact_count=len(items),
        metrics={
            "asset_count": len(items),
            "rows_without_asset_id": int(counts[1]),
            "duplicate_observation_count": sum(
                item["duplicate_observation_count"] for item in items
            ),
            "season": _season(context.period),
        },
    )
