import json
import os
import tempfile
from collections import defaultdict
from decimal import Decimal
from typing import Any

import boto3
import duckdb

REASONS = ("CNF", "REL", "ENE", "NC")


def aggregate_exposure_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        asset_id = row["id_ons"]
        if asset_id not in grouped:
            grouped[asset_id] = {
                "asset_id": asset_id,
                "asset_name": row["nom_usina"],
                "point_id": row["id_pontoconexao"],
                "point_name": row["nom_pontoconexao"],
                "state": row["id_estado"],
                "instants": [],
                "interval_count": 0,
                "limited_interval_count": 0,
                "by_reason": defaultdict(float),
            }
        item = grouped[asset_id]
        item["instants"].append(row["din_instante"])
        item["interval_count"] += 1
        if row["val_geracaolimitada"] is not None:
            item["limited_interval_count"] += 1
            reason = row["cod_razaorestricao"] or "NC"
            item["by_reason"][reason] += (row["val_geracaonaorealizadaapurada"] or 0.0) * 0.5

    aggregates = []
    for item in grouped.values():
        by_reason = {reason: round(item["by_reason"][reason], 6) for reason in REASONS}
        aggregates.append(
            {
                "asset_id": item["asset_id"],
                "asset_name": item["asset_name"],
                "point_id": item["point_id"],
                "point_name": item["point_name"],
                "state": item["state"],
                "period_start": min(item["instants"]),
                "period_end": max(item["instants"]),
                "interval_count": item["interval_count"],
                "limited_interval_count": item["limited_interval_count"],
                "curtailed_mwh": round(sum(by_reason.values()), 6),
                "curtailed_mwh_by_reason": by_reason,
                "value_status": "measured_ons",
                "method": ("sum(apurada * 0.5) when val_geracaolimitada is not null"),
            }
        )
    return sorted(aggregates, key=lambda item: item["asset_id"])


REQUIRED_COLUMNS = {
    "id_ons",
    "nom_usina",
    "id_estado",
    "din_instante",
    "val_geracaolimitada",
    "val_geracaonaorealizadaapurada",
    "cod_razaorestricao",
    "id_pontoconexao",
    "nom_pontoconexao",
}


def materialization_handler(
    event: dict[str, Any],
    context: Any,
    *,
    s3_client: Any | None = None,
    table: Any | None = None,
) -> dict[str, Any]:
    del context
    client = s3_client or boto3.client("s3", region_name="us-west-2")
    destination_table = table or boto3.resource("dynamodb", region_name="us-west-2").Table(
        os.environ["EXPOSURE_TABLE"]
    )
    bucket = event["bucket"]
    key = event["key"]

    with tempfile.NamedTemporaryFile(suffix=".parquet") as source:
        client.download_file(bucket, key, source.name)
        connection = duckdb.connect()
        columns = {
            row[0]
            for row in connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [source.name]
            ).fetchall()
        }
        missing = REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"Colunas obrigatórias ausentes: {sorted(missing)}")

        row_count = connection.execute(
            "SELECT count(*) FROM read_parquet(?)", [source.name]
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT
                id_ons AS asset_id,
                any_value(nom_usina) AS asset_name,
                any_value(id_pontoconexao) AS point_id,
                any_value(nom_pontoconexao) AS point_name,
                any_value(id_estado) AS state,
                min(din_instante) AS period_start,
                max(din_instante) AS period_end,
                count(*) AS interval_count,
                count(*) FILTER (WHERE val_geracaolimitada IS NOT NULL)
                    AS limited_interval_count,
                sum(CASE WHEN val_geracaolimitada IS NOT NULL
                    THEN coalesce(val_geracaonaorealizadaapurada, 0) * 0.5
                    ELSE 0 END) AS curtailed_mwh,
                sum(CASE WHEN val_geracaolimitada IS NOT NULL
                              AND cod_razaorestricao = 'CNF'
                    THEN coalesce(val_geracaonaorealizadaapurada, 0) * 0.5
                    ELSE 0 END) AS cnf_mwh,
                sum(CASE WHEN val_geracaolimitada IS NOT NULL
                              AND cod_razaorestricao = 'REL'
                    THEN coalesce(val_geracaonaorealizadaapurada, 0) * 0.5
                    ELSE 0 END) AS rel_mwh,
                sum(CASE WHEN val_geracaolimitada IS NOT NULL
                              AND cod_razaorestricao = 'ENE'
                    THEN coalesce(val_geracaonaorealizadaapurada, 0) * 0.5
                    ELSE 0 END) AS ene_mwh,
                sum(CASE WHEN val_geracaolimitada IS NOT NULL
                              AND cod_razaorestricao IS NULL
                    THEN coalesce(val_geracaonaorealizadaapurada, 0) * 0.5
                    ELSE 0 END) AS nc_mwh
            FROM read_parquet(?)
            WHERE id_ons IS NOT NULL
            GROUP BY id_ons
            ORDER BY id_ons
            """,
            [source.name],
        ).fetchall()

    period = key.split("source_year=")[1][:4] + "-" + key.split("source_month=")[1][:2]
    items = []
    for row in rows:
        item = {
            "asset_id": row[0],
            "period": period,
            "asset_name": row[1],
            "point_id": row[2] or "unknown",
            "point_name": row[3] or "unknown",
            "state": row[4] or "unknown",
            "period_start": row[5].isoformat(),
            "period_end": row[6].isoformat(),
            "interval_count": row[7],
            "limited_interval_count": row[8],
            "curtailed_mwh": Decimal(str(round(row[9] or 0.0, 6))),
            "curtailed_mwh_by_reason": {
                "CNF": Decimal(str(round(row[10] or 0.0, 6))),
                "REL": Decimal(str(round(row[11] or 0.0, 6))),
                "ENE": Decimal(str(round(row[12] or 0.0, 6))),
                "NC": Decimal(str(round(row[13] or 0.0, 6))),
            },
            "data_mode": "ons_materialized",
            "value_status": "measured_ons",
            "method": "sum(apurada * 0.5) when val_geracaolimitada is not null",
            "source_bucket": bucket,
            "source_key": key,
            "source_sha256": event["sha256"],
        }
        items.append(item)

    with destination_table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)

    summary = {
        "validation_status": "valid",
        "dataset": "restricao_coff_eolica_tm",
        "period": period,
        "row_count": row_count,
        "asset_count": len(items),
        "source_key": key,
        "source_sha256": event["sha256"],
    }
    client.put_object(
        Bucket=bucket,
        Key=f"curated/settlement_energy/period={period}/summary.json",
        Body=json.dumps(summary, ensure_ascii=False).encode(),
        ContentType="application/json",
    )
    return summary
