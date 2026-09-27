import hashlib
import json
import re
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from .canonical import canonical_digest

EVIDENCE_ID_MAX_LENGTH = 69
MAX_DYNAMO_ITEM_BYTES = 350 * 1024
MAX_OPERATION_PROVENANCES = 224
MAX_OPERATION_SOURCE_RECORDS = 32
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


def _dynamodb_safe(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _dynamodb_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dynamodb_safe(item) for item in value]
    return value


def _item_size(item: dict[str, Any]) -> int:
    serialized = TypeSerializer().serialize(item)
    return len(json.dumps(serialized, separators=(",", ":")).encode("utf-8"))


def _guard_item_size(item: dict[str, Any]) -> None:
    size = _item_size(item)
    if size > MAX_DYNAMO_ITEM_BYTES:
        raise ValueError(f"provenance item exceeds {MAX_DYNAMO_ITEM_BYTES} bytes: {size}")


class IssuedProvenanceRepository:
    """Persist immutable leaves and memberships before the committed operation record.

    Records have no application TTL because the shared scenarios table has no provenance
    retention policy. Only request digests, compact source metadata, and provenance needed for
    audit resolution are retained; canonical requests and outputs are deliberately not stored.
    """

    def __init__(self, table: Any):
        self.table = table

    @staticmethod
    def _evidence_digest(evidence_id: str) -> str:
        return hashlib.sha256(evidence_id.encode("utf-8")).hexdigest()

    @classmethod
    def _key(cls, evidence_id: str) -> dict[str, str]:
        return {
            "plant_id": "PROVENANCE",
            "scenario_id": f"evidence-leaf#{cls._evidence_digest(evidence_id)}",
        }

    @classmethod
    def _membership_partition(cls, evidence_id: str) -> str:
        return f"PROVENANCE#{cls._evidence_digest(evidence_id)}"

    @classmethod
    def _membership_key(cls, evidence_id: str, operation_id: str) -> dict[str, str]:
        return {
            "plant_id": cls._membership_partition(evidence_id),
            "scenario_id": f"operation#{operation_id}",
        }

    @staticmethod
    def _operation_key(operation_id: str) -> dict[str, str]:
        return {"plant_id": "PROVENANCE", "scenario_id": f"operation#{operation_id}"}

    @staticmethod
    def _leaf_content(
        provenance: dict[str, Any], source_records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return {"provenance": provenance, "source_records": source_records}

    @classmethod
    def _leaf_item(
        cls,
        evidence_id: str,
        provenance: dict[str, Any],
        source_records: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # The two-argument form is the compact-record format emitted before leaf content was
        # materialized. It remains useful only for authenticated legacy reads.
        if source_records is None:
            return {
                **cls._key(evidence_id),
                "record_type": "provenance_leaf",
                "evidence_id": evidence_id,
                "provenance_digest": canonical_digest(provenance),
            }
        content = cls._leaf_content(provenance, source_records)
        return {
            **cls._key(evidence_id),
            "record_type": "provenance_leaf_v2",
            "evidence_id": evidence_id,
            "leaf_digest": canonical_digest(content),
            **content,
        }

    @classmethod
    def _membership_item(
        cls,
        evidence_id: str,
        operation_id: str,
        provenance: dict[str, Any] | None = None,
        *,
        leaf_digest: str | None = None,
    ) -> dict[str, Any]:
        digest = leaf_digest or canonical_digest(provenance)
        digest_field = "leaf_digest" if leaf_digest is not None else "provenance_digest"
        return {
            **cls._membership_key(evidence_id, operation_id),
            "record_type": "provenance_membership",
            "evidence_id": evidence_id,
            "operation_id": operation_id,
            digest_field: digest,
        }

    @classmethod
    def _operation_item(cls, operation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            **cls._operation_key(operation_id),
            "record_type": "provenance_operation",
            "committed": True,
            "operation_id": operation_id,
            **payload,
        }

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
        if not 1 <= len(provenances) <= MAX_OPERATION_PROVENANCES:
            raise ValueError(
                f"operation requires between 1 and {MAX_OPERATION_PROVENANCES} provenance records"
            )
        if len(source_records) > MAX_OPERATION_SOURCE_RECORDS:
            raise ValueError(
                f"operation source record count exceeds {MAX_OPERATION_SOURCE_RECORDS}"
            )
        for evidence_id, provenance in provenances.items():
            if evidence_id != provenance.get("evidence_id"):
                raise ValueError("provenance map key must exactly match evidence_id")
            parse_evidence_id(evidence_id)
        source_fields = (
            "asset_id",
            "asset_ids",
            "period",
            "source_bucket",
            "source_key",
            "source_sha256",
            "method",
            "capacity_data_version",
            "capacity_method",
            "capacity_source_key",
            "capacity_source_sha256",
        )
        if operation == "point_context":
            source_fields += (
                "point_id",
                "period_start",
                "period_end",
                "limited_interval_count",
            )
        if operation in {"historical_windows", "maintenance_rank"}:
            source_fields += (
                "period_start",
                "period_end",
                "interval_count",
                "curtailed_mwh",
                "curtailed_mwh_by_reason",
            )
        compact_sources = [
            _dynamodb_safe({key: source[key] for key in source_fields if key in source})
            for source in source_records
        ]

        def sources_for(provenance: dict[str, Any]) -> list[dict[str, Any]]:
            artifacts = {
                (artifact.get("source_key"), artifact.get("source_sha256"))
                for artifact in provenance.get("source_artifacts", [])
                if isinstance(artifact, dict)
            }
            if provenance.get("source_key") and provenance.get("source_sha256"):
                artifacts.add((provenance["source_key"], provenance["source_sha256"]))
            matches = []
            for source in compact_sources:
                primary = (source.get("source_key"), source.get("source_sha256"))
                capacity = (
                    source.get("capacity_source_key"),
                    source.get("capacity_source_sha256"),
                )
                if primary in artifacts:
                    matches.append(source)
                elif capacity in artifacts:
                    matches.append(
                        {
                            key: source[key]
                            for key in (
                                "asset_id",
                                "asset_ids",
                                "capacity_data_version",
                                "capacity_method",
                                "capacity_source_key",
                                "capacity_source_sha256",
                            )
                            if key in source
                        }
                    )
            # Legacy callers did not always retain source hashes. Preserve those records only when
            # no authenticated key/hash pair can select a narrower immutable set.
            return matches or compact_sources

        leaves = {
            evidence_id: self._leaf_item(evidence_id, provenance, sources_for(provenance))
            for evidence_id, provenance in provenances.items()
        }
        manifest = [
            {"evidence_id": evidence_id, "leaf_digest": leaves[evidence_id]["leaf_digest"]}
            for evidence_id in sorted(leaves)
        ]
        payload = {
            "operation": operation,
            "request_digest": request_digest,
            "evidence_manifest": manifest,
        }
        operation_id = canonical_digest(payload)
        operation_item = self._operation_item(operation_id, payload)
        memberships = {
            evidence_id: self._membership_item(
                evidence_id,
                operation_id,
                leaf_digest=leaf["leaf_digest"],
            )
            for evidence_id, leaf in leaves.items()
        }
        # Bound every item before the first write so a validly rejected request cannot leave a
        # partial operation behind.
        for item in (*leaves.values(), *memberships.values(), operation_item):
            _guard_item_size(item)
        for leaf in leaves.values():
            self._put_immutable(leaf)
        for membership in memberships.values():
            self._put_immutable(membership)
        self._put_immutable(operation_item)
        return operation_id

    def _memberships(self, evidence_id: str) -> Iterator[dict[str, Any]]:
        exclusive_start_key = None
        while True:
            kwargs: dict[str, Any] = {
                "KeyConditionExpression": "plant_id = :plant_id",
                "ExpressionAttributeValues": {":plant_id": self._membership_partition(evidence_id)},
                "ConsistentRead": True,
            }
            if exclusive_start_key is not None:
                kwargs["ExclusiveStartKey"] = exclusive_start_key
            response = self.table.query(**kwargs)
            page = response.get("Items", [])
            if not isinstance(page, list):
                return
            yield from (item for item in page if isinstance(item, dict))
            exclusive_start_key = response.get("LastEvaluatedKey")
            if not exclusive_start_key:
                return

    def _validated_operation(
        self, operation_id: str
    ) -> (
        tuple[
            dict[str, Any],
            dict[str, dict[str, Any]],
            dict[str, list[dict[str, Any]]],
        ]
        | None
    ):
        operation = self.table.get_item(
            Key=self._operation_key(operation_id), ConsistentRead=True
        ).get("Item")
        if not isinstance(operation, dict):
            return None
        try:
            if "evidence_manifest" not in operation:
                return self._validated_legacy_operation(operation_id, operation)
            payload = {
                key: operation[key] for key in ("operation", "request_digest", "evidence_manifest")
            }
            manifest = payload["evidence_manifest"]
            if (
                not isinstance(manifest, list)
                or not manifest
                or manifest != sorted(manifest, key=lambda member: member["evidence_id"])
                or len({member["evidence_id"] for member in manifest}) != len(manifest)
                or canonical_digest(payload) != operation_id
                or operation != self._operation_item(operation_id, payload)
            ):
                return None
            provenances: dict[str, dict[str, Any]] = {}
            sources: dict[str, list[dict[str, Any]]] = {}
            for member in manifest:
                member_id = member["evidence_id"]
                leaf_digest = member["leaf_digest"]
                parse_evidence_id(member_id)
                stored_leaf = self.table.get_item(
                    Key=self._key(member_id), ConsistentRead=True
                ).get("Item")
                stored_membership = self.table.get_item(
                    Key=self._membership_key(member_id, operation_id), ConsistentRead=True
                ).get("Item")
                if not isinstance(stored_leaf, dict):
                    return None
                member_provenance = stored_leaf.get("provenance")
                member_sources = stored_leaf.get("source_records")
                if (
                    not isinstance(member_provenance, dict)
                    or not isinstance(member_sources, list)
                    or member_provenance.get("evidence_id") != member_id
                    or stored_leaf != self._leaf_item(member_id, member_provenance, member_sources)
                    or stored_leaf.get("leaf_digest") != leaf_digest
                    or stored_membership
                    != self._membership_item(member_id, operation_id, leaf_digest=leaf_digest)
                ):
                    return None
                provenances[member_id] = member_provenance
                sources[member_id] = member_sources
        except (KeyError, TypeError, ValueError):
            return None
        return operation, provenances, sources

    def _validated_legacy_operation(
        self, operation_id: str, operation: dict[str, Any]
    ) -> (
        tuple[
            dict[str, Any],
            dict[str, dict[str, Any]],
            dict[str, list[dict[str, Any]]],
        ]
        | None
    ):
        try:
            payload = {
                key: operation[key]
                for key in ("operation", "request_digest", "provenances", "source_records")
            }
            provenances = payload["provenances"]
            source_records = payload["source_records"]
            if (
                not isinstance(provenances, dict)
                or not isinstance(source_records, list)
                or canonical_digest(payload) != operation_id
                or operation != self._operation_item(operation_id, payload)
            ):
                return None
            for member_id, member_provenance in provenances.items():
                if (
                    not isinstance(member_id, str)
                    or not isinstance(member_provenance, dict)
                    or member_provenance.get("evidence_id") != member_id
                ):
                    return None
                parse_evidence_id(member_id)
                stored_leaf = self.table.get_item(
                    Key=self._key(member_id), ConsistentRead=True
                ).get("Item")
                stored_membership = self.table.get_item(
                    Key=self._membership_key(member_id, operation_id), ConsistentRead=True
                ).get("Item")
                if stored_leaf != self._leaf_item(member_id, member_provenance) or (
                    stored_membership
                    != self._membership_item(member_id, operation_id, member_provenance)
                ):
                    return None
        except (KeyError, TypeError, ValueError):
            return None
        return operation, provenances, dict.fromkeys(provenances, source_records)

    def get(self, evidence_id: str) -> dict[str, Any] | None:
        try:
            parse_evidence_id(evidence_id)
        except ValueError:
            return None
        leaf = self.table.get_item(Key=self._key(evidence_id), ConsistentRead=True).get("Item")
        if (
            not isinstance(leaf, dict)
            or leaf.get("record_type") not in {"provenance_leaf", "provenance_leaf_v2"}
            or leaf.get("evidence_id") != evidence_id
        ):
            return None
        for membership in self._memberships(evidence_id):
            operation_id = membership.get("operation_id")
            if not isinstance(operation_id, str):
                continue
            validated = self._validated_operation(operation_id)
            if validated is None:
                continue
            operation, provenances, sources = validated
            provenance = provenances.get(evidence_id)
            source_records = sources.get(evidence_id)
            if not isinstance(provenance, dict) or not isinstance(source_records, list):
                continue
            if "evidence_manifest" in operation:
                leaf_digest = canonical_digest(self._leaf_content(provenance, source_records))
                expected_leaf = self._leaf_item(evidence_id, provenance, source_records)
                expected_membership = self._membership_item(
                    evidence_id, operation_id, leaf_digest=leaf_digest
                )
            else:
                expected_leaf = self._leaf_item(evidence_id, provenance)
                expected_membership = self._membership_item(evidence_id, operation_id, provenance)
            if leaf != expected_leaf or membership != expected_membership:
                continue
            return {
                "evidence_id": evidence_id,
                "record_type": "issued_provenance",
                "operation": operation.get("operation"),
                "request_digest": operation.get("request_digest"),
                "provenance": provenance,
                "source_records": source_records,
            }
        return None


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
