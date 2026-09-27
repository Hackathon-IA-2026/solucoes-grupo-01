import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from botocore.exceptions import ClientError

LEDGER_STATES = frozenset(
    {"DISCOVERED", "COPYING", "COPIED", "MATERIALIZING", "MATERIALIZED", "FAILED"}
)
_MAX_CLAIM_ATTEMPTS = 4
_MAX_ERROR_LENGTH = 1_000
_ALLOWED_TRANSITIONS = frozenset(
    {
        ("COPIED", "MATERIALIZING"),
        ("MATERIALIZING", "MATERIALIZED"),
        ("MATERIALIZING", "FAILED"),
    }
)


class LedgerConflict(RuntimeError):
    """The ledger changed while a conditional transition was being written."""


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    dataset: str
    source_bucket: str
    source_key: str
    source_etag: str
    source_size: int
    source_last_modified: str

    def canonical_payload(self) -> dict[str, object]:
        required_strings = (
            self.dataset,
            self.source_bucket,
            self.source_key,
            self.source_etag,
        )
        if not all(required_strings):
            raise ValueError("source identity strings must be non-empty")
        if len(self.dataset) > 128 or len(self.source_bucket) > 63:
            raise ValueError("dataset or source bucket exceeds its limit")
        if len(self.source_key.encode("utf-8")) > 1_024 or len(self.source_etag) > 256:
            raise ValueError("source key or ETag exceeds its limit")
        if not 0 <= self.source_size <= 5 * 1_024**4:
            raise ValueError("source_size is outside S3 object limits")
        modified = _parse_timestamp(self.source_last_modified)
        return {
            "dataset": self.dataset,
            "source_bucket": self.source_bucket,
            "source_etag": self.source_etag.strip('"'),
            "source_key": self.source_key,
            "source_last_modified": modified.isoformat(),
            "source_size": self.source_size,
        }


@dataclass(frozen=True, slots=True)
class ClaimResult:
    outcome: Literal["CLAIMED", "BUSY", "COMPLETE"]
    item: dict[str, Any]

    @property
    def claimed(self) -> bool:
        return self.outcome == "CLAIMED"


def _parse_timestamp(value: str | datetime) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(UTC).isoformat()


def source_fingerprint(identity: SourceIdentity) -> str:
    payload = json.dumps(
        identity.canonical_payload(), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def source_identity_from_message(message: dict[str, Any]) -> SourceIdentity:
    return SourceIdentity(
        dataset=str(message["dataset"]),
        source_bucket=str(message["source_bucket"]),
        source_key=str(message["source_key"]),
        source_etag=str(message["source_etag"]),
        source_size=int(message["source_size"]),
        source_last_modified=str(message["source_last_modified"]),
    )


def _conditional_failure(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException"


class IngestionLedger:
    """Optimistic, lease-based ingestion state stored by immutable source fingerprint."""

    def __init__(self, table: Any):
        self.table = table

    @staticmethod
    def _key(fingerprint: str) -> dict[str, str]:
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ValueError("invalid source fingerprint")
        return {"source_fingerprint": fingerprint}

    def get(self, fingerprint: str, *, consistent: bool = True) -> dict[str, Any] | None:
        response = self.table.get_item(Key=self._key(fingerprint), ConsistentRead=consistent)
        item = response.get("Item")
        return dict(item) if item is not None else None

    def _put_new(self, item: dict[str, Any]) -> None:
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(source_fingerprint)",
            )
        except ClientError as exc:
            if _conditional_failure(exc):
                raise LedgerConflict("ledger record was created concurrently") from exc
            raise

    def _replace(self, item: dict[str, Any], expected_version: int) -> None:
        replacement = {**item, "version": expected_version + 1}
        try:
            self.table.put_item(
                Item=replacement,
                ConditionExpression="#version = :expected_version",
                ExpressionAttributeNames={"#version": "version"},
                ExpressionAttributeValues={":expected_version": expected_version},
            )
        except ClientError as exc:
            if _conditional_failure(exc):
                raise LedgerConflict("ledger record changed concurrently") from exc
            raise

    @staticmethod
    def _assert_identity(item: dict[str, Any], identity: SourceIdentity) -> None:
        expected = identity.canonical_payload()
        actual = {key: item.get(key) for key in expected}
        if actual != expected:
            raise RuntimeError("source fingerprint collision or corrupted ledger identity")
        if item.get("state") not in LEDGER_STATES:
            raise RuntimeError("corrupted ingestion ledger state")

    def ensure_discovered(
        self, identity: SourceIdentity, *, now: datetime
    ) -> tuple[dict[str, Any], bool]:
        fingerprint = source_fingerprint(identity)
        canonical = identity.canonical_payload()
        for _ in range(_MAX_CLAIM_ATTEMPTS):
            current = self.get(fingerprint)
            if current is not None:
                self._assert_identity(current, identity)
                return current, False
            item = {
                "source_fingerprint": fingerprint,
                **canonical,
                "state": "DISCOVERED",
                "version": 1,
                "discovered_at": _iso(now),
                "updated_at": _iso(now),
            }
            try:
                self._put_new(item)
                return item, True
            except LedgerConflict:
                continue
        raise LedgerConflict("could not create ingestion ledger record")

    @staticmethod
    def _lease_active(item: dict[str, Any], stage: str, now: datetime) -> bool:
        expires = item.get("lease_expires_at")
        return (
            item.get("lease_stage") == stage
            and isinstance(expires, str)
            and _parse_timestamp(expires) > now.astimezone(UTC)
        )

    def claim_dispatch(
        self,
        fingerprint: str,
        *,
        owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> ClaimResult:
        return self._claim(
            fingerprint,
            stage="DISPATCH",
            owner=owner,
            now=now,
            lease_seconds=lease_seconds,
        )

    def claim_copy(
        self,
        fingerprint: str,
        *,
        owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> ClaimResult:
        return self._claim(
            fingerprint,
            stage="COPY",
            owner=owner,
            now=now,
            lease_seconds=lease_seconds,
        )

    def _claim(
        self,
        fingerprint: str,
        *,
        stage: Literal["DISPATCH", "COPY"],
        owner: str,
        now: datetime,
        lease_seconds: int,
    ) -> ClaimResult:
        if not owner:
            raise ValueError("lease owner must be non-empty")
        if not 1 <= lease_seconds <= 86_400:
            raise ValueError("lease_seconds must be between 1 and 86400")
        for _ in range(_MAX_CLAIM_ATTEMPTS):
            item = self.get(fingerprint)
            if item is None:
                raise KeyError("source fingerprint is not discovered")
            state = item.get("state")
            if state not in LEDGER_STATES:
                raise RuntimeError("corrupted ingestion ledger state")
            if stage == "DISPATCH":
                if item.get("dispatched_at") or state in {
                    "COPYING",
                    "COPIED",
                    "MATERIALIZING",
                    "MATERIALIZED",
                }:
                    return ClaimResult("COMPLETE", item)
            elif state in {"COPIED", "MATERIALIZING", "MATERIALIZED"}:
                return ClaimResult("COMPLETE", item)
            if self._lease_active(item, stage, now):
                return ClaimResult("BUSY", item)

            claimed = {
                **item,
                "lease_stage": stage,
                "lease_owner": owner,
                "lease_expires_at": _iso(now + timedelta(seconds=lease_seconds)),
                "updated_at": _iso(now),
            }
            if stage == "COPY":
                claimed["state"] = "COPYING"
                claimed.pop("failure_stage", None)
                claimed.pop("failure_error", None)
            try:
                self._replace(claimed, int(item["version"]))
                claimed["version"] = int(item["version"]) + 1
                return ClaimResult("CLAIMED", claimed)
            except LedgerConflict:
                continue
        raise LedgerConflict(f"could not claim {stage.lower()} lease")

    def _finish_lease(
        self,
        fingerprint: str,
        *,
        stage: Literal["DISPATCH", "COPY"],
        owner: str,
        now: datetime,
        next_state: str | None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for _ in range(_MAX_CLAIM_ATTEMPTS):
            item = self.get(fingerprint)
            if item is None:
                raise KeyError("source fingerprint is not discovered")
            if item.get("lease_stage") != stage or item.get("lease_owner") != owner:
                raise LedgerConflict(f"{stage.lower()} lease is not owned by caller")
            updated = {**item, **(extra or {}), "updated_at": _iso(now)}
            if next_state is not None:
                updated["state"] = next_state
            for key in ("lease_stage", "lease_owner", "lease_expires_at"):
                updated.pop(key, None)
            try:
                self._replace(updated, int(item["version"]))
                updated["version"] = int(item["version"]) + 1
                return updated
            except LedgerConflict:
                continue
        raise LedgerConflict(f"could not finish {stage.lower()} lease")

    def mark_dispatched(
        self, fingerprint: str, *, owner: str, now: datetime, message_id: str
    ) -> dict[str, Any]:
        return self._finish_lease(
            fingerprint,
            stage="DISPATCH",
            owner=owner,
            now=now,
            next_state=None,
            extra={"dispatched_at": _iso(now), "dispatch_message_id": message_id},
        )

    def release_dispatch(
        self, fingerprint: str, *, owner: str, now: datetime, error: str
    ) -> dict[str, Any]:
        return self._finish_lease(
            fingerprint,
            stage="DISPATCH",
            owner=owner,
            now=now,
            next_state=None,
            extra={"dispatch_error": error[:_MAX_ERROR_LENGTH]},
        )

    def mark_copied(
        self,
        fingerprint: str,
        *,
        owner: str,
        now: datetime,
        raw_key: str,
        raw_sha256: str,
        manifest_key: str,
    ) -> dict[str, Any]:
        return self._finish_lease(
            fingerprint,
            stage="COPY",
            owner=owner,
            now=now,
            next_state="COPIED",
            extra={
                "copied_at": _iso(now),
                "raw_key": raw_key,
                "raw_sha256": raw_sha256,
                "manifest_key": manifest_key,
            },
        )

    def mark_failed(
        self,
        fingerprint: str,
        *,
        owner: str,
        now: datetime,
        stage: str,
        error: str,
    ) -> dict[str, Any]:
        return self._finish_lease(
            fingerprint,
            stage="COPY",
            owner=owner,
            now=now,
            next_state="FAILED",
            extra={
                "failed_at": _iso(now),
                "failure_stage": stage,
                "failure_error": error[:_MAX_ERROR_LENGTH],
            },
        )

    def transition(
        self,
        fingerprint: str,
        *,
        expected_state: str,
        next_state: str,
        now: datetime,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if expected_state not in LEDGER_STATES or next_state not in LEDGER_STATES:
            raise ValueError("unknown ledger state")
        if (expected_state, next_state) not in _ALLOWED_TRANSITIONS:
            raise ValueError(f"invalid ledger transition: {expected_state} -> {next_state}")
        for _ in range(_MAX_CLAIM_ATTEMPTS):
            item = self.get(fingerprint)
            if item is None:
                raise KeyError("source fingerprint is not discovered")
            if item.get("state") != expected_state:
                raise LedgerConflict(f"expected state {expected_state}, found {item.get('state')}")
            updated = {
                **item,
                **(attributes or {}),
                "state": next_state,
                "updated_at": _iso(now),
            }
            try:
                self._replace(updated, int(item["version"]))
                updated["version"] = int(item["version"]) + 1
                return updated
            except LedgerConflict:
                continue
        raise LedgerConflict("could not transition ingestion ledger state")
