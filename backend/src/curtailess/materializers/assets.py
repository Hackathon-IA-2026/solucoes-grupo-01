from datetime import datetime
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


def _materialize_relationships(
    connection: duckdb.DuckDBPyConnection, context: MaterializationContext
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT DISTINCT
            trim(id_ons_usina),
            trim(id_ons_conjunto),
            trim(nom_usina),
            trim(nom_conjunto),
            trim(ceg),
            trim(nom_tipousina),
            trim(estad_id),
            nullif(trim(dat_iniciorelacionamento), ''),
            nullif(trim(dat_fimrelacionamento), '')
        FROM source_rows
        WHERE nullif(trim(id_ons_usina), '') IS NOT NULL
        ORDER BY trim(id_ons_usina), dat_iniciorelacionamento, id_ons_conjunto
        """
    ).fetchall()
    items = []
    for row in rows:
        valid_from = row[7] or "unknown"
        group_id = row[1] or "none"
        items.append(
            {
                "asset_id": row[0],
                "period": f"identity#relationship#{valid_from}#{group_id}",
                "fact_type": "asset_group_relationship",
                "dataset": context.spec.dataset_id,
                "asset_name": row[2],
                "ons_group_id": row[1],
                "ons_group_name": row[3],
                "ceg": row[4],
                "technology_name": row[5],
                "state": row[6],
                "valid_from": row[7],
                "valid_to": row[8],
                "provenance_status": "ONS_PUBLICO",
                "source_bucket": context.source_bucket,
                "source_key": context.source_key,
                "source_sha256": context.source_sha256,
                "source_fingerprint": context.source_fingerprint,
            }
        )
    return items


def _materialize_capacity(
    connection: duckdb.DuckDBPyConnection, context: MaterializationContext
) -> list[dict[str, Any]]:
    if context.source_last_modified is None:
        raise ValueError("source_last_modified is required for deterministic capacity state")
    as_of_date = datetime.fromisoformat(context.source_last_modified.replace("Z", "+00:00")).date()
    rows = connection.execute(
        """
        SELECT
            trim(ceg),
            min(trim(nom_usina)),
            min(trim(nom_tipousina)),
            min(trim(id_estado)),
            count(*),
            count(DISTINCT trim(cod_equipamento)),
            sum(coalesce(val_potenciaefetiva, 0)),
            sum(CASE WHEN nullif(trim(dat_desativacao), '') IS NULL
                OR try_cast(trim(dat_desativacao) AS DATE) > ?::DATE
                THEN coalesce(val_potenciaefetiva, 0) ELSE 0 END),
            min(coalesce(
                nullif(trim(dat_entradaoperacao), ''),
                nullif(trim(dat_entradateste), '')
            )),
            max(nullif(trim(dat_desativacao), '')),
            count(*) FILTER (WHERE val_potenciaefetiva IS NULL)
        FROM source_rows
        WHERE nullif(trim(ceg), '') IS NOT NULL AND trim(ceg) <> '-'
        GROUP BY trim(ceg)
        ORDER BY trim(ceg)
        """,
        [as_of_date],
    ).fetchall()
    return [
        {
            "asset_id": f"ceg:{row[0]}",
            "period": "identity#capacity#snapshot",
            "fact_type": "generation_capacity_catalog",
            "dataset": context.spec.dataset_id,
            "ceg": row[0],
            "asset_name": row[1],
            "technology_name": row[2],
            "state": row[3],
            "unit_row_count": int(row[4]),
            "distinct_equipment_count": int(row[5]),
            "total_capacity_mw": _decimal(row[6]),
            "active_capacity_mw": _decimal(row[7]),
            "capacity_as_of": as_of_date.isoformat(),
            "valid_from": row[8],
            "latest_deactivation": row[9],
            "null_capacity_count": int(row[10]),
            "provenance_status": "ONS_PUBLICO",
            "source_bucket": context.source_bucket,
            "source_key": context.source_key,
            "source_sha256": context.source_sha256,
            "source_fingerprint": context.source_fingerprint,
        }
        for row in rows
    ]


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
    if context.spec.dataset_id == "usina_conjunto":
        items = _materialize_relationships(connection, context)
    elif context.spec.dataset_id == "capacidade-geracao":
        items = _materialize_capacity(connection, context)
    else:
        raise ValueError(f"Dataset de ativos não suportado: {context.spec.dataset_id}")
    counts = connection.execute("SELECT count(*) FROM source_rows").fetchone()
    return MaterializationOutput(
        dynamodb_items=items,
        row_count=int(counts[0]),
        fact_count=len(items),
        metrics={
            "catalog_item_count": len(items),
            "catalog_type": (
                "asset_group_relationship"
                if context.spec.dataset_id == "usina_conjunto"
                else "generation_capacity_catalog"
            ),
        },
    )
