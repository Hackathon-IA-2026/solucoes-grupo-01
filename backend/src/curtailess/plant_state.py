import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import boto3
from botocore.exceptions import ClientError

from .canonical import canonical_digest, canonical_json
from .provenance_service import field_provenance
from .schemas import DataOrigin, PlantStateFact, PlantStateResponse

METHOD_VERSION = "public_history_simulation_v1"
LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
_LIMITATION = (
    "Estado sintético baseado em previsão e histórico públicos do ONS; não representa "
    "SCADA privado, condição operacional confirmada ou aprovação do ONS."
)


def _normalize_as_of(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("as_of requires timezone information")
    local = value.astimezone(LOCAL_TIMEZONE)
    return local.replace(minute=(local.minute // 30) * 30, second=0, microsecond=0)


def _source_identity(item: dict[str, Any]) -> tuple[str, str]:
    return str(item["source_key"]), str(item["source_sha256"])


def _unique_sources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_identity = {_source_identity(item): item for item in items}
    return [by_identity[identity] for identity in sorted(by_identity)]


def _hash_noise(seed: str) -> Decimal:
    integer = int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16)
    unit = Decimal(integer) / Decimal(0xFFFFFFFFFFFFFFFF)
    return (unit - Decimal("0.5")) * Decimal("0.10")


def _bounded(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    return max(lower, min(value, upper))


def _number(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def _review_response(
    *,
    asset_id: str,
    as_of: datetime,
    reason: str,
    source_items: list[dict[str, Any]],
    capacity_fact: PlantStateFact | None = None,
) -> PlantStateResponse:
    source_ids = tuple(sorted({_source_identity(item)[1] for item in source_items}))
    identity = {
        "asset_id": asset_id,
        "as_of": as_of.isoformat(),
        "status": "REVIEW_REQUIRED",
        "reason": reason,
        "source_snapshot_ids": source_ids,
        "method_version": METHOD_VERSION,
    }
    return PlantStateResponse(
        snapshot_id=f"pst1.{canonical_digest(identity)}",
        asset_id=asset_id,
        as_of=as_of,
        status="REVIEW_REQUIRED",
        fallback_level="none",
        capacity_mw=capacity_fact,
        source_snapshot_ids=source_ids,
        limitations=(reason, _LIMITATION),
    )


def _public_fact(
    *,
    field_name: str,
    value: Decimal,
    source_item: dict[str, Any],
    effective_at: datetime,
    observed_at: datetime | None,
    method_version: str,
) -> PlantStateFact:
    provenance = field_provenance(
        field_name=field_name,
        method_version=method_version,
        context=canonical_json(
            {
                "field": field_name,
                "effective_at": effective_at.isoformat(),
                "source_fingerprint": source_item.get("source_fingerprint"),
            }
        ),
        origin=DataOrigin.ONS_PUBLICO,
        limitations=["Valor público do ONS usado como entrada e limite da simulação."],
        source_hashes=[source_item["source_sha256"]],
        source_item=source_item,
        use_source_period=False,
        observed_at=observed_at,
        effective_at=effective_at,
    )
    return PlantStateFact(
        value=float(value),
        value_status="previsto" if field_name == "public_forecast_mw" else "medido",
        origin=DataOrigin.ONS_PUBLICO,
        provenance=provenance,
    )


def _simulated_fact(
    *,
    field_name: str,
    value: Decimal,
    context: str,
    source_items: list[dict[str, Any]],
    parent_ids: list[str],
    as_of: datetime,
) -> PlantStateFact:
    source_hashes = sorted({_source_identity(item)[1] for item in source_items})
    provenance = field_provenance(
        field_name=field_name,
        method_version=METHOD_VERSION,
        context=context,
        origin=DataOrigin.SIMULADO,
        limitations=[_LIMITATION],
        source_hashes=source_hashes,
        source_items=source_items,
        source_uri=f"curtailess://plant-state/{field_name}",
        use_source_period=False,
        effective_at=as_of,
        parent_evidence_ids=parent_ids,
    )
    return PlantStateFact(
        value=float(value.quantize(Decimal("0.000001"))),
        value_status="simulado",
        origin=DataOrigin.SIMULADO,
        provenance=provenance,
    )


def _persist(repository: Any, response: PlantStateResponse) -> PlantStateResponse:
    repository.put_snapshot(response)
    return response


def build_plant_state(
    asset_id: str,
    as_of: datetime,
    repository: Any,
    snapshot_repository: Any,
    *,
    max_forecast_age_hours: int,
) -> PlantStateResponse:
    normalized_as_of = _normalize_as_of(as_of)
    asset = repository.get_asset(asset_id)
    if asset is None:
        raise LookupError("asset_not_found")
    identity = repository.get_identity(asset_id, normalized_as_of.date())
    source_items = [asset]
    if identity is None:
        return _persist(
            snapshot_repository,
            _review_response(
                asset_id=asset_id,
                as_of=normalized_as_of,
                reason="Identidade pública vigente não encontrada; revisão obrigatória.",
                source_items=source_items,
            ),
        )
    source_items.append(identity)
    capacity = identity.get("capacity")
    if capacity is None or _number(capacity.get("active_capacity_mw")) <= 0:
        return _persist(
            snapshot_repository,
            _review_response(
                asset_id=asset_id,
                as_of=normalized_as_of,
                reason="Capacidade pública vigente ausente; revisão obrigatória.",
                source_items=source_items,
            ),
        )
    source_items.append(capacity)
    capacity_value = _number(capacity["active_capacity_mw"])
    capacity_effective_at = datetime.combine(
        date.fromisoformat(capacity["capacity_as_of"]), datetime.min.time(), tzinfo=UTC
    )
    capacity_fact = _public_fact(
        field_name="capacity_mw",
        value=capacity_value,
        source_item=capacity,
        effective_at=capacity_effective_at,
        observed_at=capacity_effective_at,
        method_version="ons_capacity_snapshot_v1",
    )

    candidate_ids = [asset_id]
    if identity.get("ons_group_id") and identity["ons_group_id"] not in candidate_ids:
        candidate_ids.append(identity["ons_group_id"])
    forecast = next(
        (
            candidate
            for candidate_id in candidate_ids
            if (candidate := repository.get_forecast(candidate_id, normalized_as_of)) is not None
        ),
        None,
    )
    if forecast is None or forecast.get("publication_timestamp") is None:
        return _persist(
            snapshot_repository,
            _review_response(
                asset_id=asset_id,
                as_of=normalized_as_of,
                reason="Previsão pública cobrindo o instante não encontrada; revisão obrigatória.",
                source_items=source_items,
                capacity_fact=capacity_fact,
            ),
        )
    publication = datetime.fromisoformat(
        str(forecast["publication_timestamp"]).replace("Z", "+00:00")
    )
    age = normalized_as_of.astimezone(UTC) - publication.astimezone(UTC)
    if age < timedelta(0) or age > timedelta(hours=max_forecast_age_hours):
        return _persist(
            snapshot_repository,
            _review_response(
                asset_id=asset_id,
                as_of=normalized_as_of,
                reason=(
                    "Previsão pública desatualizada ou posterior ao instante; revisão obrigatória."
                ),
                source_items=source_items,
                capacity_fact=capacity_fact,
            ),
        )
    source_items.append(forecast)

    fallback_level = "none"
    profiles: list[dict[str, Any]] = []
    for candidate_id, level in ((asset_id, "asset"), (identity.get("ons_group_id"), "ons_group")):
        if not candidate_id:
            continue
        profiles = repository.get_generation_profiles(candidate_id)
        if profiles:
            fallback_level = level
            break
    if not profiles and hasattr(repository, "get_generation_profiles_by_technology_state"):
        profiles = repository.get_generation_profiles_by_technology_state(
            identity.get("technology_name") or asset.get("technology"),
            identity.get("state") or asset.get("state"),
        )
        if profiles:
            fallback_level = "technology_state"
    if not profiles:
        return _persist(
            snapshot_repository,
            _review_response(
                asset_id=asset_id,
                as_of=normalized_as_of,
                reason="Distribuição histórica pública insuficiente; revisão obrigatória.",
                source_items=source_items,
                capacity_fact=capacity_fact,
            ),
        )
    source_items.extend(profiles)
    source_items = _unique_sources(source_items)

    forecast_value = _number(forecast.get("forecast_mw"), "0")
    if forecast_value <= 0:
        forecast_value = _number(forecast.get("programmed_mw"), "0")
    forecast_value = _bounded(forecast_value, Decimal("0"), capacity_value)
    forecast_fact = _public_fact(
        field_name="public_forecast_mw",
        value=forecast_value,
        source_item=forecast,
        effective_at=normalized_as_of,
        observed_at=publication,
        method_version="ons_program_forecast_v1",
    )

    profile_values = []
    hour_key = f"{normalized_as_of.hour:02d}"
    for profile in profiles:
        hour = profile.get("hour_of_day_profile", {}).get(hour_key)
        value = hour.get("mean_mw") if hour else profile.get("mean_generation_mw")
        if value is not None:
            profile_values.append(_number(value))
    if not profile_values:
        return _persist(
            snapshot_repository,
            _review_response(
                asset_id=asset_id,
                as_of=normalized_as_of,
                reason=(
                    "Perfil histórico público não cobre o horário solicitado; revisão obrigatória."
                ),
                source_items=source_items,
                capacity_fact=capacity_fact,
            ),
        )
    historical_mean = sum(profile_values, Decimal("0")) / Decimal(len(profile_values))
    reference_total = max(_number(asset.get("reference_generation_mwh")), Decimal("1"))
    availability_ratio = _bounded(
        _number(asset.get("availability_mwh")) / reference_total,
        Decimal("0"),
        Decimal("1"),
    )
    generation_ratio = _bounded(
        _number(asset.get("generation_mwh")) / reference_total,
        Decimal("0"),
        Decimal("1"),
    )
    availability_limited = _number(asset.get("availability_limited_mwh"))
    limit_ratio = (
        _bounded(
            _number(asset.get("limited_generation_mwh")) / availability_limited,
            Decimal("0"),
            Decimal("1"),
        )
        if availability_limited > 0
        else Decimal("1")
    )
    source_snapshot_ids = tuple(sorted({_source_identity(item)[1] for item in source_items}))
    seed_payload = canonical_json(
        {
            "asset_id": asset_id,
            "as_of": normalized_as_of.isoformat(),
            "source_snapshot_ids": source_snapshot_ids,
            "method_version": METHOD_VERSION,
        }
    )
    noise = _hash_noise(seed_payload)
    reference = _bounded(
        (forecast_value * Decimal("0.7")) + (historical_mean * Decimal("0.3")),
        Decimal("0"),
        capacity_value,
    )
    availability = _bounded(capacity_value * availability_ratio, Decimal("0"), capacity_value)
    generation_limit = _bounded(
        min(reference, availability) * limit_ratio,
        Decimal("0"),
        min(reference, availability),
    )
    generation = _bounded(
        reference * generation_ratio * (Decimal("1") + noise),
        Decimal("0"),
        generation_limit,
    )
    context = canonical_json(
        {
            "seed_sha256": hashlib.sha256(seed_payload.encode()).hexdigest(),
            "fallback_level": fallback_level,
            "forecast_mw": str(forecast_value),
            "historical_mean_mw": str(historical_mean),
            "availability_ratio": str(availability_ratio),
            "generation_ratio": str(generation_ratio),
            "limit_ratio": str(limit_ratio),
        }
    )
    parent_ids = [capacity_fact.provenance.evidence_id, forecast_fact.provenance.evidence_id]
    facts = {
        field_name: _simulated_fact(
            field_name=field_name,
            value=value,
            context=context,
            source_items=source_items,
            parent_ids=parent_ids,
            as_of=normalized_as_of,
        )
        for field_name, value in (
            ("generation_mw", generation),
            ("availability_mw", availability),
            ("reference_generation_mw", reference),
            ("generation_limit_mw", generation_limit),
        )
    }
    snapshot_identity = {
        "asset_id": asset_id,
        "as_of": normalized_as_of.isoformat(),
        "source_snapshot_ids": source_snapshot_ids,
        "method_version": METHOD_VERSION,
        "facts": {name: fact.value for name, fact in facts.items()},
    }
    response = PlantStateResponse(
        snapshot_id=f"pst1.{canonical_digest(snapshot_identity)}",
        asset_id=asset_id,
        as_of=normalized_as_of,
        status="SIMULATED",
        fallback_level=fallback_level,
        public_forecast_mw=forecast_fact,
        capacity_mw=capacity_fact,
        source_snapshot_ids=source_snapshot_ids,
        limitations=(_LIMITATION,),
        **facts,
    )
    return _persist(snapshot_repository, response)


class PlantStateRepository:
    def __init__(self, table: Any):
        self.table = table

    def put_snapshot(self, response: PlantStateResponse) -> PlantStateResponse:
        response_json = canonical_json(response.model_dump(mode="json"))
        item = {
            "plant_id": f"PLANT_STATE#{response.asset_id}",
            "scenario_id": response.snapshot_id,
            "record_type": "plant_state_snapshot",
            "response_json": response_json,
            "response_sha256": hashlib.sha256(response_json.encode()).hexdigest(),
        }
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
            existing = self.table.get_item(
                Key={"plant_id": item["plant_id"], "scenario_id": item["scenario_id"]},
                ConsistentRead=True,
            ).get("Item")
            if existing != item:
                raise RuntimeError("deterministic plant-state snapshot conflict") from exc
        return response

    def get_snapshot(self, asset_id: str, snapshot_id: str) -> dict[str, Any] | None:
        item = self.table.get_item(
            Key={"plant_id": f"PLANT_STATE#{asset_id}", "scenario_id": snapshot_id},
            ConsistentRead=True,
        ).get("Item")
        return None if item is None else item


class UnconfiguredPlantStateRepository:
    def put_snapshot(self, response: PlantStateResponse) -> PlantStateResponse:
        return response

    def get_snapshot(self, asset_id: str, snapshot_id: str) -> None:
        del asset_id, snapshot_id
        return None


def create_plant_state_repository(table_name: str | None, region_name: str) -> Any:
    if not table_name:
        return UnconfiguredPlantStateRepository()
    table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)
    return PlantStateRepository(table)
