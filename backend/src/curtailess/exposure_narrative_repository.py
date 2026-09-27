from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from curtailess.exposure_narrative import NARRATIVE_SCHEMA_VERSION
from curtailess.schemas import ExposureNarrative


def _version_sort_key(input_digest: str) -> str:
    return f"VERSION#{NARRATIVE_SCHEMA_VERSION}#{input_digest}"


class ExposureNarrativeRepository:
    def __init__(self, table: Any):
        self.table = table

    def get_exact(self, asset_id: str, input_digest: str) -> ExposureNarrative | None:
        response = self.table.get_item(
            Key={"asset_id": asset_id, "version": _version_sort_key(input_digest)},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            return None
        if item.get("input_digest") != input_digest:
            raise ValueError("stored exposure narrative digest does not match its key")
        if item.get("schema_version") != NARRATIVE_SCHEMA_VERSION:
            return None
        return ExposureNarrative.model_validate(item["narrative"])

    def get_current_record(self, asset_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(
            Key={"asset_id": asset_id, "version": "CURRENT"},
            ConsistentRead=True,
        )
        item = response.get("Item")
        return dict(item) if item is not None else None

    def save(
        self,
        asset_id: str,
        input_digest: str,
        narrative: ExposureNarrative,
        model_id: str | None,
    ) -> str:
        created_at = datetime.now(UTC).isoformat()
        item = {
            "asset_id": asset_id,
            "version": _version_sort_key(input_digest),
            "input_digest": input_digest,
            "schema_version": NARRATIVE_SCHEMA_VERSION,
            "narrative": narrative.model_dump(mode="json", by_alias=True),
            "generation_mode": "bedrock" if model_id else "deterministic_fallback",
            "model_id": model_id,
            "validation_status": "validated",
            "created_at": created_at,
        }
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression=(
                    "attribute_not_exists(asset_id) AND attribute_not_exists(version)"
                ),
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            stored = self.get_exact(asset_id, input_digest)
            if stored != narrative:
                raise ValueError(
                    "immutable narrative version already contains different content"
                ) from exc
        self.table.put_item(
            Item={
                **item,
                "version": "CURRENT",
                "version_key": _version_sort_key(input_digest),
            }
        )
        return _version_sort_key(input_digest)


def create_exposure_narrative_repository(
    table_name: str | None, region_name: str
) -> ExposureNarrativeRepository | InMemoryExposureNarrativeRepository:
    if not table_name:
        return InMemoryExposureNarrativeRepository()
    table = boto3.resource("dynamodb", region_name=region_name).Table(  # type: ignore[attr-defined]
        table_name
    )
    return ExposureNarrativeRepository(table)


class InMemoryExposureNarrativeRepository:
    def __init__(self):
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def get_exact(self, asset_id: str, input_digest: str) -> ExposureNarrative | None:
        item = self.items.get((asset_id, _version_sort_key(input_digest)))
        return ExposureNarrative.model_validate(item["narrative"]) if item else None

    def get_current_record(self, asset_id: str) -> dict[str, Any] | None:
        item = self.items.get((asset_id, "CURRENT"))
        return dict(item) if item else None

    def save(
        self,
        asset_id: str,
        input_digest: str,
        narrative: ExposureNarrative,
        model_id: str | None,
    ) -> str:
        version = _version_sort_key(input_digest)
        existing = self.items.get((asset_id, version))
        serialized = narrative.model_dump(mode="json", by_alias=True)
        if existing and existing["narrative"] != serialized:
            raise ValueError("immutable narrative version already contains different content")
        item = {
            "asset_id": asset_id,
            "version": version,
            "input_digest": input_digest,
            "schema_version": NARRATIVE_SCHEMA_VERSION,
            "narrative": serialized,
            "generation_mode": "bedrock" if model_id else "deterministic_fallback",
            "model_id": model_id,
            "validation_status": "validated",
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.items[(asset_id, version)] = item
        self.items[(asset_id, "CURRENT")] = {**item, "version": "CURRENT", "version_key": version}
        return version
