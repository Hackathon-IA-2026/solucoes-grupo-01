import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import duckdb
from botocore.exceptions import ClientError

from curtailess.datasets import get_dataset_spec
from curtailess.ingestion_state import IngestionLedger
from curtailess.materializers import MaterializationContext, resolve_materializer

REASONS = ("CNF", "REL", "ENE", "NC")


class RetryableMaterializationError(RuntimeError):
    pass


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
                "method": "sum(apurada * 0.5) when val_geracaolimitada is not null",
            }
        )
    return sorted(aggregates, key=lambda item: item["asset_id"])


def _request_owner(context: Any, message_id: str) -> str:
    request_id = getattr(context, "aws_request_id", "local")
    return f"materialization:{request_id}:{message_id}"[:256]


def _lease_seconds(environment: dict[str, str]) -> int:
    try:
        value = int(environment.get("INGESTION_LEASE_SECONDS", "300"))
    except ValueError as exc:
        raise ValueError("INGESTION_LEASE_SECONDS must be an integer") from exc
    if value < 30 or value > 3_600:
        raise ValueError("INGESTION_LEASE_SECONDS must be between 30 and 3600")
    return value


def _ledger_from_environment(
    environment: dict[str, str], ledger: IngestionLedger | None
) -> IngestionLedger | None:
    if ledger is not None:
        return ledger
    table_name = environment.get("INGESTION_LEDGER_TABLE")
    if not table_name:
        return None
    table = boto3.resource("dynamodb", region_name="us-west-2").Table(table_name)
    return IngestionLedger(table)


def _expected_manifest_key(dataset: str, fingerprint: str) -> str:
    return f"manifests/{dataset}/source_fingerprint={fingerprint}.json"


def _validate_message(message: dict[str, Any], environment: dict[str, str]) -> None:
    required = {
        "bucket",
        "dataset",
        "source_period",
        "source_fingerprint",
        "raw_key",
        "raw_sha256",
        "manifest_key",
    }
    missing = required - message.keys()
    if missing:
        raise ValueError(f"materialization message missing fields: {sorted(missing)}")
    if environment.get("DATA_BUCKET") and message["bucket"] != environment["DATA_BUCKET"]:
        raise ValueError("materialization bucket does not match DATA_BUCKET")
    spec = get_dataset_spec(str(message["dataset"]))
    resolve_materializer(spec.materializer)
    period = str(message["source_period"])
    if period != "snapshot" and re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", period) is None:
        raise ValueError("source_period has an invalid format")
    digest = str(message["raw_sha256"])
    fingerprint = str(message["source_fingerprint"])
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("raw_sha256 must be a lowercase SHA-256 digest")
    if len(fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in fingerprint
    ):
        raise ValueError("source_fingerprint must be a lowercase SHA-256 digest")
    raw_key = str(message["raw_key"])
    if not raw_key.startswith(f"raw/ons/{spec.dataset_id}/") or not raw_key.endswith(
        f"sha256={digest[:2]}/{digest}.parquet"
    ):
        raise ValueError("raw_key does not match dataset and raw_sha256")
    if period == "snapshot":
        expected_partition = "source_period=snapshot/"
    else:
        month = period[5:7] if len(period) >= 7 else "01"
        expected_partition = f"source_year={period[:4]}/source_month={month}/"
    if expected_partition not in raw_key:
        raise ValueError("raw_key does not match source_period")
    if message["manifest_key"] != _expected_manifest_key(spec.dataset_id, fingerprint):
        raise ValueError("manifest_key does not match source identity")


def _verify_ledger_identity(item: dict[str, Any], message: dict[str, Any]) -> None:
    expected = {
        "dataset": message["dataset"],
        "source_fingerprint": message["source_fingerprint"],
        "source_period": message["source_period"],
        "raw_key": message["raw_key"],
        "raw_sha256": message["raw_sha256"],
        "manifest_key": message["manifest_key"],
    }
    for field, value in expected.items():
        if item.get(field) != value:
            raise ValueError(f"ledger {field} does not match materialization message")


def _write_immutable_manifest(client: Any, *, bucket: str, key: str, body: bytes) -> None:
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", ""))
        if code not in {"PreconditionFailed", "412"}:
            raise
        existing = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        if existing != body:
            raise RuntimeError("immutable manifest already exists with different content") from exc


def _read_previous_keys(client: Any, bucket: str, summary_key: str) -> set[tuple[str, str]]:
    try:
        body = client.get_object(Bucket=bucket, Key=summary_key)["Body"].read()
    except ClientError as exc:
        if str(exc.response.get("Error", {}).get("Code", "")) in {
            "404",
            "NoSuchKey",
            "NotFound",
        }:
            return set()
        raise
    summary = json.loads(body)
    entries = list(summary.get("dynamodb_keys", [])) + list(
        summary.get("superseded_dynamodb_keys", [])
    )
    keys = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"asset_id", "period"}:
            raise ValueError("existing materialization summary contains invalid DynamoDB keys")
        keys.add((str(entry["asset_id"]), str(entry["period"])))
    return keys


def _write_compact_facts(
    table: Any,
    items: list[dict[str, Any]],
    previous_keys: set[tuple[str, str]],
) -> list[dict[str, str]]:
    new_keys = {(str(item["asset_id"]), str(item["period"])) for item in items}
    obsolete = previous_keys - new_keys
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item=item)
        for asset_id, period in sorted(obsolete):
            batch.delete_item(Key={"asset_id": asset_id, "period": period})
    return [{"asset_id": asset_id, "period": period} for asset_id, period in sorted(obsolete)]


def _materialize_message(
    message: dict[str, Any],
    *,
    context: Any,
    message_id: str,
    client: Any,
    destination_table: Any,
    ledger: IngestionLedger | None,
    environment: dict[str, str],
    now: Any,
) -> dict[str, Any]:
    _validate_message(message, environment)
    fingerprint = str(message["source_fingerprint"])
    owner = _request_owner(context, message_id)
    claimed = False
    claimed_item: dict[str, Any] = {}
    if ledger is not None:
        claim = ledger.claim_materialization(
            fingerprint,
            owner=owner,
            now=now(),
            lease_seconds=_lease_seconds(environment),
        )
        if claim.outcome == "COMPLETE":
            return {"status": "already_materialized", "source_fingerprint": fingerprint}
        if claim.outcome == "BUSY":
            raise RetryableMaterializationError("materialization is not ready or is already leased")
        claimed_item = claim.item
        claimed = True

    bucket = str(message["bucket"])
    raw_key = str(message["raw_key"])
    digest = str(message["raw_sha256"])
    period = str(message["source_period"])
    dataset = str(message["dataset"])
    try:
        if ledger is not None:
            _verify_ledger_identity(claimed_item, message)
        spec = get_dataset_spec(dataset)
        summary_key = f"curated/ons/{dataset}/period={period}/summary.json"
        previous_keys = _read_previous_keys(client, bucket, summary_key)
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.parquet"
            curated_path = Path(directory) / "curated.parquet"
            client.download_file(bucket, raw_key, str(source_path))
            with source_path.open("rb") as source_file:
                actual_digest = hashlib.file_digest(source_file, "sha256").hexdigest()
            if actual_digest != digest:
                raise ValueError(
                    "downloaded raw object SHA-256 does not match materialization message"
                )
            with duckdb.connect() as connection:
                connection.read_parquet(str(source_path)).create_view("source_rows")
                materializer = resolve_materializer(spec.materializer)
                output = materializer(
                    connection,
                    MaterializationContext(
                        spec=spec,
                        period=period,
                        source_path=source_path,
                        curated_path=curated_path,
                        source_fingerprint=fingerprint,
                        source_sha256=digest,
                        source_bucket=str(claimed_item.get("source_bucket") or bucket),
                        source_key=str(claimed_item.get("source_key") or raw_key),
                        source_last_modified=claimed_item.get("source_last_modified"),
                    ),
                )
            with curated_path.open("rb") as curated_file:
                curated_sha256 = hashlib.file_digest(curated_file, "sha256").hexdigest()
            curated_key = (
                f"curated/ons/{spec.materializer}/dataset={dataset}/period={period}/"
                f"sha256={curated_sha256[:2]}/{curated_sha256}.parquet"
            )
            client.upload_file(
                str(curated_path),
                bucket,
                curated_key,
                ExtraArgs={
                    "ContentType": "application/vnd.apache.parquet",
                    "Metadata": {
                        "raw-sha256": digest,
                        "curated-sha256": curated_sha256,
                        "source-fingerprint": fingerprint,
                    },
                },
            )

        superseded = _write_compact_facts(destination_table, output.dynamodb_items, previous_keys)
        summary = {
            "schema_version": 2,
            "validation_status": "valid",
            "dataset": dataset,
            "materializer": spec.materializer,
            "period": period,
            "row_count": output.row_count,
            "fact_count": output.fact_count,
            "metrics": output.metrics,
            "source_key": raw_key,
            "source_sha256": digest,
            "source_fingerprint": fingerprint,
            "curated_key": curated_key,
            "curated_sha256": curated_sha256,
            "dynamodb_keys": output.dynamodb_keys,
            "superseded_dynamodb_keys": superseded,
        }
        summary_body = json.dumps(summary, ensure_ascii=False, sort_keys=True).encode()
        client.put_object(
            Bucket=bucket,
            Key=summary_key,
            Body=summary_body,
            ContentType="application/json",
        )
        manifest = {
            "schema_version": 2,
            "validation_status": "valid",
            "dataset": dataset,
            "materializer": spec.materializer,
            "source_period": period,
            "source_fingerprint": fingerprint,
            "source": {
                "bucket": claimed_item.get("source_bucket"),
                "key": claimed_item.get("source_key"),
                "etag": claimed_item.get("source_etag"),
                "size": claimed_item.get("source_size"),
                "last_modified": claimed_item.get("source_last_modified"),
            },
            "raw": {"bucket": bucket, "key": raw_key, "sha256": digest},
            "curated": {
                "parquet_key": curated_key,
                "parquet_sha256": curated_sha256,
                "summary_key": summary_key,
                "summary_sha256": hashlib.sha256(summary_body).hexdigest(),
                "row_count": output.row_count,
                "fact_count": output.fact_count,
            },
        }
        manifest_body = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        _write_immutable_manifest(
            client,
            bucket=bucket,
            key=str(message["manifest_key"]),
            body=manifest_body,
        )
        if ledger is not None:
            ledger.mark_materialized(
                fingerprint,
                owner=owner,
                now=now(),
                manifest_key=str(message["manifest_key"]),
                summary_key=summary_key,
            )
        return summary
    except Exception as exc:
        if ledger is not None and claimed:
            with suppress(Exception):
                ledger.mark_materialization_failed(
                    fingerprint,
                    owner=owner,
                    now=now(),
                    error=str(exc),
                )
        raise


def materialization_handler(
    event: dict[str, Any],
    context: Any,
    *,
    s3_client: Any | None = None,
    table: Any | None = None,
    ledger: IngestionLedger | None = None,
    environment: dict[str, str] | None = None,
    now: Any | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environment is None else environment)
    client = s3_client or boto3.client("s3", region_name="us-west-2")
    destination_table = table or boto3.resource("dynamodb", region_name="us-west-2").Table(
        env["EXPOSURE_TABLE"]
    )
    state = _ledger_from_environment(env, ledger)
    clock = now or (lambda: datetime.now(UTC))

    records = event.get("Records")
    if records is None:
        return _materialize_message(
            event,
            context=context,
            message_id="direct",
            client=client,
            destination_table=destination_table,
            ledger=state,
            environment=env,
            now=clock,
        )

    failures = []
    for record in records:
        message_id = str(record.get("messageId", "unknown"))
        try:
            message = json.loads(record["body"])
            _materialize_message(
                message,
                context=context,
                message_id=message_id,
                client=client,
                destination_table=destination_table,
                ledger=state,
                environment=env,
                now=clock,
            )
        except Exception:
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
