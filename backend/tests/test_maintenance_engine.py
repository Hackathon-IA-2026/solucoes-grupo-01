from datetime import UTC, date, datetime
from types import SimpleNamespace

from curtailess.maintenance_engine import evaluate_maintenance_windows

AS_OF = datetime(2026, 1, 20, 12, tzinfo=UTC)


def fact(value: float):
    return SimpleNamespace(value=value)


def plant_state(fallback_level: str = "asset"):
    return SimpleNamespace(
        status="SIMULATED",
        snapshot_id="pst1." + "a" * 64,
        fallback_level=fallback_level,
        capacity_mw=fact(100),
        reference_generation_mw=fact(70),
        source_snapshot_ids=("a" * 64,),
    )


def history_record(
    period: str,
    *,
    generation_mwh: float,
    curtailed_mwh: float,
    availability_mwh: float,
):
    return {
        "asset_id": "CJU_TEST",
        "period": period,
        "interval_count": 48,
        "generation_mwh": generation_mwh,
        "curtailed_mwh": curtailed_mwh,
        "availability_mwh": availability_mwh,
        "source_key": f"raw/ons/restricao/{period}.parquet",
        "source_sha256": ("1" if period.endswith("01") else "2") * 64,
        "source_fingerprint": ("3" if period.endswith("01") else "4") * 64,
    }


def test_generated_windows_preserve_multi_day_duration_and_order_by_residual_energy() -> None:
    result = evaluate_maintenance_windows(
        asset_id="CJU_TEST",
        as_of=AS_OF,
        planning_start=date(2026, 1, 29),
        planning_end=date(2026, 2, 6),
        duration_days=2,
        minimum_notice_hours=24,
        weekdays_only=False,
        unavailable_periods=[],
        energy_price_brl_mwh=200,
        plant_state=plant_state(),
        historical_records=[
            history_record(
                "2025-01",
                generation_mwh=600,
                curtailed_mwh=400,
                availability_mwh=1000,
            ),
            history_record(
                "2025-02",
                generation_mwh=100,
                curtailed_mwh=100,
                availability_mwh=200,
            ),
        ],
    )

    assert result.status == "RANKED"
    assert result.eligible_windows
    assert all(
        (candidate.end - candidate.start).total_seconds() == 2 * 24 * 3600
        for candidate in result.eligible_windows
    )
    assert result.eligible_windows[0].start.date().month == 2
    assert (
        result.eligible_windows[0].residual_saleable_mwh
        < result.eligible_windows[-1].residual_saleable_mwh
    )


def test_high_curtailment_does_not_win_when_residual_saleable_energy_is_larger() -> None:
    result = evaluate_maintenance_windows(
        asset_id="CJU_TEST",
        as_of=AS_OF,
        planning_start=date(2026, 1, 31),
        planning_end=date(2026, 2, 3),
        duration_days=1,
        minimum_notice_hours=0,
        weekdays_only=False,
        unavailable_periods=[],
        energy_price_brl_mwh=1,
        plant_state=plant_state(),
        historical_records=[
            history_record(
                "2025-01",
                generation_mwh=600,
                curtailed_mwh=400,
                availability_mwh=1000,
            ),
            history_record(
                "2025-02",
                generation_mwh=100,
                curtailed_mwh=100,
                availability_mwh=200,
            ),
        ],
    )

    january = next(item for item in result.eligible_windows if item.start.date().month == 1)
    february = next(item for item in result.eligible_windows if item.start.date().month == 2)
    assert january.expected_curtailment_mwh > february.expected_curtailment_mwh
    assert january.residual_saleable_mwh > february.residual_saleable_mwh
    assert february.rank < january.rank


def test_infeasible_windows_are_rejected_with_reason_codes() -> None:
    result = evaluate_maintenance_windows(
        asset_id="CJU_TEST",
        as_of=datetime(2026, 1, 30, 12, tzinfo=UTC),
        planning_start=date(2026, 1, 31),
        planning_end=date(2026, 2, 5),
        duration_days=2,
        minimum_notice_hours=72,
        weekdays_only=True,
        unavailable_periods=[(date(2026, 2, 3), date(2026, 2, 4))],
        energy_price_brl_mwh=100,
        plant_state=plant_state(),
        historical_records=[
            history_record(
                "2025-01",
                generation_mwh=600,
                curtailed_mwh=400,
                availability_mwh=1000,
            ),
            history_record(
                "2025-02",
                generation_mwh=100,
                curtailed_mwh=100,
                availability_mwh=200,
            ),
        ],
    )

    assert result.rejected_windows
    codes = {code for window in result.rejected_windows for code in window.rejection_reasons}
    assert "MINIMUM_NOTICE_NOT_MET" in codes
    assert "NON_BUSINESS_DAY" in codes
    assert "UNAVAILABLE_PERIOD_OVERLAP" in codes


def test_review_required_plant_state_rejects_every_window() -> None:
    state = plant_state()
    state.status = "REVIEW_REQUIRED"
    result = evaluate_maintenance_windows(
        asset_id="CJU_TEST",
        as_of=AS_OF,
        planning_start=date(2026, 2, 1),
        planning_end=date(2026, 2, 3),
        duration_days=1,
        minimum_notice_hours=0,
        weekdays_only=False,
        unavailable_periods=[],
        energy_price_brl_mwh=100,
        plant_state=state,
        historical_records=[],
    )

    assert result.status == "REVIEW_REQUIRED"
    assert not result.eligible_windows
    assert all(
        "PLANT_STATE_REVIEW_REQUIRED" in window.rejection_reasons
        for window in result.rejected_windows
    )
