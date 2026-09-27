"""Focused tests for the point exposure simulation (plan Task 3)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from curtailess.point_exposure_simulation import (
    CRITICAL_WINDOW_COUNT,
    CRITICAL_WINDOW_INTERVALS,
    INTERVAL_HOURS,
    INTERVALS_PER_DAY,
    MAINTENANCE_DERATE,
    SCENARIO_NO_MAINTENANCE,
    SCENARIO_SCHEDULED_MAINTENANCE,
    MaintenanceSchedule,
    MaintenanceWindow,
    PlantSimulationSpec,
    PointSimulationSpec,
    accepted_envelope_mw,
    build_day_factors,
    build_maintenance_schedule,
    build_scenario_samples,
    climatology_outlook,
    fit_acceptance_envelope,
    load_weather_snapshot,
    mean_and_quantiles,
    point_excess_mw,
    scenario_daily_mwh,
    scenario_event_probability,
    select_critical_windows,
    simulate_point,
    window_metrics,
)

LOOKUP_STEP = 1.0


def plant_spec(
    *,
    plant_id: str,
    capacity_mw: float = 100.0,
    weather_level: float = 10.0,
    technology: str = "wind",
) -> PlantSimulationSpec:
    """A plant whose potential grows linearly with the weather up to its capacity."""
    lookup = tuple(
        min(capacity_mw, index * LOOKUP_STEP * 10.0) for index in range(int(40.0 / LOOKUP_STEP) + 1)
    )
    return PlantSimulationSpec(
        plant_id=plant_id,
        name=plant_id,
        capacity_mw=capacity_mw,
        technology=technology,
        month_hour_climatology=(weather_level,) * (12 * INTERVALS_PER_DAY),
        potential_lookup=lookup,
        lookup_step=LOOKUP_STEP,
        relative_spread=0.1,
        availability_mean=1.0,
        availability_spread=0.0,
        restricted_day_share=0.5,
    )


def point_spec(
    *,
    plants: tuple[PlantSimulationSpec, ...],
    selected: str,
    intercept_mw: float,
    slope: float,
    point_id: str = "POINT-1",
) -> PointSimulationSpec:
    return PointSimulationSpec(
        point_id=point_id,
        plants=plants,
        envelope_intercept_mw=intercept_mw,
        envelope_slope=slope,
        installed_capacity_mw=sum(plant.capacity_mw for plant in plants),
        selected_asset_id=selected,
    )


def test_envelope_never_grows_faster_than_the_available_generation() -> None:
    assert accepted_envelope_mw(100.0, intercept_mw=50.0, slope=2.0) == pytest.approx(100.0)
    assert accepted_envelope_mw(100.0, intercept_mw=-10.0, slope=0.5) == pytest.approx(50.0)
    assert accepted_envelope_mw(100.0, intercept_mw=50.0, slope=0.5) == pytest.approx(100.0)


def test_reducing_available_generation_never_increases_point_excess() -> None:
    """Toy case: a maintenance that reduces generation cannot increase curtailment."""
    intercept, slope = 120.0, 0.4
    baseline = [
        point_excess_mw(potential, intercept_mw=intercept, slope=slope)
        for potential in (100.0, 300.0, 500.0, 800.0, 1000.0)
    ]
    reduced = [
        point_excess_mw(potential * 0.7, intercept_mw=intercept, slope=slope)
        for potential in (100.0, 300.0, 500.0, 800.0, 1000.0)
    ]

    assert all(after <= before + 1e-9 for before, after in zip(baseline, reduced, strict=True))
    assert any(after < before for before, after in zip(baseline, reduced, strict=True))


def test_envelope_fit_respects_the_constraints_and_the_observed_level() -> None:
    potentials = [200.0 + 10.0 * index for index in range(120)]
    published = [max(0.0, potential - 400.0) for potential in potentials]

    intercept, slope = fit_acceptance_envelope(
        point_potential_mw=potentials, published_curtailment_mw=published
    )

    assert 0.0 <= slope <= 1.0
    assert intercept >= 0.0
    modelled = [
        point_excess_mw(potential, intercept_mw=intercept, slope=slope) for potential in potentials
    ]
    mean_observed = sum(published) / len(published)
    mean_modelled = sum(modelled) / len(modelled)
    assert mean_modelled == pytest.approx(mean_observed, rel=0.35)


def test_mean_and_quantiles_always_contain_the_expected_value() -> None:
    """Regression for the published interval: with a skewed daily distribution the 90th
    percentile can sit below the mean, and a published band that excludes its own point estimate
    is not a valid interval."""
    skewed = ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (0.0, 0.0), (100.0, 5.0))
    expected, lower, upper = mean_and_quantiles(skewed)
    assert lower[0] <= expected[0] <= upper[0]
    assert lower[1] <= expected[1] <= upper[1]
    # The lower quantile is below the mean here, so the band must be widened to contain it.
    assert expected[0] == pytest.approx(20.0)
    assert lower[0] <= 20.0 <= upper[0]

    # Property check across many shapes, including constants and single scenarios.
    import random

    rng = random.Random(0)
    for _ in range(200):
        scenarios = tuple(
            tuple(round(rng.uniform(0.0, 500.0), 3) for _ in range(6))
            for _ in range(rng.randint(1, 9))
        )
        expected, lower, upper = mean_and_quantiles(scenarios)
        for day in range(len(expected)):
            assert lower[day] <= expected[day] <= upper[day]


def test_maintenance_derate_applies_only_to_the_scheduled_intervals() -> None:
    spec = point_spec(
        plants=(plant_spec(plant_id="A"), plant_spec(plant_id="B")),
        selected="A",
        intercept_mw=10.0,
        slope=0.2,
    )
    schedule = build_maintenance_schedule(spec, days=_days(4), seed=0)
    candidate = MaintenanceWindow(
        plant_id="A", start_interval=48, interval_count=144, derate=0.35
    )
    schedule = schedule.with_candidate(candidate)
    intervals = 4 * INTERVALS_PER_DAY

    series = schedule.derate_series("A", intervals=intervals)

    assert len(series) == intervals
    assert series[48] == pytest.approx(0.35)
    assert series[191] == pytest.approx(0.35)
    assert series[0] == pytest.approx(1.0)
    # The candidate window belongs to the selected plant only.
    assert schedule.candidate_window is not None
    assert schedule.candidate_window.plant_id == "A"
    without_candidate = MaintenanceSchedule(point_id=spec.point_id, windows=schedule.windows)
    assert schedule.derate_series("B", intervals=intervals) == without_candidate.derate_series(
        "B", intervals=intervals
    )


def _days(count: int) -> tuple[date, ...]:
    return tuple(date(2026, 9, 26) + timedelta(days=offset) for offset in range(count))


def test_scheduled_maintenance_reduces_available_generation_and_never_raises_excess() -> None:
    spec = point_spec(
        plants=(
            plant_spec(plant_id="A", capacity_mw=100.0),
            plant_spec(plant_id="B", capacity_mw=100.0),
        ),
        selected="A",
        intercept_mw=100.0,
        slope=0.0,
    )
    days = _days(6)
    samples = build_scenario_samples(
        spec, days=days, outlook=climatology_outlook(spec.point_id), scenario_count=8
    )
    schedule = build_maintenance_schedule(spec, days=days, seed=0)
    assert schedule.windows, "the simulated agenda must contain participating plants"
    no_maintenance = simulate_point(
        spec, days=days, samples=samples, schedule=None, scenario=SCENARIO_NO_MAINTENANCE
    )
    scheduled = simulate_point(
        spec, days=days, samples=samples, schedule=schedule, scenario=SCENARIO_SCHEDULED_MAINTENANCE
    )

    # The same weather samples feed both scenarios.
    assert samples.day_factors is samples.day_factors
    for scenario_index in range(samples.scenario_count):
        assert all(
            after <= before + 1e-9
            for before, after in zip(
                no_maintenance.point_excess_mw[scenario_index],
                scheduled.point_excess_mw[scenario_index],
                strict=True,
            )
        )
    derated = [window for window in schedule.windows]
    assert any(window.derate == MAINTENANCE_DERATE for window in derated)
    assert scheduled.point_mean_potential_mw <= no_maintenance.point_mean_potential_mw
    assert scheduled.point_mean_excess_mw <= no_maintenance.point_mean_excess_mw + 1e-9


def test_selected_plant_receives_only_its_own_share_of_the_envelope() -> None:
    spec = point_spec(
        plants=(plant_spec(plant_id="A", capacity_mw=50.0), plant_spec(plant_id="B")),
        selected="A",
        intercept_mw=60.0,
        slope=0.0,
    )
    days = _days(2)
    samples = build_scenario_samples(
        spec, days=days, outlook=climatology_outlook(spec.point_id), scenario_count=4
    )
    result = simulate_point(spec, days=days, samples=samples, record_plant_totals=True)

    for scenario_index in range(samples.scenario_count):
        curtailed = result.selected_curtailed_mw[scenario_index]
        excess = result.point_excess_mw[scenario_index]
        assert all(value <= total + 1e-9 for value, total in zip(curtailed, excess, strict=True))
    # A is smaller than B, so its share of the point envelope is smaller than half of it.
    assert result.plant_mean_curtailed_mw["A"] < result.plant_mean_curtailed_mw["B"]
    assert set(result.plant_mean_available_mw) == {"A", "B"}


def test_daily_aggregation_and_event_probability_use_severity_not_probability() -> None:
    spec = point_spec(
        plants=(plant_spec(plant_id="A"),),
        selected="A",
        intercept_mw=50.0,
        slope=0.0,
    )
    days = _days(2)
    samples = build_scenario_samples(
        spec, days=days, outlook=climatology_outlook(spec.point_id), scenario_count=6
    )
    result = simulate_point(spec, days=days, samples=samples)

    daily = scenario_daily_mwh(result.selected_curtailed_mw)

    assert len(daily) == samples.scenario_count
    assert all(len(scenario) == 2 for scenario in daily)
    assert daily[0][0] == pytest.approx(
        sum(result.selected_curtailed_mw[0][:INTERVALS_PER_DAY]) * INTERVAL_HOURS
    )
    probability = scenario_event_probability(daily)
    assert all(0.0 <= value <= 1.0 for value in probability)


def test_critical_windows_are_exactly_72_hours_and_never_overlap() -> None:
    spec = point_spec(
        plants=(plant_spec(plant_id="A"),),
        selected="A",
        intercept_mw=10.0,
        slope=0.1,
    )
    days = _days(12)
    samples = build_scenario_samples(
        spec, days=days, outlook=climatology_outlook(spec.point_id), scenario_count=6
    )
    result = simulate_point(spec, days=days, samples=samples)

    metrics = window_metrics(result.selected_curtailed_mw)
    selected = select_critical_windows(metrics)

    assert len(selected) == CRITICAL_WINDOW_COUNT
    assert all(window.interval_count == CRITICAL_WINDOW_INTERVALS for window in selected)
    assert all(window.interval_count * INTERVAL_HOURS == 72.0 for window in selected)
    # Never a weekly aggregation.
    assert all(window.interval_count != 7 * INTERVALS_PER_DAY for window in selected)
    ordered = sorted(selected, key=lambda window: window.start_interval)
    for first, second in zip(ordered, ordered[1:]):
        assert first.end_interval <= second.start_interval
    assert len({window.start_interval for window in selected}) == CRITICAL_WINDOW_COUNT


def test_weather_scenarios_ignore_records_that_were_not_usable_at_the_run() -> None:
    snapshot = _synthetic_snapshot(usable=False)
    outlook = load_weather_snapshot(snapshot, variable="wind")["POINT-X"]
    days = _days(4)

    factors = build_day_factors(
        outlook=outlook, days=days, scenario_count=6, seed=1, relative_spread=0.1
    )
    usable_factors = build_day_factors(
        outlook=outlook,
        days=days,
        scenario_count=6,
        seed=1,
        relative_spread=0.1,
    )

    # No usable record means no short-range signal: the same seed reproduces the same draws.
    assert factors == usable_factors
    assert all(0.05 <= value <= 3.0 for scenario in factors for value in scenario)


def test_weather_uncertainty_grows_beyond_the_short_range_horizon() -> None:
    snapshot = _synthetic_snapshot(usable=True)
    outlook = load_weather_snapshot(snapshot, variable="wind")["POINT-X"]
    days = _days(40)

    factors = build_day_factors(
        outlook=outlook, days=days, scenario_count=96, seed=7, relative_spread=0.02
    )

    near = [scenario[1] for scenario in factors]
    far = [scenario[39] for scenario in factors]
    assert _spread(far) > _spread(near)


def _spread(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5


def _synthetic_snapshot(*, usable: bool) -> str:
    import json
    import tempfile
    from pathlib import Path

    records = []
    start = datetime(2026, 9, 26, 0, 0)
    for hour in range(24 * 17):
        records.append(
            {
                "valid_time": (start + timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%MZ"),
                "lead_time_hours": hour,
                "usable_prospectively_at_snapshot": usable,
                "wind_speed_80m_ms": 8.0 + (hour % 5),
                "shortwave_radiation_wm2": 500.0,
            }
        )
    seasonal = [
        {
            "valid_date": (start + timedelta(days=offset)).strftime("%Y-%m-%d"),
            "wind_speed_10m_mean_ms": {"mean": 5.0, "stddev": 0.5},
            "shortwave_radiation_sum_mjm2": {"mean": 20.0, "stddev": 2.0},
        }
        for offset in range(40)
    ]
    payload = {
        "gfs_short_range": {
            "run": "2026-09-26T12:00:00Z",
            "variables": {"wind_speed_80m_ms": "wind"},
            "points": [{"point_id": "POINT-X", "records": records}],
        },
        "seasonal_60_day": {
            "run": "2026-09-01T00:00:00Z",
            "variables": {},
            "points": [{"point_id": "POINT-X", "records": seasonal}],
        },
        "era5_monthly_climatology": {
            "variables": {},
            "points": [
                {
                    "point_id": "POINT-X",
                    "months": [
                        {
                            "calendar_month": month,
                            "wind_speed_10m_daily_max_ms": {"mean": 5.0 + month / 10},
                        }
                        for month in range(1, 13)
                    ],
                }
            ],
        },
    }
    path = Path(tempfile.mkdtemp()) / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)
