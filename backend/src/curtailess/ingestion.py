import base64
import calendar
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Any

import boto3

from curtailess.datasets import DATASET_REGISTRY, DatasetPeriod, DatasetSpec, get_dataset_spec
from curtailess.ingestion_state import (
    IngestionLedger,
    SourceIdentity,
    source_fingerprint,
    source_identity_from_message,
)

_DEFAULT_DISCOVERY_CAP = 100
_MAX_DISCOVERY_CAP = 1_000
_DEFAULT_LEASE_SECONDS = 300
_CONTINUATION_VERSION = 1
_MAX_CONTINUATION_LENGTH = 4_096
_PERIOD_LABEL = re.compile(r"^(?P<year>\d{4})(?:-(?P<month>\d{2})(?:-(?P<day>\d{2}))?)?$")


def discover_latest_parquet(
    s3_client: Any,
    *,
    source_bucket: str,
    source_prefix: str,
) -> dict[str, object]:
    """Preserve the deployed empty-event discovery contract until its scheduler migrates."""
    latest: dict[str, Any] | None = None
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=source_bucket, Prefix=source_prefix):
        for item in page.get("Contents", []):
            if not item["Key"].lower().endswith(".parquet"):
                continue
            if latest is None or item["LastModified"] > latest["LastModified"]:
                latest = item

    if latest is None:
        raise RuntimeError(f"Nenhum Parquet encontrado em s3://{source_bucket}/{source_prefix}")

    return {
        "key": latest["Key"],
        "size": latest["Size"],
        "etag": latest["ETag"].strip('"'),
        "last_modified": latest["LastModified"].isoformat(),
    }


@dataclass(slots=True)
class _MalformedDiagnostics:
    limit: int | None
    count: int = 0
    keys: list[str] = field(default_factory=list)

    def record(self, source_key: str) -> None:
        self.count += 1
        if self.limit is None or len(self.keys) < self.limit:
            self.keys.append(source_key)


_StreamCandidate = tuple[dict[str, object], datetime, bool]


def _candidate_from_s3_item(
    spec: DatasetSpec, item: dict[str, Any], period: DatasetPeriod
) -> _StreamCandidate:
    last_modified = item["LastModified"]
    return (
        {
            "dataset": spec.dataset_id,
            "period": period.label,
            "parsed_period": period,
            "key": item["Key"],
            "size": item["Size"],
            "etag": item["ETag"].strip('"'),
            "last_modified": last_modified.isoformat(),
        },
        last_modified,
        False,
    )


def _merge_duplicate(existing: _StreamCandidate, candidate: _StreamCandidate) -> _StreamCandidate:
    existing_item, existing_last_modified, ambiguous = existing
    candidate_item, candidate_last_modified, _ = candidate
    if candidate_last_modified > existing_last_modified:
        return candidate
    if candidate_last_modified < existing_last_modified:
        return existing
    same_version = (
        candidate_item["size"] == existing_item["size"]
        and candidate_item["etag"] == existing_item["etag"]
    )
    return existing_item, existing_last_modified, ambiguous or not same_version


def _finalize_candidate(candidate: _StreamCandidate) -> dict[str, object]:
    item, _, ambiguous = candidate
    if ambiguous:
        raise ValueError(f"conflicting metadata for S3 source key {item['key']!r}")
    return item


def _stream_dataset_objects(
    s3_client: Any,
    spec: DatasetSpec,
    diagnostics: _MalformedDiagnostics,
    *,
    start_after: str | None = None,
    page_size: int | None = None,
) -> Iterator[dict[str, object]]:
    """Yield one lexicographically ordered object at a time using bounded duplicate state."""
    paginator = s3_client.get_paginator("list_objects_v2")
    request: dict[str, object] = {"Bucket": spec.source_bucket, "Prefix": spec.s3_prefix}
    if start_after is not None:
        request["StartAfter"] = start_after
    if page_size is not None:
        request["PaginationConfig"] = {"PageSize": page_size}

    pending: _StreamCandidate | None = None
    previous_source_key: str | None = start_after
    previous_period = spec.period_parser(start_after).label if start_after is not None else None
    for page in paginator.paginate(**request):
        contents = sorted(page.get("Contents", []), key=lambda item: item["Key"])
        for raw_item in contents:
            source_key = raw_item["Key"]
            if not isinstance(source_key, str) or (
                previous_source_key is not None and source_key < previous_source_key
            ):
                raise ValueError("S3 paginator returned nonmonotonic object keys")
            if start_after is not None and source_key <= start_after:
                raise ValueError("S3 paginator violated StartAfter ordering")

            if pending is not None and source_key != pending[0]["key"]:
                finalized = _finalize_candidate(pending)
                period_label = str(finalized["period"])
                if previous_period is not None and period_label < previous_period:
                    raise ValueError(
                        f"dataset {spec.dataset_id!r} filename order does not match period order"
                    )
                previous_period = period_label
                yield finalized
                pending = None

            previous_source_key = source_key
            try:
                period = spec.period_parser(source_key)
            except (TypeError, ValueError):
                diagnostics.record(source_key)
                continue

            candidate = _candidate_from_s3_item(spec, raw_item, period)
            pending = candidate if pending is None else _merge_duplicate(pending, candidate)

    if pending is not None:
        finalized = _finalize_candidate(pending)
        if previous_period is not None and str(finalized["period"]) < previous_period:
            raise ValueError(
                f"dataset {spec.dataset_id!r} filename order does not match period order"
            )
        yield finalized


def discover_dataset_objects(
    s3_client: Any, spec: DatasetSpec
) -> tuple[list[dict[str, object]], list[str]]:
    """Fully enumerate one dataset for callers that explicitly need a complete inventory."""
    diagnostics = _MalformedDiagnostics(limit=None)
    discovered = list(_stream_dataset_objects(s3_client, spec, diagnostics))
    return discovered, diagnostics.keys


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


def _canonical_continuation_payload(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def _encode_continuation(cursor: tuple[str, str, str], context: dict[str, object]) -> str:
    payload: dict[str, object] = {
        "context": context,
        "cursor": cursor,
        "version": _CONTINUATION_VERSION,
    }
    return base64.urlsafe_b64encode(_canonical_continuation_payload(payload)).decode()


def _decode_continuation(token: object, context: dict[str, object]) -> tuple[str, str, str] | None:
    if token is None:
        return None
    if not isinstance(token, str):
        raise ValueError("continuation must be a string")
    try:
        if not token or len(token) > _MAX_CONTINUATION_LENGTH:
            raise ValueError
        decoded = base64.b64decode(token.encode("ascii"), altchars=b"-_", validate=True)
        payload = json.loads(decoded.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"context", "cursor", "version"}:
            raise ValueError
        if type(payload["version"]) is not int or payload["version"] != _CONTINUATION_VERSION:
            raise ValueError
        cursor = payload["cursor"]
        if payload["context"] != context or not (
            isinstance(cursor, list)
            and len(cursor) == 3
            and all(isinstance(value, str) and value for value in cursor)
        ):
            raise ValueError
        if base64.urlsafe_b64encode(_canonical_continuation_payload(payload)).decode() != token:
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
        specs = sorted(
            (spec for spec in DATASET_REGISTRY.values() if mode in spec.enabled_modes),
            key=lambda spec: spec.dataset_id,
        )
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


def _within_period_bounds(item: dict[str, object], start: date | None, end: date | None) -> bool:
    if start is None or end is None:
        return True
    period = item["parsed_period"]
    return (
        isinstance(period, DatasetPeriod)
        and period.start is not None
        and period.end is not None
        and period.start >= start
        and period.end <= end
    )


def _validate_cursor(
    object_store: Any,
    specs: list[DatasetSpec],
    cursor: tuple[str, str, str],
    start: date | None,
    end: date | None,
) -> int:
    dataset_id, period_label, source_key = cursor
    try:
        dataset_index = next(
            index for index, spec in enumerate(specs) if spec.dataset_id == dataset_id
        )
    except StopIteration as exc:
        raise ValueError("invalid continuation for this discovery request") from exc

    spec = specs[dataset_index]
    try:
        period = spec.period_parser(source_key)
        boundary: dict[str, object] = {"parsed_period": period}
        if period.label != period_label or not _within_period_bounds(boundary, start, end):
            raise ValueError
        response = object_store.list_objects_v2(
            Bucket=spec.source_bucket,
            Prefix=source_key,
            MaxKeys=1,
        )
        if not any(item.get("Key") == source_key for item in response.get("Contents", [])):
            raise ValueError
    except Exception as exc:
        raise ValueError("invalid continuation for this discovery request") from exc
    return dataset_index


def _lease_seconds(environment: dict[str, str]) -> int:
    try:
        seconds = int(environment.get("INGESTION_LEASE_SECONDS", str(_DEFAULT_LEASE_SECONDS)))
    except ValueError as exc:
        raise ValueError("INGESTION_LEASE_SECONDS must be an integer") from exc
    if not 1 <= seconds <= 86_400:
        raise ValueError("INGESTION_LEASE_SECONDS must be between 1 and 86400")
    return seconds


def _request_owner(context: Any, stage: str) -> str:
    request_id = getattr(context, "aws_request_id", None)
    return f"{stage}:{request_id or 'local'}"


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


def _message_identity(message: dict[str, Any]) -> tuple[SourceIdentity, str]:
    identity = source_identity_from_message(message)
    fingerprint = source_fingerprint(identity)
    message["source_fingerprint"] = fingerprint
    return identity, fingerprint


def _send_discovery_message(
    queue: Any,
    queue_url: str,
    message: dict[str, Any],
    *,
    ledger: IngestionLedger | None,
    owner: str,
    now: datetime,
    lease_seconds: int,
) -> str | None:
    identity, fingerprint = _message_identity(message)
    if ledger is not None:
        item, _ = ledger.ensure_discovered(identity, now=now)
        if item["state"] == "MATERIALIZED":
            return None
        claim = ledger.claim_dispatch(
            fingerprint,
            owner=owner,
            now=now,
            lease_seconds=lease_seconds,
        )
        if not claim.claimed:
            return None
    try:
        response = queue.send_message(QueueUrl=queue_url, MessageBody=json.dumps(message))
    except Exception as exc:
        if ledger is not None:
            ledger.release_dispatch(
                fingerprint,
                owner=owner,
                now=now,
                error=f"{type(exc).__name__}: {exc}",
            )
        raise
    message_id = str(response["MessageId"])
    if ledger is not None:
        ledger.mark_dispatched(
            fingerprint,
            owner=owner,
            now=now,
            message_id=message_id,
        )
    return message_id


def discovery_handler(
    event: dict[str, Any],
    context: Any,
    *,
    s3_client: Any | None = None,
    sqs_client: Any | None = None,
    environment: dict[str, str] | None = None,
    ledger: IngestionLedger | None = None,
    now: Any | None = None,
) -> dict[str, object]:
    env = environment if environment is not None else dict(os.environ)
    object_store = s3_client or boto3.client("s3", region_name="us-west-2")
    queue = sqs_client or boto3.client("sqs", region_name="us-west-2")
    state = _ledger_from_environment(env, ledger)
    clock = now or (lambda: datetime.now(UTC))
    request_now = clock()
    lease_seconds = _lease_seconds(env)
    dispatch_owner = _request_owner(context, "dispatch")
    if not event:
        dataset = env["SOURCE_DATASET"]
        latest = discover_latest_parquet(
            object_store,
            source_bucket=env["SOURCE_BUCKET"],
            source_prefix=env["SOURCE_PREFIX"],
        )
        message = {
            "dataset": dataset,
            "source_bucket": env["SOURCE_BUCKET"],
            "source_key": latest["key"],
            "source_size": latest["size"],
            "source_etag": latest["etag"],
            "source_last_modified": latest["last_modified"],
        }
        message_id = _send_discovery_message(
            queue,
            env["INGESTION_QUEUE_URL"],
            message,
            ledger=state,
            owner=dispatch_owner,
            now=request_now,
            lease_seconds=lease_seconds,
        )
        return {
            "mode": "incremental",
            "dataset": dataset if message_id is not None else None,
            "source_key": str(latest["key"]) if message_id is not None else None,
            "message_id": message_id,
            "enqueued": int(message_id is not None),
            "message_ids": [message_id] if message_id is not None else [],
            "has_more": False,
            "continuation": None,
            "malformed_count": 0,
            "malformed_keys": [],
            "malformed_keys_truncated": False,
        }

    mode, specs, start, end = _validate_request(event)
    cap = _discovery_cap(env)
    continuation_context = _continuation_context(event, mode)
    cursor = _decode_continuation(event.get("continuation"), continuation_context)

    resume_index = _validate_cursor(object_store, specs, cursor, start, end) if cursor else 0
    selected: list[dict[str, object]] = []
    diagnostics = _MalformedDiagnostics(limit=cap)
    has_more = False
    for dataset_index in range(resume_index, len(specs)):
        spec = specs[dataset_index]
        start_after = cursor[2] if cursor is not None and dataset_index == resume_index else None
        remaining = cap - len(selected)
        for item in _stream_dataset_objects(
            object_store,
            spec,
            diagnostics,
            start_after=start_after,
            # One extra item proves that another result exists; a second one lets
            # the streaming deduplicator finalize its pending key in the same S3 page.
            page_size=min(1_000, remaining + 2),
        ):
            if not _within_period_bounds(item, start, end):
                continue
            if len(selected) == cap:
                has_more = True
                break
            selected.append(item)
        if has_more:
            break
    message_ids: list[str] = []
    enqueued_items: list[dict[str, object]] = []
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
        message_id = _send_discovery_message(
            queue,
            env["INGESTION_QUEUE_URL"],
            message,
            ledger=state,
            owner=dispatch_owner,
            now=request_now,
            lease_seconds=lease_seconds,
        )
        if message_id is not None:
            message_ids.append(message_id)
            enqueued_items.append(item)

    next_continuation = (
        _encode_continuation(_discovery_sort_key(selected[-1]), continuation_context)
        if has_more
        else None
    )
    result: dict[str, object] = {
        "mode": mode,
        # Legacy scalar fields are meaningful only for exactly one discovery.
        # Keep the keys stable and use null for zero or multiple discoveries.
        "dataset": None,
        "source_key": None,
        "message_id": None,
        "enqueued": len(enqueued_items),
        "message_ids": message_ids,
        "has_more": has_more,
        "continuation": next_continuation,
        "malformed_count": diagnostics.count,
        "malformed_keys": diagnostics.keys,
        "malformed_keys_truncated": diagnostics.count > len(diagnostics.keys),
    }
    # Keep the original single-message response fields for existing callers.
    if len(enqueued_items) == 1:
        result.update(
            {
                "dataset": enqueued_items[0]["dataset"],
                "source_key": enqueued_items[0]["key"],
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
    ledger: IngestionLedger | None = None,
) -> dict[str, list[dict[str, str]]]:
    env = environment if environment is not None else dict(os.environ)
    client = s3_client or boto3.client("s3", region_name="us-west-2")
    state = _ledger_from_environment(env, ledger)
    copy_owner = _request_owner(context, "copy")
    lease_seconds = _lease_seconds(env)
    function_client = lambda_client
    if function_client is None and env.get("MATERIALIZATION_FUNCTION"):
        function_client = boto3.client("lambda", region_name="us-west-2")
    clock = now or (lambda: datetime.now(UTC))
    failures = []

    for record in event.get("Records", []):
        claimed_fingerprint: str | None = None
        try:
            message = json.loads(record["body"])
            source_key = message["source_key"]
            spec = get_dataset_spec(message["dataset"])
            if message["source_bucket"] != spec.source_bucket:
                raise ValueError("source_bucket does not match registered dataset")
            period = spec.period_parser(source_key)
            if message.get("source_period", period.label) != period.label:
                raise ValueError("source_period does not match source key")
            identity = source_identity_from_message(message)
            fingerprint = source_fingerprint(identity)
            supplied_fingerprint = message.get("source_fingerprint")
            if supplied_fingerprint is not None and supplied_fingerprint != fingerprint:
                raise ValueError("source_fingerprint does not match source identity")
            message["source_fingerprint"] = fingerprint
            if state is not None:
                claim_now = clock()
                state.ensure_discovered(identity, now=claim_now)
                claim = state.claim_copy(
                    fingerprint,
                    owner=copy_owner,
                    now=claim_now,
                    lease_seconds=lease_seconds,
                )
                if not claim.claimed:
                    continue
                claimed_fingerprint = fingerprint
            filename = PurePosixPath(source_key).name
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
                "source_fingerprint": fingerprint,
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
                            "source_fingerprint": fingerprint,
                        }
                    ).encode(),
                )
            if state is not None and claimed_fingerprint is not None:
                state.mark_copied(
                    claimed_fingerprint,
                    owner=copy_owner,
                    now=clock(),
                    raw_key=raw_key,
                    raw_sha256=sha256.hexdigest(),
                    manifest_key=manifest_key,
                )
        except Exception as exc:
            if state is not None and claimed_fingerprint is not None:
                with suppress(Exception):
                    state.mark_failed(
                        claimed_fingerprint,
                        owner=copy_owner,
                        now=clock(),
                        stage="COPYING",
                        error=f"{type(exc).__name__}: {exc}",
                    )
            failures.append({"itemIdentifier": record["messageId"]})

    return {"batchItemFailures": failures}
