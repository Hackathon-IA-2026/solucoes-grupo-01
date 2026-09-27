from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from .canonical import canonical_digest
from .schemas import MaintenanceEngineResult, MaintenanceWindowEvaluation

METHOD_VERSION = "residual_saleable_energy_v1"
LOCAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")
_LIMITATION = (
    "Ranking determinístico de janelas candidatas; não representa aprovação ou "
    "coordenação operacional do ONS."
)


def _number(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _day_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=LOCAL_TIMEZONE)


def _period_bounds(period: Any) -> tuple[date, date]:
    if isinstance(period, tuple):
        return period
    return period.start, period.end


def _overlaps_unavailable(
    window_start: date, window_end_exclusive: date, unavailable_periods: list[Any]
) -> bool:
    return any(
        window_start <= period_end and period_start < window_end_exclusive
        for period_start, period_end in map(_period_bounds, unavailable_periods)
    )


def _all_business_days(window_start: date, duration_days: int) -> bool:
    return all(
        (window_start + timedelta(days=offset)).weekday() < 5 for offset in range(duration_days)
    )


def _source_hashes(records: list[dict[str, Any]], plant_state: Any) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                *getattr(plant_state, "source_snapshot_ids", ()),
                *(str(record["source_sha256"]) for record in records),
            }
        )
    )


def _candidate_id(
    *,
    asset_id: str,
    start: datetime,
    end: datetime,
    plant_state: Any,
    source_snapshot_ids: tuple[str, ...],
    rejection_reasons: tuple[str, ...],
) -> str:
    return "mw1." + canonical_digest(
        {
            "asset_id": asset_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "plant_state_snapshot_id": plant_state.snapshot_id,
            "source_snapshot_ids": source_snapshot_ids,
            "rejection_reasons": rejection_reasons,
            "method_version": METHOD_VERSION,
        }
    )


def _seasonal_profiles(
    historical_records: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in historical_records:
        try:
            month = int(str(record["period"])[5:7])
            interval_count = int(record["interval_count"])
            if not 1 <= month <= 12 or interval_count <= 0:
                continue
            grouped[month].append(record)
        except (KeyError, TypeError, ValueError):
            continue

    profiles = {}
    for month, records in grouped.items():
        potential_rates = []
        curtailment_rates = []
        for record in records:
            observed_hours = Decimal(int(record["interval_count"])) * Decimal("0.5")
            generation = _number(record.get("generation_mwh"))
            curtailed = _number(record.get("curtailed_mwh"))
            availability = _number(record.get("availability_mwh"))
            potential = min(availability, generation + curtailed)
            if observed_hours <= 0 or potential <= 0:
                continue
            potential_rates.append(potential / observed_hours)
            curtailment_rates.append(min(Decimal("1"), curtailed / potential))
        if potential_rates:
            profiles[month] = {
                "potential_mw": sum(potential_rates, Decimal("0")) / Decimal(len(potential_rates)),
                "curtailment_ratio": sum(curtailment_rates, Decimal("0"))
                / Decimal(len(curtailment_rates)),
                "record_count": len(potential_rates),
                "records": records,
            }
    return profiles


def _quality_penalty(
    fallback_level: str, record_count: int
) -> tuple[Decimal, str, tuple[str, ...]]:
    fallback_penalties = {
        "asset": Decimal("0.02"),
        "ons_group": Decimal("0.08"),
        "technology_state": Decimal("0.15"),
    }
    penalty = fallback_penalties.get(fallback_level, Decimal("0.20"))
    reasons = []
    if fallback_level != "asset":
        reasons.append(f"Distribuição histórica obtida pelo fallback {fallback_level}.")
    if record_count < 2:
        penalty += Decimal("0.05")
        reasons.append("A sazonalidade usa menos de dois períodos históricos comparáveis.")
    risk = (
        "low" if penalty <= Decimal("0.04") else "medium" if penalty <= Decimal("0.10") else "high"
    )
    return penalty, risk, tuple(reasons)


def evaluate_maintenance_windows(
    *,
    asset_id: str,
    as_of: datetime,
    planning_start: date,
    planning_end: date,
    duration_days: int,
    minimum_notice_hours: int,
    weekdays_only: bool,
    unavailable_periods: list[Any],
    energy_price_brl_mwh: float,
    plant_state: Any,
    historical_records: list[dict[str, Any]],
) -> MaintenanceEngineResult:
    if as_of.tzinfo is None:
        raise ValueError("as_of requires timezone information")
    if duration_days <= 0:
        raise ValueError("duration_days must be positive")
    if planning_start > planning_end:
        raise ValueError("planning_start must not be after planning_end")
    if energy_price_brl_mwh < 0:
        raise ValueError("energy_price_brl_mwh must be non-negative")

    latest_start = planning_end - timedelta(days=duration_days - 1)
    profiles = _seasonal_profiles(historical_records)
    eligible: list[MaintenanceWindowEvaluation] = []
    rejected: list[MaintenanceWindowEvaluation] = []
    notice_threshold = as_of.astimezone(LOCAL_TIMEZONE) + timedelta(hours=minimum_notice_hours)
    reference_mw = _number(
        getattr(getattr(plant_state, "reference_generation_mw", None), "value", 0)
    )
    capacity_mw = _number(getattr(getattr(plant_state, "capacity_mw", None), "value", 0))

    current = planning_start
    while current <= latest_start:
        start = _day_start(current)
        end = start + timedelta(days=duration_days)
        reasons = []
        if start < notice_threshold:
            reasons.append("MINIMUM_NOTICE_NOT_MET")
        if weekdays_only and not _all_business_days(current, duration_days):
            reasons.append("NON_BUSINESS_DAY")
        if _overlaps_unavailable(
            current, current + timedelta(days=duration_days), unavailable_periods
        ):
            reasons.append("UNAVAILABLE_PERIOD_OVERLAP")
        if plant_state.status != "SIMULATED":
            reasons.append("PLANT_STATE_REVIEW_REQUIRED")

        daily_profiles = []
        for offset in range(duration_days):
            month = (current + timedelta(days=offset)).month
            if month not in profiles:
                reasons.append("MISSING_HISTORICAL_DISTRIBUTION")
                break
            daily_profiles.append(profiles[month])
        rejection_reasons = tuple(sorted(set(reasons)))
        window_records = [record for profile in daily_profiles for record in profile["records"]]
        snapshot_ids = _source_hashes(window_records, plant_state)
        candidate_id = _candidate_id(
            asset_id=asset_id,
            start=start,
            end=end,
            plant_state=plant_state,
            source_snapshot_ids=snapshot_ids,
            rejection_reasons=rejection_reasons,
        )
        if rejection_reasons:
            rejected.append(
                MaintenanceWindowEvaluation(
                    candidate_id=candidate_id,
                    start=start,
                    end=end,
                    eligible=False,
                    rejection_reasons=rejection_reasons,
                    data_quality_risk="high",
                    risk_reasons=("A janela não satisfaz todos os critérios de elegibilidade.",),
                    source_snapshot_ids=snapshot_ids,
                )
            )
            current += timedelta(days=1)
            continue

        energy_not_injected = Decimal("0")
        expected_curtailment = Decimal("0")
        record_count = 0
        for profile in daily_profiles:
            seasonal_mw = min(capacity_mw, profile["potential_mw"])
            projected_mw = min(
                capacity_mw,
                reference_mw * Decimal("0.3") + seasonal_mw * Decimal("0.7"),
            )
            daily_energy = projected_mw * Decimal("24")
            energy_not_injected += daily_energy
            expected_curtailment += daily_energy * profile["curtailment_ratio"]
            record_count += profile["record_count"]
        expected_curtailment = min(energy_not_injected, expected_curtailment)
        residual_saleable = max(Decimal("0"), energy_not_injected - expected_curtailment)
        penalty_ratio, quality_risk, risk_reasons = _quality_penalty(
            plant_state.fallback_level, record_count
        )
        uncertainty_penalty = energy_not_injected * penalty_ratio
        objective_score = residual_saleable + uncertainty_penalty
        opportunity_cost = objective_score * Decimal(str(energy_price_brl_mwh))
        eligible.append(
            MaintenanceWindowEvaluation(
                candidate_id=candidate_id,
                start=start,
                end=end,
                eligible=True,
                energy_not_injected_mwh=float(energy_not_injected.quantize(Decimal("0.000001"))),
                expected_curtailment_mwh=float(expected_curtailment.quantize(Decimal("0.000001"))),
                residual_saleable_mwh=float(residual_saleable.quantize(Decimal("0.000001"))),
                uncertainty_penalty_mwh=float(uncertainty_penalty.quantize(Decimal("0.000001"))),
                opportunity_cost_brl=float(opportunity_cost.quantize(Decimal("0.01"))),
                objective_score_mwh=float(objective_score.quantize(Decimal("0.000001"))),
                data_quality_risk=quality_risk,
                risk_reasons=risk_reasons,
                source_snapshot_ids=snapshot_ids,
            )
        )
        current += timedelta(days=1)

    eligible.sort(
        key=lambda item: (
            item.residual_saleable_mwh,
            item.uncertainty_penalty_mwh,
            item.opportunity_cost_brl,
            item.start,
            item.candidate_id,
        )
    )
    ranked = tuple(
        item.model_copy(update={"rank": rank}) for rank, item in enumerate(eligible, start=1)
    )
    if ranked:
        status = "RANKED"
    elif plant_state.status != "SIMULATED":
        status = "REVIEW_REQUIRED"
    else:
        status = "NO_ELIGIBLE_WINDOW"
    limitations = (
        _LIMITATION,
        "Objetivo primário: menor energia residual vendável durante a indisponibilidade.",
        "Desempates: incerteza, custo de oportunidade, início e identificador da janela.",
    )
    return MaintenanceEngineResult(
        asset_id=asset_id,
        status=status,
        eligible_windows=ranked,
        rejected_windows=tuple(rejected),
        limitations=limitations,
    )
