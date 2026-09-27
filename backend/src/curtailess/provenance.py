from typing import Any

import boto3


class IssuedProvenanceRepository:
    """Persist and resolve server-issued derived evidence by its exact identifier."""

    def __init__(self, table: Any):
        self.table = table

    def put(self, record: dict[str, Any]) -> None:
        self.table.put_item(Item=record)

    def get(self, evidence_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(
            Key={"plant_id": "PROVENANCE", "scenario_id": evidence_id},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None or item.get("record_type") != "issued_provenance":
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
