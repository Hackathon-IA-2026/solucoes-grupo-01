import hashlib
from typing import Any

import boto3
from botocore.exceptions import ClientError


class IssuedProvenanceRepository:
    """Persist and resolve server-issued derived evidence by its exact identifier."""

    def __init__(self, table: Any):
        self.table = table

    @staticmethod
    def _key(evidence_id: str) -> dict[str, str]:
        digest = hashlib.sha256(evidence_id.encode("utf-8")).hexdigest()
        return {"plant_id": "PROVENANCE", "scenario_id": f"evidence#{digest}"}

    def put(self, record: dict[str, Any]) -> None:
        evidence_id = record.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id:
            raise ValueError("issued provenance record requires a full evidence_id")
        canonical_record = {**record, **self._key(evidence_id)}
        try:
            self.table.put_item(
                Item=canonical_record,
                ConditionExpression=(
                    "attribute_not_exists(plant_id) AND attribute_not_exists(scenario_id)"
                ),
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            response = self.table.get_item(Key=self._key(evidence_id), ConsistentRead=True)
            existing = response.get("Item")
            if existing != canonical_record:
                raise RuntimeError(
                    "issued provenance key collision or immutable record mismatch"
                ) from exc

    def get(self, evidence_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(Key=self._key(evidence_id), ConsistentRead=True)
        item = response.get("Item")
        if (
            item is None
            or item.get("record_type") != "issued_provenance"
            or item.get("evidence_id") != evidence_id
        ):
            return None
        return item


class UnconfiguredIssuedProvenanceRepository:
    def put(self, record: dict[str, Any]) -> None:
        del record
        raise RuntimeError("Repositório de proveniência emitida não configurado.")

    def get(self, evidence_id: str) -> None:
        del evidence_id
        return None


def create_issued_provenance_repository(
    table_name: str | None, region_name: str
) -> IssuedProvenanceRepository | UnconfiguredIssuedProvenanceRepository:
    if not table_name:
        return UnconfiguredIssuedProvenanceRepository()
    table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)
    return IssuedProvenanceRepository(table)
