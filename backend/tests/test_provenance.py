from datetime import datetime, timedelta, timezone

import pytest

from curtailess.canonical import canonical_json
from curtailess.provenance import build_public_evidence_id, parse_evidence_id


def test_canonical_json_normalizes_utc_and_negative_zero() -> None:
    value = {
        "timestamp": datetime(2026, 1, 1, 3, tzinfo=timezone(timedelta(hours=3))),
        "value": -0.0,
    }
    assert canonical_json(value) == '{"timestamp":"2026-01-01T00:00:00Z","value":0.0}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_nonfinite_numbers(value: float) -> None:
    with pytest.raises(ValueError, match="non-finite"):
        canonical_json({"value": value})


def test_public_id_registry_keeps_materialized_ids_compact() -> None:
    evidence_id = build_public_evidence_id("a" * 64, "asset_id", "ons_materialized_asset_v1", "A")
    assert len(evidence_id) == 69
    assert parse_evidence_id(evidence_id)["kind"] == "public_materialized"
