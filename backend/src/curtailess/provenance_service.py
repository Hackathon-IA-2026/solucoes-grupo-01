from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException

from .canonical import canonical_digest, canonical_json
from .schemas import DataOrigin, EvidenceProvenance, SourceArtifact

_SERVER_PROVENANCE_CONTRACTS: dict[
    tuple[str, str], tuple[DataOrigin, Literal["medido", "calculado"]]
] = {
    ("capacity_mw", "ons_capacity_source_v1"): (DataOrigin.ONS_PUBLICO, "medido"),
    ("capacity_mw", "asset_capacity_unavailable_v1"): (DataOrigin.PROXY_CALCULADO, "calculado"),
    **{
        (field, "ons_materialized_asset_v1"): (DataOrigin.ONS_PUBLICO, "medido")
        for field in ("asset_id", "name", "technology", "ons_group", "connection_point")
    },
    ("total_curtailed_energy", "curtailed_energy_sum_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("anonymized_entity_count", "distinct_latest_constrained_off_assets_at_point_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("simultaneity_rate", "historical_simultaneity_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    **{
        ("expected_curtailed_energy", method): (DataOrigin.PROXY_CALCULADO, "calculado")
        for method in (
            "monthly_observed_rate_prorated_to_window_v1",
            "monthly_observed_reason_rate_prorated_to_window_v1",
        )
    },
    ("rank", "maintenance_rank_v1"): (DataOrigin.PROXY_CALCULADO, "calculado"),
    ("start", "maintenance_window_boundary_v1"): (DataOrigin.PROXY_CALCULADO, "calculado"),
    ("end", "maintenance_window_boundary_v1"): (DataOrigin.PROXY_CALCULADO, "calculado"),
    ("opportunity_cost", "opportunity_cost_v1"): (DataOrigin.PROXY_CALCULADO, "calculado"),
    ("difference_from_baseline_mwh", "maintenance_difference_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("difference_from_baseline", "maintenance_difference_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    ("residual_exposure_source", "curtailed_energy_sum_v1"): (
        DataOrigin.PROXY_CALCULADO,
        "calculado",
    ),
    **{
        (field, "bess_screen_v1"): (DataOrigin.PROXY_CALCULADO, "calculado")
        for field in (
            "residual_exposure_mwh",
            "technically_absorbable_mwh",
            "annual_benefit_brl",
            "annual_net_benefit_brl",
            "preliminary_viable",
        )
    },
}


def aware(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    aware_value = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return aware_value.astimezone(UTC)


def field_provenance(
    *,
    field_name: str,
    method_version: str,
    context: str,
    origin: DataOrigin,
    limitations: list[str],
    source_hashes: list[str] | tuple[str, ...] = (),
    source_item: dict[str, Any] | None = None,
    source_items: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    source_uri: str | None = None,
    source_key: str | None = None,
    use_source_period: bool = True,
    observed_at: datetime | None = None,
    effective_at: datetime | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    parent_evidence_ids: list[str] | tuple[str, ...] = (),
) -> EvidenceProvenance:
    from .provenance import build_evidence_id, build_public_evidence_id

    hashes = tuple(sorted(set(source_hashes)))
    artifact_items = source_items or ((source_item,) if source_item else ())
    artifact_identities = {
        (item["source_key"], item["source_sha256"])
        for item in artifact_items
        if item.get("source_key") and item.get("source_sha256")
    }
    if source_key and len(hashes) == 1:
        artifact_identities.add((source_key, hashes[0]))
    artifacts = tuple(
        SourceArtifact(source_key=key, source_sha256=sha256)
        for key, sha256 in sorted(artifact_identities)
    )
    representative = artifacts[0] if artifacts else None
    identities = list(hashes) or [source_uri or "curtailess://unspecified"]
    id_builder = build_public_evidence_id if origin is DataOrigin.ONS_PUBLICO else build_evidence_id
    evidence_id = id_builder(identities, field_name, method_version, context)
    period_item = source_item if source_item and use_source_period else None
    observed_at = observed_at or (aware(period_item["period_end"]) if period_item else None)
    valid_from = valid_from or (aware(period_item["period_start"]) if period_item else None)
    valid_to = valid_to or (aware(period_item["period_end"]) if period_item else None)
    temporal_coverage = (
        "unknown"
        if observed_at is None and effective_at is None
        else "partial"
        if (valid_from is None) != (valid_to is None)
        else "known"
    )
    if temporal_coverage == "partial":
        valid_from = valid_to = None
    return EvidenceProvenance(
        evidence_id=evidence_id,
        field_name=field_name,
        origin=origin,
        source_uri=source_uri,
        source_key=(
            representative.source_key
            if representative
            else (source_key or (source_item.get("source_key") if source_item else None))
            if len(hashes) <= 1
            else None
        ),
        source_sha256=(
            representative.source_sha256
            if representative
            else hashes[0]
            if len(hashes) == 1
            else None
        ),
        source_sha256s=hashes,
        source_artifacts=artifacts,
        parent_evidence_ids=tuple(sorted(set(parent_evidence_ids))),
        observed_at=observed_at,
        effective_at=effective_at
        or (observed_at if origin is not DataOrigin.ONS_PUBLICO else None),
        valid_from=valid_from,
        valid_to=valid_to,
        temporal_coverage=temporal_coverage,
        method_version=method_version,
        limitations=tuple(limitations),
    )


def persist_operation(
    issued_repository: Any,
    *,
    operation: str,
    request_value: Any,
    provenances: list[EvidenceProvenance],
    source_records: list[dict[str, Any]],
) -> str:
    provenance_map = {
        provenance.evidence_id: provenance.model_dump(mode="json") for provenance in provenances
    }
    canonical_sources = {canonical_json(source): source for source in source_records}
    return issued_repository.put_operation(
        operation=operation,
        request_digest=canonical_digest(request_value),
        provenances=provenance_map,
        source_records=[canonical_sources[key] for key in sorted(canonical_sources)],
    )


def _resolve_server_record(
    evidence_id: str, record: dict[str, Any] | None
) -> tuple[
    dict[str, Any],
    DataOrigin,
    Literal["medido", "calculado"],
    list[dict[str, Any]],
    EvidenceProvenance,
]:
    if record is None:
        raise HTTPException(status_code=404, detail="Proveniência não encontrada.")
    try:
        candidate = EvidenceProvenance.model_validate(record["provenance"])
        source_records = record["source_records"]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Registro de proveniência inválido.") from exc
    contract = _SERVER_PROVENANCE_CONTRACTS.get((candidate.field_name, candidate.method_version))
    if contract is None or candidate.evidence_id != evidence_id or not source_records:
        raise HTTPException(status_code=404, detail="Registro de proveniência inconsistente.")
    persisted_artifacts = {
        pair
        for source in source_records
        for pair in (
            (source.get("source_key"), source.get("source_sha256")),
            (source.get("capacity_source_key"), source.get("capacity_source_sha256")),
        )
        if pair[0] is not None and pair[1] is not None
    }
    persisted_by_key: dict[str, set[str]] = {}
    persisted_by_hash: dict[str, set[str]] = {}
    for key, sha256 in persisted_artifacts:
        persisted_by_key.setdefault(key, set()).add(sha256)
        persisted_by_hash.setdefault(sha256, set()).add(key)
    if any(
        len(values) != 1 for values in (*persisted_by_key.values(), *persisted_by_hash.values())
    ):
        raise HTTPException(status_code=404, detail="Linhagem de proveniência conflitante.")
    expected_artifacts = {
        (artifact.source_key, artifact.source_sha256) for artifact in candidate.source_artifacts
    }
    if not expected_artifacts and candidate.source_key and candidate.source_sha256:
        expected_artifacts.add((candidate.source_key, candidate.source_sha256))
    if not expected_artifacts or not expected_artifacts.issubset(persisted_artifacts):
        raise HTTPException(status_code=404, detail="Artefato de proveniência não resolvível.")
    origin, classification = contract
    if candidate.origin is not origin:
        raise HTTPException(status_code=404, detail="Origem de proveniência inconsistente.")
    identity = {
        "field": candidate.field_name,
        "method": candidate.method_version,
        "sources": list(candidate.source_sha256s),
    }
    return identity, origin, classification, source_records, candidate


def resolve_server_evidence(
    evidence_id: str, issued_repository: Any
) -> tuple[
    dict[str, Any],
    DataOrigin,
    Literal["medido", "calculado"],
    list[dict[str, Any]],
    EvidenceProvenance,
]:
    return _resolve_server_record(evidence_id, issued_repository.get(evidence_id))


def validate_caller_provenance(
    provenances: dict[str, EvidenceProvenance], issued_repository: Any
) -> None:
    server_provenances = []
    for provenance in provenances.values():
        if provenance.origin is DataOrigin.CLIENTE_INFORMADO:
            continue
        if provenance.origin is DataOrigin.SIMULADO:
            raise HTTPException(
                status_code=422, detail="Proveniência simulada não é entrada confiável."
            )
        server_provenances.append(provenance)

    evidence_ids = [provenance.evidence_id for provenance in server_provenances]
    if hasattr(issued_repository, "get_many"):
        records = issued_repository.get_many(evidence_ids)
    else:
        records = {evidence_id: issued_repository.get(evidence_id) for evidence_id in evidence_ids}
    for provenance in server_provenances:
        try:
            identity, origin, _, _, candidate = _resolve_server_record(
                provenance.evidence_id, records.get(provenance.evidence_id)
            )
        except HTTPException as exc:
            raise HTTPException(
                status_code=422,
                detail="Alegação de proveniência pública/calculada não pôde ser resolvida.",
            ) from exc
        if (
            provenance.origin is not origin
            or provenance.field_name != identity["field"]
            or provenance.method_version != identity["method"]
            or list(provenance.source_sha256s) != identity["sources"]
            or provenance != candidate
        ):
            raise HTTPException(
                status_code=422,
                detail="Metadados de proveniência não correspondem ao contrato do servidor.",
            )
