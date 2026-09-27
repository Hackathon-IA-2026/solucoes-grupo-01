"""Point-level 30-minute exposure simulation for the Exposure screen.

The module answers a different question from the individual plant history: how much energy
can the connection point still accept while every active plant linked to it keeps producing?
Every plant of the point is simulated at half-hour resolution, the point acceptance envelope
is estimated from the published group curtailment, and the selected plant receives only its
own share of the envelope.

Three deterministic scenarios run over the same weather samples:

* ``no_maintenance`` — every plant fully available;
* ``scheduled_maintenance`` — the simulated maintenance agenda of the participating plants;
* ``candidate_maintenance`` — the scheduled agenda plus the candidate window of the selected
  plant, used as the counterfactual of a future maintenance.

The point acceptance envelope is ``min(potential, intercept + slope * potential)`` with
``slope`` in ``[0, 1]`` and a non-negative intercept, so reducing the available generation of
any plant can only reduce or keep the point excess. A maintenance never increases curtailment
silently.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

INTERVAL_HOURS = 0.5
INTERVALS_PER_DAY = 48
CRITICAL_WINDOW_HOURS = 72
CRITICAL_WINDOW_INTERVALS = 144
CRITICAL_WINDOW_COUNT = 3
DEFAULT_SCENARIO_COUNT = 24
MAINTENANCE_DERATE = 0.35
MINIMUM_MAINTENANCE_DAYS = 3
MAXIMUM_MAINTENANCE_DAYS = 6
CANDIDATE_WINDOW_INTERVALS = CRITICAL_WINDOW_INTERVALS
SIMULATION_METHOD = "SIMULADO_FROM_ONS_HISTORY"
ORIGIN_SIMULATED = "SIMULADO"

SCENARIO_NO_MAINTENANCE = "no_maintenance"
SCENARIO_SCHEDULED_MAINTENANCE = "scheduled_maintenance"
SCENARIO_CANDIDATE_MAINTENANCE = "candidate_maintenance"

WEATHER_SOURCE_FORECAST = "gfs_seas5_era5"
WEATHER_SOURCE_CLIMATOLOGY = "ons_plant_climatology"
WEATHER_UNIT_WIND = "m/s"
WEATHER_UNIT_SOLAR = "W/m2"

GFS_HORIZON_DAYS = 16
SEASONAL_SIGNAL_WEIGHT = 0.5
BEYOND_HORIZON_SIGNAL_WEIGHT = 0.5
WEEKLY_UNCERTAINTY_INFLATION = 0.08
CLIMATOLOGY_RELATIVE_SPREAD = 0.18
MAXIMUM_WEATHER_FACTOR = 3.0
MINIMUM_WEATHER_FACTOR = 0.05
WIND_LOOKUP_MAXIMUM = 40.0
WIND_LOOKUP_STEP = 0.05
SOLAR_LOOKUP_MAXIMUM = 1400.0
SOLAR_LOOKUP_STEP = 1.0
ENVELOPE_SLOPE_GRID = tuple(index / 20 for index in range(21))
ENVELOPE_INTERCEPT_GRID = 60
ENVELOPE_FIT_SUBSAMPLE = 8


def deterministic_seed(*parts: str) -> int:
    """Stable seed for a simulated artefact: no wall clock, no process state."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def accepted_envelope_mw(potential_mw: float, *, intercept_mw: float, slope: float) -> float:
    """Injection the point still accepts for a given available generation.

    The slope is clipped to ``[0, 1]`` and the intercept to non-negative values, so the
    envelope never grows faster than the available generation.
    """
    bounded_slope = _clamp(float(slope), 0.0, 1.0)
    bounded_intercept = max(float(intercept_mw), 0.0)
    available = max(float(potential_mw), 0.0)
    linear = bounded_intercept + bounded_slope * available
    return available if available <= linear else linear


def point_excess_mw(potential_mw: float, *, intercept_mw: float, slope: float) -> float:
    """Curtailed power at the point: available generation above the accepted envelope."""
    available = max(float(potential_mw), 0.0)
    return max(
        0.0, available - accepted_envelope_mw(available, intercept_mw=intercept_mw, slope=slope)
    )


def fit_acceptance_envelope(
    *,
    point_potential_mw: Sequence[float],
    published_curtailment_mw: Sequence[float],
) -> tuple[float, float]:
    """Fit ``(intercept, slope)`` against the published point curtailment.

    The published group curtailment summed at the point is the only public measurement of how
    much the point had to refuse. The fit searches the constrained grid and keeps the pair
    with the smallest squared error, so the envelope stays monotone by construction.
    """
    if len(point_potential_mw) != len(published_curtailment_mw):
        raise ValueError("potential and published series must have the same length")
    samples = [
        (max(float(potential), 0.0), max(float(published), 0.0))
        for potential, published in zip(point_potential_mw, published_curtailment_mw, strict=True)
    ]
    if not samples:
        raise ValueError("envelope fit needs at least one observation")
    best: tuple[float, float, float] | None = None
    for slope in ENVELOPE_SLOPE_GRID:
        highest = max(potential * (1.0 - slope) for potential, _ in samples)
        step = max(highest / ENVELOPE_INTERCEPT_GRID, 1.0)
        for index in range(ENVELOPE_INTERCEPT_GRID + 1):
            intercept = index * step
            error = 0.0
            for potential, published in samples:
                modelled = point_excess_mw(potential, intercept_mw=intercept, slope=slope)
                error += (modelled - published) ** 2
            if best is None or error < best[2]:
                best = (intercept, slope, error)
    assert best is not None
    return (round(best[0], 6), round(best[1], 6))


def build_potential_lookup(
    curve: Any,
    *,
    capacity_mw: float,
    maximum: float,
    step: float,
) -> tuple[float, ...]:
    """Sample a generation curve onto a fixed grid so the simulation can index it."""
    values: list[float] = []
    limit = max(float(capacity_mw), 0.0)
    value = 0.0
    while value <= maximum + step / 2:
        potential = float(curve.potential(value))
        if limit > 0:
            potential = min(potential, limit)
        values.append(max(potential, 0.0))
        value += step
    return tuple(values)


def lookup_potential_mw(lookup: Sequence[float], value: float, *, step: float) -> float:
    if not lookup or value <= 0.0:
        return lookup[0] if lookup else 0.0
    index = int(value / step)
    if index >= len(lookup):
        return lookup[-1]
    return lookup[index]


@dataclass(frozen=True)
class PlantSimulationSpec:
    """Everything the point simulation needs about one active plant."""

    plant_id: str
    name: str
    capacity_mw: float
    technology: str
    ons_group_id: str
    month_hour_climatology: tuple[float, ...]
    potential_lookup: tuple[float, ...]
    lookup_step: float
    relative_spread: float
    availability_mean: float
    availability_spread: float
    restricted_day_share: float


@dataclass(frozen=True)
class PointSimulationSpec:
    """One connection point with every active plant linked to it."""

    point_id: str
    plants: tuple[PlantSimulationSpec, ...]
    envelope_intercept_mw: float
    envelope_slope: float
    installed_capacity_mw: float
    selected_asset_id: str

    def plant(self, plant_id: str) -> PlantSimulationSpec:
        for candidate in self.plants:
            if candidate.plant_id == plant_id:
                return candidate
        raise KeyError(plant_id)


@dataclass(frozen=True)
class MaintenanceWindow:
    """One simulated unavailability window of one plant."""

    plant_id: str
    start_interval: int
    interval_count: int
    derate: float

    @property
    def end_interval(self) -> int:
        return self.start_interval + self.interval_count


@dataclass(frozen=True)
class MaintenanceSchedule:
    """Simulated maintenance agenda of one point, plus the candidate window."""

    point_id: str
    windows: tuple[MaintenanceWindow, ...] = ()
    candidate_window: MaintenanceWindow | None = None
    origin: str = ORIGIN_SIMULATED
    method: str = "agenda simulada das usinas participantes"

    def derate_series(self, plant_id: str, *, intervals: int) -> tuple[float, ...]:
        series = [1.0] * intervals
        windows = list(self.windows)
        if self.candidate_window is not None:
            windows.append(self.candidate_window)
        for window in windows:
            if window.plant_id != plant_id:
                continue
            for index in range(max(window.start_interval, 0), min(window.end_interval, intervals)):
                series[index] = min(series[index], window.derate)
        return tuple(series)

    def with_candidate(self, candidate: MaintenanceWindow) -> MaintenanceSchedule:
        return MaintenanceSchedule(
            point_id=self.point_id,
            windows=self.windows,
            candidate_window=candidate,
            origin=self.origin,
            method=self.method,
        )


@dataclass(frozen=True)
class PointWeatherOutlook:
    """Weather outlook of one connection point, with its emission metadata."""

    point_id: str
    source: str
    issued_at: str | None
    gfs_run: str | None
    seasonal_run: str | None
    gfs_hourly: tuple[tuple[datetime, float | None, bool], ...]
    seasonal_daily: tuple[tuple[date, float, float], ...]
    era5_monthly: tuple[tuple[int, float], ...]
    variables: Mapping[str, str]


def load_weather_snapshot(path: str, *, variable: str) -> dict[str, PointWeatherOutlook]:
    """Read the bundled prospective weather snapshot without any network access.

    ``variable`` selects the column pair used by the point technology: ``wind`` reads the
    80 m wind speed from the short-range run and the 10 m mean from the seasonal run;
    ``solar`` reads the shortwave radiation.
    """
    with open(path, encoding="utf-8") as stream:
        payload = json.load(stream)
    gfs = payload.get("gfs_short_range", {})
    seasonal = payload.get("seasonal_60_day", {})
    era5 = payload.get("era5_monthly_climatology", {})
    if variable == "wind":
        gfs_column, seasonal_column, era5_column = (
            "wind_speed_80m_ms",
            "wind_speed_10m_mean_ms",
            "wind_speed_10m_daily_max_ms",
        )
    else:
        gfs_column, seasonal_column, era5_column = (
            "shortwave_radiation_wm2",
            "shortwave_radiation_sum_mjm2",
            "shortwave_radiation_daily_sum_mjm2",
        )
    gfs_points = {point["point_id"]: point for point in gfs.get("points", [])}
    seasonal_points = {point["point_id"]: point for point in seasonal.get("points", [])}
    era5_points = {point["point_id"]: point for point in era5.get("points", [])}
    outlooks: dict[str, PointWeatherOutlook] = {}
    for point_id, point in gfs_points.items():
        hourly = tuple(
            (
                datetime.fromisoformat(record["valid_time"].replace("Z", "+00:00")),
                record.get(gfs_column),
                bool(record.get("usable_prospectively_at_snapshot")),
            )
            for record in point.get("records", [])
        )
        daily: list[tuple[date, float, float]] = []
        for record in seasonal_points.get(point_id, {}).get("records", []):
            statistic = record.get(seasonal_column) or {}
            mean = statistic.get("mean")
            spread = statistic.get("stddev")
            if mean is None:
                continue
            daily.append(
                (date.fromisoformat(record["valid_date"]), float(mean), float(spread or 0.0))
            )
        monthly = tuple(
            (int(entry["calendar_month"]), float((entry.get(era5_column) or {}).get("mean", 0.0)))
            for entry in era5_points.get(point_id, {}).get("months", [])
            if entry.get(era5_column)
        )
        outlooks[point_id] = PointWeatherOutlook(
            point_id=point_id,
            source=WEATHER_SOURCE_FORECAST,
            issued_at=str(gfs.get("run") or ""),
            gfs_run=str(gfs.get("run") or "") or None,
            seasonal_run=str(seasonal.get("run") or "") or None,
            gfs_hourly=hourly,
            seasonal_daily=tuple(daily),
            era5_monthly=monthly,
            variables={gfs_column: str((gfs.get("variables") or {}).get(gfs_column, ""))},
        )
    return outlooks


def climatology_outlook(point_id: str) -> PointWeatherOutlook:
    """Outlook of a point without published coordinates: its own plant climatology only."""
    return PointWeatherOutlook(
        point_id=point_id,
        source=WEATHER_SOURCE_CLIMATOLOGY,
        issued_at=None,
        gfs_run=None,
        seasonal_run=None,
        gfs_hourly=(),
        seasonal_daily=(),
        era5_monthly=(),
        variables={},
    )


def _standardised(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    deviation = math.sqrt(variance)
    if deviation <= 1e-9:
        return [0.0] * len(values)
    return [(value - mean) / deviation for value in values]


def build_day_factors(
    *,
    outlook: PointWeatherOutlook | None,
    days: Sequence[date],
    scenario_count: int,
    seed: int,
    relative_spread: float,
) -> tuple[tuple[float, ...], ...]:
    """Weather anomaly factor per scenario and day, without future observations.

    Inside the short-range horizon the standardised daily anomaly of the archived run is the
    deterministic signal. Beyond it the coarse seasonal outlook contributes a reduced signal
    and the sampled spread grows with the lead time, so uncertainty increases with distance.
    A point without published coordinates falls back to its own plant climatology.
    """
    if scenario_count <= 0:
        raise ValueError("scenario_count must be positive")
    rng = random.Random(seed)
    if outlook is None or outlook.source == WEATHER_SOURCE_CLIMATOLOGY:
        spread = max(relative_spread, CLIMATOLOGY_RELATIVE_SPREAD)
        return tuple(
            tuple(
                _clamp(
                    1.0 + spread * rng.gauss(0.0, 1.0),
                    MINIMUM_WEATHER_FACTOR,
                    MAXIMUM_WEATHER_FACTOR,
                )
                for _ in days
            )
            for _ in range(scenario_count)
        )

    hourly: dict[date, list[float]] = {}
    for valid_time, value, usable in outlook.gfs_hourly:
        if value is None or not usable:
            continue
        hourly.setdefault(valid_time.date(), []).append(float(value))
    gfs_days = [day for day in days if day in hourly]
    gfs_values = [sum(hourly[day]) / len(hourly[day]) for day in gfs_days]
    gfs_z = dict(zip(gfs_days, _standardised(gfs_values), strict=True))

    seasonal = {day: (mean, spread) for day, mean, spread in outlook.seasonal_daily}
    seasonal_days = [day for day in days if day in seasonal]
    seasonal_z = dict(
        zip(
            seasonal_days,
            _standardised([seasonal[day][0] for day in seasonal_days]),
            strict=True,
        )
    )
    factors: list[tuple[float, ...]] = []
    for _ in range(scenario_count):
        scenario: list[float] = []
        for offset, day in enumerate(days):
            signal = 0.0
            spread = max(relative_spread, 0.02)
            if day in gfs_z:
                signal = gfs_z[day]
                spread = min(spread, 0.35)
            elif day in seasonal_z:
                signal = BEYOND_HORIZON_SIGNAL_WEIGHT * seasonal_z[day]
                base = seasonal[day][0]
                if base > 0:
                    spread = max(spread, seasonal[day][1] / base)
                spread *= 1.0 + WEEKLY_UNCERTAINTY_INFLATION * max(
                    0.0, (offset - GFS_HORIZON_DAYS) / 7.0
                )
            factor = 1.0 + signal + spread * rng.gauss(0.0, 1.0)
            scenario.append(_clamp(factor, MINIMUM_WEATHER_FACTOR, MAXIMUM_WEATHER_FACTOR))
        factors.append(tuple(scenario))
    return tuple(factors)


@dataclass(frozen=True)
class ScenarioSamples:
    """Weather, noise and availability draws shared by every maintenance scenario."""

    scenario_count: int
    day_count: int
    day_factors: tuple[tuple[float, ...], ...]
    plant_noise: Mapping[str, tuple[float, ...]]
    availability: Mapping[str, tuple[tuple[float, ...], ...]]


def build_scenario_samples(
    spec: PointSimulationSpec,
    *,
    days: Sequence[date],
    outlook: PointWeatherOutlook | None,
    scenario_count: int = DEFAULT_SCENARIO_COUNT,
) -> ScenarioSamples:
    """Sample every shared input once so the three scenarios differ only by maintenance."""
    factors = build_day_factors(
        outlook=outlook,
        days=days,
        scenario_count=scenario_count,
        seed=deterministic_seed(spec.point_id, "weather"),
        relative_spread=(
            sum(plant.relative_spread for plant in spec.plants) / len(spec.plants)
            if spec.plants
            else CLIMATOLOGY_RELATIVE_SPREAD
        ),
    )
    plant_noise: dict[str, tuple[float, ...]] = {}
    availability: dict[str, tuple[tuple[float, ...], ...]] = {}
    for plant in sorted(spec.plants, key=lambda item: item.plant_id):
        rng = random.Random(deterministic_seed(spec.point_id, plant.plant_id, "noise"))
        plant_noise[plant.plant_id] = tuple(
            1.0 + 0.06 * rng.gauss(0.0, 1.0) for _ in range(scenario_count)
        )
        draws: list[tuple[float, ...]] = []
        for _ in range(scenario_count):
            draws.append(
                tuple(
                    _clamp(
                        plant.availability_mean - plant.availability_spread * rng.random(),
                        0.6,
                        1.0,
                    )
                    for _ in days
                )
            )
        availability[plant.plant_id] = tuple(draws)
    return ScenarioSamples(
        scenario_count=scenario_count,
        day_count=len(days),
        day_factors=factors,
        plant_noise=plant_noise,
        availability=availability,
    )


def build_maintenance_schedule(
    spec: PointSimulationSpec,
    *,
    days: Sequence[date],
    seed: int,
    include_plant_id: str | None = None,
) -> MaintenanceSchedule:
    """Simulate the agenda of the participating plants, deterministically."""
    horizon = len(days) * INTERVALS_PER_DAY
    windows: list[MaintenanceWindow] = []
    for plant in sorted(spec.plants, key=lambda item: item.plant_id):
        rng = random.Random(deterministic_seed(spec.point_id, plant.plant_id, "maintenance"))
        if rng.random() > 0.65:
            continue
        duration = rng.randint(MINIMUM_MAINTENANCE_DAYS, MAXIMUM_MAINTENANCE_DAYS)
        latest = max(len(days) - duration, 0)
        start_day = rng.randint(0, latest) if latest > 0 else 0
        windows.append(
            MaintenanceWindow(
                plant_id=plant.plant_id,
                start_interval=start_day * INTERVALS_PER_DAY,
                interval_count=min(duration * INTERVALS_PER_DAY, horizon),
                derate=MAINTENANCE_DERATE,
            )
        )
    if include_plant_id is not None and not any(
        window.plant_id == include_plant_id for window in windows
    ):
        rng = random.Random(deterministic_seed(spec.point_id, include_plant_id, "maintenance"))
        duration = rng.randint(MINIMUM_MAINTENANCE_DAYS, MAXIMUM_MAINTENANCE_DAYS)
        latest = max(len(days) - duration, 0)
        start_day = rng.randint(0, latest) if latest > 0 else 0
        windows.append(
            MaintenanceWindow(
                plant_id=include_plant_id,
                start_interval=start_day * INTERVALS_PER_DAY,
                interval_count=duration * INTERVALS_PER_DAY,
                derate=MAINTENANCE_DERATE,
            )
        )
    windows.sort(key=lambda window: (window.start_interval, window.plant_id))
    return MaintenanceSchedule(point_id=spec.point_id, windows=tuple(windows))


def candidate_maintenance_window(
    *, plant_id: str, start_day: int, derate: float = MAINTENANCE_DERATE
) -> MaintenanceWindow:
    """The 72-hour counterfactual window of the selected plant."""
    return MaintenanceWindow(
        plant_id=plant_id,
        start_interval=start_day * INTERVALS_PER_DAY,
        interval_count=CANDIDATE_WINDOW_INTERVALS,
        derate=derate,
    )


@dataclass(frozen=True)
class PointSimulationResult:
    """Half-hour series of one point under one maintenance scenario."""

    point_id: str
    scenario: str
    selected_asset_id: str
    intervals: int
    selected_curtailed_mw: tuple[tuple[float, ...], ...]
    selected_available_mw: tuple[tuple[float, ...], ...]
    selected_potential_mw: tuple[tuple[float, ...], ...]
    point_potential_mw: tuple[tuple[float, ...], ...]
    point_available_mw: tuple[tuple[float, ...], ...]
    point_envelope_mw: tuple[tuple[float, ...], ...]
    point_excess_mw: tuple[tuple[float, ...], ...]
    plant_mean_operational_capacity_mw: Mapping[str, float]
    plant_mean_availability_mw: Mapping[str, float]
    plant_mean_available_mw: Mapping[str, float]
    plant_mean_potential_mw: Mapping[str, float]
    plant_mean_accepted_limit_mw: Mapping[str, float]
    plant_mean_generation_mw: Mapping[str, float]
    plant_mean_curtailed_mw: Mapping[str, float]
    point_mean_potential_mw: float
    point_mean_available_mw: float
    point_mean_envelope_mw: float
    point_mean_excess_mw: float


def simulate_point(
    spec: PointSimulationSpec,
    *,
    days: Sequence[date],
    samples: ScenarioSamples,
    schedule: MaintenanceSchedule | None = None,
    scenario: str = SCENARIO_NO_MAINTENANCE,
    record_plant_totals: bool = False,
) -> PointSimulationResult:
    """Simulate every plant of the point at half-hour resolution.

    All plants share the same weather samples, so spatial correlation is preserved. The
    selected plant keeps only its own share of the point envelope; the energy of the other
    entities is never reported as the selected plant's energy. ``record_plant_totals`` also
    accumulates the mean available and curtailed generation of every entity of the point.
    """
    if not spec.plants:
        raise ValueError("point simulation needs at least one plant")
    if len(days) != samples.day_count:
        raise ValueError("scenario samples do not match the requested horizon")
    intervals = len(days) * INTERVALS_PER_DAY
    month_hour_index: list[int] = []
    day_index: list[int] = []
    for offset, day in enumerate(days):
        for slot in range(INTERVALS_PER_DAY):
            month_hour_index.append((day.month - 1) * INTERVALS_PER_DAY + slot)
            day_index.append(offset)

    plants = tuple(sorted(spec.plants, key=lambda item: item.plant_id))
    selected_position = next(
        (
            position
            for position, plant in enumerate(plants)
            if plant.plant_id == spec.selected_asset_id
        ),
        None,
    )
    if selected_position is None:
        raise ValueError(f"selected plant {spec.selected_asset_id} is not linked to the point")

    base_series: list[tuple[float, ...]] = [
        tuple(plant.month_hour_climatology[index] for index in month_hour_index) for plant in plants
    ]
    derates: list[tuple[float, ...]] = [
        (
            schedule.derate_series(plant.plant_id, intervals=intervals)
            if schedule is not None
            else (1.0,) * intervals
        )
        for plant in plants
    ]
    noise: list[tuple[float, ...]] = [samples.plant_noise[plant.plant_id] for plant in plants]
    availability: list[tuple[tuple[float, ...], ...]] = [
        samples.availability[plant.plant_id] for plant in plants
    ]
    lookups = [plant.potential_lookup for plant in plants]
    steps = [plant.lookup_step for plant in plants]

    intercept = spec.envelope_intercept_mw
    slope = _clamp(spec.envelope_slope, 0.0, 1.0)
    selected_curtailed: list[tuple[float, ...]] = []
    selected_available: list[tuple[float, ...]] = []
    selected_resource_potential: list[tuple[float, ...]] = []
    point_potential: list[tuple[float, ...]] = []
    point_available: list[tuple[float, ...]] = []
    point_envelope: list[tuple[float, ...]] = []
    point_excess: list[tuple[float, ...]] = []
    plant_operational_capacity_sum = [0.0] * len(plants)
    plant_availability_sum = [0.0] * len(plants)
    plant_available_sum = [0.0] * len(plants)
    plant_potential_sum = [0.0] * len(plants)
    plant_accepted_limit_sum = [0.0] * len(plants)
    plant_generation_sum = [0.0] * len(plants)
    plant_curtailed_sum = [0.0] * len(plants)
    available_generations: list[float] = [0.0] * len(plants)
    resource_potentials: list[float] = [0.0] * len(plants)
    availability_capacities: list[float] = [0.0] * len(plants)
    operational_capacities: list[float] = [0.0] * len(plants)
    for scenario_index in range(samples.scenario_count):
        factors = samples.day_factors[scenario_index]
        curtailed_series: list[float] = []
        available_series: list[float] = []
        selected_potential_series: list[float] = []
        potential_series: list[float] = []
        point_available_series: list[float] = []
        envelope_series: list[float] = []
        excess_series: list[float] = []
        for interval in range(intervals):
            factor = factors[day_index[interval]]
            total_resource_potential = 0.0
            total_available_generation = 0.0
            selected_available_value = 0.0
            selected_potential_value = 0.0
            for position, plant in enumerate(plants):
                weather = (
                    base_series[position][interval] * factor * noise[position][scenario_index]
                )
                weather_potential = lookup_potential_mw(
                    lookups[position], weather, step=steps[position]
                )
                equipment_factor = availability[position][scenario_index][day_index[interval]]
                operational_capacity = plant.capacity_mw * equipment_factor
                availability_capacity = operational_capacity * derates[position][interval]
                resource_potential = min(weather_potential, operational_capacity)
                available_generation = min(resource_potential, availability_capacity)
                operational_capacities[position] = operational_capacity
                availability_capacities[position] = availability_capacity
                resource_potentials[position] = resource_potential
                available_generations[position] = available_generation
                total_resource_potential += resource_potential
                total_available_generation += available_generation
                if position == selected_position:
                    selected_available_value = available_generation
                    selected_potential_value = resource_potential
            envelope = accepted_envelope_mw(
                total_available_generation, intercept_mw=intercept, slope=slope
            )
            ratio = envelope / total_available_generation if total_available_generation > 0 else 0.0
            potential_series.append(total_resource_potential)
            point_available_series.append(total_available_generation)
            envelope_series.append(envelope)
            excess_series.append(total_available_generation - envelope)
            available_series.append(selected_available_value)
            selected_potential_series.append(selected_potential_value)
            selected_curtailed_value = selected_available_value * (1.0 - ratio)
            curtailed_series.append(selected_curtailed_value)
            if record_plant_totals:
                for position in range(len(plants)):
                    accepted_limit = available_generations[position] * ratio
                    generation = min(resource_potentials[position], accepted_limit)
                    plant_operational_capacity_sum[position] += operational_capacities[position]
                    plant_availability_sum[position] += availability_capacities[position]
                    plant_available_sum[position] += available_generations[position]
                    plant_potential_sum[position] += resource_potentials[position]
                    plant_accepted_limit_sum[position] += accepted_limit
                    plant_generation_sum[position] += generation
                    plant_curtailed_sum[position] += max(
                        available_generations[position] - generation, 0.0
                    )
        selected_curtailed.append(tuple(curtailed_series))
        selected_available.append(tuple(available_series))
        selected_resource_potential.append(tuple(selected_potential_series))
        point_potential.append(tuple(potential_series))
        point_available.append(tuple(point_available_series))
        point_envelope.append(tuple(envelope_series))
        point_excess.append(tuple(excess_series))
    divisor = samples.scenario_count * intervals

    def plant_means(values: Sequence[float]) -> dict[str, float]:
        return {
            plant.plant_id: round(values[position] / divisor, 6)
            for position, plant in enumerate(plants)
        }

    return PointSimulationResult(
        point_id=spec.point_id,
        scenario=scenario,
        selected_asset_id=spec.selected_asset_id,
        intervals=intervals,
        selected_curtailed_mw=tuple(selected_curtailed),
        selected_available_mw=tuple(selected_available),
        selected_potential_mw=tuple(selected_resource_potential),
        point_potential_mw=tuple(point_potential),
        point_available_mw=tuple(point_available),
        point_envelope_mw=tuple(point_envelope),
        point_excess_mw=tuple(point_excess),
        plant_mean_operational_capacity_mw=plant_means(plant_operational_capacity_sum),
        plant_mean_availability_mw=plant_means(plant_availability_sum),
        plant_mean_available_mw=plant_means(plant_available_sum),
        plant_mean_potential_mw=plant_means(plant_potential_sum),
        plant_mean_accepted_limit_mw=plant_means(plant_accepted_limit_sum),
        plant_mean_generation_mw=plant_means(plant_generation_sum),
        plant_mean_curtailed_mw=plant_means(plant_curtailed_sum),
        point_mean_potential_mw=round(sum(sum(series) for series in point_potential) / divisor, 6),
        point_mean_available_mw=round(sum(sum(series) for series in point_available) / divisor, 6),
        point_mean_envelope_mw=round(sum(sum(series) for series in point_envelope) / divisor, 6),
        point_mean_excess_mw=round(sum(sum(series) for series in point_excess) / divisor, 6),
    )


def scenario_daily_mwh(
    series: tuple[tuple[float, ...], ...], *, intervals_per_day: int = INTERVALS_PER_DAY
) -> tuple[tuple[float, ...], ...]:
    """Daily MWh per scenario from a half-hour MW series."""
    daily: list[tuple[float, ...]] = []
    for scenario in series:
        days: list[float] = []
        for start in range(0, len(scenario), intervals_per_day):
            window = scenario[start : start + intervals_per_day]
            days.append(round(sum(window) * INTERVAL_HOURS, 6))
        daily.append(tuple(days))
    return tuple(daily)


def mean_and_quantiles(
    daily_mwh: tuple[tuple[float, ...], ...],
    *,
    lower_quantile: float = 0.1,
    upper_quantile: float = 0.9,
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """Expected value plus a scenario quantile band for every day.

    The band is widened to contain the expected value: with few scenarios and a skewed daily
    distribution (most scenarios at zero, one much larger) the 90th percentile can sit below
    the mean, and a published interval that excludes its own point estimate is not a valid
    interval. The widening is a definitional property of the interval, not a cosmetic clamp of
    the scenario results.
    """
    if not daily_mwh:
        raise ValueError("daily scenario series cannot be empty")
    day_count = len(daily_mwh[0])
    expected: list[float] = []
    lower: list[float] = []
    upper: list[float] = []
    for day in range(day_count):
        values = sorted(scenario[day] for scenario in daily_mwh)
        mean = sum(values) / len(values)
        expected.append(round(mean, 6))
        lower.append(round(min(_quantile(values, lower_quantile), mean), 6))
        upper.append(round(max(_quantile(values, upper_quantile), mean), 6))
    return tuple(expected), tuple(lower), tuple(upper)


def _quantile(sorted_values: Sequence[float], quantile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = _clamp(quantile, 0.0, 1.0) * (len(sorted_values) - 1)
    lower_index = int(math.floor(position))
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = position - lower_index
    return float(
        sorted_values[lower_index] * (1.0 - fraction) + sorted_values[upper_index] * fraction
    )


def scenario_event_probability(
    daily_mwh: tuple[tuple[float, ...], ...], *, threshold_mwh: float = 0.0
) -> tuple[float, ...]:
    """Share of scenarios with curtailment on each day: occurrence, not severity."""
    if not daily_mwh:
        raise ValueError("daily scenario series cannot be empty")
    day_count = len(daily_mwh[0])
    return tuple(
        round(
            sum(1 for scenario in daily_mwh if scenario[day] > threshold_mwh) / len(daily_mwh),
            6,
        )
        for day in range(day_count)
    )


@dataclass(frozen=True)
class WindowMetric:
    """One candidate 72-hour window of the point or plant series."""

    start_interval: int
    interval_count: int
    expected_mwh: float
    probability: float

    @property
    def end_interval(self) -> int:
        return self.start_interval + self.interval_count


def window_metrics(
    series: tuple[tuple[float, ...], ...],
    *,
    window_intervals: int = CRITICAL_WINDOW_INTERVALS,
    intervals_per_day: int = INTERVALS_PER_DAY,
) -> tuple[WindowMetric, ...]:
    """Every day-aligned window of exactly ``window_intervals`` half-hour intervals."""
    if not series:
        raise ValueError("window metrics need at least one scenario")
    horizon = len(series[0])
    metrics: list[WindowMetric] = []
    for start in range(0, horizon - window_intervals + 1, intervals_per_day):
        totals = [
            sum(scenario[start : start + window_intervals]) * INTERVAL_HOURS for scenario in series
        ]
        expected = sum(totals) / len(totals)
        probability = sum(1 for total in totals if total > 0.0) / len(totals)
        metrics.append(
            WindowMetric(
                start_interval=start,
                interval_count=window_intervals,
                expected_mwh=round(expected, 6),
                probability=round(probability, 6),
            )
        )
    return tuple(metrics)


def select_critical_windows(
    metrics: Sequence[WindowMetric], *, count: int = CRITICAL_WINDOW_COUNT
) -> tuple[WindowMetric, ...]:
    """Rank by expected MWh then probability, dropping every overlapping candidate."""
    ranked = sorted(
        metrics,
        key=lambda metric: (-metric.expected_mwh, -metric.probability, metric.start_interval),
    )
    selected: list[WindowMetric] = []
    for metric in ranked:
        if len(selected) >= count:
            break
        if any(
            metric.start_interval < chosen.end_interval
            and chosen.start_interval < metric.end_interval
            for chosen in selected
        ):
            continue
        selected.append(metric)
    return tuple(selected)


def window_expected_mwh(series: tuple[tuple[float, ...], ...], window: WindowMetric) -> float:
    """Expected MWh of an already selected window, recomputed on any scenario set."""
    totals = [
        sum(scenario[window.start_interval : window.end_interval]) * INTERVAL_HOURS
        for scenario in series
    ]
    return round(sum(totals) / len(totals), 6)


def format_display_label(day: date) -> str:
    """``DD/MM`` label used by the daily line chart."""
    return f"{day.day:02d}/{day.month:02d}"


def format_window_bounds(start: date, window: WindowMetric) -> tuple[str, str]:
    """ISO instants of a window, from its first interval to its last one."""
    begins = datetime.combine(start, datetime.min.time()) + timedelta(
        minutes=int(window.start_interval * INTERVAL_HOURS * 60)
    )
    ends = begins + timedelta(minutes=int(window.interval_count * INTERVAL_HOURS * 60))
    return begins.isoformat(), ends.isoformat()
