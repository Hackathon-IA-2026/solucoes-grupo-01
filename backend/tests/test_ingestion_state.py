from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from botocore.exceptions import ClientError

from curtailess.ingestion_state import (
    IngestionLedger,
    LedgerConflict,
    SourceIdentity,
    source_fingerprint,
)

NOW = datetime(2026, 9, 27, 4, 0, tzinfo=UTC)


def conditional_failure() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "conflict"}},
        "PutItem",
    )


class FakeLedgerTable:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.put_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.conflicts_remaining = 0

    def get_item(self, **kwargs):
        self.get_calls.append(kwargs)
        item = self.items.get(kwargs["Key"]["source_fingerprint"])
        return {"Item": deepcopy(item)} if item is not None else {}

    def put_item(self, **kwargs):
        self.put_calls.append(kwargs)
        item = deepcopy(kwargs["Item"])
        fingerprint = item["source_fingerprint"]
        existing = self.items.get(fingerprint)
        if self.conflicts_remaining:
            self.conflicts_remaining -= 1
            raise conditional_failure()
        condition = kwargs["ConditionExpression"]
        if condition == "attribute_not_exists(source_fingerprint)":
            if existing is not None:
                raise conditional_failure()
        elif condition == "#version = :expected_version":
            expected = kwargs["ExpressionAttributeValues"][":expected_version"]
            if existing is None or existing["version"] != expected:
                raise conditional_failure()
        else:
            raise AssertionError(f"unexpected condition {condition}")
        self.items[fingerprint] = item
        return {}


def identity(*, etag: str = "etag-a", size: int = 100) -> SourceIdentity:
    return SourceIdentity(
        dataset="restricao_coff_eolica_tm",
        source_bucket="ons-aws-prod-opendata",
        source_key=("dataset/restricao_coff_eolica_tm/RESTRICAO_COFF_EOLICA_2026_09.parquet"),
        source_etag=etag,
        source_size=size,
        source_last_modified="2026-09-26T00:00:00+00:00",
    )


def test_fingerprint_is_canonical_and_changes_with_source_version() -> None:
    quoted = identity(etag='"etag-a"')
    plain = identity(etag="etag-a")
    changed = identity(etag="etag-b")
    assert source_fingerprint(quoted) == source_fingerprint(plain)
    assert source_fingerprint(changed) != source_fingerprint(plain)
    assert len(source_fingerprint(plain)) == 64


@pytest.mark.parametrize(
    "invalid_identity",
    [
        SourceIdentity("d" * 129, "bucket", "key", "etag", 1, NOW.isoformat()),
        SourceIdentity("dataset", "b" * 64, "key", "etag", 1, NOW.isoformat()),
        SourceIdentity("dataset", "bucket", "k" * 1_025, "etag", 1, NOW.isoformat()),
        SourceIdentity("dataset", "bucket", "key", "e" * 257, 1, NOW.isoformat()),
        SourceIdentity("dataset", "bucket", "key", "etag", -1, NOW.isoformat()),
        SourceIdentity("dataset", "bucket", "key", "etag", 5 * 1_024**4 + 1, NOW.isoformat()),
    ],
)
def test_source_identity_limits_bound_ledger_items(invalid_identity: SourceIdentity) -> None:
    with pytest.raises(ValueError, match="limit|outside"):
        source_fingerprint(invalid_identity)


def test_duplicate_discovery_is_a_no_op() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    first, created = ledger.ensure_discovered(identity(), now=NOW)
    second, created_again = ledger.ensure_discovered(identity(), now=NOW + timedelta(seconds=1))
    assert created is True
    assert created_again is False
    assert first == second
    assert len(table.items) == 1


def test_changed_source_at_same_key_creates_distinct_ledger_record() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    first, _ = ledger.ensure_discovered(identity(etag="etag-a"), now=NOW)
    second, _ = ledger.ensure_discovered(identity(etag="etag-b", size=101), now=NOW)
    assert first["source_key"] == second["source_key"]
    assert first["source_fingerprint"] != second["source_fingerprint"]
    assert len(table.items) == 2


def test_dispatch_claim_suppresses_duplicate_after_message_is_recorded() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    item, _ = ledger.ensure_discovered(identity(), now=NOW)
    fingerprint = item["source_fingerprint"]
    claim = ledger.claim_dispatch(fingerprint, owner="dispatch-1", now=NOW, lease_seconds=60)
    assert claim.claimed
    busy = ledger.claim_dispatch(
        fingerprint, owner="dispatch-2", now=NOW + timedelta(seconds=1), lease_seconds=60
    )
    assert busy.outcome == "BUSY"
    ledger.mark_dispatched(
        fingerprint, owner="dispatch-1", now=NOW + timedelta(seconds=2), message_id="m-1"
    )
    complete = ledger.claim_dispatch(
        fingerprint, owner="dispatch-2", now=NOW + timedelta(seconds=3), lease_seconds=60
    )
    assert complete.outcome == "COMPLETE"


def test_failed_dispatch_releases_lease_for_retry() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    item, _ = ledger.ensure_discovered(identity(), now=NOW)
    fingerprint = item["source_fingerprint"]
    ledger.claim_dispatch(fingerprint, owner="d-1", now=NOW, lease_seconds=60)
    ledger.release_dispatch(fingerprint, owner="d-1", now=NOW, error="SQS unavailable")
    retry = ledger.claim_dispatch(fingerprint, owner="d-2", now=NOW, lease_seconds=60)
    assert retry.claimed


def test_expired_copy_lease_can_be_reclaimed() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    item, _ = ledger.ensure_discovered(identity(), now=NOW)
    fingerprint = item["source_fingerprint"]
    first = ledger.claim_copy(fingerprint, owner="copy-1", now=NOW, lease_seconds=10)
    assert first.claimed
    busy = ledger.claim_copy(
        fingerprint, owner="copy-2", now=NOW + timedelta(seconds=9), lease_seconds=10
    )
    assert busy.outcome == "BUSY"
    reclaimed = ledger.claim_copy(
        fingerprint, owner="copy-2", now=NOW + timedelta(seconds=11), lease_seconds=10
    )
    assert reclaimed.claimed
    assert reclaimed.item["lease_owner"] == "copy-2"


def test_failed_copy_can_retry_and_completed_copy_is_a_no_op() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    item, _ = ledger.ensure_discovered(identity(), now=NOW)
    fingerprint = item["source_fingerprint"]
    ledger.claim_copy(fingerprint, owner="copy-1", now=NOW, lease_seconds=60)
    failed = ledger.mark_failed(
        fingerprint,
        owner="copy-1",
        now=NOW + timedelta(seconds=1),
        stage="COPYING",
        error="download failed",
    )
    assert failed["state"] == "FAILED"
    retry = ledger.claim_copy(
        fingerprint, owner="copy-2", now=NOW + timedelta(seconds=2), lease_seconds=60
    )
    assert retry.claimed
    copied = ledger.mark_copied(
        fingerprint,
        owner="copy-2",
        now=NOW + timedelta(seconds=3),
        raw_key="raw/key",
        raw_sha256="a" * 64,
        manifest_key="manifest/key",
    )
    assert copied["state"] == "COPIED"
    duplicate = ledger.claim_copy(
        fingerprint, owner="copy-3", now=NOW + timedelta(seconds=4), lease_seconds=60
    )
    assert duplicate.outcome == "COMPLETE"


def test_materialized_fingerprint_remains_complete() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    item, _ = ledger.ensure_discovered(identity(), now=NOW)
    fingerprint = item["source_fingerprint"]
    ledger.claim_copy(fingerprint, owner="copy", now=NOW, lease_seconds=60)
    ledger.mark_copied(
        fingerprint,
        owner="copy",
        now=NOW,
        raw_key="raw/key",
        raw_sha256="a" * 64,
        manifest_key="manifest/key",
    )
    ledger.transition(
        fingerprint,
        expected_state="COPIED",
        next_state="MATERIALIZING",
        now=NOW,
    )
    ledger.transition(
        fingerprint,
        expected_state="MATERIALIZING",
        next_state="MATERIALIZED",
        now=NOW,
    )
    assert ledger.claim_copy(fingerprint, owner="later", now=NOW, lease_seconds=60).outcome == (
        "COMPLETE"
    )
    assert (
        ledger.claim_dispatch(fingerprint, owner="later", now=NOW, lease_seconds=60).outcome
        == "COMPLETE"
    )


def test_optimistic_conflict_is_retried() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    item, _ = ledger.ensure_discovered(identity(), now=NOW)
    table.conflicts_remaining = 1
    claim = ledger.claim_copy(item["source_fingerprint"], owner="copy", now=NOW, lease_seconds=60)
    assert claim.claimed


def test_wrong_owner_cannot_finish_lease() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    item, _ = ledger.ensure_discovered(identity(), now=NOW)
    fingerprint = item["source_fingerprint"]
    ledger.claim_copy(fingerprint, owner="copy-1", now=NOW, lease_seconds=60)
    with pytest.raises(LedgerConflict, match="not owned"):
        ledger.mark_copied(
            fingerprint,
            owner="copy-2",
            now=NOW,
            raw_key="raw/key",
            raw_sha256="a" * 64,
            manifest_key="manifest/key",
        )


def test_materialized_state_cannot_transition_backwards() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    item, _ = ledger.ensure_discovered(identity(), now=NOW)
    fingerprint = item["source_fingerprint"]
    ledger.claim_copy(fingerprint, owner="copy", now=NOW, lease_seconds=60)
    ledger.mark_copied(
        fingerprint,
        owner="copy",
        now=NOW,
        raw_key="raw/key",
        raw_sha256="a" * 64,
        manifest_key="manifest/key",
    )
    ledger.transition(
        fingerprint,
        expected_state="COPIED",
        next_state="MATERIALIZING",
        now=NOW,
    )
    ledger.transition(
        fingerprint,
        expected_state="MATERIALIZING",
        next_state="MATERIALIZED",
        now=NOW,
    )
    with pytest.raises(ValueError, match="invalid ledger transition"):
        ledger.transition(
            fingerprint,
            expected_state="MATERIALIZED",
            next_state="DISCOVERED",
            now=NOW,
        )


def test_materialization_lease_recovers_failure_and_suppresses_completed_replay() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    item, _ = ledger.ensure_discovered(identity(), now=NOW)
    fingerprint = item["source_fingerprint"]
    before_copy = ledger.claim_materialization(
        fingerprint, owner="materialize-early", now=NOW, lease_seconds=60
    )
    assert before_copy.outcome == "BUSY"
    ledger.claim_copy(fingerprint, owner="copy", now=NOW, lease_seconds=60)
    copied = ledger.mark_copied(
        fingerprint,
        owner="copy",
        now=NOW,
        raw_key="raw/key",
        raw_sha256="a" * 64,
        manifest_key="manifest/key",
        materialization_message_id="message-1",
    )
    assert copied["materialization_message_id"] == "message-1"

    first = ledger.claim_materialization(
        fingerprint, owner="materialize-1", now=NOW, lease_seconds=60
    )
    assert first.claimed
    busy = ledger.claim_materialization(
        fingerprint,
        owner="materialize-2",
        now=NOW + timedelta(seconds=30),
        lease_seconds=60,
    )
    assert busy.outcome == "BUSY"
    failed = ledger.mark_materialization_failed(
        fingerprint,
        owner="materialize-1",
        now=NOW + timedelta(seconds=31),
        error="curated write failed",
    )
    assert failed["state"] == "FAILED"
    retry = ledger.claim_materialization(
        fingerprint,
        owner="materialize-2",
        now=NOW + timedelta(seconds=32),
        lease_seconds=60,
    )
    assert retry.claimed
    completed = ledger.mark_materialized(
        fingerprint,
        owner="materialize-2",
        now=NOW + timedelta(seconds=33),
        manifest_key="manifest/key",
        summary_key="curated/summary.json",
    )
    assert completed["state"] == "MATERIALIZED"
    replay = ledger.claim_materialization(
        fingerprint,
        owner="materialize-3",
        now=NOW + timedelta(seconds=34),
        lease_seconds=60,
    )
    assert replay.outcome == "COMPLETE"


def test_expired_materialization_lease_can_be_reclaimed() -> None:
    table = FakeLedgerTable()
    ledger = IngestionLedger(table)
    item, _ = ledger.ensure_discovered(identity(), now=NOW)
    fingerprint = item["source_fingerprint"]
    ledger.claim_copy(fingerprint, owner="copy", now=NOW, lease_seconds=60)
    ledger.mark_copied(
        fingerprint,
        owner="copy",
        now=NOW,
        raw_key="raw/key",
        raw_sha256="a" * 64,
        manifest_key="manifest/key",
    )
    ledger.claim_materialization(fingerprint, owner="materialize-1", now=NOW, lease_seconds=10)
    reclaimed = ledger.claim_materialization(
        fingerprint,
        owner="materialize-2",
        now=NOW + timedelta(seconds=11),
        lease_seconds=10,
    )
    assert reclaimed.claimed
    assert reclaimed.item["lease_owner"] == "materialize-2"
