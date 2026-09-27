import copy
import hashlib
import json
from datetime import timedelta

import pytest
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError
from fastapi import FastAPI
from fastapi.testclient import TestClient

import curtailess.main as main
from curtailess.canonical import canonical_digest
from curtailess.main import app
from curtailess.provenance import (
    EVIDENCE_ID_MAX_LENGTH,
    IssuedProvenanceRepository,
    build_evidence_id,
    build_public_evidence_id,
)
from curtailess.provenance_service import field_provenance
from curtailess.schemas import DataOrigin, EvidenceProvenance

client = TestClient(app)
evidence_contract_app = FastAPI()


@evidence_contract_app.post("/evidence")
def validate_evidence_contract(evidence: EvidenceProvenance) -> EvidenceProvenance:
    return evidence


evidence_contract_client = TestClient(evidence_contract_app)


class FakeScenariosTable:
    def __init__(self) -> None:
        self.items = {}
        self.consistent_reads = 0
        self.put_count = 0
        self.fail_on_put: int | None = None
        self.throttle = False

    @staticmethod
    def _validate_key(key: dict) -> None:
        if len(key["plant_id"].encode("utf-8")) > 2048:
            raise ClientError({"Error": {"Code": "ValidationException"}}, "FakeDynamoDB")
        if len(key["scenario_id"].encode("utf-8")) > 1024:
            raise ClientError({"Error": {"Code": "ValidationException"}}, "FakeDynamoDB")

    def put_item(self, *, Item, ConditionExpression=None) -> dict:
        self.put_count += 1
        if self.throttle:
            raise ClientError(
                {"Error": {"Code": "ProvisionedThroughputExceededException"}}, "PutItem"
            )
        if self.fail_on_put == self.put_count:
            raise ClientError({"Error": {"Code": "InternalServerError"}}, "PutItem")
        TypeSerializer().serialize(Item)
        assert len(json.dumps(TypeSerializer().serialize(Item)).encode()) < 400 * 1024
        key = {"plant_id": Item["plant_id"], "scenario_id": Item["scenario_id"]}
        self._validate_key(key)
        item_key = (key["plant_id"], key["scenario_id"])
        if ConditionExpression is not None and item_key in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[item_key] = copy.deepcopy(Item)
        return {}

    def get_item(self, *, Key, ConsistentRead=False) -> dict:
        self._validate_key(Key)
        self.consistent_reads += int(ConsistentRead)
        item = self.items.get((Key["plant_id"], Key["scenario_id"]))
        return {} if item is None else {"Item": item}

    def query(
        self,
        *,
        KeyConditionExpression,
        ExpressionAttributeValues,
        ConsistentRead=False,
        ExclusiveStartKey=None,
    ) -> dict:
        assert KeyConditionExpression == "plant_id = :plant_id"
        self.consistent_reads += int(ConsistentRead)
        plant_id = ExpressionAttributeValues[":plant_id"]
        items = [
            item
            for (item_plant_id, _), item in sorted(self.items.items())
            if item_plant_id == plant_id
        ]
        if ExclusiveStartKey is not None:
            start = ExclusiveStartKey["scenario_id"]
            items = [item for item in items if item["scenario_id"] > start]
        return {"Items": items}


@pytest.fixture(autouse=True)
def issued_provenance_table(monkeypatch) -> FakeScenariosTable:
    table = FakeScenariosTable()
    monkeypatch.setattr(main, "issued_provenance_repository", IssuedProvenanceRepository(table))
    return table


def _stored_provenance(evidence_id: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "field_name": "annual_net_benefit_brl",
        "origin": "PROXY_CALCULADO",
        "source_uri": "curtailess://test",
        "source_key": "raw/source.parquet",
        "source_sha256": "a" * 64,
        "source_sha256s": ["a" * 64],
        "parent_evidence_ids": [],
        "observed_at": "2026-01-01T00:00:00Z",
        "effective_at": "2026-01-01T00:00:00Z",
        "valid_from": None,
        "valid_to": None,
        "temporal_coverage": "known",
        "method_version": "bess_screen_v1",
        "limitations": ["test"],
    }


def test_evidence_ids_are_compact_bounded_digests() -> None:
    evidence_id = build_evidence_id(["x" * 50_000], "field", "method", "context" * 50_000)
    assert evidence_id.startswith("evd1.")
    assert len(evidence_id) <= EVIDENCE_ID_MAX_LENGTH


def evidence_contract_payload(origin: str, evidence_id: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "field_name": "test_field",
        "origin": origin,
        "source_uri": "curtailess://test/source",
        "source_key": "dataset/test/source.parquet",
        "source_sha256": "a" * 64,
        "effective_at": "2026-09-01T00:00:00Z",
        "method_version": "test_v1",
        "limitations": [],
    }


@pytest.mark.parametrize(
    ("origin", "id_builder"),
    [
        ("ONS_PUBLICO", build_public_evidence_id),
        ("PROXY_CALCULADO", build_evidence_id),
        ("SIMULADO", build_evidence_id),
        ("CLIENTE_INFORMADO", build_evidence_id),
    ],
)
def test_api_accepts_evidence_id_family_required_by_origin(origin, id_builder) -> None:
    evidence_id = id_builder("source", "test_field", "test_v1", "context")

    response = evidence_contract_client.post(
        "/evidence", json=evidence_contract_payload(origin, evidence_id)
    )

    assert response.status_code == 200
    assert response.json()["evidence_id"] == evidence_id


@pytest.mark.parametrize(
    ("origin", "wrong_id_builder"),
    [
        ("ONS_PUBLICO", build_evidence_id),
        ("PROXY_CALCULADO", build_public_evidence_id),
        ("SIMULADO", build_public_evidence_id),
        ("CLIENTE_INFORMADO", build_public_evidence_id),
    ],
)
def test_api_rejects_evidence_id_family_contradicting_origin(origin, wrong_id_builder) -> None:
    evidence_id = wrong_id_builder("source", "test_field", "test_v1", "context")

    response = evidence_contract_client.post(
        "/evidence", json=evidence_contract_payload(origin, evidence_id)
    )

    assert response.status_code == 422
    assert "evidence_id family" in response.text


def test_operation_persistence_stores_one_commit_and_compact_indexes() -> None:
    table = FakeScenariosTable()
    repository = IssuedProvenanceRepository(table)
    ids = [build_evidence_id("a" * 64, f"field-{i}", "bess_screen_v1", "ctx") for i in range(2)]
    repository.put_operation(
        operation="bess_screen",
        request_digest="b" * 64,
        provenances={value: _stored_provenance(value) for value in ids},
        source_records=[{"asset_id": "A", "period": "2026-01", "source_key": "raw/source.parquet"}],
    )
    assert len(table.items) == 5
    operation = next(
        item for item in table.items.values() if item["record_type"] == "provenance_operation"
    )
    assert "request_json" not in operation and "output_json" not in operation
    assert repository.get(ids[0])["provenance"]["evidence_id"] == ids[0]


def _stored_capacity_provenance(evidence_id: str) -> dict:
    return {
        **_stored_provenance(evidence_id),
        "field_name": "capacity_mw",
        "origin": "ONS_PUBLICO",
        "source_uri": "curtailess://ons/capacidade-geracao",
        "source_key": "raw/capacity.parquet",
        "source_sha256": "c" * 64,
        "source_sha256s": ["c" * 64],
        "method_version": "ons_capacity_source_v1",
    }


def _operation_kwargs(shared_id: str, unique_id: str, *, month: str, request_digest: str) -> dict:
    return {
        "operation": "materialize_asset",
        "request_digest": request_digest,
        "provenances": {
            shared_id: _stored_capacity_provenance(shared_id),
            unique_id: _stored_provenance(unique_id),
        },
        "source_records": [
            {
                "asset_id": "A",
                "period": month,
                "source_key": f"raw/{month}.parquet",
                "source_sha256": "a" * 64,
                "capacity_source_key": "raw/capacity.parquet",
                "capacity_source_sha256": "c" * 64,
            }
        ],
    }


def test_unchanged_capacity_evidence_is_reusable_across_july_and_august_operations() -> None:
    table = FakeScenariosTable()
    repository = IssuedProvenanceRepository(table)
    capacity_id = build_public_evidence_id("c" * 64, "capacity_mw", "ons_capacity_source_v1", "A")
    july_id = build_evidence_id("july", "field", "bess_screen_v1", "A:2026-07")
    august_id = build_evidence_id("august", "field", "bess_screen_v1", "A:2026-08")

    repository.put_operation(
        **_operation_kwargs(capacity_id, july_id, month="2026-07", request_digest="7" * 64)
    )
    assert repository.get(july_id) is not None
    repository.put_operation(
        **_operation_kwargs(capacity_id, august_id, month="2026-08", request_digest="8" * 64)
    )

    fresh = IssuedProvenanceRepository(table)
    assert fresh.get(capacity_id) is not None
    assert fresh.get(july_id) is not None
    assert fresh.get(august_id) is not None
    membership_partition = IssuedProvenanceRepository._membership_partition(capacity_id)
    memberships = [key for key in table.items if key[0] == membership_partition]
    assert len(memberships) == 2


@pytest.mark.parametrize("failed_put", range(1, 6))
def test_interrupted_reuse_never_shadows_first_operation_and_retry_recovers(failed_put) -> None:
    table = FakeScenariosTable()
    repository = IssuedProvenanceRepository(table)
    capacity_id = build_public_evidence_id("c" * 64, "capacity_mw", "ons_capacity_source_v1", "A")
    july_id = build_evidence_id("july", "field", "bess_screen_v1", "A:2026-07")
    august_id = build_evidence_id("august", "field", "bess_screen_v1", "A:2026-08")
    repository.put_operation(
        **_operation_kwargs(capacity_id, july_id, month="2026-07", request_digest="7" * 64)
    )

    table.put_count = 0
    table.fail_on_put = failed_put
    with pytest.raises(ClientError):
        repository.put_operation(
            **_operation_kwargs(capacity_id, august_id, month="2026-08", request_digest="8" * 64)
        )
    fresh = IssuedProvenanceRepository(table)
    assert fresh.get(capacity_id) is not None
    assert fresh.get(july_id) is not None
    assert fresh.get(august_id) is None

    table.fail_on_put = None
    repository.put_operation(
        **_operation_kwargs(capacity_id, august_id, month="2026-08", request_digest="8" * 64)
    )
    repository.put_operation(
        **_operation_kwargs(capacity_id, august_id, month="2026-08", request_digest="8" * 64)
    )
    assert IssuedProvenanceRepository(table).get(august_id) is not None


def test_reused_evidence_id_rejects_conflicting_payload_without_harming_first_operation() -> None:
    table = FakeScenariosTable()
    repository = IssuedProvenanceRepository(table)
    evidence_id = build_public_evidence_id("c" * 64, "capacity_mw", "ons_capacity_source_v1", "A")
    first = _operation_kwargs(
        evidence_id,
        build_evidence_id("july", "field", "bess_screen_v1", "A:2026-07"),
        month="2026-07",
        request_digest="7" * 64,
    )
    repository.put_operation(**first)
    conflicting = _stored_capacity_provenance(evidence_id)
    conflicting["limitations"] = ["conflicting immutable payload"]
    before = len(table.items)

    with pytest.raises(RuntimeError, match="immutable record mismatch"):
        repository.put_operation(
            operation="materialize_asset",
            request_digest="8" * 64,
            provenances={evidence_id: conflicting},
            source_records=[{"asset_id": "A", "period": "2026-08"}],
        )

    assert len(table.items) == before
    assert IssuedProvenanceRepository(table).get(evidence_id) is not None


class ConcurrentWinnerTable(FakeScenariosTable):
    def put_item(self, *, Item, ConditionExpression=None) -> dict:
        key = (Item["plant_id"], Item["scenario_id"])
        if ConditionExpression is not None and key not in self.items:
            self.items[key] = copy.deepcopy(Item)
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        return super().put_item(Item=Item, ConditionExpression=ConditionExpression)


def test_simulated_concurrent_duplicate_writer_is_idempotent() -> None:
    table = ConcurrentWinnerTable()
    repository = IssuedProvenanceRepository(table)
    evidence_id = build_public_evidence_id("c" * 64, "capacity_mw", "ons_capacity_source_v1", "A")
    kwargs = {
        "operation": "materialize_asset",
        "request_digest": "7" * 64,
        "provenances": {evidence_id: _stored_capacity_provenance(evidence_id)},
        "source_records": [{"asset_id": "A", "period": "2026-07"}],
    }

    first_id = repository.put_operation(**kwargs)
    second_id = repository.put_operation(**kwargs)

    assert first_id == second_id
    assert IssuedProvenanceRepository(table).get(evidence_id) is not None


@pytest.mark.parametrize(
    ("source_artifacts", "source_records"),
    [
        ([], [{"source_key": "raw/a.parquet", "source_sha256": "a" * 64}]),
        (
            [{"source_key": "raw/a.parquet", "source_sha256": "a" * 64}],
            [{"source_key": "raw/a.parquet", "source_sha256": "a" * 64}],
        ),
        (
            [
                {"source_key": "raw/a.parquet", "source_sha256": "a" * 64},
                {"source_key": "raw/b.parquet", "source_sha256": "b" * 64},
            ],
            [
                {"source_key": "raw/a.parquet", "source_sha256": "a" * 64},
                {"source_key": "raw/tampered.parquet", "source_sha256": "b" * 64},
            ],
        ),
    ],
)
def test_fresh_resolver_rejects_incomplete_or_unresolvable_multi_source_lineage(
    monkeypatch, source_artifacts, source_records
) -> None:
    first_hash, second_hash = "a" * 64, "b" * 64
    evidence_id = build_evidence_id(
        [first_hash, second_hash], "annual_net_benefit_brl", "bess_screen_v1", "ctx"
    )
    provenance = {
        **_stored_provenance(evidence_id),
        "source_key": "raw/a.parquet",
        "source_sha256": first_hash,
        "source_sha256s": [first_hash, second_hash],
        "source_artifacts": source_artifacts,
    }
    table = FakeScenariosTable()
    repository = IssuedProvenanceRepository(table)
    repository.put_operation(
        operation="bess_screen",
        request_digest="c" * 64,
        provenances={evidence_id: provenance},
        source_records=source_records,
    )
    monkeypatch.setattr(main, "issued_provenance_repository", repository)

    assert fresh_api_client().get(f"/v1/provenances/{evidence_id}").status_code == 404


def test_field_provenance_rejects_incomplete_multi_source_mapping() -> None:
    with pytest.raises(ValueError, match="source_artifacts"):
        field_provenance(
            field_name="total_curtailed_energy",
            method_version="curtailed_energy_sum_v1",
            context="ctx",
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=["test"],
            source_hashes=["a" * 64, "b" * 64],
            source_items=[
                {"source_key": "raw/a.parquet", "source_sha256": "a" * 64},
            ],
            source_uri="curtailess://test",
        )


def test_partial_multi_write_is_uncommitted_and_retry_safe() -> None:
    table = FakeScenariosTable()
    repository = IssuedProvenanceRepository(table)
    evidence_id = build_evidence_id("a" * 64, "field", "bess_screen_v1", "ctx")
    kwargs = {
        "operation": "bess_screen",
        "request_digest": "b" * 64,
        "provenances": {evidence_id: _stored_provenance(evidence_id)},
        "source_records": [
            {"asset_id": "A", "period": "2026-01", "source_key": "raw/source.parquet"}
        ],
    }
    table.fail_on_put = 2
    with pytest.raises(ClientError):
        repository.put_operation(**kwargs)
    assert repository.get(evidence_id) is None
    table.fail_on_put = None
    repository.put_operation(**kwargs)
    repository.put_operation(**kwargs)
    assert repository.get(evidence_id) is not None


def test_operation_rejects_conditional_conflict_and_tampered_read() -> None:
    table = FakeScenariosTable()
    repository = IssuedProvenanceRepository(table)
    evidence_id = build_evidence_id("a", "field", "bess_screen_v1", "ctx")
    kwargs = {
        "operation": "bess_screen",
        "request_digest": "b" * 64,
        "provenances": {evidence_id: _stored_provenance(evidence_id)},
        "source_records": [{"asset_id": "A"}],
    }
    operation_id = repository.put_operation(**kwargs)
    operation_key = ("PROVENANCE", f"operation#{operation_id}")
    table.items[operation_key]["provenances"][evidence_id]["field_name"] = "tampered"
    assert repository.get(evidence_id) is None
    with pytest.raises(RuntimeError, match="immutable record mismatch"):
        repository.put_operation(**kwargs)


def _persist_two_member_operation() -> tuple[
    FakeScenariosTable, IssuedProvenanceRepository, list[str], str
]:
    table = FakeScenariosTable()
    repository = IssuedProvenanceRepository(table)
    evidence_ids = [
        build_evidence_id("a", f"field-{index}", "bess_screen_v1", "ctx") for index in range(2)
    ]
    provenances = {value: _stored_provenance(value) for value in evidence_ids}
    provenances[evidence_ids[0]]["parent_evidence_ids"] = [evidence_ids[1]]
    operation_id = repository.put_operation(
        operation="bess_screen",
        request_digest="b" * 64,
        provenances=provenances,
        source_records=[
            {
                "asset_id": "A",
                "source_key": "original",
                "source_sha256": "a" * 64,
                "method": "original_method",
            }
        ],
    )
    return table, repository, evidence_ids, operation_id


@pytest.mark.parametrize(
    "mutate",
    [
        lambda operation, _table, _ids: operation["source_records"][0].__setitem__(
            "source_key", "tampered"
        ),
        lambda operation, _table, _ids: operation["source_records"][0].__setitem__(
            "asset_id", "tampered"
        ),
        lambda operation, _table, _ids: operation["source_records"][0].__setitem__(
            "source_sha256", "f" * 64
        ),
        lambda operation, _table, ids: operation["provenances"][ids[0]].__setitem__(
            "parent_evidence_ids", []
        ),
        lambda operation, _table, ids: operation["provenances"].pop(ids[1]),
        lambda operation, _table, ids: operation["provenances"].__setitem__(
            build_evidence_id("extra", "extra", "bess_screen_v1", "ctx"),
            _stored_provenance(build_evidence_id("extra", "extra", "bess_screen_v1", "ctx")),
        ),
        lambda operation, _table, _ids: operation["source_records"].clear(),
        lambda operation, _table, _ids: operation["source_records"].append(
            {"source_key": "unexpected", "source_sha256": "f" * 64}
        ),
    ],
    ids=[
        "source-key",
        "source-value",
        "source-sha256",
        "lineage",
        "missing-member",
        "extra-member",
        "deleted-source-record",
        "extra-source-record",
    ],
)
def test_fresh_read_rejects_tampered_operation_content(mutate) -> None:
    table, _repository, evidence_ids, operation_id = _persist_two_member_operation()
    operation = table.items[("PROVENANCE", f"operation#{operation_id}")]
    mutate(operation, table, evidence_ids)

    fresh_repository = IssuedProvenanceRepository(table)

    assert fresh_repository.get(evidence_ids[0]) is None


def test_fresh_read_rejects_missing_operation_member_index() -> None:
    table, _repository, evidence_ids, _operation_id = _persist_two_member_operation()
    missing_index_key = IssuedProvenanceRepository._key(evidence_ids[1])
    del table.items[(missing_index_key["plant_id"], missing_index_key["scenario_id"])]

    assert IssuedProvenanceRepository(table).get(evidence_ids[0]) is None


def test_fresh_read_rejects_unexpected_index_content() -> None:
    table, _repository, evidence_ids, _operation_id = _persist_two_member_operation()
    index_key = IssuedProvenanceRepository._key(evidence_ids[0])
    index = table.items[(index_key["plant_id"], index_key["scenario_id"])]
    index["unexpected"] = "tampered"

    assert IssuedProvenanceRepository(table).get(evidence_ids[0]) is None


@pytest.mark.parametrize("mutation", ["missing", "tampered"])
def test_fresh_read_rejects_changed_operation_membership(mutation) -> None:
    table, _repository, evidence_ids, operation_id = _persist_two_member_operation()
    membership_key = IssuedProvenanceRepository._membership_key(evidence_ids[0], operation_id)
    item_key = (membership_key["plant_id"], membership_key["scenario_id"])
    if mutation == "missing":
        del table.items[item_key]
    else:
        table.items[item_key]["provenance_digest"] = "f" * 64

    assert IssuedProvenanceRepository(table).get(evidence_ids[0]) is None


def test_fresh_read_rejects_index_operation_membership_mismatch() -> None:
    table, repository, evidence_ids, operation_id = _persist_two_member_operation()
    other_evidence_id = build_evidence_id("other", "other", "bess_screen_v1", "ctx")
    other_operation_id = repository.put_operation(
        operation="bess_screen",
        request_digest="c" * 64,
        provenances={other_evidence_id: _stored_provenance(other_evidence_id)},
        source_records=[{"source_key": "other", "source_sha256": "c" * 64}],
    )
    index_key = IssuedProvenanceRepository._key(evidence_ids[0])
    index = table.items[(index_key["plant_id"], index_key["scenario_id"])]
    index["operation_id"] = other_operation_id

    assert operation_id != index["operation_id"]
    assert IssuedProvenanceRepository(table).get(evidence_ids[0]) is None


def test_fresh_read_rejects_recomputed_provenance_leaf_digest_after_tampering() -> None:
    table, _repository, evidence_ids, operation_id = _persist_two_member_operation()
    operation = table.items[("PROVENANCE", f"operation#{operation_id}")]
    operation["provenances"][evidence_ids[0]]["field_name"] = "tampered"
    index_key = IssuedProvenanceRepository._key(evidence_ids[0])
    index = table.items[(index_key["plant_id"], index_key["scenario_id"])]
    index["provenance_digest"] = canonical_digest(operation["provenances"][evidence_ids[0]])

    assert IssuedProvenanceRepository(table).get(evidence_ids[0]) is None


def test_operation_item_size_guard_runs_before_dynamodb_write() -> None:
    table = FakeScenariosTable()
    repository = IssuedProvenanceRepository(table)
    evidence_id = build_evidence_id("a", "field", "bess_screen_v1", "ctx")
    oversized = _stored_provenance(evidence_id)
    oversized["limitations"] = ["x" * (351 * 1024)]
    with pytest.raises(ValueError, match="exceeds"):
        repository.put_operation(
            operation="bess_screen",
            request_digest="b" * 64,
            provenances={evidence_id: oversized},
            source_records=[{"asset_id": "A"}],
        )
    assert not table.items


def test_operation_provenance_count_is_capped_before_writes() -> None:
    table = FakeScenariosTable()
    repository = IssuedProvenanceRepository(table)
    ids = [
        build_evidence_id("a", f"field-{index}", "bess_screen_v1", "ctx") for index in range(225)
    ]
    with pytest.raises(ValueError, match="224"):
        repository.put_operation(
            operation="bess_screen",
            request_digest="b" * 64,
            provenances={value: _stored_provenance(value) for value in ids},
            source_records=[{"asset_id": "A"}],
        )
    assert table.put_count == 0


def test_throttling_propagates_without_false_commit() -> None:
    table = FakeScenariosTable()
    table.throttle = True
    evidence_id = build_evidence_id("a", "field", "bess_screen_v1", "ctx")
    with pytest.raises(ClientError):
        IssuedProvenanceRepository(table).put_operation(
            operation="bess_screen",
            request_digest="b" * 64,
            provenances={evidence_id: _stored_provenance(evidence_id)},
            source_records=[{"asset_id": "A"}],
        )
    assert not table.items


def fresh_api_client() -> TestClient:
    fresh_app = FastAPI()
    fresh_app.router.routes.extend(
        route for route in app.router.routes if getattr(route, "path", "").startswith("/v1")
    )
    return TestClient(fresh_app)


def client_provenance(field_name: str) -> dict:
    return {
        "evidence_id": build_evidence_id("client", field_name, "client_input_v1", field_name),
        "field_name": field_name,
        "origin": "CLIENTE_INFORMADO",
        "source_uri": f"client://scenario/{field_name}",
        "source_key": None,
        "source_sha256": None,
        "source_sha256s": [],
        "observed_at": None,
        "effective_at": "2026-08-01T00:00:00Z",
        "valid_from": None,
        "valid_to": None,
        "method_version": "client_input_v1",
        "limitations": ["Valor informado pelo cliente para o cenário."],
    }


def energy_price_payload(value: float = 250) -> dict:
    return {
        "value": value,
        "unit": "BRL/MWh",
        "source": "client_scenario",
        "value_status": "informado",
        "origin": "CLIENTE_INFORMADO",
        "provenance": client_provenance("energy_price"),
    }


def maintenance_input_provenance() -> dict:
    return {
        field_name: client_provenance(field_name)
        for field_name in (
            "asset_id",
            "start",
            "end",
            "duration_hours",
            "minimum_notice_hours",
            "baseline_window_start",
            "weekdays_only",
            "unavailable_periods",
            "energy_price",
        )
    }


def bess_input_provenance() -> dict:
    return {
        field_name: client_provenance(field_name)
        for field_name in (
            "asset_id",
            "maintenance_result_id",
            "power_mw",
            "energy_mwh",
            "capex_brl",
            "annualized_cost_brl",
            "round_trip_efficiency",
            "cycles_per_year",
            "energy_price_brl_mwh",
        )
    }


MATERIALIZED_ITEM = {
    "asset_id": "CJU_BAOUR",
    "period": "2026-08",
    "asset_name": "Conj. Ourolândia II",
    "point_id": "BAOUR-500-A",
    "point_name": "OUROLANDIA II500kVA",
    "state": "BA",
    "period_start": "2026-08-01T00:00:00",
    "period_end": "2026-08-31T23:30:00",
    "curtailed_mwh": 23968.0945,
    "source_key": "raw/ons/restricao_coff_eolica_tm/source_year=2026/source_month=08/file.parquet",
    "source_sha256": "45fa63e984245c17862bf8cc028437311ee7e1ca8a7cd0a6550226432ccbe2fa",
    "method": "sum(apurada * 0.5) when val_geracaolimitada is not null",
}


def historical_window(
    source_record: dict,
    *,
    start: main.datetime,
    curtailed_mwh: float,
    duration_hours: int = 72,
    reason: str | None = None,
) -> dict:
    source_record = {
        **source_record,
        "period_start": start.replace(tzinfo=None).isoformat(),
        "interval_count": duration_hours * 2,
        "curtailed_mwh": curtailed_mwh,
        **({"curtailed_mwh_by_reason": {reason: curtailed_mwh}} if reason else {}),
    }
    method = (
        "monthly_observed_reason_rate_prorated_to_window_v1"
        if reason
        else "monthly_observed_rate_prorated_to_window_v1"
    )
    return {
        "start": start,
        "end": start + timedelta(hours=duration_hours),
        "curtailed_mwh": curtailed_mwh,
        "period": source_record["period"],
        "source_key": source_record["source_key"],
        "source_sha256": source_record["source_sha256"],
        "method": method,
        "source_record": source_record,
    }


def mixed_point_context_records() -> list[dict]:
    return [
        {**MATERIALIZED_ITEM, "limited_interval_count": 0},
        {
            **MATERIALIZED_ITEM,
            "asset_id": "CJU_SOLAR_PEER",
            "asset_name": "Solar peer",
            "limited_interval_count": 4,
            "source_key": (
                "raw/ons/restricao_coff_fotovoltaica_tm/"
                "source_year=2026/source_month=08/file.parquet"
            ),
            "source_sha256": "b" * 64,
            "method": "count constrained-off photovoltaic intervals",
        },
    ]


def test_api_info() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "name": "CurtaiLess API",
        "version": "0.1.0",
        "environment": "local",
        "docs": "/docs",
    }


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "CurtaiLess API",
        "version": "0.1.0",
        "environment": "local",
    }


def test_cors_preflight() -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_list_assets_returns_materialized_ons_assets(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "list_assets", lambda: [MATERIALIZED_ITEM])

    response = client.get("/v1/assets")

    assert response.status_code == 200
    payload = response.json()["items"][0]
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["name"] == "Conj. Ourolândia II"
    assert payload["technology"] == "wind"
    assert payload["capacity_mw"] is None
    assert payload["capacity_provenance"] is None
    assert payload["ons_group"] == "CJU_BAOUR"
    assert payload["connection_point"] == "BAOUR-500-A"
    assert payload["data_mode"] == "ons_materialized"
    assert set(payload["field_provenance"]) == {
        "asset_id",
        "name",
        "technology",
        "capacity_mw",
        "ons_group",
        "connection_point",
    }


def test_get_asset_returns_materialized_ons_asset(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)

    response = client.get("/v1/assets/CJU_BAOUR")

    assert response.status_code == 200
    assert response.json()["asset_id"] == "CJU_BAOUR"
    assert response.json()["data_mode"] == "ons_materialized"


def test_get_asset_capacity_has_public_field_level_provenance(monkeypatch) -> None:
    capacity_hash = "b" * 64
    item = {
        **MATERIALIZED_ITEM,
        "capacity_mw": 87.5,
        "capacity_source_key": "dataset/capacidade-geracao/CAPACIDADE_GERACAO.parquet",
        "capacity_source_sha256": capacity_hash,
        "capacity_method_version": "ons_capacity_source_v1",
    }
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: item)

    response = client.get("/v1/assets/CJU_BAOUR")

    assert response.status_code == 200
    payload = response.json()
    assert payload["capacity_mw"] == 87.5
    provenance = payload["capacity_provenance"]
    assert provenance["origin"] == "ONS_PUBLICO"
    assert provenance["field_name"] == "capacity_mw"
    assert provenance["source_sha256"] == capacity_hash
    assert provenance["source_key"].endswith("CAPACIDADE_GERACAO.parquet")
    assert provenance["observed_at"] is None
    assert provenance["valid_from"] is None
    assert provenance["valid_to"] is None
    assert provenance["temporal_coverage"] == "unknown"
    assert "temporal" in " ".join(provenance["limitations"]).lower()
    assert set(payload["field_provenance"]) == {
        "asset_id",
        "name",
        "technology",
        "capacity_mw",
        "ons_group",
        "connection_point",
    }
    assert all(
        value["field_name"] == field_name
        for field_name, value in payload["field_provenance"].items()
    )


def test_get_asset_exposure_returns_materialized_ons_values(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_exposure",
        lambda asset_id, start, end, reason=None: {
            "curtailed_mwh": 23968.0945,
            "periods": ["2026-08"],
            "source_sha256s": [MATERIALIZED_ITEM["source_sha256"]],
            "items": [MATERIALIZED_ITEM],
        },
    )

    response = client.get(
        "/v1/assets/CJU_BAOUR/exposure",
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["perspective_type"] == "historical_observed"
    assert payload["data_mode"] == "ons_materialized"
    assert payload["total_curtailed_energy"]["value"] == 23968.0945
    assert payload["total_curtailed_energy"]["unit"] == "MWh"
    assert payload["total_curtailed_energy"]["value_status"] == "calculado"
    assert payload["total_curtailed_energy"]["origin"] == "PROXY_CALCULADO"
    assert payload["total_curtailed_energy"]["data_version"] == "2026-08"
    evidence = payload["total_curtailed_energy"]
    assert evidence["source"] == "ONS/restricao_coff_eolica_tm"
    assert evidence["provenance_id"].startswith("evd1.")
    assert evidence["provenance_id"] == evidence["provenance"]["evidence_id"]
    assert evidence["provenance"]["field_name"] == "total_curtailed_energy"
    assert evidence["provenance"]["source_sha256s"] == [MATERIALIZED_ITEM["source_sha256"]]
    assert evidence["provenance"]["observed_at"] == "2026-08-31T23:30:00Z"
    assert evidence["provenance"]["effective_at"] == "2026-08-31T23:30:00Z"
    assert evidence["provenance"]["valid_from"] == "2026-08-01T00:00:00Z"
    assert evidence["provenance"]["valid_to"] == "2026-08-31T23:59:59.999999Z"
    assert evidence["provenance"]["method_version"] == "curtailed_energy_sum_v1"
    assert evidence["provenance"]["limitations"]
    assert "materializado" in " ".join(payload["limitations"]).lower()


def test_multi_source_exposure_preserves_key_hash_pairs_and_is_order_invariant(
    monkeypatch, issued_provenance_table
) -> None:
    hashes = {"2026-01": "f" * 64, "2026-02": "8" * 64, "2026-03": "0" * 64}
    items = [
        {
            **MATERIALIZED_ITEM,
            "period": period,
            "period_start": f"{period}-01T00:00:00",
            "period_end": f"{period}-28T23:30:00",
            "source_key": f"raw/ons/restricao/source_month={period[-2:]}/file.parquet",
            "source_sha256": source_hash,
        }
        for period, source_hash in hashes.items()
    ]

    def exposure(source_items):
        return {
            "curtailed_mwh": 30.0,
            "periods": sorted(hashes),
            "source_sha256s": [item["source_sha256"] for item in source_items],
            "items": source_items,
        }

    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_exposure",
        lambda asset_id, start, end, reason=None: exposure(items),
    )
    first = client.get(
        "/v1/assets/CJU_BAOUR/exposure",
        params={"start": "2026-01-01", "end": "2026-03-31"},
    )
    assert first.status_code == 200
    first_provenance = first.json()["total_curtailed_energy"]["provenance"]
    expected_artifacts = [
        {"source_key": item["source_key"], "source_sha256": item["source_sha256"]} for item in items
    ]
    assert first_provenance["source_artifacts"] == expected_artifacts
    assert first_provenance["source_key"] == items[0]["source_key"]
    assert first_provenance["source_sha256"] == items[0]["source_sha256"]

    monkeypatch.setattr(
        main.repository,
        "get_exposure",
        lambda asset_id, start, end, reason=None: exposure([*reversed(items), items[1]]),
    )
    duplicate = client.get(
        "/v1/assets/CJU_BAOUR/exposure",
        params={"start": "2026-01-01", "end": "2026-03-31"},
    )
    assert duplicate.status_code == 200
    duplicate_provenance = duplicate.json()["total_curtailed_energy"]["provenance"]
    assert duplicate_provenance == first_provenance

    fresh_client = fresh_api_client()
    resolved = fresh_client.get(f"/v1/provenances/{first_provenance['evidence_id']}")
    assert resolved.status_code == 200
    assert resolved.json()["provenance"]["source_artifacts"] == expected_artifacts
    assert resolved.json()["source_key"] == items[0]["source_key"]
    assert resolved.json()["source_sha256"] == items[0]["source_sha256"]

    operation = next(
        item
        for item in issued_provenance_table.items.values()
        if item["record_type"] == "provenance_operation"
        and first_provenance["evidence_id"] in item["provenances"]
    )
    operation["provenances"][first_provenance["evidence_id"]]["source_artifacts"][0][
        "source_sha256"
    ] = "1" * 64
    assert fresh_client.get(f"/v1/provenances/{first_provenance['evidence_id']}").status_code == 404


def test_get_asset_exposure_filters_materialized_reason(monkeypatch) -> None:
    item = {
        **MATERIALIZED_ITEM,
        "curtailed_mwh_by_reason": {"ENE": 120.5, "REL": 80.0, "CNF": 10.0, "NC": 2.0},
    }
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: item)
    monkeypatch.setattr(
        main.repository,
        "get_exposure",
        lambda asset_id, start, end, reason=None: {
            "curtailed_mwh": 120.5,
            "periods": ["2026-08"],
            "source_sha256s": [MATERIALIZED_ITEM["source_sha256"]],
            "items": [item],
        },
    )

    response = client.get(
        "/v1/assets/CJU_BAOUR/exposure",
        params={
            "start": "2026-08-01",
            "end": "2026-08-31",
            "granularity": "period",
            "reason": "ENE",
            "technology": "wind",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["reason"] == "ENE"
    assert payload["granularity"] == "period"
    assert payload["total_curtailed_energy"]["value"] == 120.5


def test_get_asset_exposure_rejects_unmaterialized_granularity(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)

    response = client.get(
        "/v1/assets/CJU_BAOUR/exposure",
        params={"start": "2026-08-01", "end": "2026-08-31", "granularity": "hour"},
    )

    assert response.status_code == 422
    assert "granularity=period" in response.json()["detail"]


def test_get_asset_exposure_rejects_inverted_period() -> None:
    response = client.get(
        "/v1/assets/demo-wind-ne-001/exposure",
        params={"start": "2026-09-01", "end": "2026-08-01"},
    )

    assert response.status_code == 422


def test_get_unknown_asset_returns_not_found() -> None:
    response = client.get("/v1/assets/unknown")

    assert response.status_code == 404


def test_get_data_quality_returns_materialized_coverage(monkeypatch) -> None:
    item = {**MATERIALIZED_ITEM, "interval_count": 1488, "limited_interval_count": 296}
    monkeypatch.setattr(main.repository, "get_data_quality", lambda asset_id: item)

    response = client.get("/v1/data-quality/CJU_BAOUR")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["validation_status"] == "valid"
    assert payload["coverage_percent"] == 100.0
    assert payload["observed_interval_count"] == 1488
    assert payload["expected_interval_count"] == 1488
    assert payload["null_count"] is None
    assert payload["duplicate_count"] is None
    assert payload["source_sha256"] == MATERIALIZED_ITEM["source_sha256"]
    assert "não materializadas" in " ".join(payload["limitations"]).lower()


def test_get_provenance_returns_source_lineage(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_provenance",
        lambda source_sha256: MATERIALIZED_ITEM,
    )
    monkeypatch.setattr(
        main.repository,
        "get_exposure",
        lambda asset_id, start, end, reason=None: {
            "curtailed_mwh": MATERIALIZED_ITEM["curtailed_mwh"],
            "periods": [MATERIALIZED_ITEM["period"]],
            "source_sha256s": [MATERIALIZED_ITEM["source_sha256"]],
            "items": [MATERIALIZED_ITEM],
        },
    )

    emitted = client.get(
        "/v1/assets/CJU_BAOUR/exposure",
        params={"start": "2026-08-01", "end": "2026-08-31"},
    )
    assert emitted.status_code == 200
    evidence_id = emitted.json()["total_curtailed_energy"]["provenance_id"]
    response = client.get(f"/v1/provenances/{evidence_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["provenance_id"] == evidence_id
    assert payload["classification"] == "calculado"
    assert payload["source"] == "ONS/restricao_coff_eolica_tm"
    assert payload["source_key"] == MATERIALIZED_ITEM["source_key"]
    assert payload["source_sha256"] == MATERIALIZED_ITEM["source_sha256"]
    assert payload["source_sha256s"] == [MATERIALIZED_ITEM["source_sha256"]]
    assert payload["method"] == MATERIALIZED_ITEM["method"]
    assert payload["origin"] == "PROXY_CALCULADO"
    assert payload["evidence_id"] == payload["provenance_id"]
    assert payload["method_version"] == "curtailed_energy_sum_v1"
    assert payload["field_name"] == "total_curtailed_energy"
    assert payload["provenance"]["evidence_id"] == evidence_id
    assert payload["valid_from"] == "2026-08-01T00:00:00Z"
    assert payload["valid_to"] == "2026-08-31T23:59:59.999999Z"
    assert payload["asset_ids"] == ["CJU_BAOUR"]


@pytest.mark.parametrize(
    ("field_name", "method_version"),
    [
        ("forged_public_measurement", "curtailed_energy_sum_v1"),
        ("total_curtailed_energy", "forged_method_v99"),
        ("simulated_plant_state", "simulation_v1"),
        ("energy_price", "client_input_v1"),
    ],
)
def test_get_provenance_rejects_forged_or_non_server_contracts(
    monkeypatch, field_name, method_version
) -> None:
    monkeypatch.setattr(main.repository, "get_provenance", lambda source_sha256: MATERIALIZED_ITEM)
    forged_id = main.build_evidence_id(
        MATERIALIZED_ITEM["source_sha256"],
        field_name,
        method_version,
        "caller-controlled-context",
    )

    response = client.get(f"/v1/provenances/{forged_id}")

    assert response.status_code == 404


def test_get_provenance_rejects_valid_hash_id_for_non_emitted_context(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_provenance", lambda source_sha256: MATERIALIZED_ITEM)
    forged_id = main.build_evidence_id(
        MATERIALIZED_ITEM["source_sha256"],
        "total_curtailed_energy",
        "curtailed_energy_sum_v1",
        "CJU_BAOUR:1900-01-01:1900-01-31:all",
    )

    response = client.get(f"/v1/provenances/{forged_id}")

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("field_name", "method_version", "context"),
    [
        (
            "expected_curtailed_energy",
            "monthly_observed_rate_prorated_to_window_v1",
            main._json_context(
                "maintenance_rank",
                asset_id="CJU_BAOUR",
                candidate_start="2026-08-01T00:00:00+00:00",
                candidate_end="2026-08-04T00:00:00+00:00",
                baseline_start="2026-08-15T00:00:00+00:00",
                request_start="2026-08-01",
                request_end="2026-08-31",
                input_evidence_ids={"energy_price": "client:forged"},
            ),
        ),
        (
            "annual_net_benefit_brl",
            "bess_screen_v1",
            main._json_context(
                "bess_screen",
                asset_id="CJU_BAOUR",
                maintenance_result_id="forged",
                parent_evidence_ids=["client:forged"],
                inputs={"energy_mwh": 80},
            ),
        ),
    ],
)
def test_get_provenance_rejects_valid_hash_unissued_derived_evidence(
    field_name, method_version, context
) -> None:
    forged_id = main.build_evidence_id(
        MATERIALIZED_ITEM["source_sha256"], field_name, method_version, context
    )

    response = client.get(f"/v1/provenances/{forged_id}")

    assert response.status_code == 404


def test_get_provenance_rejects_arbitrary_dataset_and_context_pairing(monkeypatch) -> None:
    item = {
        **MATERIALIZED_ITEM,
        "capacity_mw": 87.5,
        "capacity_source_key": "dataset/capacidade-geracao/CAPACIDADE_GERACAO.parquet",
        "capacity_source_sha256": "b" * 64,
    }
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: item)
    monkeypatch.setattr(main.repository, "get_provenance", lambda source_sha256: item)
    forged_id = main.build_evidence_id(
        MATERIALIZED_ITEM["source_sha256"],
        "capacity_mw",
        "ons_capacity_source_v1",
        "CJU_BAOUR",
    )

    response = client.get(f"/v1/provenances/{forged_id}")

    assert response.status_code == 404


def test_capacity_provenance_resolves_capacity_dataset_without_borrowed_dates(monkeypatch) -> None:
    capacity_hash = "b" * 64
    item = {
        **MATERIALIZED_ITEM,
        "capacity_mw": 87.5,
        "capacity_source_key": "dataset/capacidade-geracao/CAPACIDADE_GERACAO.parquet",
        "capacity_source_sha256": capacity_hash,
    }
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: item)
    monkeypatch.setattr(main.repository, "get_provenance", lambda source_sha256: item)
    emitted = client.get("/v1/assets/CJU_BAOUR").json()["capacity_provenance"]

    response = client.get(f"/v1/provenances/{emitted['evidence_id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["dataset"] == "capacidade-geracao"
    assert payload["source"] == "ONS/capacidade-geracao"
    assert payload["source_key"] == item["capacity_source_key"]
    assert payload["source_sha256"] == capacity_hash
    assert payload["valid_from"] is None
    assert payload["valid_to"] is None


def test_get_point_context_uses_exact_mixed_constrained_off_lineage(
    monkeypatch, issued_provenance_table
) -> None:
    records = mixed_point_context_records()
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: records[0])
    monkeypatch.setattr(
        main.repository,
        "get_point_context",
        lambda asset_id, asset=None: {
            "connection_point": "point-" + MATERIALIZED_ITEM["source_sha256"][:12],
            "entity_count": 2,
            "limited_entity_count": 1,
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "data_version": "2026-08",
            "source_sha256s": sorted(record["source_sha256"] for record in records),
            "items": records,
        },
    )

    response = client.get("/v1/assets/CJU_BAOUR/point-context")

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["data_mode"] == "ons_materialized"
    assert payload["connection_point"].startswith("point-")
    assert payload["anonymized_entity_count"]["value"] == 2
    assert payload["anonymized_entity_count"]["unit"] == "entities"
    assert payload["simultaneity_rate"]["value"] == 50.0
    assert payload["simultaneity_rate"]["unit"] == "%"
    assert payload["physical_limit_available"] is False
    entity_evidence = payload["anonymized_entity_count"]
    rate_evidence = payload["simultaneity_rate"]
    assert entity_evidence["source"] == (
        "ONS/restricao_coff_eolica_tm + ONS/restricao_coff_fotovoltaica_tm"
    )
    assert entity_evidence["method"] == "distinct_latest_constrained_off_assets_at_point_v1"
    assert entity_evidence["value_status"] == "calculado"
    assert entity_evidence["origin"] == "PROXY_CALCULADO"
    expected_artifacts = [
        {"source_key": record["source_key"], "source_sha256": record["source_sha256"]}
        for record in records
    ]
    assert entity_evidence["provenance"]["source_artifacts"] == expected_artifacts
    assert entity_evidence["provenance_id"] != rate_evidence["provenance_id"]
    assert entity_evidence["provenance"]["field_name"] == "anonymized_entity_count"
    assert rate_evidence["provenance"]["field_name"] == "simultaneity_rate"
    operation = next(
        item
        for item in issued_provenance_table.items.values()
        if item["record_type"] == "provenance_operation"
    )
    lineage_fields = {
        "asset_id",
        "period",
        "point_id",
        "period_start",
        "period_end",
        "limited_interval_count",
        "source_key",
        "source_sha256",
        "method",
    }
    assert operation["source_records"] == [
        {key: value for key, value in record.items() if key in lineage_fields} for record in records
    ]

    monkeypatch.setattr(
        main,
        "issued_provenance_repository",
        IssuedProvenanceRepository(issued_provenance_table),
    )
    fresh_client = fresh_api_client()
    resolved = fresh_client.get(f"/v1/provenances/{entity_evidence['provenance_id']}")
    assert resolved.status_code == 200
    assert resolved.json()["provenance"] == entity_evidence["provenance"]
    assert resolved.json()["source_sha256s"] == entity_evidence["provenance"]["source_sha256s"]
    assert resolved.json()["dataset"] == (
        "restricao_coff_eolica_tm + restricao_coff_fotovoltaica_tm"
    )
    assert resolved.json()["source"] == entity_evidence["source"]
    assert resolved.json()["method"] == entity_evidence["method"]
    assert "usina_conjunto" not in json.dumps(payload)
    assert "nomes" in " ".join(payload["limitations"]).lower()
    assert "entities" not in payload


@pytest.mark.parametrize("mutation", ["missing", "tampered"])
def test_point_context_fresh_resolution_rejects_changed_source_member(
    monkeypatch, issued_provenance_table, mutation
) -> None:
    records = mixed_point_context_records()
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: records[0])
    monkeypatch.setattr(
        main.repository,
        "get_point_context",
        lambda asset_id, asset=None: {
            "connection_point": "point-test",
            "entity_count": 2,
            "limited_entity_count": 1,
            "period_start": "2026-08-01",
            "period_end": "2026-08-31",
            "data_version": "2026-08",
            "source_sha256s": sorted(record["source_sha256"] for record in records),
            "items": records,
        },
    )
    response = client.get("/v1/assets/CJU_BAOUR/point-context")
    evidence_id = response.json()["anonymized_entity_count"]["provenance_id"]
    operation = next(
        item
        for item in issued_provenance_table.items.values()
        if item["record_type"] == "provenance_operation"
    )
    if mutation == "missing":
        operation["source_records"].pop()
    else:
        operation["source_records"][1]["source_key"] = "tampered.parquet"

    monkeypatch.setattr(
        main,
        "issued_provenance_repository",
        IssuedProvenanceRepository(issued_provenance_table),
    )
    assert fresh_api_client().get(f"/v1/provenances/{evidence_id}").status_code == 404


def test_get_historical_windows_uses_materialized_monthly_signal(monkeypatch) -> None:
    item = {**MATERIALIZED_ITEM, "interval_count": 1488}
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: item)
    monkeypatch.setattr(
        main.repository,
        "get_historical_windows",
        lambda asset_id, start, end, duration_hours, reason=None: [
            historical_window(
                item,
                start=main.datetime(2026, 8, 1, tzinfo=main.UTC),
                curtailed_mwh=2319.493016,
            )
        ],
    )

    response = client.get(
        "/v1/assets/CJU_BAOUR/windows",
        params={
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["perspective_type"] == "historical_seasonal"
    assert payload["validation_status"] == "historical_signal"
    assert payload["data_mode"] == "ons_materialized"
    assert payload["duration_hours"] == 72
    assert len(payload["windows"]) == 1
    assert payload["windows"][0]["expected_curtailed_energy"]["value"] == 2319.493016
    assert payload["windows"][0]["expected_curtailed_energy"]["value_status"] == "calculado"
    assert "não é previsão" in " ".join(payload["limitations"]).lower()


def test_historical_windows_preserve_each_period_source_and_restart_resolution(
    monkeypatch, issued_provenance_table
) -> None:
    august = {
        **MATERIALIZED_ITEM,
        "period": "2026-08",
        "source_key": "raw/ons/2026/08/august.parquet",
        "source_sha256": "1" * 64,
    }
    september = {
        **MATERIALIZED_ITEM,
        "period": "2026-09",
        "source_key": "raw/ons/2026/09/september.parquet",
        "source_sha256": "2" * 64,
        "period_end": "2026-09-30T23:30:00",
    }
    candidates = [
        historical_window(
            august, start=main.datetime(2026, 8, 1, tzinfo=main.UTC), curtailed_mwh=10.0
        ),
        historical_window(
            september, start=main.datetime(2026, 9, 1, tzinfo=main.UTC), curtailed_mwh=20.0
        ),
    ]
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: september)
    monkeypatch.setattr(
        main.repository, "get_historical_windows", lambda *args, **kwargs: candidates
    )

    response = client.get(
        "/v1/assets/CJU_BAOUR/windows",
        params={"start": "2026-08-01", "end": "2026-09-29", "duration_hours": 72},
    )

    assert response.status_code == 200
    windows = response.json()["windows"]
    assert [
        (
            window["expected_curtailed_energy"]["provenance"]["source_key"],
            window["expected_curtailed_energy"]["provenance"]["source_sha256"],
        )
        for window in windows
    ] == [
        (august["source_key"], august["source_sha256"]),
        (september["source_key"], september["source_sha256"]),
    ]
    operation = next(
        item
        for item in issued_provenance_table.items.values()
        if item["record_type"] == "provenance_operation"
    )
    assert {record["period"] for record in operation["source_records"]} == {
        "2026-08",
        "2026-09",
    }
    assert all(
        "curtailed_mwh" in record and "interval_count" in record
        for record in operation["source_records"]
    )

    monkeypatch.setattr(
        main,
        "issued_provenance_repository",
        IssuedProvenanceRepository(issued_provenance_table),
    )
    fresh_client = fresh_api_client()
    for window in windows:
        evidence_id = window["expected_curtailed_energy"]["provenance_id"]
        assert fresh_client.get(f"/v1/provenances/{evidence_id}").status_code == 200


def test_get_asset_windows_passes_reason_filter(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    captured = {}

    def fake_windows(asset_id, start, end, duration_hours, reason=None):
        captured["reason"] = reason
        return [
            historical_window(
                MATERIALIZED_ITEM,
                start=main.datetime(2026, 8, 1, tzinfo=main.UTC),
                curtailed_mwh=12.5,
                reason=reason,
            )
        ]

    monkeypatch.setattr(main.repository, "get_historical_windows", fake_windows)

    response = client.get(
        "/v1/assets/CJU_BAOUR/windows",
        params={
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
            "reason": "REL",
        },
    )

    assert response.status_code == 200
    assert captured["reason"] == "REL"
    assert response.json()["reason"] == "REL"


def test_get_historical_windows_rejects_non_positive_duration() -> None:
    response = client.get(
        "/v1/assets/demo-wind-ne-001/windows",
        params={
            "start": "2026-10-01",
            "end": "2026-10-30",
            "duration_hours": 0,
        },
    )

    assert response.status_code == 422


def test_get_historical_windows_rejects_inverted_period() -> None:
    response = client.get(
        "/v1/assets/demo-wind-ne-001/windows",
        params={
            "start": "2026-10-30",
            "end": "2026-10-01",
            "duration_hours": 72,
        },
    )

    assert response.status_code == 422


def test_rank_maintenance_uses_materialized_ons_historical_windows(
    monkeypatch, issued_provenance_table
) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_historical_windows",
        lambda asset_id, start, end, duration_hours: [
            historical_window(
                MATERIALIZED_ITEM,
                start=main.datetime(2026, 8, 1, tzinfo=main.UTC),
                curtailed_mwh=20.0,
            ),
            historical_window(
                MATERIALIZED_ITEM,
                start=main.datetime(2026, 8, 15, tzinfo=main.UTC),
                curtailed_mwh=8.0,
            ),
        ],
    )

    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "CJU_BAOUR",
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-08-15T00:00:00Z",
            "constraints": {
                "weekdays_only": False,
                "unavailable_periods": [],
            },
            "energy_price": energy_price_payload(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["ranking_mode"] == "historical_prototype"
    assert payload["data_mode"] == "ons_materialized"
    assert payload["baseline_window_start"] == "2026-08-15T00:00:00Z"
    assert [item["expected_curtailed_energy"]["value"] for item in payload["ranked_windows"]] == [
        20.0,
        8.0,
    ]
    assert payload["ranked_windows"][0]["opportunity_cost"]["value"] == 5000.0
    evidence = payload["ranked_windows"][0]["expected_curtailed_energy"]
    assert evidence["value_status"] == "calculado"
    assert evidence["origin"] == "PROXY_CALCULADO"
    window = payload["ranked_windows"][0]
    assert window["opportunity_cost"]["origin"] == "PROXY_CALCULADO"
    assert evidence["source"] == "ONS/restricao_coff_eolica_tm"
    assert evidence["provenance_id"].startswith("evd1.")
    assert window["difference_from_baseline"]["value"] == 12.0
    assert window["difference_from_baseline"]["provenance"]["field_name"] == (
        "difference_from_baseline"
    )
    ids = {
        evidence["provenance_id"],
        window["opportunity_cost"]["provenance_id"],
        window["difference_from_baseline"]["provenance_id"],
    }
    assert len(ids) == 3
    assert set(payload["input_provenance"]) == {
        "asset_id",
        "start",
        "end",
        "duration_hours",
        "minimum_notice_hours",
        "baseline_window_start",
        "weekdays_only",
        "unavailable_periods",
        "energy_price",
    }
    assert all(
        provenance["field_name"] == field_name
        for field_name, provenance in payload["input_provenance"].items()
    )
    assert set(window["field_provenance"]) == {
        "rank",
        "start",
        "end",
        "expected_curtailed_energy",
        "opportunity_cost",
        "difference_from_baseline_mwh",
        "difference_from_baseline",
    }
    assert all(
        provenance["field_name"] == field_name
        for field_name, provenance in window["field_provenance"].items()
    )
    cost_parents = set(window["opportunity_cost"]["provenance"]["parent_evidence_ids"])
    assert cost_parents == {
        window["expected_curtailed_energy"]["provenance_id"],
        payload["input_provenance"]["energy_price"]["evidence_id"],
    }
    assert len(issued_provenance_table.items) == 29
    operation = next(
        item
        for item in issued_provenance_table.items.values()
        if item["record_type"] == "provenance_operation"
    )
    assert (
        operation["request_digest"]
        and "request_json" not in operation
        and "output_json" not in operation
    )
    monkeypatch.setattr(
        main,
        "issued_provenance_repository",
        IssuedProvenanceRepository(issued_provenance_table),
    )
    fresh_client = fresh_api_client()
    for ranked_window in payload["ranked_windows"]:
        for field_name, provenance in ranked_window["field_provenance"].items():
            resolved = fresh_client.get(f"/v1/provenances/{provenance['evidence_id']}")
            assert resolved.status_code == 200
            assert resolved.json()["field_name"] == field_name
            assert resolved.json()["parent_evidence_ids"] == provenance["parent_evidence_ids"]
            assert resolved.json()["provenance"] == provenance
    assert "não é previsão" in " ".join(payload["limitations"]).lower()


def test_rank_maintenance_preserves_multi_month_sources_and_rejects_tampering(
    monkeypatch, issued_provenance_table
) -> None:
    august = {
        **MATERIALIZED_ITEM,
        "source_key": "raw/ons/2026/08/august.parquet",
        "source_sha256": "3" * 64,
    }
    september = {
        **MATERIALIZED_ITEM,
        "period": "2026-09",
        "period_end": "2026-09-30T23:30:00",
        "source_key": "raw/ons/2026/09/september.parquet",
        "source_sha256": "4" * 64,
    }
    candidates = [
        historical_window(
            august, start=main.datetime(2026, 8, 1, tzinfo=main.UTC), curtailed_mwh=10.0
        ),
        historical_window(
            september, start=main.datetime(2026, 9, 1, tzinfo=main.UTC), curtailed_mwh=20.0
        ),
    ]
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: september)
    monkeypatch.setattr(
        main.repository, "get_historical_windows", lambda *args, **kwargs: candidates
    )

    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "CJU_BAOUR",
            "start": "2026-08-01",
            "end": "2026-09-29",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-09-01T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(),
        },
    )

    assert response.status_code == 200
    ranked = response.json()["ranked_windows"]
    august_ranked = next(item for item in ranked if item["start"].startswith("2026-08"))
    difference = august_ranked["difference_from_baseline"]["provenance"]
    assert {
        (item["source_key"], item["source_sha256"]) for item in difference["source_artifacts"]
    } == {
        (august["source_key"], august["source_sha256"]),
        (september["source_key"], september["source_sha256"]),
    }
    operation = next(
        item
        for item in issued_provenance_table.items.values()
        if item["record_type"] == "provenance_operation"
    )
    assert {record["period"] for record in operation["source_records"]} == {
        "2026-08",
        "2026-09",
    }

    monkeypatch.setattr(
        main,
        "issued_provenance_repository",
        IssuedProvenanceRepository(issued_provenance_table),
    )
    evidence_id = august_ranked["expected_curtailed_energy"]["provenance_id"]
    assert fresh_api_client().get(f"/v1/provenances/{evidence_id}").status_code == 200
    operation["source_records"][0]["curtailed_mwh"] += 1
    assert fresh_api_client().get(f"/v1/provenances/{evidence_id}").status_code == 404


def test_rank_maintenance_same_hash_periods_keep_both_source_records(
    monkeypatch, issued_provenance_table
) -> None:
    shared = {
        **MATERIALIZED_ITEM,
        "source_key": "raw/ons/shared.parquet",
        "source_sha256": "5" * 64,
    }
    september = {**shared, "period": "2026-09", "period_end": "2026-09-30T23:30:00"}
    candidates = [
        historical_window(
            shared, start=main.datetime(2026, 8, 1, tzinfo=main.UTC), curtailed_mwh=10.0
        ),
        historical_window(
            september, start=main.datetime(2026, 9, 1, tzinfo=main.UTC), curtailed_mwh=20.0
        ),
    ]
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: september)
    monkeypatch.setattr(
        main.repository, "get_historical_windows", lambda *args, **kwargs: candidates
    )

    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "CJU_BAOUR",
            "start": "2026-08-01",
            "end": "2026-09-29",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-09-01T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(),
        },
    )

    assert response.status_code == 200
    operation = next(
        item
        for item in issued_provenance_table.items.values()
        if item["record_type"] == "provenance_operation"
    )
    assert [record["period"] for record in operation["source_records"]] == [
        "2026-08",
        "2026-09",
    ]
    for ranked in response.json()["ranked_windows"]:
        evidence_id = ranked["expected_curtailed_energy"]["provenance_id"]
        assert client.get(f"/v1/provenances/{evidence_id}").status_code == 200


@pytest.mark.parametrize("mutation", ["missing", "key_mismatch", "value_mismatch"])
@pytest.mark.parametrize("endpoint", ["windows", "maintenance"])
def test_historical_endpoints_reject_incomplete_or_mismatched_lineage(
    monkeypatch, issued_provenance_table, mutation, endpoint
) -> None:
    candidate = historical_window(
        MATERIALIZED_ITEM,
        start=main.datetime(2026, 8, 1, tzinfo=main.UTC),
        curtailed_mwh=20.0,
    )
    if mutation == "missing":
        candidate.pop("source_record")
    elif mutation == "key_mismatch":
        candidate["source_record"]["source_key"] = "raw/ons/other.parquet"
    else:
        candidate["source_record"]["curtailed_mwh"] = 21.0
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository, "get_historical_windows", lambda *args, **kwargs: [candidate]
    )

    if endpoint == "windows":
        response = client.get(
            "/v1/assets/CJU_BAOUR/windows",
            params={"start": "2026-08-01", "end": "2026-08-31", "duration_hours": 72},
        )
    else:
        response = client.post(
            "/v1/maintenance/rank",
            json={
                "asset_id": "CJU_BAOUR",
                "start": "2026-08-01",
                "end": "2026-08-31",
                "duration_hours": 72,
                "minimum_notice_hours": 168,
                "baseline_window_start": "2026-08-01T00:00:00Z",
                "constraints": {"weekdays_only": False, "unavailable_periods": []},
                "energy_price": energy_price_payload(),
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "Linhagem mensal materializada inválida ou incompleta."
    assert not issued_provenance_table.items


def test_rank_maintenance_changed_values_get_new_immutable_ids(
    monkeypatch, issued_provenance_table
) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_historical_windows",
        lambda asset_id, start, end, duration_hours: [
            historical_window(
                MATERIALIZED_ITEM,
                start=main.datetime(2026, 8, 1, tzinfo=main.UTC),
                curtailed_mwh=20.0,
            )
        ],
    )
    request = {
        "asset_id": "CJU_BAOUR",
        "start": "2026-08-01",
        "end": "2026-08-31",
        "duration_hours": 72,
        "minimum_notice_hours": 168,
        "baseline_window_start": "2026-08-01T00:00:00Z",
        "constraints": {"weekdays_only": False, "unavailable_periods": []},
        "energy_price": energy_price_payload(250),
        "input_provenance": maintenance_input_provenance(),
    }

    first = client.post("/v1/maintenance/rank", json=request)
    assert first.status_code == 200
    first_window = first.json()["ranked_windows"][0]
    first_ids = {
        provenance["evidence_id"] for provenance in first_window["field_provenance"].values()
    }
    first_cost_id = first_window["opportunity_cost"]["provenance_id"]

    changed_request = {**request, "energy_price": energy_price_payload(300)}
    second = client.post("/v1/maintenance/rank", json=changed_request)
    assert second.status_code == 200
    second_window = second.json()["ranked_windows"][0]
    second_ids = {
        provenance["evidence_id"] for provenance in second_window["field_provenance"].values()
    }
    assert first_ids.isdisjoint(second_ids)
    assert second_window["opportunity_cost"]["value"] == 6000.0
    assert len(issued_provenance_table.items) == 30

    prior = client.get(f"/v1/provenances/{first_cost_id}")
    assert prior.status_code == 200
    assert prior.json()["evidence_id"] == first_cost_id

    duplicate = client.post("/v1/maintenance/rank", json=changed_request)
    assert duplicate.status_code == 200
    assert (
        duplicate.json()["ranked_windows"][0]["field_provenance"]
        == second_window["field_provenance"]
    )
    assert len(issued_provenance_table.items) == 30


def test_rank_maintenance_accepts_legacy_payload_and_infers_client_lineage(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_historical_windows",
        lambda asset_id, start, end, duration_hours: [
            historical_window(
                MATERIALIZED_ITEM,
                start=main.datetime(2026, 8, 1, tzinfo=main.UTC),
                curtailed_mwh=20.0,
            )
        ],
    )

    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "CJU_BAOUR",
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-08-01T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": {
                "value": 250,
                "unit": "BRL/MWh",
                "source": "legacy_client_scenario",
                "value_status": "informado",
                "origin": "CLIENTE_INFORMADO",
            },
        },
    )

    assert response.status_code == 200
    inferred = response.json()["input_provenance"]
    assert {item["origin"] for item in inferred.values()} == {"CLIENTE_INFORMADO"}
    assert all("inferida" in " ".join(item["limitations"]).lower() for item in inferred.values())
    assert len({item["evidence_id"] for item in inferred.values()}) == len(inferred)


def test_rank_maintenance_rejects_baseline_outside_period(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)

    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "demo-wind-ne-001",
            "start": "2026-10-01",
            "end": "2026-10-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-11-15T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(),
        },
    )

    assert response.status_code == 422


def test_rank_maintenance_rejects_non_positive_price() -> None:
    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "demo-wind-ne-001",
            "start": "2026-10-01",
            "end": "2026-10-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-10-15T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(-1),
        },
    )

    assert response.status_code == 422


def test_rank_maintenance_rejects_unknown_asset() -> None:
    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "unknown",
            "start": "2026-10-01",
            "end": "2026-10-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-10-15T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(),
        },
    )

    assert response.status_code == 404


def test_bess_screen_uses_materialized_residual_and_explicit_assumptions(
    monkeypatch, issued_provenance_table
) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)

    response = client.post(
        "/v1/bess/screen",
        json={
            "asset_id": "CJU_BAOUR",
            "maintenance_result_id": "historical:CJU_BAOUR:2026-08",
            "power_mw": 20,
            "energy_mwh": 80,
            "capex_brl": 1000000,
            "annualized_cost_brl": 100000,
            "round_trip_efficiency": 0.85,
            "cycles_per_year": 200,
            "energy_price_brl_mwh": 250,
            "input_provenance": bess_input_provenance(),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["asset_id"] == "CJU_BAOUR"
    assert payload["screening_mode"] == "historical_deterministic"
    assert payload["data_mode"] == "ons_materialized"
    assert payload["residual_exposure_mwh"] == 23968.0945
    assert payload["technically_absorbable_mwh"] == 13600.0
    assert payload["annual_benefit_brl"] == 3400000.0
    assert payload["annual_net_benefit_brl"] == 3300000.0
    assert payload["preliminary_viable"] is True
    assert set(payload["input_provenance"]) == set(bess_input_provenance())
    assert payload["source_observation"]["origin"] == "PROXY_CALCULADO"
    output_evidence = payload["output_evidence"]
    assert set(output_evidence) == {
        "residual_exposure_mwh",
        "technically_absorbable_mwh",
        "annual_benefit_brl",
        "annual_net_benefit_brl",
        "preliminary_viable",
    }
    assert {item["origin"] for item in output_evidence.values()} == {"PROXY_CALCULADO"}
    assert len({item["provenance_id"] for item in output_evidence.values()}) == 5
    assert all(
        item["provenance"]["method_version"] == "bess_screen_v1"
        for item in output_evidence.values()
    )
    expected_parents = {
        payload["source_observation"]["evidence_id"],
        *(item["evidence_id"] for item in bess_input_provenance().values()),
    }
    assert all(
        set(item["provenance"]["parent_evidence_ids"]) == expected_parents
        for item in output_evidence.values()
    )
    assert len(issued_provenance_table.items) == 13
    source_id = payload["source_observation"]["evidence_id"]
    source_key = IssuedProvenanceRepository._key(source_id)["scenario_id"]
    assert ("PROVENANCE", source_key) in issued_provenance_table.items
    operation = next(
        item
        for item in issued_provenance_table.items.values()
        if item["record_type"] == "provenance_operation"
    )
    assert (
        operation["request_digest"]
        and "request_json" not in operation
        and "output_json" not in operation
    )
    monkeypatch.setattr(
        main,
        "issued_provenance_repository",
        IssuedProvenanceRepository(issued_provenance_table),
    )
    fresh_client = fresh_api_client()
    source_response = fresh_client.get(f"/v1/provenances/{source_id}")
    assert source_response.status_code == 200
    assert source_response.json()["provenance"] == payload["source_observation"]
    for field_name, evidence in output_evidence.items():
        provenance_response = fresh_client.get(f"/v1/provenances/{evidence['provenance_id']}")
        assert provenance_response.status_code == 200
        assert provenance_response.json()["field_name"] == field_name
        assert provenance_response.json()["origin"] == "PROXY_CALCULADO"
        assert set(provenance_response.json()["parent_evidence_ids"]) == expected_parents
        assert provenance_response.json()["provenance"] == evidence["provenance"]
    assert "soc_cronológico" in payload["missing_data"]
    assert "não é dimensionamento" in " ".join(payload["limitations"]).lower()


def test_bess_screen_changed_input_values_get_new_immutable_ids(
    monkeypatch, issued_provenance_table
) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    request = {
        "asset_id": "CJU_BAOUR",
        "maintenance_result_id": "historical:CJU_BAOUR:2026-08",
        "power_mw": 20,
        "energy_mwh": 80,
        "capex_brl": 1000000,
        "annualized_cost_brl": 100000,
        "round_trip_efficiency": 0.85,
        "cycles_per_year": 200,
        "energy_price_brl_mwh": 250,
        "input_provenance": bess_input_provenance(),
    }

    first = client.post("/v1/bess/screen", json=request)
    assert first.status_code == 200
    first_payload = first.json()
    first_ids = {
        first_payload["source_observation"]["evidence_id"],
        *(evidence["provenance_id"] for evidence in first_payload["output_evidence"].values()),
    }
    first_net_id = first_payload["output_evidence"]["annual_net_benefit_brl"]["provenance_id"]

    changed_request = {**request, "energy_mwh": 40}
    second = client.post("/v1/bess/screen", json=changed_request)
    assert second.status_code == 200
    second_payload = second.json()
    second_ids = {
        second_payload["source_observation"]["evidence_id"],
        *(evidence["provenance_id"] for evidence in second_payload["output_evidence"].values()),
    }
    assert first_ids.isdisjoint(second_ids)
    assert len(issued_provenance_table.items) == 26

    prior = client.get(f"/v1/provenances/{first_net_id}")
    assert prior.status_code == 200
    assert prior.json()["evidence_id"] == first_net_id


def test_bess_screen_accepts_legacy_payload_and_infers_client_lineage(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)

    response = client.post(
        "/v1/bess/screen",
        json={
            "asset_id": "CJU_BAOUR",
            "maintenance_result_id": "historical:CJU_BAOUR:2026-08",
            "power_mw": 20,
            "energy_mwh": 80,
            "capex_brl": 1000000,
            "annualized_cost_brl": 100000,
            "round_trip_efficiency": 0.85,
            "cycles_per_year": 200,
            "energy_price_brl_mwh": 250,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    parents = payload["output_evidence"]["annual_net_benefit_brl"]["provenance"][
        "parent_evidence_ids"
    ]
    assert len(parents) == 10
    assert set(payload["input_provenance"]) == {
        "asset_id",
        "maintenance_result_id",
        "power_mw",
        "energy_mwh",
        "capex_brl",
        "annualized_cost_brl",
        "round_trip_efficiency",
        "cycles_per_year",
        "energy_price_brl_mwh",
    }
    assert all(not parent.startswith("ons:") for parent in parents)
    assert "inferida" in " ".join(payload["limitations"]).lower()


@pytest.mark.parametrize("claimed_origin", ["ONS_PUBLICO", "PROXY_CALCULADO"])
def test_bess_screen_rejects_unresolvable_server_input_claim(monkeypatch, claimed_origin) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    forged = bess_input_provenance()
    id_builder = build_public_evidence_id if claimed_origin == "ONS_PUBLICO" else build_evidence_id
    forged["power_mw"] = {
        **forged["power_mw"],
        "evidence_id": id_builder(
            MATERIALIZED_ITEM["source_sha256"],
            "power_mw",
            "bess_screen_v1",
            "forged-client-claim",
        ),
        "origin": claimed_origin,
        "source_key": MATERIALIZED_ITEM["source_key"],
        "source_sha256": MATERIALIZED_ITEM["source_sha256"],
        "source_sha256s": [MATERIALIZED_ITEM["source_sha256"]],
    }

    response = client.post(
        "/v1/bess/screen",
        json={
            "asset_id": "CJU_BAOUR",
            "maintenance_result_id": "historical:CJU_BAOUR:2026-08",
            "power_mw": 20,
            "energy_mwh": 80,
            "capex_brl": 1000000,
            "annualized_cost_brl": 100000,
            "round_trip_efficiency": 0.85,
            "cycles_per_year": 200,
            "energy_price_brl_mwh": 250,
            "input_provenance": forged,
        },
    )

    assert response.status_code == 422


def test_get_materialization_model_run_is_explicitly_historical(monkeypatch) -> None:
    monkeypatch.setattr(
        main.repository,
        "get_materialization_run",
        lambda period: {
            "period": period,
            "asset_count": 153,
            "source_sha256s": [MATERIALIZED_ITEM["source_sha256"]],
        },
    )

    response = client.get("/v1/model-runs/materialization:2026-08")

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_run_id"] == "materialization:2026-08"
    assert payload["run_type"] == "historical_replay"
    assert payload["model_used"] is False
    assert payload["validation_status"] == "materialized_historical_data"
    assert payload["asset_count"] == 153
    assert payload["metrics"] is None


def test_report_lifecycle_uses_frozen_materialized_evidence(monkeypatch) -> None:
    stored = {}

    def fake_create(report):
        stored.update(report)
        return report

    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(main.artifact_repository, "create_report", fake_create)
    monkeypatch.setattr(main.artifact_repository, "get_report", lambda report_id: stored or None)
    monkeypatch.setattr(
        main.artifact_repository,
        "get_report_file_url",
        lambda report: "https://example.invalid/temporary-report-url",
    )

    create_response = client.post(
        "/v1/reports",
        json={
            "asset_id": "CJU_BAOUR",
            "evidence_ids": [
                build_evidence_id(
                    MATERIALIZED_ITEM["source_sha256"], "report", "report_input_v1", "test"
                )
            ],
            "report_type": "decision_support",
            "format": "json",
        },
    )

    assert create_response.status_code == 202
    created = create_response.json()
    assert created["execution_status"] == "completed"
    assert created["generation_mode"] == "deterministic_fallback"
    assert created["hash_sha256"] == hashlib.sha256(stored["body"].encode()).hexdigest()
    assert json.loads(stored["body"])["data_mode"] == "ons_materialized"

    get_response = client.get(f"/v1/reports/{created['report_id']}")
    assert get_response.status_code == 200
    assert get_response.json()["hash_sha256"] == created["hash_sha256"]

    file_response = client.get(f"/v1/reports/{created['report_id']}/file")
    assert file_response.status_code == 200
    assert file_response.json()["expires_in_seconds"] == 300
    assert file_response.json()["url"].startswith("https://")


def test_optimize_curtailment_returns_explainable_recommendation(monkeypatch) -> None:
    def fake_optimize(_scenario):
        return {
            "recomendacao": "Reduzir 8 MW de geração renovável por 30 minutos.",
            "justificativa_tecnica": "A restrição de transmissão limita o escoamento.",
            "nivel_risco": "medio",
            "acoes_sugeridas": ["Monitorar o intercâmbio", "Reavaliar em 15 minutos"],
            "premissas_usadas": ["Demanda prevista de 120 MW"],
            "modelo_bedrock_utilizado": "us.anthropic.claude-opus-5",
        }

    monkeypatch.setattr(main, "optimize_with_bedrock", fake_optimize, raising=False)

    response = client.post(
        "/optimize-curtailment",
        json={
            "regiao_subsistema": "Nordeste",
            "timestamp": "2026-09-26T15:00:00Z",
            "demanda_prevista_mw": 120,
            "geracao_renovavel_prevista_mw": 150,
            "geracao_convencional_disponivel_mw": 20,
            "restricoes_transmissao": ["Limite de exportação: 140 MW"],
            "limite_corte_permitido_mw": 15,
            "prioridade_operacional": "alta",
            "observacoes": "Preservar estabilidade do sistema.",
        },
    )

    assert response.status_code == 200
    assert response.json()["nivel_risco"] == "medio"
    assert response.json()["modelo_bedrock_utilizado"] == "us.anthropic.claude-opus-5"
    assert len(response.json()["acoes_sugeridas"]) == 2


def test_optimize_curtailment_rejects_invalid_generation() -> None:
    response = client.post(
        "/optimize-curtailment",
        json={
            "regiao_subsistema": "Nordeste",
            "timestamp": "2026-09-26T15:00:00Z",
            "demanda_prevista_mw": 120,
            "geracao_renovavel_prevista_mw": -1,
            "geracao_convencional_disponivel_mw": 20,
            "restricoes_transmissao": [],
            "limite_corte_permitido_mw": 15,
            "prioridade_operacional": "alta",
        },
    )

    assert response.status_code == 422


def test_optimize_curtailment_returns_controlled_error(monkeypatch) -> None:
    def fake_optimize(_scenario):
        raise main.BedrockOptimizationError("all models failed")

    monkeypatch.setattr(main, "optimize_with_bedrock", fake_optimize)

    response = client.post(
        "/optimize-curtailment",
        json={
            "regiao_subsistema": "Nordeste",
            "timestamp": "2026-09-26T15:00:00Z",
            "demanda_prevista_mw": 120,
            "geracao_renovavel_prevista_mw": 150,
            "geracao_convencional_disponivel_mw": 20,
            "restricoes_transmissao": [],
            "limite_corte_permitido_mw": 15,
            "prioridade_operacional": "alta",
        },
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Serviço de otimização temporariamente indisponível."}


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), float("-inf")])
def test_bess_rejects_nonfinite_numbers_before_any_write(
    nonfinite, issued_provenance_table
) -> None:
    payload = {
        "asset_id": "CJU_BAOUR",
        "maintenance_result_id": "result-1",
        "power_mw": nonfinite,
        "energy_mwh": 80,
        "capex_brl": 1000000,
        "annualized_cost_brl": 100000,
        "round_trip_efficiency": 0.85,
        "cycles_per_year": 200,
        "energy_price_brl_mwh": 250,
    }
    response = client.post(
        "/v1/bess/screen",
        content=json.dumps(payload),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert not issued_provenance_table.items


def test_maintenance_rejects_oversized_client_provenance_with_422(
    issued_provenance_table,
) -> None:
    provenance = maintenance_input_provenance()
    provenance["asset_id"]["source_uri"] = "x" * 513
    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "CJU_BAOUR",
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-08-15T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(),
            "input_provenance": provenance,
        },
    )
    assert response.status_code == 422
    assert not issued_provenance_table.items


def test_decision_requests_reject_extreme_finite_inputs_before_writes(
    issued_provenance_table,
) -> None:
    bess = client.post(
        "/v1/bess/screen",
        json={
            "asset_id": "CJU_BAOUR",
            "maintenance_result_id": "result-1",
            "power_mw": 1e308,
            "energy_mwh": 80,
            "capex_brl": 1000000,
            "annualized_cost_brl": 100000,
            "round_trip_efficiency": 0.85,
            "cycles_per_year": 200,
            "energy_price_brl_mwh": 250,
        },
    )
    maintenance = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "CJU_BAOUR",
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-08-15T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(1e308),
        },
    )
    assert bess.status_code == 422
    assert maintenance.status_code == 422
    assert not issued_provenance_table.items


def test_maintenance_overflow_from_materialized_value_returns_422_before_write(
    monkeypatch, issued_provenance_table
) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    monkeypatch.setattr(
        main.repository,
        "get_historical_windows",
        lambda asset_id, start, end, duration_hours: [
            {
                "start": main.datetime(2026, 8, 1, tzinfo=main.UTC),
                "end": main.datetime(2026, 8, 4, tzinfo=main.UTC),
                "curtailed_mwh": 1e308,
                "period": "2026-08",
                "source_sha256": MATERIALIZED_ITEM["source_sha256"],
                "method": "monthly_observed_rate_prorated_to_window_v1",
            }
        ],
    )
    response = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "CJU_BAOUR",
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-08-01T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(1e100),
        },
    )
    assert response.status_code == 422
    assert not issued_provenance_table.items


def test_decision_numeric_boundary_is_accepted(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    response = client.post(
        "/v1/bess/screen",
        json={
            "asset_id": "CJU_BAOUR",
            "maintenance_result_id": "result-1",
            "power_mw": 1e100,
            "energy_mwh": 1e100,
            "capex_brl": 1e100,
            "annualized_cost_brl": 1e100,
            "round_trip_efficiency": 1,
            "cycles_per_year": 1_000_000,
            "energy_price_brl_mwh": 1e100,
        },
    )
    assert response.status_code == 200


def test_planning_horizon_and_36_window_result_are_bounded(monkeypatch) -> None:
    oversized_horizon = client.get(
        "/v1/assets/CJU_BAOUR/windows",
        params={"start": "2026-01-01", "end": "2026-03-02", "duration_hours": 72},
    )
    assert oversized_horizon.status_code == 422

    monkeypatch.setattr(main.repository, "get_asset", lambda asset_id: MATERIALIZED_ITEM)
    window = {
        "start": main.datetime(2026, 8, 1, tzinfo=main.UTC),
        "end": main.datetime(2026, 8, 4, tzinfo=main.UTC),
        "curtailed_mwh": 20.0,
        "period": "2026-08",
        "source_sha256": MATERIALIZED_ITEM["source_sha256"],
        "method": "monthly_observed_rate_prorated_to_window_v1",
    }
    monkeypatch.setattr(
        main.repository,
        "get_historical_windows",
        lambda asset_id, start, end, duration_hours, reason=None: [dict(window) for _ in range(36)],
    )
    windows = client.get(
        "/v1/assets/CJU_BAOUR/windows",
        params={"start": "2026-08-01", "end": "2026-08-31", "duration_hours": 72},
    )
    assert windows.status_code == 422

    maintenance = client.post(
        "/v1/maintenance/rank",
        json={
            "asset_id": "CJU_BAOUR",
            "start": "2026-08-01",
            "end": "2026-08-31",
            "duration_hours": 72,
            "minimum_notice_hours": 168,
            "baseline_window_start": "2026-08-01T00:00:00Z",
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": energy_price_payload(),
        },
    )
    assert maintenance.status_code == 422


def test_caller_evidence_ids_must_match_exact_compact_registry() -> None:
    malformed = "evd1." + "a" * 65
    response = client.post(
        "/v1/reports",
        json={
            "asset_id": "CJU_BAOUR",
            "evidence_ids": [malformed],
            "report_type": "decision_support",
            "format": "json",
        },
    )
    assert len(malformed) == 70
    assert response.status_code == 422
