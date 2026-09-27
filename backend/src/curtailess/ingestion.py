import base64
import calendar
import hashlib
import json
import os
import re
import tempfile
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Any

import boto3

from curtailess.datasets import DATASET_REGISTRY, DatasetPeriod, DatasetSpec, get_dataset_spec

_DEFAULT_DISCOVERY_CAP = 100
_MAX_DISCOVERY_CAP = 1_000
_PERIOD_LABEL = re.compile(r"^(?P<year>\d{4})(?:-(?P<month>\d{2})(?:-(?P<day>\d{2}))?)?$")


def discover_dataset_objects(
    s3_client: Any, spec: DatasetSpec
) -> tuple[list[dict[str, object]], list[str]]:
    """Enumerate and deduplicate a dataset; newest metadata wins, ambiguous ties fail."""
    latest_by_key: dict[str, tuple[dict[str, object], datetime, bool]] = {}
    malformed_keys: list[str] = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=spec.source_bucket, Prefix=spec.s3_prefix):
        for item in page.get("Contents", []):
            source_key = item["Key"]
            try:
                period = spec.period_parser(source_key)
            except (TypeError, ValueError):
                malformed_keys.append(source_key)
                continue
            last_modified = item["LastModified"]
            candidate = {
                "dataset": spec.dataset_id,
                "period": period.label,
                "parsed_period": period,
                "key": source_key,
                "size": item["Size"],
                "etag": item["ETag"].strip('"'),
                "last_modified": last_modified.isoformat(),
            }
            existing = latest_by_key.get(source_key)
            if existing is None:
                latest_by_key[source_key] = candidate, last_modified, False
                continue

            existing_item, existing_last_modified, ambiguous = existing
            if last_modified > existing_last_modified:
                latest_by_key[source_key] = candidate, last_modified, False
            elif last_modified == existing_last_modified:
                same_version = (
                    candidate["size"] == existing_item["size"]
                    and candidate["etag"] == existing_item["etag"]
                )
                latest_by_key[source_key] = (
                    existing_item,
                    existing_last_modified,
                    ambiguous or not same_version,
                )

    discovered: list[dict[str, object]] = []
    for source_key, (item, _, ambiguous) in latest_by_key.items():
        if ambiguous:
            raise ValueError(f"conflicting metadata for S3 source key {source_key!r}")
        discovered.append(item)
    discovered.sort(key=_discovery_sort_key)
    malformed_keys.sort()
    return discovered, malformed_keys


def _discovery_sort_key(item: dict[str, object]) -> tuple[str, str, str]:
    return str(item["dataset"]), str(item["period"]), str(item["key"])


def _parse_period_bound(label: object, *, end: bool) -> date:
    if not isinstance(label, str):
        raise ValueError("period bounds must be strings")
    match = _PERIOD_LABEL.fullmatch(label)
    if match is None:
        raise ValueError(f"invalid period bound: {label!r}")
    year = int(match.group("year"))
    month_text = match.group("month")
    day_text = match.group("day")
    try:
        if month_text is None:
            return date(year, 12 if end else 1, 31 if end else 1)
        month = int(month_text)
        if day_text is not None:
            return date(year, month, int(day_text))
        day = calendar.monthrange(year, month)[1] if end else 1
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"invalid period bound: {label!r}") from exc


def _continuation_context(event: dict[str, Any], mode: str) -> dict[str, object]:
    if mode == "incremental":
        return {"mode": mode}
    return {
        "mode": mode,
        "dataset": event["dataset"],
        "start_period": event["start_period"],
        "end_period": event["end_period"],
    }


def _encode_continuation(cursor: tuple[str, str, str], context: dict[str, object]) -> str:
    payload = json.dumps(
        {"context": context, "cursor": cursor}, separators=(",", ":"), sort_keys=True
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_continuation(token: object, context: dict[str, object]) -> tuple[str, str, str] | None:
    if token is None:
        return None
    if not isinstance(token, str):
        raise ValueError("continuation must be a string")
    try:
        payload = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        cursor = payload["cursor"]
        if payload["context"] != context or not (
            isinstance(cursor, list)
            and len(cursor) == 3
            and all(isinstance(value, str) for value in cursor)
        ):
            raise ValueError
    except Exception as exc:
        raise ValueError("invalid continuation for this discovery request") from exc
    return cursor[0], cursor[1], cursor[2]


def _validate_request(
    event: dict[str, Any],
) -> tuple[str, list[DatasetSpec], date | None, date | None]:
    mode = event.get("mode", "incremental")
    if mode not in {"backfill", "incremental"}:
        raise ValueError("mode must be 'backfill' or 'incremental'")
    if mode == "incremental":
        unexpected = {"dataset", "start_period", "end_period"}.intersection(event)
        if unexpected:
            raise ValueError("incremental mode enumerates enabled datasets and accepts no bounds")
        specs = [spec for spec in DATASET_REGISTRY.values() if mode in spec.enabled_modes]
        return mode, specs, None, None

    dataset = event.get("dataset")
    if not isinstance(dataset, str) or not dataset:
        raise ValueError("backfill mode requires one dataset")
    spec = get_dataset_spec(dataset)
    if mode not in spec.enabled_modes:
        raise ValueError(f"dataset {dataset!r} does not enable backfill mode")
    if "start_period" not in event:
        raise ValueError("backfill mode requires start_period")
    if "end_period" not in event:
        raise ValueError("backfill mode requires end_period")
    start = _parse_period_bound(event["start_period"], end=False)
    end = _parse_period_bound(event["end_period"], end=True)
    if end < start:
        raise ValueError("backfill bounds require start_period <= end_period")
    return mode, [spec], start, end


def _discovery_cap(environment: dict[str, str]) -> int:
    try:
        cap = int(environment.get("DISCOVERY_MAX_MESSAGES", str(_DEFAULT_DISCOVERY_CAP)))
    except ValueError as exc:
        raise ValueError("DISCOVERY_MAX_MESSAGES must be an integer") from exc
    if not 1 <= cap <= _MAX_DISCOVERY_CAP:
        raise ValueError(f"DISCOVERY_MAX_MESSAGES must be between 1 and {_MAX_DISCOVERY_CAP}")
    return cap


def discovery_handler(
    event: dict[str, Any],
    context: Any,
    *,
    s3_client: Any | None = None,
    sqs_client: Any | None = None,
    environment: dict[str, str] | None = None,
) -> dict[str, object]:
    del context
    env = environment if environment is not None else dict(os.environ)
    object_store = s3_client or boto3.client("s3", region_name="us-west-2")
    queue = sqs_client or boto3.client("sqs", region_name="us-west-2")
    mode, specs, start, end = _validate_request(event)
    cap = _discovery_cap(env)
    continuation_context = _continuation_context(event, mode)
    cursor = _decode_continuation(event.get("continuation"), continuation_context)

    discovered: list[dict[str, object]] = []
    malformed_keys: list[str] = []
    for spec in specs:
        dataset_objects, dataset_malformed = discover_dataset_objects(object_store, spec)
        discovered.extend(dataset_objects)
        malformed_keys.extend(dataset_malformed)
    discovered.sort(key=_discovery_sort_key)
    malformed_keys.sort()

    if start is not None and end is not None:
        discovered = [
            item
            for item in discovered
            if isinstance(item["parsed_period"], DatasetPeriod)
            and item["parsed_period"].start is not None
            and item["parsed_period"].end is not None
            and item["parsed_period"].start >= start
            and item["parsed_period"].end <= end
        ]
    if cursor is not None:
        discovered = [item for item in discovered if _discovery_sort_key(item) > cursor]

    selected = discovered[:cap]
    has_more = len(discovered) > cap
    message_ids: list[str] = []
    for item in selected:
        message = {
            "dataset": item["dataset"],
            "source_bucket": DATASET_REGISTRY[str(item["dataset"])].source_bucket,
            "source_key": item["key"],
            "source_period": item["period"],
            "source_size": item["size"],
            "source_etag": item["etag"],
            "source_last_modified": item["last_modified"],
        }
        response = queue.send_message(
            QueueUrl=env["INGESTION_QUEUE_URL"],
            MessageBody=json.dumps(message),
        )
        message_ids.append(response["MessageId"])

    next_continuation = (
        _encode_continuation(_discovery_sort_key(selected[-1]), continuation_context)
        if has_more
        else None
    )
    result: dict[str, object] = {
        "mode": mode,
        "enqueued": len(selected),
        "message_ids": message_ids,
        "has_more": has_more,
        "continuation": next_continuation,
        "malformed_count": len(malformed_keys),
        "malformed_keys": malformed_keys[:cap],
        "malformed_keys_truncated": len(malformed_keys) > cap,
    }
    # Keep the original single-message response fields for existing callers.
    if len(selected) == 1:
        result.update(
            {
                "dataset": selected[0]["dataset"],
                "source_key": selected[0]["key"],
                "message_id": message_ids[0],
            }
        )
    return result


def copy_handler(
    event: dict[str, Any],
    context: Any,
    *,
    s3_client: Any | None = None,
    lambda_client: Any | None = None,
    environment: dict[str, str] | None = None,
    now: Any | None = None,
) -> dict[str, list[dict[str, str]]]:
    del context
    env = environment if environment is not None else dict(os.environ)
    client = s3_client or boto3.client("s3", region_name="us-west-2")
    function_client = lambda_client
    if function_client is None and env.get("MATERIALIZATION_FUNCTION"):
        function_client = boto3.client("lambda", region_name="us-west-2")
    clock = now or (lambda: datetime.now(UTC))
    failures = []

    for record in event.get("Records", []):
        try:
            message = json.loads(record["body"])
            source_key = message["source_key"]
            filename = PurePosixPath(source_key).name
            spec = get_dataset_spec(message["dataset"])
            period = spec.period_parser(source_key)
            if period.start is None:
                raw_key = f"raw/ons/{message['dataset']}/source_period=snapshot/{filename}"
            else:
                raw_key = (
                    f"raw/ons/{message['dataset']}/source_year={period.start.year:04d}/"
                    f"source_month={period.start.month:02d}/{filename}"
                )

            response = client.get_object(
                Bucket=message["source_bucket"],
                Key=source_key,
            )
            sha256 = hashlib.sha256()
            with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as body:
                for chunk in response["Body"].iter_chunks(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    sha256.update(chunk)
                    body.write(chunk)
                body.seek(0)
                client.upload_fileobj(
                    body,
                    env["DATA_BUCKET"],
                    raw_key,
                    ExtraArgs={
                        "ContentType": "application/vnd.apache.parquet",
                        "Metadata": {
                            "source-bucket": message["source_bucket"],
                            "source-key": source_key,
                            "source-etag": message["source_etag"],
                            "sha256": sha256.hexdigest(),
                        },
                    },
                )

            collected_at = clock()
            manifest_key = (
                f"manifests/{message['dataset']}/"
                f"ingestion_date={collected_at.date().isoformat()}/"
                f"{filename.removesuffix('.parquet')}.json"
            )
            manifest = {
                "dataset": message["dataset"],
                "source_url": f"s3://{message['source_bucket']}/{source_key}",
                "source_key": source_key,
                "source_size": message["source_size"],
                "source_etag": message["source_etag"],
                "source_last_modified": message["source_last_modified"],
                "destination_key": raw_key,
                "sha256": sha256.hexdigest(),
                "collected_at": collected_at.isoformat(),
                "validation_status": "pending",
            }
            client.put_object(
                Bucket=env["DATA_BUCKET"],
                Key=manifest_key,
                Body=json.dumps(manifest, ensure_ascii=False).encode(),
                ContentType="application/json",
            )
            if function_client is not None and env.get("MATERIALIZATION_FUNCTION"):
                function_client.invoke(
                    FunctionName=env["MATERIALIZATION_FUNCTION"],
                    InvocationType="Event",
                    Payload=json.dumps(
                        {
                            "bucket": env["DATA_BUCKET"],
                            "key": raw_key,
                            "sha256": sha256.hexdigest(),
                            "manifest_key": manifest_key,
                        }
                    ).encode(),
                )
        except Exception:
            failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": failures}
