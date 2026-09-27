from collections import defaultdict
from decimal import Decimal
from zoneinfo import ZoneInfo

import duckdb

from curtailess.materializers import (
    MaterializationContext,
    MaterializationOutput,
    create_curated_copy,
    require_columns,
)


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(round(float(value), 6)))


def materialize(
    connection: duckdb.DuckDBPyConnection, context: MaterializationContext
) -> MaterializationOutput:
    require_columns(connection, context.spec.required_columns)
    create_curated_copy(
        connection,
        context,
        """
        SELECT
            strptime(trim(dat_programacao), '%Y%m%d')::DATE AS program_date,
            num_patamar AS interval_number,
            strptime(trim(dat_programacao), '%Y%m%d')
                + (num_patamar - 1) * INTERVAL 30 MINUTE AS valid_at,
            'America/Sao_Paulo'::VARCHAR AS valid_timezone,
            trim(cod_usinapdp) AS program_entity_id,
            trim(nom_usinapdp) AS program_entity_name,
            try_cast(replace(trim(val_previsao), ',', '.') AS DOUBLE) AS forecast_mw,
            try_cast(replace(trim(val_programado), ',', '.') AS DOUBLE) AS programmed_mw,
            ?::VARCHAR AS source_dataset,
            ?::VARCHAR AS source_period,
            ?::VARCHAR AS source_fingerprint,
            ?::VARCHAR AS source_sha256,
            ?::VARCHAR AS source_bucket,
            ?::VARCHAR AS source_key,
            ?::VARCHAR AS source_object_last_modified,
            'source_object_last_modified_proxy'::VARCHAR AS publication_time_status,
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
            context.source_last_modified,
        ],
    )
    rows = connection.execute(
        """
        SELECT
            trim(cod_usinapdp),
            trim(nom_usinapdp),
            num_patamar,
            strptime(trim(dat_programacao), '%Y%m%d')
                + (num_patamar - 1) * INTERVAL 30 MINUTE,
            try_cast(replace(trim(val_previsao), ',', '.') AS DOUBLE),
            try_cast(replace(trim(val_programado), ',', '.') AS DOUBLE)
        FROM source_rows
        WHERE nullif(trim(cod_usinapdp), '') IS NOT NULL
          AND num_patamar BETWEEN 1 AND 48
        ORDER BY trim(cod_usinapdp), num_patamar
        """
    ).fetchall()
    by_entity: dict[str, list[dict]] = defaultdict(list)
    names: dict[str, str] = {}
    for entity_id, name, interval_number, valid_at, forecast_mw, programmed_mw in rows:
        names[entity_id] = name
        by_entity[entity_id].append(
            {
                "interval_number": int(interval_number),
                "valid_at": valid_at.replace(tzinfo=ZoneInfo("America/Sao_Paulo")).isoformat(),
                "forecast_mw": _decimal(forecast_mw),
                "programmed_mw": _decimal(programmed_mw),
            }
        )
    items = []
    for entity_id in sorted(by_entity):
        intervals = by_entity[entity_id]
        items.append(
            {
                "asset_id": f"program:{entity_id}",
                "period": f"forecast#{context.period}",
                "fact_type": "forecast_program_daily",
                "dataset": context.spec.dataset_id,
                "grain": context.spec.grain,
                "technology": context.spec.technology,
                "program_entity_id": entity_id,
                "program_entity_name": names[entity_id],
                "program_date": context.period,
                "publication_timestamp": context.source_last_modified,
                "publication_time_status": "source_object_last_modified_proxy",
                "intervals": intervals,
                "interval_count": len(intervals),
                "provenance_status": "ONS_PUBLICO",
                "source_bucket": context.source_bucket,
                "source_key": context.source_key,
                "source_sha256": context.source_sha256,
                "source_fingerprint": context.source_fingerprint,
            }
        )
    counts = connection.execute(
        """
        SELECT
            count(*),
            count(*) - count(DISTINCT (trim(cod_usinapdp), num_patamar)),
            count(*) FILTER (
                WHERE try_cast(replace(trim(val_previsao), ',', '.') AS DOUBLE) IS NULL
            ),
            count(*) FILTER (
                WHERE try_cast(replace(trim(val_programado), ',', '.') AS DOUBLE) IS NULL
            )
        FROM source_rows
        """
    ).fetchone()
    return MaterializationOutput(
        dynamodb_items=items,
        row_count=int(counts[0]),
        fact_count=len(items),
        metrics={
            "program_entity_count": len(items),
            "duplicate_interval_count": int(counts[1]),
            "invalid_or_null_forecast_count": int(counts[2]),
            "invalid_or_null_programmed_count": int(counts[3]),
            "publication_time_status": "source_object_last_modified_proxy",
        },
    )
