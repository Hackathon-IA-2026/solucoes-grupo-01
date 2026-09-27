import hashlib
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical JSON does not allow non-finite numbers")
        value = float(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON does not allow non-finite numbers")
        return 0.0 if value == 0 else value
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _normalize(value),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
