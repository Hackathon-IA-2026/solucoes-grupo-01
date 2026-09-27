from datetime import UTC, datetime, timedelta

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import curtailess.main as main
from curtailess.config import Settings
from curtailess.maintenance_decisions import (
    IdempotencyConflict,
    MaintenanceDecisionRepository,
    create_maintenance_decision,
)
from curtailess.schemas import (
    DecisionExplanation,
    MaintenanceDecisionRequest,
)

AS_OF = datetime(2026, 1, 20, 3, 30, tzinfo=UTC)


def source_record(period: str, generation: float, curtailed: float, availability: float):
    digit = "1" if period.endswith("01") else "2"
    return {
        "asset_id": "CJU_TEST",
        "period": period,
        "fact_type": "constrained_off_monthly",
        "interval_count": 48,
        "generation_mwh": generation,
        "curtailed_mwh": curtailed,
        "availability_mwh": availability,
        "reference_generation_mwh": availability,
        "limited_generation_mwh": availability * 0.8,
        "availability_limited_mwh": availability,
        "source_key": f"raw/ons/restricao/{period}.parquet",
        "source_sha256": digit * 64,
        "source_fingerprint": ("3" if digit == "1" else "4") * 64,
    }


class FakeExposureRepository:
    def __init__(self):
        self.history = [
            source_record("2025-01", 600, 400, 1000),
            source_record("2025-02", 100, 100, 200),
        ]
        self.asset = self.history[0]
        self.identity = {
            "asset_id": "CJU_TEST",
            "period": "identity#relationship#2020-01-01#GROUP_TEST",
            "ons_group_id": "GROUP_TEST",
            "technology_name": "EOLIELÉTRICA",
            "state": "RN",
            "ceg": "CEG-TEST",
            "source_key": "raw/ons/usina_conjunto/snapshot.parquet",
            "source_sha256": "5" * 64,
            "source_fingerprint": "6" * 64,
            "capacity": {
                "asset_id": "ceg:CEG-TEST",
                "period": "identity#capacity#snapshot",
                "active_capacity_mw": 100,
                "capacity_as_of": "2026-01-20",
                "source_key": "raw/ons/capacidade/snapshot.parquet",
                "source_sha256": "7" * 64,
                "source_fingerprint": "8" * 64,
            },
        }
        self.forecast = {
            "program_entity_id": "CJU_TEST",
            "program_entity_name": "Teste",
            "valid_at": "2026-01-20T00:30:00-03:00",
            "forecast_mw": 80,
            "programmed_mw": 75,
            "publication_timestamp": (AS_OF - timedelta(hours=2)).isoformat(),
            "publication_time_status": "source_object_last_modified_proxy",
            "source_key": "raw/ons/programacao/forecast.parquet",
            "source_sha256": "9" * 64,
            "source_fingerprint": "a" * 64,
        }
        self.profile = {
            "asset_id": "CJU_TEST",
            "period": "generation#2025-01",
            "season": "summer",
            "mean_generation_mw": 60,
            "hour_of_day_profile": {"00": {"mean_mw": 65, "observation_count": 31}},
            "source_key": "raw/ons/geracao/january.parquet",
            "source_sha256": "b" * 64,
            "source_fingerprint": "c" * 64,
        }

    def get_asset(self, asset_id):
        return self.asset if asset_id == "CJU_TEST" else None

    def get_asset_history(self, asset_id):
        return self.history if asset_id == "CJU_TEST" else []

    def get_identity(self, asset_id, as_of):
        del as_of
        return self.identity if asset_id == "CJU_TEST" else None

    def get_forecast(self, program_entity_id, valid_at):
        del valid_at
        return self.forecast if program_entity_id == "CJU_TEST" else None

    def get_generation_profiles(self, asset_id, start_period=None, end_period=None):
        del start_period, end_period
        return [self.profile] if asset_id == "CJU_TEST" else []


class FakePlantStateRepository:
    def __init__(self):
        self.items = {}

    def put_snapshot(self, response):
        self.items[response.snapshot_id] = response.model_dump(mode="json")
        return response


class FakeDecisionRepository:
    def __init__(self):
        self.items = {}
        self.by_id = {}
        self.put_count = 0

    def get_by_idempotency(self, key):
        return self.items.get(key)

    def get_decision(self, decision_id):
        return self.by_id.get(decision_id)

    def put_decision(self, *, idempotency_key, request_digest, response):
        del request_digest
        self.put_count += 1
        previous = self.items.setdefault(idempotency_key, response)
        if previous.request_digest != response.request_digest:
            raise IdempotencyConflict
        self.by_id[previous.decision_id] = previous
        return previous


def request_payload(price: float = 200) -> MaintenanceDecisionRequest:
    return MaintenanceDecisionRequest.model_validate(
        {
            "asset_id": "CJU_TEST",
            "as_of": AS_OF.isoformat(),
            "planning_start": "2026-01-29",
            "planning_end": "2026-02-06",
            "duration_days": 2,
            "minimum_notice_hours": 24,
            "constraints": {"weekdays_only": False, "unavailable_periods": []},
            "energy_price": {
                "value": price,
                "unit": "BRL/MWh",
                "source": "Premissa do cliente",
                "value_status": "informado",
                "origin": "CLIENTE_INFORMADO",
            },
        }
    )


def test_same_idempotency_key_replays_exact_decision_without_second_model_call() -> None:
    decisions = FakeDecisionRepository()
    model_calls = []

    def explain(payload, evidence_ids, *, settings):
        del payload, settings
        model_calls.append(evidence_ids)
        return DecisionExplanation(
            summary="A janela minimiza a energia residual vendável estimada.",
            evidence_ids=evidence_ids[:2],
            limitations=("Janela candidata, sem aprovação do ONS.",),
            generation_mode="bedrock",
            model_id="test-model",
        )

    kwargs = {
        "exposure_repository": FakeExposureRepository(),
        "plant_state_repository": FakePlantStateRepository(),
        "decision_repository": decisions,
        "settings": Settings(),
        "explanation_builder": explain,
    }
    first = create_maintenance_decision(request_payload(), "same-key-123", **kwargs)
    second = create_maintenance_decision(request_payload(), "same-key-123", **kwargs)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.status == "RECOMMENDED"
    assert first.selected_window.rank == 1
    assert first.decision_provenance.origin == "PROXY_CALCULADO"
    assert first.evidence_bundle.request_digest == first.request_digest
    assert first.evidence_bundle.source_artifacts
    assert first.evidence_bundle.parent_evidence_ids
    assert len(model_calls) == 1
    assert decisions.put_count == 1


def test_same_idempotency_key_with_changed_request_is_conflict() -> None:
    decisions = FakeDecisionRepository()

    def explain(payload, evidence_ids, *, settings):
        del payload, settings
        return DecisionExplanation(
            summary="Explicação controlada.",
            evidence_ids=evidence_ids[:1],
            limitations=("Sem aprovação do ONS.",),
            generation_mode="bedrock",
            model_id="test-model",
        )

    kwargs = {
        "exposure_repository": FakeExposureRepository(),
        "plant_state_repository": FakePlantStateRepository(),
        "decision_repository": decisions,
        "settings": Settings(),
        "explanation_builder": explain,
    }
    create_maintenance_decision(request_payload(), "same-key-456", **kwargs)

    with pytest.raises(IdempotencyConflict):
        create_maintenance_decision(request_payload(price=201), "same-key-456", **kwargs)


def test_decision_post_and_get_api_contract(monkeypatch) -> None:
    decisions = FakeDecisionRepository()

    def explain(payload, evidence_ids, *, settings):
        del payload, settings
        return DecisionExplanation(
            summary="Explicação controlada.",
            evidence_ids=evidence_ids[:1],
            limitations=("Sem aprovação do ONS.",),
            generation_mode="bedrock",
            model_id="test-model",
        )

    stored = create_maintenance_decision(
        request_payload(),
        "api-key-1234",
        exposure_repository=FakeExposureRepository(),
        plant_state_repository=FakePlantStateRepository(),
        decision_repository=decisions,
        settings=Settings(),
        explanation_builder=explain,
    )
    monkeypatch.setattr(main, "maintenance_decision_repository", decisions)
    monkeypatch.setattr(
        main,
        "create_maintenance_decision",
        lambda request, idempotency_key, **kwargs: stored,
    )
    client = TestClient(main.app)
    payload = request_payload().model_dump(mode="json")

    missing_header = client.post("/v1/maintenance/decisions", json=payload)
    created = client.post(
        "/v1/maintenance/decisions",
        json=payload,
        headers={"Idempotency-Key": "api-key-1234"},
    )
    replayed = client.get(f"/v1/maintenance/decisions/{stored.decision_id}")

    assert missing_header.status_code == 422
    assert created.status_code == 200, created.text
    assert replayed.status_code == 200, replayed.text
    assert created.json() == replayed.json()


def test_dynamodb_repository_replays_exact_response_and_detects_corruption() -> None:
    class FakeTable:
        def __init__(self):
            self.items = {}

        def put_item(self, *, Item, ConditionExpression):
            del ConditionExpression
            key = (Item["plant_id"], Item["scenario_id"])
            if key in self.items:
                raise ClientError(
                    {"Error": {"Code": "ConditionalCheckFailedException"}},
                    "PutItem",
                )
            self.items[key] = Item.copy()

        def get_item(self, *, Key, ConsistentRead):
            del ConsistentRead
            return {"Item": self.items.get((Key["plant_id"], Key["scenario_id"]))}

    transient = FakeDecisionRepository()

    def explain(payload, evidence_ids, *, settings):
        del payload, settings
        return DecisionExplanation(
            summary="Explicação controlada.",
            evidence_ids=evidence_ids[:1],
            limitations=("Sem aprovação do ONS.",),
            generation_mode="bedrock",
            model_id="test-model",
        )

    response = create_maintenance_decision(
        request_payload(),
        "storage-key-123",
        exposure_repository=FakeExposureRepository(),
        plant_state_repository=FakePlantStateRepository(),
        decision_repository=transient,
        settings=Settings(),
        explanation_builder=explain,
    )
    table = FakeTable()
    repository = MaintenanceDecisionRepository(table)
    repository.put_decision(
        idempotency_key="storage-key-123",
        request_digest=response.request_digest,
        response=response,
    )

    replayed = repository.get_decision(response.decision_id)
    assert replayed.model_dump(mode="json") == response.model_dump(mode="json")

    key = ("MAINTENANCE_DECISION", response.decision_id)
    table.items[key]["response_json"] += " "
    with pytest.raises(RuntimeError, match="integrity"):
        repository.get_decision(response.decision_id)
