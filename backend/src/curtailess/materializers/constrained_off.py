from collections import defaultdict
from decimal import Decimal
from typing import Any

import duckdb

from curtailess.materializers import (
    MaterializationContext,
    MaterializationOutput,
    create_curated_copy,
    require_columns,
    source_columns,
)

KNOWN_REASONS = {"CNF", "REL", "ENE", "PAR"}
VALUE_COLUMNS = (
    "val_geracao",
    "val_disponibilidade",
    "val_geracaolimitada",
    "val_geracaoreferencia",
    "val_geracaonaorealizadaapurada",
)


def _decimal(value: Any) -> Decimal:
    return Decimal(str(round(float(value or 0), 6)))


def materialize(
    connection: duckdb.DuckDBPyConnection, context: MaterializationContext
) -> MaterializationOutput:
    require_columns(connection, context.spec.required_columns)
    columns = source_columns(connection)
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
            ?::VARCHAR AS technology,
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
            context.spec.technology,
        ],
    )
    point_name = "min(nom_pontoconexao)" if "nom_pontoconexao" in columns else "NULL"
    ceg = "min(ceg)" if "ceg" in columns else "NULL"
    null_expressions = ",\n".join(
        f"count(*) FILTER (WHERE {column} IS NULL) AS null_{column}" for column in VALUE_COLUMNS
    )
    aggregates = connection.execute(
        f"""
        SELECT
            id_ons,
            min(nom_usina),
            min(id_estado),
            min(id_pontoconexao),
            {point_name},
            {ceg},
            min(din_instante),
            max(din_instante),
            count(*),
            count(*) - count(DISTINCT din_instante),
            count(*) FILTER (WHERE val_geracaolimitada IS NOT NULL),
            sum(coalesce(val_geracao, 0) * 0.5),
            sum(coalesce(val_disponibilidade, 0) * 0.5),
            sum(coalesce(val_geracaoreferencia, 0) * 0.5),
            sum(CASE WHEN val_geracaolimitada IS NOT NULL
                THEN coalesce(val_geracaolimitada, 0) * 0.5 ELSE 0 END),
            sum(CASE WHEN val_geracaolimitada IS NOT NULL
                THEN coalesce(val_disponibilidade, 0) * 0.5 ELSE 0 END),
            sum(CASE WHEN val_geracaolimitada IS NOT NULL
                THEN coalesce(val_geracaonaorealizadaapurada, 0) * 0.5 ELSE 0 END),
            {null_expressions}
        FROM source_rows
        WHERE id_ons IS NOT NULL
        GROUP BY id_ons
        ORDER BY id_ons
        """
    ).fetchall()
    reason_rows = connection.execute(
        """
        SELECT
            id_ons,
            coalesce(nullif(trim(cod_razaorestricao), ''), '__NULL__') AS reason,
            count(*) AS interval_count,
            sum(coalesce(val_geracaonaorealizadaapurada, 0) * 0.5) AS curtailed_mwh
        FROM source_rows
        WHERE id_ons IS NOT NULL AND val_geracaolimitada IS NOT NULL
        GROUP BY id_ons, reason
        ORDER BY id_ons, reason
        """
    ).fetchall()
    origin_rows = connection.execute(
        """
        SELECT
            id_ons,
            coalesce(nullif(trim(cod_origemrestricao), ''), '__NULL__') AS origin,
            count(*) AS interval_count
        FROM source_rows
        WHERE id_ons IS NOT NULL AND val_geracaolimitada IS NOT NULL
        GROUP BY id_ons, origin
        ORDER BY id_ons, origin
        """
    ).fetchall()
    reasons: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for asset_id, reason, count, curtailed_mwh in reason_rows:
        reasons[asset_id][reason] = {
            "interval_count": int(count),
            "curtailed_mwh": _decimal(curtailed_mwh),
        }
    origins: dict[str, dict[str, int]] = defaultdict(dict)
    for asset_id, origin, count in origin_rows:
        origins[asset_id][origin] = int(count)

    items = []
    unknown_reason_count = 0
    null_reason_count = 0
    for row in aggregates:
        exact_reasons = reasons[row[0]]
        unknown_reasons = {
            reason: values
            for reason, values in exact_reasons.items()
            if reason not in KNOWN_REASONS and reason != "__NULL__"
        }
        unknown_reason_count += sum(value["interval_count"] for value in unknown_reasons.values())
        null_reason_count += exact_reasons.get("__NULL__", {}).get("interval_count", 0)
        compatibility_reasons = {
            reason: exact_reasons.get(reason, {}).get("curtailed_mwh", Decimal("0"))
            for reason in sorted(KNOWN_REASONS)
        }
        compatibility_reasons["NC"] = exact_reasons.get("__NULL__", {}).get(
            "curtailed_mwh", Decimal("0")
        )
        null_counts = {column: int(row[17 + index]) for index, column in enumerate(VALUE_COLUMNS)}
        items.append(
            {
                "asset_id": row[0],
                "period": context.period,
                "fact_type": "constrained_off_monthly",
                "dataset": context.spec.dataset_id,
                "technology": context.spec.technology,
                "asset_name": row[1],
                "state": row[2],
                "point_id": row[3] or "unknown",
                "point_name": row[4] or "unknown",
                "ceg": row[5],
                "period_start": row[6].isoformat(),
                "period_end": row[7].isoformat(),
                "interval_count": int(row[8]),
                "duplicate_interval_count": int(row[9]),
                "limited_interval_count": int(row[10]),
                "generation_mwh": _decimal(row[11]),
                "availability_mwh": _decimal(row[12]),
                "reference_generation_mwh": _decimal(row[13]),
                "limited_generation_mwh": _decimal(row[14]),
                "availability_limited_mwh": _decimal(row[15]),
                "curtailed_mwh": _decimal(row[16]),
                "curtailed_mwh_by_reason": compatibility_reasons,
                "curtailed_mwh_by_reason_exact": exact_reasons,
                "limited_interval_count_by_origin": origins[row[0]],
                "null_counts": null_counts,
                "unknown_reason_codes": sorted(unknown_reasons),
                "data_mode": "ons_materialized",
                "value_status": "measured_ons",
                "provenance_status": "ONS_PUBLICO",
                "method": "sum(half_hour_mwmed * 0.5)_v2",
                "source_bucket": context.source_bucket,
                "source_key": context.source_key,
                "source_sha256": context.source_sha256,
                "source_fingerprint": context.source_fingerprint,
            }
        )
    row_count = int(connection.execute("SELECT count(*) FROM source_rows").fetchone()[0])
    return MaterializationOutput(
        dynamodb_items=items,
        row_count=row_count,
        fact_count=len(items),
        metrics={
            "asset_count": len(items),
            "null_reason_interval_count": null_reason_count,
            "unknown_reason_interval_count": unknown_reason_count,
            "duplicate_interval_count": sum(item["duplicate_interval_count"] for item in items),
        },
    )
