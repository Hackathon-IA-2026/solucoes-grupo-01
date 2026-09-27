"""Focused tests for the individual plant risk and energy forecast (plan Task 3)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from curtailess.plant_exposure_forecast import (
    FEATURE_NAMES,
    HORIZON_DAYS,
    PROBABILITY_SOURCE_BASELINE,
    LogisticModel,
    PlantDailyHistory,
    PlantForecastInputs,
    brier_score,
    build_plant_forecast,
    candidate_eligibility,
    count_outside_support,
    default_backtest_plan,
    enforce_published_series,
    feature_row,
    fit_logistic_model,
    fit_platt_calibration,
    forward_probabilities,
    probability_distribution,
    reliability_bins,
    run_backtest,
    seasonal_rates,
    validate_forecast_artifact,
)
from curtailess.point_exposure_simulation import (
    INTERVALS_PER_DAY,
    MaintenanceSchedule,
    PlantSimulationSpec,
    PointSimulationSpec,
    build_maintenance_schedule,
    build_scenario_samples,
    climatology_outlook,
)

BUNDLED_FORECAST = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "curtailess"
    / "data"
    / "individual_plant_forecast.json"
)
START = date(2024, 4, 1)


def synthetic_history(
    *,
    asset_id: str = "PLANT1",
    days: int = 908,
    event_rate: float = 0.8,
    mean_mwh: float = 100.0,
) -> PlantDailyHistory:
    """Deterministic synthetic history with a seasonal event pattern."""
    dates: list[date] = []
    restricted: list[bool] = []
    curtailed: list[float] = []
    for offset in range(days):
        day = START + timedelta(days=offset)
        dates.append(day)
        seasonal = 0.1 if day.month in (1, 2, 3) else 0.0
        index = (offset * 7919) % 1000 / 1000.0
        event = index < min(max(event_rate - seasonal, 0.0), 0.99)
        restricted.append(event)
        curtailed.append(round(mean_mwh * (1.0 + 0.5 * index) if event else 0.0, 6))
    return PlantDailyHistory(
        asset_id=asset_id,
        days=tuple(dates),
        restricted=tuple(restricted),
        curtailed_mwh=tuple(curtailed),
    )


def plant_spec(
    *, plant_id: str, capacity_mw: float = 100.0, level: float = 12.0
) -> PlantSimulationSpec:
    return PlantSimulationSpec(
        plant_id=plant_id,
        name=plant_id,
        capacity_mw=capacity_mw,
        technology="wind",
        month_hour_climatology=(level,) * (12 * INTERVALS_PER_DAY),
        potential_lookup=tuple(min(capacity_mw, index * 10.0) for index in range(41)),
        lookup_step=1.0,
        relative_spread=0.1,
        availability_mean=1.0,
        availability_spread=0.0,
        restricted_day_share=0.8,
    )


def build_forecast(
    *,
    history: PlantDailyHistory,
    slope: float,
    intercept_mw: float,
    scenario_count: int = 6,
    horizon_days: int = HORIZON_DAYS,
    level: float = 12.0,
    maintenance_for_selected: bool = True,
) -> dict:
    spec = PointSimulationSpec(
        point_id="POINT-1",
        plants=(
            plant_spec(plant_id=history.asset_id, level=level),
            plant_spec(plant_id="OTHER", capacity_mw=50.0),
        ),
        envelope_intercept_mw=intercept_mw,
        envelope_slope=slope,
        installed_capacity_mw=150.0,
        selected_asset_id=history.asset_id,
    )
    days = tuple(
        START + timedelta(days=len(history.days) + offset) for offset in range(horizon_days)
    )
    samples = build_scenario_samples(
        spec, days=days, outlook=climatology_outlook(spec.point_id), scenario_count=scenario_count
    )
    schedule = build_maintenance_schedule(
        spec,
        days=days,
        seed=0,
        include_plant_id=history.asset_id if maintenance_for_selected else None,
    )
    return build_plant_forecast(
        plant=PlantForecastInputs(
            asset_id=history.asset_id,
            name="Usina Sintética",
            technology="wind",
            state="RN",
            ceg="EOL.CV.RN.000001-1.01",
            ons_group_id="CJU_TEST",
            ons_group_name="Conjunto Teste",
            connection_point="POINT-1",
            capacity_mw=100.0,
            history=history,
        ),
        spec=spec,
        samples=samples,
        schedule=schedule,
        days=days,
        weather_normal_z={},
        point_share=tuple(0.5 for _ in history.days),
        backtest_plan=default_backtest_plan(len(history.days)),
        weather_source="ons_plant_climatology",
        weather_unit="m/s",
        scenario_count=scenario_count,
    )


def test_features_use_shift_one_and_never_the_forecast_day() -> None:
    history = synthetic_history(days=60)
    day = history.days[30]
    baseline = feature_row(
        day=day,
        history=history,
        point_share=tuple(0.5 for _ in history.days),
        month_rate=0.5,
        weekday_rate=0.5,
        weather_normal_z=0.0,
        capacity_mw=100.0,
    )
    changed = PlantDailyHistory(
        asset_id=history.asset_id,
        days=history.days,
        restricted=tuple(
            True if index == 30 else flag for index, flag in enumerate(history.restricted)
        ),
        curtailed_mwh=tuple(
            9999.0 if index == 30 else value for index, value in enumerate(history.curtailed_mwh)
        ),
    )
    after = feature_row(
        day=day,
        history=changed,
        point_share=tuple(0.5 for _ in history.days),
        month_rate=0.5,
        weekday_rate=0.5,
        weather_normal_z=0.0,
        capacity_mw=100.0,
    )

    assert baseline == after
    assert len(baseline) == len(FEATURE_NAMES)


def test_no_feature_reads_verified_generation_availability_or_capacity_factor() -> None:
    forbidden = (
        "val_geracaoverificada",
        "verified_generation",
        "availability",
        "capacity_factor",
        "geracaoverificada",
    )

    assert not any(token in name for name in FEATURE_NAMES for token in forbidden)


def test_probability_stays_bounded_and_interval_contains_the_expected_value() -> None:
    payload = build_forecast(history=synthetic_history(), slope=0.0, intercept_mw=500.0)

    for row in payload["forecasts"]:
        assert 0.0 <= row["curtailment_probability"] <= 1.0
        assert row["lower_mwh"] <= row["expected_curtailed_mwh"] <= row["upper_mwh"]
        assert row["expected_curtailed_mwh"] >= 0.0
        assert row["potential_generation_mwh"] >= 0.0
        assert row["scheduled_maintenance_relief_mwh"] >= 0.0
        assert row["risk_reduction_percentage_points"] >= 0.0


def test_expected_energy_is_not_probability_times_severity() -> None:
    # With slope 1 the envelope always covers the potential, so no MWh are curtailed even
    # though the plant is historically restricted on most days.
    payload = build_forecast(history=synthetic_history(event_rate=0.8), slope=1.0, intercept_mw=0.0)

    probabilities = [row["curtailment_probability"] for row in payload["forecasts"]]
    expected = [row["expected_curtailed_mwh"] for row in payload["forecasts"]]

    assert max(probabilities) > 0.5
    assert max(expected) == pytest.approx(0.0, abs=1e-9)


def test_low_frequency_plant_never_returns_the_old_ninety_nine_percent() -> None:
    payload = build_forecast(
        history=synthetic_history(event_rate=0.05), slope=0.3, intercept_mw=200.0
    )

    probabilities = [row["curtailment_probability"] for row in payload["forecasts"]]

    assert max(probabilities) < 0.5
    assert payload["probability_diagnostics"]["days_at_or_above_99_pct"] == 0
    assert payload["probability_diagnostics"]["min"] < 0.2


def test_probability_varies_with_season_and_recent_activity() -> None:
    history = synthetic_history(event_rate=0.6)
    payload = build_forecast(history=history, slope=0.2, intercept_mw=300.0)

    probabilities = [row["curtailment_probability"] for row in payload["forecasts"]]
    distribution = payload["probability_diagnostics"]

    # The model's own forward trajectory varies with season and recent activity.
    model_forward = distribution["model_forward_probabilities"]
    assert len({round(value, 4) for value in model_forward}) > 3
    assert max(model_forward) > min(model_forward)
    assert distribution["max"] > distribution["min"]
    assert distribution["median"] > 0.0
    # The published series is whatever the frozen validation policy chose. Under the strict
    # support rule that may legitimately be a constant baseline, published honestly as one row
    # per date; what can never happen is a model series leaving the frozen support.
    published = distribution["published"]
    if published["candidate"] in {"model_raw", "model_calibrated"}:
        assert published["future_days_outside_support"] == 0
    else:
        assert published["candidate"].startswith("baseline_")
    assert len(set(probabilities)) >= 1
    assert all(0.0 <= value <= 1.0 for value in probabilities)


def test_materialization_fails_when_every_day_is_above_the_alert_threshold() -> None:
    with pytest.raises(ValueError, match="acima de 95%"):
        enforce_published_series("PLANT1", [0.99] * 60)
    with pytest.raises(ValueError, match="95%"):
        enforce_published_series("PLANT1", [0.96] * 60)
    with pytest.raises(ValueError, match="inválida"):
        enforce_published_series("PLANT1", [1.4] * 60)
    # A constant published series is allowed: the frozen policy may pick a constant baseline,
    # and it is published honestly, one row per date, instead of a saturated model series.
    constant = enforce_published_series(
        "PLANT1", [0.5] * 60, candidate="baseline_frequency"
    )
    assert constant["days_above_95_pct"] == 0
    assert constant["distinct_values"] == 1
    assert constant["saturated"] is False
    # Isolated days above the alert threshold remain allowed for a baseline source.
    distribution = enforce_published_series(
        "PLANT1", [0.4 + 0.009 * index for index in range(60)], candidate="baseline_frequency"
    )
    assert distribution["days"] == 60
    assert distribution["days_above_95_pct"] == 0
    assert distribution["distinct_values"] == 60
    assert distribution["saturated"] is False


def test_published_gate_refuses_any_model_day_outside_the_frozen_support() -> None:
    """Strict, auditable policy: no tolerance, no clamp, no jitter. A model series with a single
    day outside the support the validation paths froze is refused instead of published."""
    inside = [0.5] * 59 + [0.9]
    allowed = enforce_published_series(
        "PLANT1",
        inside,
        candidate="model_raw",
        support_low=0.4,
        support_high=0.9,
    )
    assert allowed["days"] == 60
    with pytest.raises(ValueError, match="fora do suporte"):
        enforce_published_series(
            "PLANT1",
            [0.5] * 59 + [0.900001],
            candidate="model_raw",
            support_low=0.4,
            support_high=0.9,
        )
    # A constant baseline is a declared fallback, never refused by the support rule.
    fallback = enforce_published_series(
        "PLANT1",
        [0.95] * 60,
        candidate="baseline_frequency",
        support_low=0.4,
        support_high=0.9,
    )
    assert fallback["distinct_values"] == 1


def test_count_outside_support_bounds_the_frozen_validation_range() -> None:
    assert count_outside_support([0.5, 0.8], support_low=0.4, support_high=0.9) == 0
    assert count_outside_support([0.3, 0.5, 0.95], support_low=0.4, support_high=0.9) == 2
    # The bounds are inclusive: the extreme values of the validation paths are inside.
    assert count_outside_support([0.4, 0.9], support_low=0.4, support_high=0.9) == 0
    # An undefined support means nothing was validated, so every day is outside.
    assert count_outside_support([0.5, 0.5], support_low=None, support_high=None) == 2


def test_candidate_eligibility_refuses_a_model_that_leaves_the_frozen_support() -> None:
    # The BAEA52 case: the validation paths never saw probabilities near the horizon, so both the
    # raw and the calibrated model are extrapolation even though the calibration map itself was
    # rejected. A constant baseline stays eligible.
    horizon = [0.93 + 0.001 * index for index in range(HORIZON_DAYS)]
    raw = candidate_eligibility(
        name="model_raw",
        probabilities=horizon,
        support_low=0.611629,
        support_high=0.89008,
        calibration_applied=False,
    )
    assert raw["eligible"] is False
    assert raw["outside_support_days"] == HORIZON_DAYS
    assert "extrapolação" in raw["reason"]

    calibrated = candidate_eligibility(
        name="model_calibrated",
        probabilities=horizon,
        support_low=0.611629,
        support_high=0.89008,
        calibration_applied=False,
    )
    assert calibrated["eligible"] is False

    baseline = candidate_eligibility(
        name="baseline_frequency",
        probabilities=[0.6] * HORIZON_DAYS,
        support_low=0.611629,
        support_high=0.89008,
        calibration_applied=False,
    )
    assert baseline["eligible"] is True

    # A model series inside the support stays eligible.
    inside = candidate_eligibility(
        name="model_raw",
        probabilities=[0.62 + 0.004 * index for index in range(HORIZON_DAYS)],
        support_low=0.611629,
        support_high=0.89008,
        calibration_applied=True,
    )
    assert inside["eligible"] is True
    assert inside["outside_support_days"] == 0

    # The strict policy is the whole point: a single isolated day outside the support is already
    # enough to refuse the model, with no tolerance, clamp or jitter.
    near = candidate_eligibility(
        name="model_raw",
        probabilities=[0.6, 0.62] + [0.7] * (HORIZON_DAYS - 2),
        support_low=0.611629,
        support_high=0.89008,
        calibration_applied=True,
    )
    assert near["outside_support_days"] == 1
    assert near["eligible"] is False
    assert "1 de 60" in near["reason"]


def test_candidate_eligibility_still_refuses_saturated_baselines() -> None:
    saturated = candidate_eligibility(
        name="baseline_persistence",
        probabilities=[1.0] * HORIZON_DAYS,
        support_low=0.3,
        support_high=0.99,
        calibration_applied=False,
    )
    assert saturated["eligible"] is False
    assert "saturada" in saturated["reason"]


def test_published_gate_has_no_arbitrary_dose_rule() -> None:
    """The old ``PUBLISHED_DOZENS_ABOVE_95`` threshold is gone: eligibility is decided by the
    strict support rule, not by counting how many days sit above an arbitrary level."""
    series = [0.96] * 30 + [0.4] * 30
    # A baseline with dozens of days above 95% is allowed: the validation ranking chose it.
    allowed = enforce_published_series(
        "PLANT1", series, candidate="baseline_frequency", support_low=0.3, support_high=0.99
    )
    assert allowed["days_above_95_pct"] == 30
    assert allowed["saturated"] is False
    # The same series as a model with any day outside the support is refused.
    with pytest.raises(ValueError, match="fora do suporte"):
        enforce_published_series(
            "PLANT1", series, candidate="model_raw", support_low=0.3, support_high=0.95
        )


def test_small_sample_seasonal_rates_are_shrunk_toward_the_base_rate() -> None:
    # A plant restricted on every day of the fitting window: without shrinkage the weekday
    # feature would reach logit(1.0) = 9.21 and saturate the whole horizon.
    history = PlantDailyHistory(
        asset_id="PLANT1",
        days=tuple(START + timedelta(days=offset) for offset in range(120)),
        restricted=tuple(1.0 for _ in range(120)),
        curtailed_mwh=tuple(10.0 for _ in range(120)),
    )
    month_rates, weekday_rates, overall = seasonal_rates(history, index=120)
    row = feature_row(
        day=START + timedelta(days=121),
        history=history,
        point_share=[0.0] * 120,
        month_rate=month_rates.get((START + timedelta(days=121)).month, overall),
        weekday_rate=weekday_rates.get((START + timedelta(days=121)).weekday(), overall),
        weather_normal_z=0.0,
        capacity_mw=100.0,
    )

    assert overall == pytest.approx(1.0)
    assert all(rate <= 1.0 for rate in month_rates.values())
    assert all(rate <= 1.0 for rate in weekday_rates.values())
    assert row[3] < 9.0  # event_rate_7d stays below logit(1.0) = 9.21
    assert row[4] < 9.0

    # With a base rate below 1.0 the shrinkage pulls a fully restricted category down, which is
    # what keeps the seasonal feature away from the saturated logit.
    mixed = PlantDailyHistory(
        asset_id="PLANT2",
        days=tuple(START + timedelta(days=offset) for offset in range(120)),
        restricted=tuple(1.0 if index % 5 else 0.0 for index in range(120)),
        curtailed_mwh=tuple(10.0 for _ in range(120)),
    )
    mixed_month, mixed_weekday, mixed_overall = seasonal_rates(mixed, index=120)
    assert mixed_overall == pytest.approx(0.8)
    assert all(rate < 1.0 for rate in mixed_month.values())
    assert all(rate < 1.0 for rate in mixed_weekday.values())


def test_recursive_feedback_keeps_a_persistently_restricted_plant_off_saturation() -> None:
    """Regression for the BAEA52 gate: a plant restricted on every recent day must still
    produce a 60-day distribution that leaves the alert band and varies."""
    days = 908
    history = PlantDailyHistory(
        asset_id="BAEA52",
        days=tuple(START + timedelta(days=offset) for offset in range(days)),
        restricted=tuple(
            1.0 if index >= 300 else (1.0 if index % 4 else 0.0) for index in range(days)
        ),
        curtailed_mwh=tuple(
            120.0 if index >= 300 else (120.0 if index % 4 else 0.0) for index in range(days)
        ),
    )
    plan = default_backtest_plan(days)
    result = run_backtest(
        history=history,
        point_share=tuple(0.8 for _ in range(days)),
        weather_normal_z={},
        capacity_mw=100.0,
        plan=plan,
    )
    horizon = tuple(START + timedelta(days=days + offset) for offset in range(HORIZON_DAYS))
    probabilities = forward_probabilities(
        history=history,
        point_share=tuple(0.8 for _ in range(days)),
        weather_normal_z={},
        capacity_mw=100.0,
        horizon_days=horizon,
        simulated_mwh=[120.0] * HORIZON_DAYS,
        calibration=None,
        calibration_accepted=False,
        l2=result.l2_penalty,
    )
    distribution = enforce_published_series("BAEA52", probabilities)

    assert distribution["days_above_95_pct"] < HORIZON_DAYS
    assert distribution["min"] < 0.95
    assert distribution["distinct_values"] >= 10
    assert result.l2_selection["selection_basis"] == "validation_paths_only"
    assert result.l2_penalty in {candidate["l2"] for candidate in result.l2_selection["candidates"]}


def test_calibration_is_rejected_when_it_inflates_the_alert_band() -> None:
    # Validation much more restricted than test: a Platt fit on validation pushes the whole
    # test band above the observed rate, so the acceptance rule must refuse it.
    days = 908
    restricted = []
    for index in range(days):
        if 540 <= index < 660:
            restricted.append(1.0)
        elif index >= 660:
            restricted.append(1.0 if index % 10 else 0.0)
        else:
            restricted.append(1.0 if index % 3 else 0.0)
    history = PlantDailyHistory(
        asset_id="PLANT1",
        days=tuple(START + timedelta(days=offset) for offset in range(days)),
        restricted=tuple(restricted),
        curtailed_mwh=tuple(50.0 if flag else 0.0 for flag in restricted),
    )
    result = run_backtest(
        history=history,
        point_share=tuple(0.5 for _ in range(days)),
        weather_normal_z={},
        capacity_mw=100.0,
        plan=default_backtest_plan(days),
    )

    assert result.calibration is not None
    if result.brier_calibrated is not None and result.brier_calibrated < result.brier_raw:
        assert (
            result.alert_band_gap_calibrated is None
            or result.alert_band_gap_raw is None
            or result.alert_band_gap_calibrated <= result.alert_band_gap_raw + 1e-9
        ) == result.calibration_accepted
    assert result.probability_source in {
        "model_calibrated_backtested",
        "model_raw_backtested",
        PROBABILITY_SOURCE_BASELINE,
    }
    assert PROBABILITY_SOURCE_BASELINE == "baseline_frequency"
    assert result.probability_decision_note
    assert result.baseline_briers
    assert result.baseline_reliability_gaps
    assert result.brier_best_varying_baseline >= min(result.baseline_briers.values())


def test_calibration_is_accepted_only_when_it_improves_the_out_of_sample_brier() -> None:
    probabilities = [0.05] * 40 + [0.95] * 40
    targets = [1] * 40 + [1] * 40
    calibration = fit_platt_calibration(probabilities, targets)

    improved = brier_score([calibration.apply(value) for value in probabilities], targets)
    raw = brier_score(probabilities, targets)
    assert improved < raw


def test_backtest_publishes_brier_baselines_and_reliability_bins() -> None:
    history = synthetic_history(event_rate=0.7)
    plan = default_backtest_plan(len(history.days))
    result = run_backtest(
        history=history,
        point_share=tuple(0.4 for _ in history.days),
        weather_normal_z={},
        capacity_mw=100.0,
        plan=plan,
    )

    assert result.test_days == 4 * 60
    assert result.validation_days == 2 * 60
    assert 0.0 <= result.brier_raw <= 1.0
    assert result.brier_baseline_frequency >= 0.0
    assert result.brier_baseline_persistence >= 0.0
    assert result.brier_baseline_seasonal >= 0.0
    assert result.best_baseline_name in {
        "baseline_frequency",
        "baseline_persistence",
        "baseline_seasonal",
        "baseline_seasonal_blend",
    }
    assert result.calibration is not None
    assert isinstance(result.calibration_accepted, bool)
    if result.brier_calibrated is not None and result.brier_calibrated < result.brier_raw:
        assert result.calibration_accepted
    else:
        assert not result.calibration_accepted
    total = sum(bin_["count"] for bin_ in result.reliability_bins)
    assert total == result.test_days
    assert 0.0 <= result.event_rate_train <= 1.0
    assert 0.0 <= result.event_rate_test <= 1.0


def test_backtest_freezes_the_probability_support_on_the_validation_paths() -> None:
    history = synthetic_history(event_rate=0.7)
    result = run_backtest(
        history=history,
        point_share=tuple(0.4 for _ in history.days),
        weather_normal_z={},
        capacity_mw=100.0,
        plan=default_backtest_plan(len(history.days)),
    )
    payload = result.to_payload()

    assert result.frozen_support_days == result.validation_days
    assert result.frozen_support_days > 0
    assert result.frozen_support_low is not None
    assert result.frozen_support_high is not None
    assert 0.0 <= result.frozen_support_low <= result.frozen_support_high <= 1.0
    assert payload["frozen_support"] == {
        "low": result.frozen_support_low,
        "high": result.frozen_support_high,
        "days": result.frozen_support_days,
        "basis": "validation_paths",
    }


def test_reliability_bins_report_the_observed_rate_per_bin() -> None:
    bins = reliability_bins([0.1, 0.2, 0.6, 0.8], [0, 0, 1, 1])

    assert sum(bin_["count"] for bin_ in bins) == 4
    assert all(0.0 <= bin_["observed_rate"] <= 1.0 for bin_ in bins)
    assert all(0.0 <= bin_["mean_predicted"] <= 1.0 for bin_ in bins)


def test_three_critical_windows_of_exactly_seventy_two_hours_without_weekly_grouping() -> None:
    payload = build_forecast(history=synthetic_history(), slope=0.1, intercept_mw=200.0)

    windows = payload["critical_windows_72h"]

    assert [window["rank"] for window in windows] == [1, 2, 3]
    assert all(window["interval_count"] == 144 for window in windows)
    assert all(window["interval_count"] != 7 * INTERVALS_PER_DAY for window in windows)
    assert len({window["start_date"] for window in windows}) == 3
    ordered = sorted(windows, key=lambda window: window["start_date"])
    for first, second in zip(ordered, ordered[1:], strict=False):
        assert first["end_date"] < second["start_date"]
    assert all(window["expected_curtailed_mwh"] >= 0.0 for window in windows)
    assert all(window["candidate_maintenance_relief_mwh"] >= 0.0 for window in windows)


def test_point_context_simulates_every_entity_without_attributing_their_energy() -> None:
    payload = build_forecast(history=synthetic_history(), slope=0.2, intercept_mw=300.0)

    context = payload["point_context"]

    assert context["entity_count"] == 2
    assert {entity["plant_id"] for entity in context["simulated_entities"]} == {
        "PLANT1",
        "OTHER",
    }
    assert all(entity["origin"] == "SIMULADO" for entity in context["simulated_entities"])
    assert context["estimated_excess_mw"] >= 0.0
    assert context["accepted_generation_envelope_mw"] <= context["potential_generation_mw"] + 1e-6
    assert context["scheduled_maintenance_relief_mw"] >= 0.0
    # The selected plant keeps only its own share of the point.
    selected = next(
        entity for entity in context["simulated_entities"] if entity["plant_id"] == "PLANT1"
    )
    assert selected["mean_available_generation_mw"] <= context["potential_generation_mw"] + 1e-6


def test_simulated_telemetry_separates_physical_quantities() -> None:
    """I1: installed capacity, availability, operational capacity, resource potential, accepted
    envelope and delivered generation are distinct physical quantities in a fixed order."""
    payload = build_forecast(history=synthetic_history(), slope=0.3, intercept_mw=200.0, level=4.0)
    telemetry = payload["simulated_telemetry"]
    capacity = payload["capacity_mw"]

    assert telemetry["origin"] == "SIMULADO"
    assert 0.0 < telemetry["availability_mw"] <= capacity + 1e-9
    assert 0.0 < telemetry["operational_capacity_mw"] <= capacity + 1e-9
    assert telemetry["availability_mw"] <= telemetry["operational_capacity_mw"] + 1e-9
    assert telemetry["potential_generation_mw"] <= telemetry["operational_capacity_mw"] + 1e-9
    assert telemetry["generation_mw"] <= telemetry["potential_generation_mw"] + 1e-9
    assert telemetry["generation_mw"] <= telemetry["accepted_generation_limit_mw"] + 1e-9
    assert telemetry["potentially_curtailed_mw"] == pytest.approx(
        max(telemetry["potential_generation_mw"] - telemetry["generation_mw"], 0.0), abs=1e-9
    )
    assert telemetry["restricted"] == (telemetry["potentially_curtailed_mw"] > 0.0)
    # The defect this replaces published the same number as availability, operational capacity,
    # potential and accepted limit at once. The resource potential sits below the ceiling, and the
    # scheduled maintenance derate separates the operational ceiling from the availability.
    assert telemetry["potential_generation_mw"] < telemetry["operational_capacity_mw"]
    assert telemetry["availability_mw"] < telemetry["operational_capacity_mw"]
    assert telemetry["potential_generation_mw"] != telemetry["generation_mw"]


def test_daily_potential_is_the_resource_curve_before_the_plant_own_maintenance() -> None:
    """I2: the published daily potential is the meteorological resource potential, never the
    already derated available energy. The maintenance appears in the relief and the avoided
    curtailment, without collapsing the potential curve."""
    history = synthetic_history()
    spec = PointSimulationSpec(
        point_id="POINT-1",
        plants=(
            plant_spec(plant_id=history.asset_id, level=4.0),
            plant_spec(plant_id="OTHER", capacity_mw=50.0),
        ),
        envelope_intercept_mw=60.0,
        envelope_slope=0.2,
        installed_capacity_mw=150.0,
        selected_asset_id=history.asset_id,
    )
    days = tuple(
        START + timedelta(days=len(history.days) + offset) for offset in range(HORIZON_DAYS)
    )
    samples = build_scenario_samples(
        spec, days=days, outlook=climatology_outlook(spec.point_id), scenario_count=6
    )
    scheduled = build_maintenance_schedule(
        spec, days=days, seed=0, include_plant_id=history.asset_id
    )
    window = next(item for item in scheduled.windows if item.plant_id == history.asset_id)
    plant = PlantForecastInputs(
        asset_id=history.asset_id,
        name="Usina Sintética",
        technology="wind",
        state="RN",
        ceg="EOL.CV.RN.000001-1.01",
        ons_group_id="CJU_TEST",
        ons_group_name="Conjunto Teste",
        connection_point="POINT-1",
        capacity_mw=100.0,
        history=history,
    )

    def run(schedule: MaintenanceSchedule) -> dict:
        return build_plant_forecast(
            plant=plant,
            spec=spec,
            samples=samples,
            schedule=schedule,
            days=days,
            weather_normal_z={},
            point_share=tuple(0.5 for _ in history.days),
            backtest_plan=default_backtest_plan(len(history.days)),
            weather_source="ons_plant_climatology",
            weather_unit="m/s",
            scenario_count=6,
        )

    with_maintenance = run(scheduled)
    without_maintenance = run(MaintenanceSchedule(point_id="POINT-1"))
    potentials_with = [row["potential_generation_mwh"] for row in with_maintenance["forecasts"]]
    potentials_without = [
        row["potential_generation_mwh"] for row in without_maintenance["forecasts"]
    ]

    # The potential curve is the resource curve: identical with and without the plant's own
    # maintenance, so it cannot collapse because of it.
    assert potentials_with == potentials_without
    assert all(value > 0.0 for value in potentials_with)
    start_day = window.start_interval // INTERVALS_PER_DAY
    end_day = (window.end_interval - 1) // INTERVALS_PER_DAY
    during = with_maintenance["forecasts"][start_day : end_day + 1]
    # The maintenance is visible in the relief and the avoided curtailment on its own days.
    assert any(row["scheduled_maintenance_relief_mwh"] > 0.0 for row in during)
    assert any(row["avoided_curtailment_mwh"] > 0.0 for row in during)
    # The day immediately before the window is not a collapse artefact either.
    before = with_maintenance["forecasts"][max(start_day - 1, 0)]
    assert before["potential_generation_mwh"] > 0.0
    assert all(row["potential_generation_mwh"] > 0.0 for row in during)


def test_input_manifest_is_deterministic_and_identifies_the_inputs(tmp_path) -> None:
    """M2: a deterministic SHA-256 manifest of the inputs actually read, with no mtime."""
    from curtailess.plant_exposure_forecast import build_input_manifest

    catalog = tmp_path / "catalog.json"
    catalog.write_bytes(b'{"plants":[]}')
    history = tmp_path / "history.json"
    history.write_bytes(b'{"plants":[]}')
    ons = tmp_path / "ons"
    ons.mkdir()
    (ons / "a.parquet").write_bytes(b"ons-a")
    (ons / "b.parquet").write_bytes(b"ons-b")

    inputs = [
        ("catalog", str(catalog)),
        ("history", str(history)),
        ("wind_aggregate", str(ons / "*.parquet")),
    ]
    first = build_input_manifest(inputs)
    second = build_input_manifest(inputs)

    assert first == second
    assert first["algorithm"] == "sha256"
    assert first["digest"] == second["digest"]
    assert {entry["role"] for entry in first["inputs"]} == {
        "catalog",
        "history",
        "wind_aggregate",
    }
    assert all(len(entry["sha256"]) == 64 for entry in first["inputs"])
    assert all("mtime" not in entry for entry in first["inputs"])
    assert all(entry["file_count"] > 0 for entry in first["inputs"])

    catalog.write_bytes(b'{"plants":[1]}')
    third = build_input_manifest(inputs)
    assert third["digest"] != first["digest"]


def test_limitations_state_the_selection_is_frozen_on_validation() -> None:
    """M1: the selection is frozen on the validation paths; the test only reports. No limitation
    may describe the choice as made out of sample."""
    from curtailess.plant_exposure_forecast import LIMITATIONS

    text = " ".join(LIMITATIONS)
    lowered = text.lower()
    assert "fora da amostra" not in lowered
    assert "validação" in lowered
    assert "congelad" in lowered


def test_backtest_plan_keeps_the_test_paths_out_of_the_fitting_window() -> None:
    plan = default_backtest_plan(908)

    assert plan.train_end == 9 * 60
    assert plan.validation_origins == (540, 600)
    assert plan.test_origins == (660, 720, 780, 840)
    assert plan.validation_origins[-1] + plan.path_days <= plan.test_origins[0]
    with pytest.raises(ValueError, match="four complete"):
        default_backtest_plan(120)


def test_seasonal_rates_only_use_days_before_the_origin() -> None:
    history = synthetic_history(days=120)
    month_rates, weekday_rates, overall = seasonal_rates(history, index=60)

    later = PlantDailyHistory(
        asset_id=history.asset_id,
        days=history.days,
        restricted=tuple(
            True if index >= 60 else flag for index, flag in enumerate(history.restricted)
        ),
        curtailed_mwh=history.curtailed_mwh,
    )
    assert seasonal_rates(later, index=60) == (month_rates, weekday_rates, overall)


def test_forward_probabilities_are_recursive_and_bounded() -> None:
    history = synthetic_history(event_rate=0.7)
    days = tuple(START + timedelta(days=len(history.days) + offset) for offset in range(30))

    probabilities = forward_probabilities(
        history=history,
        point_share=tuple(0.4 for _ in history.days),
        weather_normal_z={},
        capacity_mw=100.0,
        horizon_days=days,
        simulated_mwh=[50.0] * len(days),
        calibration=None,
        calibration_accepted=False,
    )

    assert len(probabilities) == 30
    assert all(0.0 <= value <= 1.0 for value in probabilities)
    assert len(set(probabilities)) > 1


def test_logistic_model_learns_the_direction_of_its_features() -> None:
    rows = [(1.0, -3.0), (1.0, -1.0), (1.0, 1.0), (1.0, 3.0)]
    model = fit_logistic_model(rows, [0, 0, 1, 1])

    assert isinstance(model, LogisticModel)
    assert model.probability(rows[0]) < model.probability(rows[-1])


def test_distribution_reports_minimum_median_maximum_and_counts() -> None:
    distribution = probability_distribution([0.1, 0.5, 0.9, 0.97])

    assert distribution["min"] == pytest.approx(0.1)
    assert distribution["median"] == pytest.approx(0.7)
    assert distribution["max"] == pytest.approx(0.97)
    assert distribution["days_above_95_pct"] == 1
    assert distribution["days_at_or_above_99_pct"] == 0


def test_artifact_validation_rejects_broken_contracts() -> None:
    payload = _minimal_artifact()
    validate_forecast_artifact(payload)

    def broken(edit) -> dict:
        clone = json.loads(json.dumps(payload))
        edit(clone)
        return clone

    with pytest.raises(ValueError, match="conjunto"):
        validate_forecast_artifact(
            broken(lambda clone: clone["plants"][0].update({"asset_id": "CJU_TEST"}))
        )
    with pytest.raises(ValueError, match="60 pontos"):
        validate_forecast_artifact(
            broken(
                lambda clone: clone["plants"][0].update(
                    {"forecasts": clone["plants"][0]["forecasts"][:59]}
                )
            )
        )
    with pytest.raises(ValueError, match="consecutivas"):
        validate_forecast_artifact(
            broken(
                lambda clone: [
                    row.update(
                        {
                            "forecast_date": (
                                date.fromisoformat(row["forecast_date"]) + timedelta(days=1)
                            ).isoformat()
                        }
                    )
                    for row in clone["plants"][0]["forecasts"][40:]
                ]
            )
        )
    with pytest.raises(ValueError, match="intervalo"):
        validate_forecast_artifact(
            broken(lambda clone: clone["plants"][0]["forecasts"][0].update({"lower_mwh": 99.0}))
        )
    with pytest.raises(ValueError, match="95%"):
        validate_forecast_artifact(
            broken(
                lambda clone: [
                    row.update({"curtailment_probability": 0.99})
                    for row in clone["plants"][0]["forecasts"]
                ]
            )
        )
    with pytest.raises(ValueError, match="três janelas"):
        validate_forecast_artifact(
            broken(
                lambda clone: clone["plants"][0].update(
                    {"critical_windows_72h": clone["plants"][0]["critical_windows_72h"][:2]}
                )
            )
        )
    with pytest.raises(ValueError, match="144 intervalos"):
        validate_forecast_artifact(
            broken(
                lambda clone: clone["plants"][0]["critical_windows_72h"][0].update(
                    {"interval_count": 7 * INTERVALS_PER_DAY}
                )
            )
        )
    with pytest.raises(ValueError, match="95%"):
        validate_forecast_artifact(
            broken(
                lambda clone: clone["checks"].update(
                    {"all_plants_have_days_below_95_pct": False}
                )
            )
        )


def _minimal_artifact() -> dict:
    plants = []
    for plant_index in range(5):
        asset_id = f"PLANT{plant_index + 1}"
        plants.append(
            {
                "asset_id": asset_id,
                "name": f"Usina {plant_index + 1}",
                "entity_level": "plant",
                "connection_point": f"POINT-{plant_index + 1}",
                "probability_source": "baseline_frequency",
                "forecasts": [
                    {
                        "forecast_date": (
                            date(2026, 9, 26) + timedelta(days=offset)
                        ).isoformat(),
                        "display_label": (
                            f"{(date(2026, 9, 26) + timedelta(days=offset)).day:02d}/09"
                        ),
                        "expected_curtailed_mwh": 10.0,
                        "lower_mwh": 0.0,
                        "upper_mwh": 20.0,
                        "curtailment_probability": 0.5,
                        "potential_generation_mwh": 30.0,
                        "accepted_generation_envelope_mwh": 20.0,
                        "scheduled_maintenance_relief_mwh": 1.0,
                        "avoided_curtailment_mwh": 2.0,
                    }
                    for offset in range(HORIZON_DAYS)
                ],
                "critical_windows_72h": [
                    {
                        "rank": rank,
                        "interval_count": 144,
                        "expected_curtailed_mwh": 10.0,
                        "curtailment_probability": 0.5,
                    }
                    for rank in (1, 2, 3)
                ],
            }
        )
    return {
        "schema": "curtailless.individual_plant_forecast.v1",
        "simulation": "SIMULADO",
        "plants": plants,
        "point_contexts": {f"POINT-{index + 1}": {} for index in range(5)},
        "checks": {"all_plants_have_days_below_95_pct": True},
    }


@pytest.mark.skipif(not BUNDLED_FORECAST.exists(), reason="forecast not materialized yet")
def test_bundled_forecast_has_five_plants_sixty_consecutive_days_and_three_windows() -> None:
    payload = json.loads(BUNDLED_FORECAST.read_text(encoding="utf-8"))

    validate_forecast_artifact(payload)
    assert len(payload["plants"]) == 5
    assert len(payload["point_contexts"]) == 5
    interval_rows = 0
    for plant in payload["plants"]:
        assert not plant["asset_id"].startswith("CJU_")
        assert plant["entity_level"] == "plant"
        assert plant["origin"] == "SIMULADO"
        assert plant["connection_point"] in payload["point_contexts"]
        assert plant["weather_source"] in {"gfs_seas5_era5", "ons_plant_climatology"}
        diagnostics = plant["probability_diagnostics"]
        assert diagnostics["min"] < 0.95
        assert diagnostics["days"] == HORIZON_DAYS
        assert diagnostics["days_above_95_pct"] < HORIZON_DAYS
        # Every one of the 300 published days keeps lower <= expected <= upper.
        for row in plant["forecasts"]:
            interval_rows += 1
            assert row["lower_mwh"] <= row["expected_curtailed_mwh"] <= row["upper_mwh"]
        # The artifact records the frozen validation support and the future excursion from it.
        published = diagnostics["published"]
        assert published["candidate"]
        assert published["selection_basis"] == (
            "validation_only_policy_with_support_and_saturation_guard"
        )
        assert published["frozen_support"]["basis"] == "validation_paths"
        assert published["frozen_support"]["low"] is not None
        assert published["frozen_support"]["high"] is not None
        assert (
            published["frozen_support"]["low"] <= published["frozen_support"]["high"]
        )
        assert published["frozen_support"]["days"] > 0
        assert published["future_days"] == HORIZON_DAYS
        assert isinstance(published["future_days_outside_support"], int)
        assert published["future_days_outside_support"] >= 0
        # Strict support policy: a published model series never leaves the frozen support.
        if published["candidate"] in {"model_raw", "model_calibrated"}:
            assert published["future_days_outside_support"] == 0
        else:
            assert published["candidate"].startswith("baseline_")
            assert plant["probability_source"] == PROBABILITY_SOURCE_BASELINE
        # The simulated telemetry keeps physically distinct quantities, never the same number
        # under different names.
        telemetry = plant["simulated_telemetry"]
        capacity = plant["capacity_mw"]
        assert telemetry["availability_mw"] <= capacity + 1e-6
        assert telemetry["operational_capacity_mw"] <= capacity + 1e-6
        assert (
            telemetry["availability_mw"] <= telemetry["operational_capacity_mw"] + 1e-6
        )
        assert (
            telemetry["potential_generation_mw"] <= telemetry["operational_capacity_mw"] + 1e-6
        )
        assert telemetry["generation_mw"] <= telemetry["potential_generation_mw"] + 1e-6
        assert (
            telemetry["generation_mw"] <= telemetry["accepted_generation_limit_mw"] + 1e-6
        )
        assert telemetry["potentially_curtailed_mw"] == pytest.approx(
            max(
                telemetry["potential_generation_mw"] - telemetry["generation_mw"],
                0.0,
            ),
            abs=1e-6,
        )
        assert telemetry["restricted"] == (telemetry["potentially_curtailed_mw"] > 0.0)
        # The daily potential is the resource curve, never negative and never above the ceiling.
        for row in plant["forecasts"]:
            assert row["potential_generation_mwh"] >= 0.0
            assert row["accepted_generation_envelope_mwh"] >= 0.0
            assert row["scheduled_maintenance_relief_mwh"] >= 0.0
            assert row["avoided_curtailment_mwh"] >= 0.0
        backtest = diagnostics["backtest"]
        assert backtest["test_days"] > 0
        assert backtest["validation_days"] > 0
        assert 0.0 <= backtest["event_rate_train"] <= 1.0
        assert 0.0 <= backtest["event_rate_validation"] <= 1.0
        assert 0.0 <= backtest["event_rate_test"] <= 1.0
        assert 0.0 <= backtest["brier_raw"] <= 1.0
        assert backtest["best_baseline_name"] in {
            "baseline_frequency",
            "baseline_persistence",
            "baseline_seasonal",
            "baseline_seasonal_blend",
        }
        assert backtest["reliability_bins"]
        assert sum(bin_["count"] for bin_ in backtest["reliability_bins"]) == backtest["test_days"]
        assert plant["critical_windows_72h"]
        context = plant["point_context"]
        assert context["entity_count"] == len(context["simulated_entities"])
        assert context["entity_count"] > 0
        assert all(
            entity["operational_data_status"] == "simulated"
            for entity in context["simulated_entities"]
        )
        assert any(
            entity["scheduled_maintenance_intervals"] > 0
            for entity in context["simulated_entities"]
        )
    assert payload["checks"]["all_plants_have_days_below_95_pct"] is True
    assert payload["checks"]["published_series_within_validated_support"] is True
    assert payload["checks"]["published_model_series_outside_support_days"] == 0
    assert interval_rows == 5 * HORIZON_DAYS
    assert payload["interval_series"]["resolution_minutes"] == 30
    assert payload["interval_series"]["intervals_per_day"] == INTERVALS_PER_DAY

    # RNEM13 has exactly one future day outside its frozen validation support. Under the strict
    # policy that single day makes the raw model ineligible, so the plant publishes the baseline.
    rnem13 = next(plant for plant in payload["plants"] if plant["asset_id"] == "RNEM13")
    rnem13_published = rnem13["probability_diagnostics"]["published"]
    assert rnem13_published["candidate"].startswith("baseline_")
    assert rnem13["probability_source"] == PROBABILITY_SOURCE_BASELINE
    assert rnem13_published["eligibility"]["model_raw"]["eligible"] is False
    assert rnem13_published["eligibility"]["model_raw"]["outside_support_days"] >= 1
    assert rnem13_published["future_days_outside_support"] == 0

    # M2: both artifacts carry the same deterministic SHA-256 manifest of the inputs read.
    manifest = payload["input_manifest"]
    assert manifest["algorithm"] == "sha256"
    assert manifest["digest"]
    roles = {entry["role"] for entry in manifest["inputs"]}
    assert {
        "catalog",
        "history",
        "relationship",
        "capacity",
        "wind_aggregate",
        "solar_aggregate",
        "wind_detail",
        "solar_detail",
        "weather_snapshot",
    } <= roles
    assert all(len(entry["sha256"]) == 64 for entry in manifest["inputs"])
    assert all(entry["file_count"] > 0 for entry in manifest["inputs"])


@pytest.mark.skipif(not BUNDLED_FORECAST.exists(), reason="forecast not materialized yet")
def test_bundled_schedule_shares_the_forecast_input_manifest() -> None:
    forecast = json.loads(BUNDLED_FORECAST.read_text(encoding="utf-8"))
    schedule_path = BUNDLED_FORECAST.parent / "simulated_point_maintenance_schedule.json"
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))

    assert schedule["input_manifest"] == forecast["input_manifest"]
    assert schedule["input_manifest"]["digest"] == forecast["input_manifest"]["digest"]


@pytest.mark.skipif(not BUNDLED_FORECAST.exists(), reason="forecast not materialized yet")
def test_bundled_schedule_is_simulated_and_keeps_the_candidate_window() -> None:
    schedule_path = BUNDLED_FORECAST.parent / "simulated_point_maintenance_schedule.json"
    schedule = json.loads(schedule_path.read_text(encoding="utf-8"))

    assert schedule["origin"] == "SIMULADO"
    assert len(schedule["points"]) == 5
    for point_id, payload in schedule["points"].items():
        assert payload["point_id"] == point_id
        assert payload["origin"] == "SIMULADO"
        assert payload["plant_count"] > 0
        assert payload["candidate_asset_ids"]
        assert all(
            isinstance(asset_id, str) and asset_id for asset_id in payload["candidate_asset_ids"]
        )
        assert len(set(payload["candidate_asset_ids"])) == len(payload["candidate_asset_ids"])
        assert all(window["origin"] == "SIMULADO" for window in payload["windows"])
        assert all(window["interval_count"] > 0 for window in payload["windows"])
        assert all(0.0 < window["derate"] <= 1.0 for window in payload["windows"])
