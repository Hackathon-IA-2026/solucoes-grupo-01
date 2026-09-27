import hashlib
import json
import re
from typing import Any

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from .canonical import canonical_digest

EVIDENCE_ID_MAX_LENGTH = 96
MAX_DYNAMO_ITEM_BYTES = 350 * 1024
_ID_REGISTRY = {
    "evd1": ("derived", re.compile(r"^evd1\.[0-9a-f]{64}$")),
    "evp1": ("public_materialized", re.compile(r"^evp1\.[0-9a-f]{64}$")),
}


def _build_digest_id(prefix: str, payload: dict[str, Any]) -> str:
    if prefix not in _ID_REGISTRY:
        raise ValueError("unregistered evidence ID prefix")
    return f"{prefix}.{canonical_digest(payload)}"


def build_evidence_id(
    source_identities: str | list[str] | tuple[str, ...],
    field_name: str,
    method_version: str,
    context: str,
) -> str:
    """Build a bounded derived identifier; its metadata lives in an operation record."""
    sources = (
        [source_identities] if isinstance(source_identities, str) else sorted(source_identities)
    )
    return _build_digest_id(
        "evd1",
        {"context": context, "field": field_name, "method": method_version, "sources": sources},
    )


def build_public_evidence_id(
    source_identities: str | list[str] | tuple[str, ...],
    field_name: str,
    method_version: str,
    context: str,
) -> str:
    sources = (
        [source_identities] if isinstance(source_identities, str) else sorted(source_identities)
    )
    return _build_digest_id(
        "evp1",
        {"context": context, "field": field_name, "method": method_version, "sources": sources},
    )


def parse_evidence_id(evidence_id: str) -> dict[str, Any]:
    """Validate a compact identifier through the prefix/pattern registry."""
    if len(evidence_id) > EVIDENCE_ID_MAX_LENGTH:
        raise ValueError("evidence_id inválido ou corrompido")
    prefix = evidence_id.partition(".")[0]
    registration = _ID_REGISTRY.get(prefix)
    if registration is None or not registration[1].fullmatch(evidence_id):
        raise ValueError("evidence_id inválido ou corrompido")
    return {"digest": evidence_id.removeprefix(f"{prefix}."), "kind": registration[0]}


def _item_size(item: dict[str, Any]) -> int:
    serialized = TypeSerializer().serialize(item)
    return len(json.dumps(serialized, separators=(",", ":")).encode("utf-8"))


def _guard_item_size(item: dict[str, Any]) -> None:
    size = _item_size(item)
    if size > MAX_DYNAMO_ITEM_BYTES:
        raise ValueError(f"provenance item exceeds {MAX_DYNAMO_ITEM_BYTES} bytes: {size}")


class IssuedProvenanceRepository:
    """Persist compact evidence indexes first and a committed operation record last.

    Records have no application TTL because the shared scenarios table has no provenance
    retention policy. Only request digests, compact source metadata, and provenance needed for
    audit resolution are retained; canonical requests and outputs are deliberately not stored.
    """

    def __init__(self, table: Any):
        self.table = table

    @staticmethod
    def _key(evidence_id: str) -> dict[str, str]:
        digest = hashlib.sha256(evidence_id.encode("utf-8")).hexdigest()
        return {"plant_id": "PROVENANCE", "scenario_id": f"evidence#{digest}"}

    @staticmethod
    def _operation_key(operation_id: str) -> dict[str, str]:
        return {"plant_id": "PROVENANCE", "scenario_id": f"operation#{operation_id}"}

    def _put_immutable(self, item: dict[str, Any]) -> None:
        _guard_item_size(item)
        key = {"plant_id": item["plant_id"], "scenario_id": item["scenario_id"]}
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression=(
                    "attribute_not_exists(plant_id) AND attribute_not_exists(scenario_id)"
                ),
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = self.table.get_item(Key=key, ConsistentRead=True).get("Item")
            if existing != item:
                raise RuntimeError("provenance key collision or immutable record mismatch") from exc

    def put_operation(
        self,
        *,
        operation: str,
        request_digest: str,
        provenances: dict[str, dict[str, Any]],
        source_records: list[dict[str, Any]],
    ) -> str:
        if not isinstance(operation, str) or not 1 <= len(operation) <= 64:
            raise ValueError("operation must be a non-empty string of at most 64 characters")
        if not re.fullmatch(r"[0-9a-f]{64}", request_digest):
            raise ValueError("request_digest must be a SHA-256 hex digest")
        if not 1 <= len(provenances) <= 512:
            raise ValueError("operation requires between 1 and 512 provenance records")
        if len(source_records) > 32:
            raise ValueError("operation source record count exceeds 32")
        for evidence_id, provenance in provenances.items():
            if evidence_id != provenance.get("evidence_id"):
                raise ValueError("provenance map key must exactly match evidence_id")
            parse_evidence_id(evidence_id)
        compact_sources = [
            {
                key: source[key]
                for key in (
                    "asset_id",
                    "asset_ids",
                    "period",
                    "source_bucket",
                    "source_key",
                    "source_sha256",
                    "method",
                    "capacity_data_version",
                    "capacity_method",
                )
                if key in source
            }
            for source in source_records
        ]
        payload = {
            "operation": operation,
            "request_digest": request_digest,
            "provenances": provenances,
            "source_records": compact_sources,
        }
        operation_id = canonical_digest(payload)
        operation_item = {
            **self._operation_key(operation_id),
            "record_type": "provenance_operation",
            "committed": True,
            "operation_id": operation_id,
            **payload,
        }
        _guard_item_size(operation_item)
        for evidence_id, provenance in provenances.items():
            index = {
                **self._key(evidence_id),
                "record_type": "provenance_index",
                "evidence_id": evidence_id,
                "operation_id": operation_id,
                "provenance_digest": canonical_digest(provenance),
            }
            self._put_immutable(index)
        self._put_immutable(operation_item)
        return operation_id

    def get(self, evidence_id: str) -> dict[str, Any] | None:
        try:
            parse_evidence_id(evidence_id)
        except ValueError:
            return None
        index = self.table.get_item(Key=self._key(evidence_id), ConsistentRead=True).get("Item")
        if (
            index is None
            or index.get("record_type") != "provenance_index"
            or index.get("evidence_id") != evidence_id
        ):
            return None
        operation_id = index.get("operation_id")
        if not isinstance(operation_id, str):
            return None
        operation = self.table.get_item(
            Key=self._operation_key(operation_id), ConsistentRead=True
        ).get("Item")
        if (
            operation is None
            or operation.get("record_type") != "provenance_operation"
            or operation.get("committed") is not True
            or operation.get("operation_id") != operation_id
        ):
            return None
        provenance = operation.get("provenances", {}).get(evidence_id)
        if (
            not isinstance(provenance, dict)
            or provenance.get("evidence_id") != evidence_id
            or canonical_digest(provenance) != index.get("provenance_digest")
        ):
            return None
        return {
            "evidence_id": evidence_id,
            "record_type": "issued_provenance",
            "operation": operation.get("operation"),
            "request_digest": operation.get("request_digest"),
            "provenance": provenance,
            "source_records": operation.get("source_records", []),
        }


class UnconfiguredIssuedProvenanceRepository:
    def put_operation(self, **kwargs: Any) -> str:
        del kwargs
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
