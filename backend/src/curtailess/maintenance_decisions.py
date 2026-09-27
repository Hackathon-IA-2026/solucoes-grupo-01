import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .bedrock import deterministic_decision_explanation, explain_maintenance_decision
from .canonical import canonical_digest, canonical_json
from .config import Settings
from .maintenance_engine import evaluate_maintenance_windows
from .plant_state import build_plant_state
from .provenance_service import field_provenance
from .schemas import (
    DataOrigin,
    DecisionExplanation,
    MaintenanceDecisionEvidenceBundle,
    MaintenanceDecisionRequest,
    MaintenanceDecisionResponse,
    SourceArtifact,
)


class IdempotencyConflict(RuntimeError):
    pass


class DecisionPersistenceUnavailable(RuntimeError):
    pass


def decision_id_from_idempotency_key(idempotency_key: str) -> str:
    return "dec1." + hashlib.sha256(idempotency_key.encode()).hexdigest()


def _plant_parent_evidence_ids(plant_state: Any) -> list[str]:
    facts = (
        plant_state.public_forecast_mw,
        plant_state.capacity_mw,
        plant_state.generation_mw,
        plant_state.availability_mw,
        plant_state.reference_generation_mw,
        plant_state.generation_limit_mw,
    )
    return sorted({fact.provenance.evidence_id for fact in facts if fact is not None})


def _source_records_for_window(
    historical_records: list[dict[str, Any]], source_snapshot_ids: tuple[str, ...]
) -> list[dict[str, Any]]:
    allowed = set(source_snapshot_ids)
    by_identity = {
        (str(record["source_key"]), str(record["source_sha256"])): record
        for record in historical_records
        if record.get("source_sha256") in allowed
    }
    return [by_identity[identity] for identity in sorted(by_identity)]


def create_maintenance_decision(
    request: MaintenanceDecisionRequest,
    idempotency_key: str,
    *,
    exposure_repository: Any,
    plant_state_repository: Any,
    decision_repository: Any,
    settings: Settings,
    explanation_builder: Callable[..., DecisionExplanation] = explain_maintenance_decision,
) -> MaintenanceDecisionResponse:
    request_digest = canonical_digest(request.model_dump(mode="json"))
    existing = decision_repository.get_by_idempotency(idempotency_key)
    if existing is not None:
        if existing.request_digest != request_digest:
            raise IdempotencyConflict("idempotency key already used for a different request")
        return existing

    plant_state = build_plant_state(
        request.asset_id,
        request.as_of,
        exposure_repository,
        plant_state_repository,
        max_forecast_age_hours=settings.public_data_max_age_hours,
    )
    historical_records = exposure_repository.get_asset_history(request.asset_id)
    engine_result = evaluate_maintenance_windows(
        asset_id=request.asset_id,
        as_of=request.as_of,
        planning_start=request.planning_start,
        planning_end=request.planning_end,
        duration_days=request.duration_days,
        minimum_notice_hours=request.minimum_notice_hours,
        weekdays_only=request.constraints.weekdays_only,
        unavailable_periods=request.constraints.unavailable_periods,
        energy_price_brl_mwh=request.energy_price.value,
        plant_state=plant_state,
        historical_records=historical_records,
    )
    selected = engine_result.eligible_windows[0] if engine_result.eligible_windows else None
    decision_provenance = None
    source_records: list[dict[str, Any]] = []
    parent_ids = sorted(
        {
            request.energy_price.provenance.evidence_id,
            *_plant_parent_evidence_ids(plant_state),
        }
    )
    if selected is not None:
        source_records = _source_records_for_window(
            historical_records, selected.source_snapshot_ids
        )
        decision_provenance = field_provenance(
            field_name="selected_window",
            method_version=engine_result.method_version,
            context=canonical_json(
                {
                    "request_digest": request_digest,
                    "candidate": selected.model_dump(mode="json"),
                    "parent_evidence_ids": parent_ids,
                }
            ),
            origin=DataOrigin.PROXY_CALCULADO,
            limitations=list(engine_result.limitations),
            source_hashes=sorted({str(record["source_sha256"]) for record in source_records}),
            source_items=source_records,
            source_uri=f"curtailess://maintenance/{request.asset_id}/selected-window",
            use_source_period=False,
            effective_at=selected.start,
            parent_evidence_ids=parent_ids,
        )
        status = "RECOMMENDED"
    elif engine_result.status == "REVIEW_REQUIRED":
        status = "REVIEW_REQUIRED"
    else:
        status = "NO_ELIGIBLE_WINDOW"

    decision_id = decision_id_from_idempotency_key(idempotency_key)
    evidence_ids = tuple(
        dict.fromkeys(
            [
                plant_state.snapshot_id,
                request.energy_price.provenance.evidence_id,
                *(
                    [selected.candidate_id, decision_provenance.evidence_id]
                    if selected is not None and decision_provenance is not None
                    else []
                ),
                *(selected.source_snapshot_ids if selected is not None else ()),
            ]
        )
    )
    explanation_payload = {
        "decision_id": decision_id,
        "status": status,
        "deterministic_method": engine_result.method_version,
        "selected_window": selected.model_dump(mode="json") if selected else None,
        "limitations": list(engine_result.limitations),
    }
    if selected is None:
        explanation = deterministic_decision_explanation(explanation_payload, evidence_ids)
    else:
        explanation = explanation_builder(
            explanation_payload,
            evidence_ids,
            settings=settings,
        )
    artifact_pairs = sorted(
        {(str(record["source_key"]), str(record["source_sha256"])) for record in source_records}
    )
    evidence_bundle = MaintenanceDecisionEvidenceBundle(
        plant_state_snapshot_id=plant_state.snapshot_id,
        source_artifacts=tuple(
            SourceArtifact(source_key=source_key, source_sha256=source_sha256)
            for source_key, source_sha256 in artifact_pairs
        ),
        parent_evidence_ids=tuple(parent_ids),
        request_digest=request_digest,
    )
    response = MaintenanceDecisionResponse(
        decision_id=decision_id,
        request_digest=request_digest,
        status=status,
        request=request,
        plant_state=plant_state,
        engine_result=engine_result,
        evidence_bundle=evidence_bundle,
        selected_window=selected,
        decision_provenance=decision_provenance,
        explanation=explanation,
    )
    return decision_repository.put_decision(
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        response=response,
    )


class MaintenanceDecisionRepository:
    def __init__(self, table: Any):
        self.table = table

    def get_by_idempotency(self, idempotency_key: str) -> MaintenanceDecisionResponse | None:
        return self.get_decision(decision_id_from_idempotency_key(idempotency_key))

    def get_decision(self, decision_id: str) -> MaintenanceDecisionResponse | None:
        item = self.table.get_item(
            Key={"plant_id": "MAINTENANCE_DECISION", "scenario_id": decision_id},
            ConsistentRead=True,
        ).get("Item")
        if item is None:
            return None
        response_json = str(item["response_json"])
        if hashlib.sha256(response_json.encode()).hexdigest() != item["response_sha256"]:
            raise RuntimeError("stored maintenance decision failed integrity validation")
        response = MaintenanceDecisionResponse.model_validate(json.loads(response_json))
        if response.decision_id != decision_id or response.request_digest != item["request_digest"]:
            raise RuntimeError("stored maintenance decision identity mismatch")
        return response

    def put_decision(
        self,
        *,
        idempotency_key: str,
        request_digest: str,
        response: MaintenanceDecisionResponse,
    ) -> MaintenanceDecisionResponse:
        expected_id = decision_id_from_idempotency_key(idempotency_key)
        if response.decision_id != expected_id:
            raise ValueError("decision id does not match idempotency key")
        response_json = canonical_json(response.model_dump(mode="json"))
        item = {
            "plant_id": "MAINTENANCE_DECISION",
            "scenario_id": expected_id,
            "record_type": "maintenance_decision_v1",
            "idempotency_sha256": hashlib.sha256(idempotency_key.encode()).hexdigest(),
            "request_digest": request_digest,
            "response_json": response_json,
            "response_sha256": hashlib.sha256(response_json.encode()).hexdigest(),
            "created_at": datetime.now(UTC).isoformat(),
            "model_id": response.explanation.model_id or "deterministic_fallback",
            "generation_mode": response.explanation.generation_mode,
        }
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression=(
                    "attribute_not_exists(plant_id) AND attribute_not_exists(scenario_id)"
                ),
            )
            return response
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = self.get_decision(expected_id)
            if existing is None:
                raise RuntimeError("conditional decision conflict without stored item") from exc
            if existing.request_digest != request_digest:
                raise IdempotencyConflict(
                    "idempotency key already used for a different request"
                ) from exc
            return existing


class UnconfiguredMaintenanceDecisionRepository:
    def get_by_idempotency(self, idempotency_key: str) -> None:
        del idempotency_key
        return None

    def get_decision(self, decision_id: str) -> None:
        del decision_id
        return None

    def put_decision(self, **kwargs: Any) -> MaintenanceDecisionResponse:
        del kwargs
        raise DecisionPersistenceUnavailable("maintenance decision repository is not configured")


def create_maintenance_decision_repository(table_name: str | None, region_name: str) -> Any:
    if not table_name:
        return UnconfiguredMaintenanceDecisionRepository()
    table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)
    return MaintenanceDecisionRepository(table)
