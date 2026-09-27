"""Individual plant curtailment risk and energy forecast (plan Task 3).

Two quantities are produced separately and never multiplied together:

* occurrence — the calibrated probability that the plant carries at least one restricted
  half-hour interval on the day, estimated from an explicit binary target built on
  ``flg_geracaorestrita`` with features available strictly before the forecast day;
* severity — the expected curtailed MWh, produced by the half-hour point simulation of
  every plant linked to the connection point, including the simulated maintenance agenda.

The probability model is validated by a recursive temporal backtest. Calibration is accepted
only when it improves the Brier score on paths that were never used to fit it; otherwise the
empirical uncalibrated probability is published and the negative result is recorded.

No feature reads the verified generation, the availability or the capacity factor of the
forecast interval itself. Lags always come from ``shift(1)`` windows.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from curtailess import plant_exposure_history as history_module
from curtailess.point_exposure_simulation import (
    CRITICAL_WINDOW_COUNT,
    DEFAULT_SCENARIO_COUNT,
    INTERVALS_PER_DAY,
    ORIGIN_SIMULATED,
    SCENARIO_CANDIDATE_MAINTENANCE,
    SCENARIO_NO_MAINTENANCE,
    SCENARIO_SCHEDULED_MAINTENANCE,
    SIMULATION_METHOD,
    WEATHER_SOURCE_CLIMATOLOGY,
    WEATHER_UNIT_SOLAR,
    WEATHER_UNIT_WIND,
    MaintenanceSchedule,
    PlantSimulationSpec,
    PointSimulationResult,
    PointSimulationSpec,
    PointWeatherOutlook,
    ScenarioSamples,
    build_maintenance_schedule,
    build_potential_lookup,
    build_scenario_samples,
    candidate_maintenance_window,
    climatology_outlook,
    fit_acceptance_envelope,
    format_display_label,
    format_window_bounds,
    load_weather_snapshot,
    mean_and_quantiles,
    scenario_daily_mwh,
    scenario_event_probability,
    select_critical_windows,
    simulate_point,
    window_expected_mwh,
    window_metrics,
)

SCHEMA = "curtailless.individual_plant_forecast.v1"
HORIZON_DAYS = 60
PROXY_ORIGIN = history_module.PROXY_ORIGIN
ONS_ORIGIN = history_module.ONS_ORIGIN
PROBABILITY_STATUS_CALIBRATED = "backtested_calibrated"
PROBABILITY_STATUS_UNCALIBRATED = "backtested_empirical_uncalibrated"
PROBABILITY_STATUS_BASELINE = "baseline_historical_frequency"
POTENTIAL_QUANTILE = 0.85
PROBABILITY_ALERT_THRESHOLD = 0.95
PROBABILITY_EXTREME_THRESHOLD = 0.99
LOGISTIC_ITERATIONS = 500
LOGISTIC_LEARNING_RATE = 0.45
LOGISTIC_L2 = 0.02
LOGISTIC_L2_GRID = (0.02, 0.25, 1.0)
CALIBRATION_PATH_DAYS = 60
BACKTEST_TEST_PATHS = 4
BACKTEST_VALIDATION_PATHS = 2
RELIABILITY_BIN_COUNT = 5
LOGIT_EPSILON = 1e-4
MINIMUM_RATE = 0.001
# Empirical-Bayes shrinkage: small-sample rates (a weekday, a month, a 7-day window) are pulled
# toward the base rate of the fitting window. Without it, a week with seven restricted days
# produces logit(1.0) = 9.2 and the standardisation of that feature amplifies it into a
# near-certain probability for the whole horizon.
ACTIVITY_SHRINKAGE_PRIOR_DAYS = 14.0
SEASONAL_SHRINKAGE_PRIOR_DAYS = 21.0
PRESSURE_SHRINKAGE_PRIOR_DAYS = 7.0
PROBABILITY_SOURCE_MODEL_CALIBRATED = "model_calibrated_backtested"
PROBABILITY_SOURCE_MODEL_RAW = "model_raw_backtested"
PROBABILITY_SOURCE_BASELINE = "baseline_frequency_seasonal"
ALERT_BAND_LOWER = 0.8
# A published 60-day series may never sit entirely above the alert threshold: that is the
# saturated regime the gate exists to catch. Isolated values above it remain allowed when the
# out-of-sample evidence supports them, but never all 60 days.
PUBLISHED_SATURATION_THRESHOLD = PROBABILITY_ALERT_THRESHOLD
# The horizon may not leave, materially, the probability range the model was validated on. A
# trajectory that sits systematically above (or below) the frozen validation support is
# extrapolation no matter whether the calibration or the raw model is published, so it is marked
# ineligible and the best eligible baseline of the frozen validation ranking is published instead.
# A couple of isolated days outside the support are tolerated; a shift of the whole trajectory is
# not.
OUT_OF_SUPPORT_TOLERANCE_DAYS = 2
# A published series with dozens of days above the alert threshold is only defensible when the
# validation paths actually reached that range. When those days come from an out-of-support
# extrapolation the gate refuses the series instead of publishing a saturated curve.
PUBLISHED_DOZENS_ABOVE_95 = 20
CANDIDATE_MODEL_RAW = "model_raw"
CANDIDATE_MODEL_CALIBRATED = "model_calibrated"
BASELINE_NAMES = ("frequency", "persistence", "seasonal", "seasonal_blend")
SOURCE_BY_CANDIDATE = {
    CANDIDATE_MODEL_CALIBRATED: PROBABILITY_SOURCE_MODEL_CALIBRATED,
    CANDIDATE_MODEL_RAW: PROBABILITY_SOURCE_MODEL_RAW,
    **{f"baseline_{name}": PROBABILITY_SOURCE_BASELINE for name in BASELINE_NAMES},
}
STATUS_BY_CANDIDATE = {
    CANDIDATE_MODEL_CALIBRATED: PROBABILITY_STATUS_CALIBRATED,
    CANDIDATE_MODEL_RAW: PROBABILITY_STATUS_UNCALIBRATED,
    **{f"baseline_{name}": PROBABILITY_STATUS_BASELINE for name in BASELINE_NAMES},
}

FEATURE_NAMES = (
    "bias",
    "seasonal_month_rate",
    "weekday_rate",
    "event_rate_7d",
    "event_rate_30d",
    "mean_mwh_7d_per_capacity",
    "point_pressure_7d",
    "weather_normal_z",
)

LIMITATIONS = (
    "A probabilidade responde à ocorrência de restrição e os MWh respondem à severidade; "
    "as duas quantidades são calculadas separadamente e nunca multiplicadas.",
    "O alvo histórico de ocorrência é flg_geracaorestrita da própria usina, nunca a geração "
    "verificada, a disponibilidade ou o fator de capacidade do intervalo previsto.",
    "O backtest é temporal e recursivo; o ajuste usa apenas o passado do ponto de emissão, a "
    "regularização e a calibração são escolhidas nos caminhos de validação e o teste é "
    "preservado; a calibração só é aceita quando melhora o Brier e não piora a confiabilidade.",
    "Quando o modelo não supera o baseline de frequência histórica fora da amostra, a "
    "probabilidade publicada é o baseline sazonal de frequência, declarado no artefato.",
    "As taxas de mês, dia da semana e das janelas recentes passam por encolhimento empírico "
    "em direção à taxa base, para que amostras pequenas não virem certeza.",
    "A meteorologia histórica vem da própria usina e a prevista entra como anomalia "
    "padronizada da rodada arquivada, aplicada sobre a climatologia da usina.",
    "Não há snapshots históricos de emissão de previsão meteorológica; por isso o backtest "
    "mede a ocorrência e a severidade sem a previsão meteorológica do dia.",
    "Além do horizonte útil da rodada de curto prazo, a incerteza cresce com a distância e a "
    "previsão passa a depender de cenários sazonais e climatológicos.",
    "As agendas de manutenção das demais usinas são simuladas e não representam coordenação "
    "real entre agentes.",
    "A energia das demais entidades do ponto nunca é apresentada como energia da usina "
    "selecionada.",
)


# --------------------------------------------------------------------------------------
# daily history and features
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlantDailyHistory:
    """Reconciled daily history of one plant: occurrence and allocated energy.

    ``restricted`` holds observed 0/1 flags for a measured history and the model's *expected*
    indicator (a probability) for the days inside a recursive path.
    """

    asset_id: str
    days: tuple[date, ...]
    restricted: tuple[float, ...]
    curtailed_mwh: tuple[float, ...]

    def __post_init__(self) -> None:
        if not (len(self.days) == len(self.restricted) == len(self.curtailed_mwh)):
            raise ValueError("plant history series must have the same length")
        if tuple(sorted(set(self.days))) != self.days:
            raise ValueError("plant history days must be sorted and unique")

    @property
    def event_rate(self) -> float:
        if not self.days:
            return 0.0
        return sum(float(flag) for flag in self.restricted) / len(self.days)

    @property
    def capacity_normalised_mean_mwh(self) -> float:
        return sum(self.curtailed_mwh) / len(self.curtailed_mwh) if self.days else 0.0


def _logit(probability: float) -> float:
    bounded = min(max(float(probability), LOGIT_EPSILON), 1.0 - LOGIT_EPSILON)
    return math.log(bounded / (1.0 - bounded))


def _sigmoid(value: float) -> float:
    if value >= 0:
        exponent = math.exp(-value)
        return 1.0 / (1.0 + exponent)
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def _rate(values: Iterable[float]) -> float | None:
    items = list(values)
    if not items:
        return None
    return sum(float(item) for item in items) / len(items)


def _shrunk_rate(values: Iterable[float], *, prior_rate: float, prior_days: float) -> float | None:
    """Empirical-Bayes rate: ``(events + prior_rate * prior_days) / (days + prior_days)``.

    Small samples are pulled toward the base rate of the fitting window, which keeps the
    feature inside a defensible range instead of reaching ``logit(1.0)``.
    """
    items = list(values)
    if not items:
        return None
    events = sum(float(item) for item in items)
    return (events + prior_rate * prior_days) / (len(items) + prior_days)


def _shrunk_share(values: Iterable[float], *, prior_rate: float, prior_days: float) -> float | None:
    """Same shrinkage for a mean of shares (point pressure)."""
    items = [float(item) for item in values]
    if not items:
        return None
    total = sum(items)
    return (total + prior_rate * prior_days) / (len(items) + prior_days)


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    if not items:
        return None
    return sum(items) / len(items)


def seasonal_rates(
    history: PlantDailyHistory, *, index: int
) -> tuple[dict[int, float], dict[int, float], float]:
    """Month, weekday and overall event rates fitted only before ``index``.

    Month and weekday rates are shrunk toward the overall rate of the fitting window, so a
    category with few observations (or a fully restricted week) cannot produce an extreme
    feature value.
    """
    restricted = history.restricted[:index]
    days = history.days[:index]
    overall = _rate(restricted) or 0.0
    by_month: dict[int, list[float]] = {}
    by_weekday: dict[int, list[float]] = {}
    for day, flag in zip(days, restricted, strict=True):
        by_month.setdefault(day.month, []).append(flag)
        by_weekday.setdefault(day.weekday(), []).append(flag)
    month_rates = {
        month: _shrunk_rate(flags, prior_rate=overall, prior_days=SEASONAL_SHRINKAGE_PRIOR_DAYS)
        or overall
        for month, flags in by_month.items()
    }
    weekday_rates = {
        weekday: _shrunk_rate(flags, prior_rate=overall, prior_days=SEASONAL_SHRINKAGE_PRIOR_DAYS)
        or overall
        for weekday, flags in by_weekday.items()
    }
    return month_rates, weekday_rates, overall


def feature_row(
    *,
    day: date,
    history: PlantDailyHistory,
    point_share: Sequence[float],
    month_rate: float,
    weekday_rate: float,
    weather_normal_z: float,
    capacity_mw: float,
    shift_days: int = 1,
) -> tuple[float, ...]:
    """Features of one day built only from values before that day.

    ``shift_days`` is fixed at 1: the trailing windows end on the previous day, so the value
    of the forecast day itself can never enter its own features. Every rate is shrunk toward
    the base rate of the fitting window, which is the only level available at issue time.
    """
    index = bisect.bisect_left(history.days, day)
    end = max(index - shift_days + 1, 0)
    window7 = range(max(0, end - 7), end)
    window30 = range(max(0, end - 30), end)
    fallback_rate = month_rate
    base_rate = min(max(fallback_rate, MINIMUM_RATE), 1.0 - MINIMUM_RATE)
    event_rate_7 = _shrunk_rate(
        (history.restricted[i] for i in window7),
        prior_rate=base_rate,
        prior_days=ACTIVITY_SHRINKAGE_PRIOR_DAYS,
    )
    event_rate_30 = _shrunk_rate(
        (history.restricted[i] for i in window30),
        prior_rate=base_rate,
        prior_days=ACTIVITY_SHRINKAGE_PRIOR_DAYS,
    )
    mean_mwh_7 = _mean(history.curtailed_mwh[i] for i in window7)
    pressure_7 = _shrunk_share(
        (point_share[i] for i in window7 if i < len(point_share)),
        prior_rate=base_rate,
        prior_days=PRESSURE_SHRINKAGE_PRIOR_DAYS,
    )
    capacity = capacity_mw if capacity_mw > 0 else 1.0
    return (
        1.0,
        _logit(month_rate),
        _logit(weekday_rate),
        _logit(fallback_rate if event_rate_7 is None else event_rate_7),
        _logit(fallback_rate if event_rate_30 is None else event_rate_30),
        _logit(min((fallback_rate if mean_mwh_7 is None else mean_mwh_7 / capacity) / 24.0, 0.99)),
        _logit(fallback_rate if pressure_7 is None else pressure_7),
        float(weather_normal_z),
    )


# --------------------------------------------------------------------------------------
# probability model
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LogisticModel:
    """Logistic regression with standardised features, fitted by gradient descent."""

    coefficients: tuple[float, ...]
    means: tuple[float, ...]
    deviations: tuple[float, ...]

    def probability(self, row: Sequence[float]) -> float:
        standardised = [
            row[0],
            *(
                (value - mean) / (deviation if deviation > 1e-9 else 1.0)
                for value, mean, deviation in zip(
                    row[1:], self.means[1:], self.deviations[1:], strict=True
                )
            ),
        ]
        total = sum(
            coefficient * value
            for coefficient, value in zip(self.coefficients, standardised, strict=True)
        )
        return _sigmoid(total)


def fit_logistic_model(
    rows: Sequence[Sequence[float]],
    targets: Sequence[int],
    *,
    iterations: int = LOGISTIC_ITERATIONS,
    learning_rate: float = LOGISTIC_LEARNING_RATE,
    l2: float = LOGISTIC_L2,
) -> LogisticModel:
    """Fit the occurrence model on training days only, in chronological order."""
    if len(rows) != len(targets):
        raise ValueError("rows and targets must have the same length")
    if not rows:
        raise ValueError("the probability model needs training days")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ValueError("every feature row must have the same width")
    means = [0.0] * width
    deviations = [1.0] * width
    for column in range(1, width):
        values = [row[column] for row in rows]
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        means[column] = mean
        deviations[column] = math.sqrt(variance)
    standardised = [
        [
            row[0],
            *(
                (value - means[column]) / (deviations[column] if deviations[column] > 1e-9 else 1.0)
                for column, value in enumerate(row[1:], start=1)
            ),
        ]
        for row in rows
    ]
    coefficients = [0.0] * width
    base_rate = sum(targets) / len(targets)
    coefficients[0] = _logit(min(max(base_rate, MINIMUM_RATE), 1.0 - MINIMUM_RATE))
    count = len(standardised)
    for _ in range(iterations):
        gradients = [0.0] * width
        for row, target in zip(standardised, targets, strict=True):
            probability = _sigmoid(
                sum(
                    coefficient * value
                    for coefficient, value in zip(coefficients, row, strict=True)
                )
            )
            error = probability - target
            for column in range(width):
                gradients[column] += error * row[column]
        for column in range(width):
            penalty = 0.0 if column == 0 else l2 * coefficients[column]
            coefficients[column] -= learning_rate * (gradients[column] / count + penalty)
    return LogisticModel(
        coefficients=tuple(round(value, 8) for value in coefficients),
        means=tuple(round(value, 8) for value in means),
        deviations=tuple(round(value, 8) for value in deviations),
    )


@dataclass(frozen=True)
class PlattCalibration:
    """Platt scaling fitted on validation paths only.

    ``support_low``/``support_high`` bound the raw probabilities the map was fitted on. Applying
    it outside that window is extrapolation, so :func:`apply_calibration_with_support` refuses
    instead of silently pushing a horizon probability toward the asymptote.
    """

    slope: float
    intercept: float
    support_low: float
    support_high: float

    def apply(self, probability: float) -> float:
        return _sigmoid(self.slope * _logit(probability) + self.intercept)

    def supports(self, probability: float) -> bool:
        return self.support_low <= probability <= self.support_high


def fit_platt_calibration(
    probabilities: Sequence[float], targets: Sequence[int], *, iterations: int = 400
) -> PlattCalibration:
    """Fit ``sigmoid(a * logit(p) + b)`` on a path never used for the test."""
    if len(probabilities) != len(targets):
        raise ValueError("probabilities and targets must have the same length")
    if not probabilities:
        raise ValueError("calibration needs validation predictions")
    logits = [_logit(probability) for probability in probabilities]
    slope = 1.0
    intercept = 0.0
    learning_rate = 0.3
    count = len(logits)
    for _ in range(iterations):
        gradient_slope = 0.0
        gradient_intercept = 0.0
        for logit, target in zip(logits, targets, strict=True):
            probability = _sigmoid(slope * logit + intercept)
            error = probability - target
            gradient_slope += error * logit
            gradient_intercept += error
        slope -= learning_rate * gradient_slope / count
        intercept -= learning_rate * gradient_intercept / count
    return PlattCalibration(
        slope=round(slope, 8),
        intercept=round(intercept, 8),
        support_low=round(min(probabilities), 8),
        support_high=round(max(probabilities), 8),
    )


def apply_calibration_with_support(
    calibration: PlattCalibration, probabilities: Sequence[float]
) -> tuple[list[float], bool]:
    """Apply a calibration only inside its fitted support; refuse extrapolation.

    Returns the calibrated series and whether the map was applicable. Refusing is the honest
    outcome: a calibration fitted where the plant was almost always restricted cannot be
    extrapolated to a horizon whose raw probabilities live far below that window.
    """
    if any(not calibration.supports(probability) for probability in probabilities):
        return [float(probability) for probability in probabilities], False
    return [round(calibration.apply(probability), 6) for probability in probabilities], True


def brier_score(probabilities: Sequence[float], targets: Sequence[int]) -> float:
    if not probabilities:
        return 0.0
    return round(
        sum(
            (probability - target) ** 2
            for probability, target in zip(probabilities, targets, strict=True)
        )
        / len(probabilities),
        6,
    )


def reliability_bins(
    probabilities: Sequence[float],
    targets: Sequence[int],
    *,
    bin_count: int = RELIABILITY_BIN_COUNT,
) -> tuple[dict[str, Any], ...]:
    """Mean predicted probability against the observed rate in each bin."""
    if not probabilities:
        return ()
    bins: list[dict[str, Any]] = []
    for index in range(bin_count):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        members = [
            (probability, target)
            for probability, target in zip(probabilities, targets, strict=True)
            if lower <= probability < upper or (index == bin_count - 1 and probability == 1.0)
        ]
        if not members:
            continue
        bins.append(
            {
                "bin_lower": round(lower, 4),
                "bin_upper": round(upper, 4),
                "count": len(members),
                "mean_predicted": round(sum(item[0] for item in members) / len(members), 6),
                "observed_rate": round(sum(item[1] for item in members) / len(members), 6),
            }
        )
    return tuple(bins)


# --------------------------------------------------------------------------------------
# recursive temporal backtest
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BacktestPlan:
    """Chronological split of the daily history into train, validation and test paths."""

    train_end: int
    validation_origins: tuple[int, ...]
    test_origins: tuple[int, ...]
    path_days: int = CALIBRATION_PATH_DAYS


def default_backtest_plan(
    day_count: int, *, path_days: int = CALIBRATION_PATH_DAYS
) -> BacktestPlan:
    """Reserve the last paths for test, the previous ones for validation and the rest for train."""
    paths = day_count // path_days
    if paths < 4:
        raise ValueError("the backtest needs at least four complete 60-day paths")
    test_paths = min(BACKTEST_TEST_PATHS, paths - 2)
    validation_paths = min(BACKTEST_VALIDATION_PATHS, paths - test_paths - 1)
    train_paths = paths - test_paths - validation_paths
    train_end = train_paths * path_days
    validation_origins = tuple(train_end + index * path_days for index in range(validation_paths))
    test_origins = tuple(
        train_end + (validation_paths + index) * path_days for index in range(test_paths)
    )
    return BacktestPlan(
        train_end=train_end,
        validation_origins=validation_origins,
        test_origins=test_origins,
        path_days=path_days,
    )


@dataclass(frozen=True)
class PathPrediction:
    """One recursive prediction of one day inside a backtest path."""

    day: date
    origin: int
    raw_probability: float
    observed: int
    observed_mwh: float
    predicted_mwh: float
    persistence_probability: float
    seasonal_probability: float
    weekday_probability: float
    frequency_probability: float


def _seasonal_energy_factors(history: PlantDailyHistory, *, index: int) -> dict[int, float]:
    if index <= 0:
        return {}
    overall = _mean(history.curtailed_mwh[:index]) or 0.0
    if overall <= 0:
        return {}
    by_month: dict[int, list[float]] = {}
    for day, value in zip(history.days[:index], history.curtailed_mwh[:index], strict=True):
        by_month.setdefault(day.month, []).append(value)
    return {month: (sum(values) / len(values)) / overall for month, values in by_month.items()}


def predict_path(
    *,
    history: PlantDailyHistory,
    point_share: Sequence[float],
    weather_normal_z: Mapping[date, float],
    capacity_mw: float,
    origin: int,
    path_days: int,
    plan_origin: int | None = None,
    l2: float = LOGISTIC_L2,
) -> tuple[PathPrediction, ...]:
    """Recursive path: fit on days before ``origin`` and predict ``path_days`` ahead.

    Inside the path the working series stores the model's *expected* indicator (its own
    probability), not a hard threshold, so the recursion cannot lock the lag features at
    "restricted" for the whole horizon.
    """
    if origin <= 0:
        raise ValueError("the origin must have training days before it")
    month_rates, weekday_rates, overall_rate = seasonal_rates(history, index=origin)
    energy_factors = _seasonal_energy_factors(history, index=origin)
    rows = [
        feature_row(
            day=history.days[index],
            history=history,
            point_share=point_share,
            month_rate=month_rates.get(history.days[index].month, overall_rate),
            weekday_rate=weekday_rates.get(history.days[index].weekday(), overall_rate),
            weather_normal_z=weather_normal_z.get(history.days[index], 0.0),
            capacity_mw=capacity_mw,
        )
        for index in range(1, origin)
    ]
    targets = [1 if flag else 0 for flag in history.restricted[1:origin]]
    model = fit_logistic_model(rows, targets, l2=l2)
    predictions: list[PathPrediction] = []
    working_restricted: list[float] = [1.0 if flag else 0.0 for flag in history.restricted[:origin]]
    working_mwh = list(history.curtailed_mwh[:origin])
    working_days = list(history.days[:origin])
    working_pressure = list(point_share[:origin])
    last_known = bool(history.restricted[origin - 1]) if origin else False
    for offset in range(path_days):
        index = origin + offset
        if index >= len(history.days):
            break
        day = history.days[index]
        trailing30 = [value for value in working_mwh[-30:] if value >= 0]
        trailing_mean = sum(trailing30) / len(trailing30) if trailing30 else 0.0
        factor = energy_factors.get(day.month, 1.0)
        predicted_mwh = max(0.0, trailing_mean * factor)
        row = feature_row(
            day=day,
            history=PlantDailyHistory(
                asset_id=history.asset_id,
                days=tuple(working_days),
                restricted=tuple(working_restricted),
                curtailed_mwh=tuple(working_mwh),
            ),
            point_share=working_pressure,
            month_rate=month_rates.get(day.month, overall_rate),
            weekday_rate=weekday_rates.get(day.weekday(), overall_rate),
            weather_normal_z=weather_normal_z.get(day, 0.0),
            capacity_mw=capacity_mw,
        )
        probability = model.probability(row)
        observed = 1 if history.restricted[index] else 0
        predictions.append(
            PathPrediction(
                day=day,
                origin=origin,
                raw_probability=round(probability, 6),
                observed=observed,
                observed_mwh=round(history.curtailed_mwh[index], 6),
                predicted_mwh=round(predicted_mwh, 6),
                persistence_probability=1.0 if last_known else 0.0,
                seasonal_probability=round(month_rates.get(day.month, overall_rate), 6),
                weekday_probability=round(weekday_rates.get(day.weekday(), overall_rate), 6),
                frequency_probability=round(overall_rate, 6),
            )
        )
        working_days.append(day)
        working_restricted.append(probability)
        working_mwh.append(predicted_mwh)
        working_pressure.append(probability)
        last_known = bool(history.restricted[index])
    return tuple(predictions)


def interval_coverage(
    *, residuals: Sequence[float], predicted: Sequence[float], observed: Sequence[float]
) -> dict[str, float]:
    """Empirical coverage of a residual-based band, reported honestly even when it is low."""
    if not residuals:
        return {"coverage": 0.0, "lower_mwh": 0.0, "upper_mwh": 0.0}
    ordered = sorted(residuals)
    lower_residual = ordered[int(0.1 * (len(ordered) - 1))]
    upper_residual = ordered[int(0.9 * (len(ordered) - 1))]
    inside = sum(
        1
        for prediction, value in zip(predicted, observed, strict=True)
        if prediction + lower_residual <= value <= prediction + upper_residual
    )
    return {
        "coverage": round(inside / len(predicted), 6),
        "lower_residual_mwh": round(lower_residual, 6),
        "upper_residual_mwh": round(upper_residual, 6),
    }


@dataclass(frozen=True)
class CandidateScore:
    """One publishable probability source, ranked on validation and reported on test."""

    name: str
    kind: str
    validation_brier: float
    validation_reliability_gap: float
    test_brier: float
    test_reliability_gap: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "validation_brier": self.validation_brier,
            "validation_reliability_gap": self.validation_reliability_gap,
            "test_brier": self.test_brier,
            "test_reliability_gap": self.test_reliability_gap,
        }


def _blended_probability(seasonal: float, weekday: float) -> float:
    return round(
        min(max(0.5 * seasonal + 0.5 * weekday, MINIMUM_RATE), 1.0 - MINIMUM_RATE),
        6,
    )


def _baseline_series(predictions: Sequence[PathPrediction], name: str) -> list[float]:
    """Historical-frequency, persistence, seasonal and blended seasonal baselines."""
    if name == "frequency":
        return [prediction.frequency_probability for prediction in predictions]
    if name == "persistence":
        return [prediction.persistence_probability for prediction in predictions]
    if name == "seasonal":
        return [prediction.seasonal_probability for prediction in predictions]
    if name == "seasonal_blend":
        return [
            _blended_probability(prediction.seasonal_probability, prediction.weekday_probability)
            for prediction in predictions
        ]
    raise ValueError(f"baseline desconhecido: {name}")


@dataclass(frozen=True)
class BacktestResult:
    """Backtest evidence of one plant, including the negative results."""

    train_days: int
    validation_days: int
    test_days: int
    event_rate_train: float
    event_rate_validation: float
    event_rate_test: float
    brier_raw: float
    brier_calibrated: float | None
    brier_baseline_frequency: float
    brier_baseline_persistence: float
    brier_baseline_seasonal: float
    best_baseline_name: str
    best_baseline_brier: float
    calibration: PlattCalibration | None
    calibration_accepted: bool
    calibration_note: str
    calibration_rejection_reasons: tuple[str, ...]
    validation_brier_raw: float
    validation_brier_calibrated: float | None
    validation_reliability_gap_raw: float
    validation_reliability_gap_calibrated: float | None
    validation_alert_band_gap_raw: float | None
    validation_alert_band_gap_calibrated: float | None
    reliability_bins: tuple[dict[str, Any], ...]
    reliability_gap_raw: float
    reliability_gap_calibrated: float | None
    alert_band_gap_raw: float | None
    alert_band_gap_calibrated: float | None
    brier_model_best: float
    brier_best_baseline: float
    brier_best_varying_baseline: float
    best_varying_baseline_name: str
    baseline_briers: dict[str, float]
    baseline_reliability_gaps: dict[str, float]
    reliability_gap_best_baseline: float
    beats_baseline: bool
    probability_source: str
    probability_decision_note: str
    l2_penalty: float
    l2_selection: dict[str, Any]
    mean_absolute_error_mwh: float
    baseline_mean_absolute_error_mwh: float
    interval: dict[str, float]
    validation_reliability_bins: tuple[dict[str, Any], ...]
    test_predictions: tuple[PathPrediction, ...]
    candidates: tuple[CandidateScore, ...] = ()
    selected_candidate: str = CANDIDATE_MODEL_RAW
    baseline_briers_validation: dict[str, float] = field(default_factory=dict)
    baseline_reliability_gaps_validation: dict[str, float] = field(default_factory=dict)
    frozen_support_low: float | None = None
    frozen_support_high: float | None = None
    frozen_support_days: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "train_days": self.train_days,
            "validation_days": self.validation_days,
            "test_days": self.test_days,
            "event_rate_train": self.event_rate_train,
            "event_rate_validation": self.event_rate_validation,
            "event_rate_test": self.event_rate_test,
            "brier_raw": self.brier_raw,
            "brier_calibrated": self.brier_calibrated,
            "brier_baseline_frequency": self.brier_baseline_frequency,
            "brier_baseline_persistence": self.brier_baseline_persistence,
            "brier_baseline_seasonal": self.brier_baseline_seasonal,
            "best_baseline_name": self.best_baseline_name,
            "best_baseline_brier": self.best_baseline_brier,
            "calibration": (
                None
                if self.calibration is None
                else {
                    "slope": self.calibration.slope,
                    "intercept": self.calibration.intercept,
                    "support_low": self.calibration.support_low,
                    "support_high": self.calibration.support_high,
                }
            ),
            "candidates": [item.to_payload() for item in self.candidates],
            "selected_candidate": self.selected_candidate,
            "baseline_briers_validation": dict(self.baseline_briers_validation),
            "baseline_reliability_gaps_validation": dict(self.baseline_reliability_gaps_validation),
            "frozen_support": {
                "low": self.frozen_support_low,
                "high": self.frozen_support_high,
                "days": self.frozen_support_days,
                "basis": "validation_paths",
            },
            "calibration_accepted": self.calibration_accepted,
            "calibration_note": self.calibration_note,
            "calibration_rejection_reasons": list(self.calibration_rejection_reasons),
            "validation_brier_raw": self.validation_brier_raw,
            "validation_brier_calibrated": self.validation_brier_calibrated,
            "validation_reliability_gap_raw": self.validation_reliability_gap_raw,
            "validation_reliability_gap_calibrated": self.validation_reliability_gap_calibrated,
            "validation_alert_band_gap_raw": self.validation_alert_band_gap_raw,
            "validation_alert_band_gap_calibrated": self.validation_alert_band_gap_calibrated,
            "reliability_bins": [dict(item) for item in self.reliability_bins],
            "reliability_gap_raw": self.reliability_gap_raw,
            "reliability_gap_calibrated": self.reliability_gap_calibrated,
            "alert_band_gap_raw": self.alert_band_gap_raw,
            "alert_band_gap_calibrated": self.alert_band_gap_calibrated,
            "brier_model_best": self.brier_model_best,
            "brier_best_baseline": self.brier_best_baseline,
            "brier_best_varying_baseline": self.brier_best_varying_baseline,
            "best_varying_baseline_name": self.best_varying_baseline_name,
            "baseline_briers": dict(self.baseline_briers),
            "baseline_reliability_gaps": dict(self.baseline_reliability_gaps),
            "reliability_gap_best_baseline": self.reliability_gap_best_baseline,
            "beats_baseline": self.beats_baseline,
            "probability_source": self.probability_source,
            "probability_decision_note": self.probability_decision_note,
            "l2_penalty": self.l2_penalty,
            "l2_selection": self.l2_selection,
            "validation_reliability_bins": [
                dict(item) for item in self.validation_reliability_bins
            ],
            "mean_absolute_error_mwh": self.mean_absolute_error_mwh,
            "baseline_mean_absolute_error_mwh": self.baseline_mean_absolute_error_mwh,
            "interval": dict(self.interval),
            "probability_status": (
                PROBABILITY_STATUS_BASELINE
                if self.probability_source == PROBABILITY_SOURCE_BASELINE
                else (
                    PROBABILITY_STATUS_CALIBRATED
                    if self.calibration_accepted
                    else PROBABILITY_STATUS_UNCALIBRATED
                )
            ),
        }


def run_backtest(
    *,
    history: PlantDailyHistory,
    point_share: Sequence[float],
    weather_normal_z: Mapping[date, float],
    capacity_mw: float,
    plan: BacktestPlan,
    l2: float | None = None,
) -> BacktestResult:
    """Recursive temporal backtest with raw and calibrated Brier scores plus baselines.

    The ridge penalty is selected on the validation paths, the calibration is fitted on the
    validation paths, and the test paths are used only for evaluation.
    """
    selection: dict[str, Any]
    if l2 is None:
        l2, selection = select_l2_penalty(
            history=history,
            point_share=point_share,
            weather_normal_z=weather_normal_z,
            capacity_mw=capacity_mw,
            plan=plan,
        )
    else:
        selection = {"selected_l2": l2, "selection_basis": "explicit", "candidates": []}
    validation = [
        prediction
        for origin in plan.validation_origins
        for prediction in predict_path(
            history=history,
            point_share=point_share,
            weather_normal_z=weather_normal_z,
            capacity_mw=capacity_mw,
            origin=origin,
            path_days=plan.path_days,
            l2=l2,
        )
    ]
    test = [
        prediction
        for origin in plan.test_origins
        for prediction in predict_path(
            history=history,
            point_share=point_share,
            weather_normal_z=weather_normal_z,
            capacity_mw=capacity_mw,
            origin=origin,
            path_days=plan.path_days,
            l2=l2,
        )
    ]
    if not test:
        raise ValueError("the backtest produced no test predictions")
    calibration: PlattCalibration | None = None
    if validation:
        calibration = fit_platt_calibration(
            [prediction.raw_probability for prediction in validation],
            [prediction.observed for prediction in validation],
        )
    test_targets = [prediction.observed for prediction in test]
    raw_probabilities = [prediction.raw_probability for prediction in test]
    calibrated_probabilities = (
        [calibration.apply(probability) for probability in raw_probabilities]
        if calibration is not None
        else []
    )
    # The calibration decision is frozen on the validation split; the test split only reports
    # the effect, so no test information can select or reject the calibration.
    validation_targets = [prediction.observed for prediction in validation]
    validation_raw = [prediction.raw_probability for prediction in validation]
    validation_calibrated = (
        [calibration.apply(probability) for probability in validation_raw]
        if calibration is not None
        else []
    )
    validation_brier_raw = brier_score(validation_raw, validation_targets)
    validation_brier_calibrated = (
        brier_score(validation_calibrated, validation_targets) if validation_calibrated else None
    )
    validation_raw_bins = reliability_bins(validation_raw, validation_targets)
    validation_calibrated_bins = (
        reliability_bins(validation_calibrated, validation_targets) if validation_calibrated else ()
    )
    validation_gap_raw = reliability_gap(validation_raw_bins)
    validation_gap_calibrated = (
        reliability_gap(validation_calibrated_bins) if validation_calibrated_bins else None
    )
    validation_alert_raw = alert_band_gap(validation_raw_bins)
    validation_alert_calibrated = (
        alert_band_gap(validation_calibrated_bins) if validation_calibrated_bins else None
    )
    brier_raw = brier_score(raw_probabilities, test_targets)
    brier_calibrated = (
        brier_score(calibrated_probabilities, test_targets) if calibrated_probabilities else None
    )
    raw_bins = reliability_bins(raw_probabilities, test_targets)
    calibrated_bins = (
        reliability_bins(calibrated_probabilities, test_targets) if calibrated_probabilities else ()
    )
    raw_gap = reliability_gap(raw_bins)
    calibrated_gap = reliability_gap(calibrated_bins) if calibrated_bins else None
    raw_alert_gap = alert_band_gap(raw_bins)
    calibrated_alert_gap = alert_band_gap(calibrated_bins) if calibrated_bins else None
    rejection_reasons: list[str] = []
    if calibration is None:
        rejection_reasons.append("não houve caminhos de validação para ajustar a calibração")
    else:
        if (
            validation_brier_calibrated is None
            or validation_brier_calibrated >= validation_brier_raw
        ):
            rejection_reasons.append(
                "o Brier na validação não melhorou "
                f"({validation_brier_raw:.6f} para {validation_brier_calibrated})"
            )
        if (
            validation_gap_calibrated is None
            or validation_gap_calibrated > validation_gap_raw + 1e-9
        ):
            rejection_reasons.append(
                "a confiabilidade na validação piorou "
                f"({validation_gap_raw:.6f} para {validation_gap_calibrated})"
            )
        if (
            validation_alert_raw is not None
            and validation_alert_calibrated is not None
            and validation_alert_calibrated > validation_alert_raw + 1e-9
        ):
            rejection_reasons.append(
                "a confiabilidade na faixa de alerta da validação piorou "
                f"({validation_alert_raw:.6f} para {validation_alert_calibrated:.6f})"
            )
    accepted = calibration is not None and not rejection_reasons
    validation_targets = [prediction.observed for prediction in validation]
    test_targets = [prediction.observed for prediction in test]
    validation_baseline_series = {
        name: _baseline_series(validation, name) for name in BASELINE_NAMES
    }
    test_baseline_series = {name: _baseline_series(test, name) for name in BASELINE_NAMES}
    validation_baseline_briers = {
        name: brier_score(series, validation_targets)
        for name, series in validation_baseline_series.items()
    }
    validation_baseline_gaps = {
        name: reliability_gap(reliability_bins(series, validation_targets))
        for name, series in validation_baseline_series.items()
    }
    baseline_briers = {
        name: brier_score(series, test_targets) for name, series in test_baseline_series.items()
    }
    baseline_gaps = {
        name: reliability_gap(reliability_bins(series, test_targets))
        for name, series in test_baseline_series.items()
    }
    candidates = [
        CandidateScore(
            name=CANDIDATE_MODEL_RAW,
            kind="model",
            validation_brier=validation_brier_raw,
            validation_reliability_gap=validation_gap_raw,
            test_brier=brier_raw,
            test_reliability_gap=raw_gap,
        )
    ]
    if calibration is not None and accepted and validation_brier_calibrated is not None:
        candidates.append(
            CandidateScore(
                name=CANDIDATE_MODEL_CALIBRATED,
                kind="model",
                validation_brier=validation_brier_calibrated,
                validation_reliability_gap=validation_gap_calibrated or 0.0,
                test_brier=brier_calibrated or brier_raw,
                test_reliability_gap=calibrated_gap or raw_gap,
            )
        )
    for name in BASELINE_NAMES:
        candidates.append(
            CandidateScore(
                name=f"baseline_{name}",
                kind="baseline",
                validation_brier=validation_baseline_briers[name],
                validation_reliability_gap=validation_baseline_gaps[name],
                test_brier=baseline_briers[name],
                test_reliability_gap=baseline_gaps[name],
            )
        )
    # The policy is frozen on validation only: every candidate, constant baselines included, is
    # ranked by its validation Brier and reliability. The test columns travel with the table but
    # never decide anything.
    candidates.sort(
        key=lambda item: (item.validation_brier, item.validation_reliability_gap, item.name)
    )
    selected = candidates[0]
    best_baseline = next(item for item in candidates if item.kind == "baseline")
    best_model = next(item for item in candidates if item.kind == "model")
    model_brier = best_model.test_brier
    beats_baseline = selected.kind == "model"
    probability_source = SOURCE_BY_CANDIDATE[selected.name]
    decision_note = (
        "A política de publicação é congelada na validação e o teste apenas reporta o efeito. "
        f"Melhor candidato na validação: {selected.name} (Brier {selected.validation_brier:.6f}, "
        f"confiabilidade {selected.validation_reliability_gap:.6f}); o baseline mais forte "
        f"incluindo constantes é {best_baseline.name} (Brier na validação "
        f"{best_baseline.validation_brier:.6f}, confiabilidade "
        f"{best_baseline.validation_reliability_gap:.6f}). "
        + (
            "O modelo superou o baseline mais forte na validação."
            if beats_baseline
            else "O modelo não superou o baseline mais forte na validação."
        )
    )
    if rejection_reasons:
        decision_note += " Calibração rejeitada na validação: " + "; ".join(rejection_reasons) + "."
    elif calibration is not None:
        decision_note += (
            " Calibração aceita na validação (Brier "
            f"{validation_brier_raw:.6f} -> {validation_brier_calibrated}, confiabilidade "
            f"{validation_gap_raw:.6f} -> {validation_gap_calibrated}, faixa de alerta "
            f"{validation_alert_raw} -> {validation_alert_calibrated}); a aplicação ao horizonte "
            "ainda passa pelo teste de suporte da calibração."
        )
    if calibration is not None:
        decision_note += (
            " Efeito no teste (informativo): Brier bruto "
            f"{brier_raw:.6f} -> calibrado {brier_calibrated}; confiabilidade bruta "
            f"{raw_gap:.6f} -> calibrada {calibrated_gap}; faixa de alerta "
            f"{raw_alert_gap} -> {calibrated_alert_gap}."
        )
    predicted_mwh = [prediction.predicted_mwh for prediction in test]
    observed_mwh = [prediction.observed_mwh for prediction in test]
    residuals = [
        observed - predicted
        for observed, predicted in zip(observed_mwh, predicted_mwh, strict=True)
    ]
    validation_residuals = [
        prediction.observed_mwh - prediction.predicted_mwh for prediction in validation
    ]
    overall_mean = _mean(observed_mwh) or 0.0
    return BacktestResult(
        train_days=plan.train_end,
        validation_days=len(validation),
        test_days=len(test),
        event_rate_train=round(_rate(history.restricted[: plan.train_end]) or 0.0, 6),
        event_rate_validation=round(
            _rate(prediction.observed for prediction in validation) or 0.0, 6
        ),
        event_rate_test=round(_rate(test_targets) or 0.0, 6),
        brier_raw=brier_raw,
        brier_calibrated=brier_calibrated,
        brier_baseline_frequency=baseline_briers["frequency"],
        brier_baseline_persistence=baseline_briers["persistence"],
        brier_baseline_seasonal=baseline_briers["seasonal"],
        best_baseline_name=best_baseline.name,
        best_baseline_brier=best_baseline.validation_brier,
        calibration=calibration,
        calibration_accepted=accepted,
        calibration_note=(
            "Calibração aceita na validação: o Brier melhorou e a confiabilidade (inclusive na "
            "faixa de alerta) não piorou; o teste apenas reporta o efeito."
            if accepted
            else "Calibração rejeitada na validação: "
            + ("; ".join(rejection_reasons) if rejection_reasons else "sem caminhos de validação")
            + "; a probabilidade empírica não calibrada foi mantida."
        ),
        calibration_rejection_reasons=tuple(rejection_reasons),
        validation_brier_raw=validation_brier_raw,
        validation_brier_calibrated=validation_brier_calibrated,
        validation_reliability_gap_raw=validation_gap_raw,
        validation_reliability_gap_calibrated=validation_gap_calibrated,
        validation_alert_band_gap_raw=validation_alert_raw,
        validation_alert_band_gap_calibrated=validation_alert_calibrated,
        reliability_bins=(calibrated_bins if accepted else raw_bins),
        reliability_gap_raw=raw_gap,
        reliability_gap_calibrated=calibrated_gap,
        alert_band_gap_raw=raw_alert_gap,
        alert_band_gap_calibrated=calibrated_alert_gap,
        brier_model_best=model_brier,
        brier_best_baseline=best_baseline.test_brier,
        brier_best_varying_baseline=min(
            baseline_briers["seasonal"], baseline_briers["seasonal_blend"]
        ),
        best_varying_baseline_name=min(
            ("seasonal", "seasonal_blend"), key=lambda name: baseline_briers[name]
        ),
        baseline_briers=baseline_briers,
        baseline_reliability_gaps=baseline_gaps,
        baseline_briers_validation=validation_baseline_briers,
        baseline_reliability_gaps_validation=validation_baseline_gaps,
        candidates=tuple(candidates),
        selected_candidate=selected.name,
        reliability_gap_best_baseline=best_baseline.validation_reliability_gap,
        beats_baseline=beats_baseline,
        probability_source=probability_source,
        probability_decision_note=decision_note,
        l2_penalty=l2,
        l2_selection=selection,
        validation_reliability_bins=reliability_bins(
            [prediction.raw_probability for prediction in validation],
            [prediction.observed for prediction in validation],
        ),
        mean_absolute_error_mwh=round(sum(abs(value) for value in residuals) / len(residuals), 6),
        baseline_mean_absolute_error_mwh=round(
            sum(abs(value - overall_mean) for value in observed_mwh) / len(observed_mwh), 6
        ),
        interval=interval_coverage(
            residuals=validation_residuals or residuals,
            predicted=predicted_mwh,
            observed=observed_mwh,
        ),
        test_predictions=tuple(test),
        frozen_support_low=round(min(validation_raw), 6) if validation_raw else None,
        frozen_support_high=round(max(validation_raw), 6) if validation_raw else None,
        frozen_support_days=len(validation_raw),
    )


def reliability_gap(bins: Sequence[Mapping[str, Any]]) -> float:
    """Mean absolute difference between predicted and observed rate, weighted by bin count."""
    total = sum(float(item["count"]) for item in bins)
    if total <= 0:
        return 0.0
    return round(
        sum(
            float(item["count"]) * abs(float(item["mean_predicted"]) - float(item["observed_rate"]))
            for item in bins
        )
        / total,
        6,
    )


def alert_band_gap(bins: Sequence[Mapping[str, Any]]) -> float | None:
    """Reliability gap inside the alert band, where the published horizon usually lives.

    ``None`` when no bin falls in the band: an empty band is undefined, not a perfect score.
    """
    selected = [item for item in bins if float(item["bin_lower"]) >= ALERT_BAND_LOWER]
    return reliability_gap(selected) if selected else None


def select_l2_penalty(
    *,
    history: PlantDailyHistory,
    point_share: Sequence[float],
    weather_normal_z: Mapping[date, float],
    capacity_mw: float,
    plan: BacktestPlan,
) -> tuple[float, dict[str, Any]]:
    """Choose the ridge penalty on the validation paths only, never on the test paths."""
    candidates: list[dict[str, Any]] = []
    best_penalty = LOGISTIC_L2_GRID[0]
    best_brier: float | None = None
    for penalty in LOGISTIC_L2_GRID:
        predictions = [
            prediction
            for origin in plan.validation_origins
            for prediction in predict_path(
                history=history,
                point_share=point_share,
                weather_normal_z=weather_normal_z,
                capacity_mw=capacity_mw,
                origin=origin,
                path_days=plan.path_days,
                l2=penalty,
            )
        ]
        if not predictions:
            continue
        brier = brier_score(
            [prediction.raw_probability for prediction in predictions],
            [prediction.observed for prediction in predictions],
        )
        candidates.append({"l2": penalty, "validation_brier": brier, "days": len(predictions)})
        if best_brier is None or brier < best_brier:
            best_brier = brier
            best_penalty = penalty
    return best_penalty, {
        "selected_l2": best_penalty,
        "selection_basis": "validation_paths_only",
        "candidates": candidates,
    }


def baseline_forward_probabilities(
    history: PlantDailyHistory, *, horizon_days: Sequence[date]
) -> tuple[float, ...]:
    """Safest published alternative: seasonal frequency blended with the base rate.

    Used when the model does not beat the historical-frequency baseline out of sample. Both
    inputs come from the fitting window, so the baseline is available at issue time.
    """
    month_rates, weekday_rates, overall = seasonal_rates(history, index=len(history.days))
    return tuple(
        round(
            min(
                max(
                    0.5 * month_rates.get(day.month, overall)
                    + 0.5 * weekday_rates.get(day.weekday(), overall),
                    MINIMUM_RATE,
                ),
                1.0 - MINIMUM_RATE,
            ),
            6,
        )
        for day in horizon_days
    )


def baseline_forward_series(
    history: PlantDailyHistory, *, horizon_days: Sequence[date]
) -> dict[str, tuple[float, ...]]:
    """All four publishable baselines over the horizon, from issue-time information only.

    The constant baselines (``frequency`` and ``persistence``) are first-class candidates: if
    one of them wins on validation it is published as-is, one row per date, instead of being
    discarded in favour of a model series that does not beat it.
    """
    month_rates, weekday_rates, overall = seasonal_rates(history, index=len(history.days))
    persistence = 1.0 if history.restricted[-1] else 0.0
    seasonal = tuple(
        round(min(max(month_rates.get(day.month, overall), MINIMUM_RATE), 1.0 - MINIMUM_RATE), 6)
        for day in horizon_days
    )
    return {
        "frequency": tuple(round(overall, 6) for _ in horizon_days),
        "persistence": tuple(round(persistence, 6) for _ in horizon_days),
        "seasonal": seasonal,
        "seasonal_blend": baseline_forward_probabilities(history, horizon_days=horizon_days),
    }


def forward_probabilities(
    *,
    history: PlantDailyHistory,
    point_share: Sequence[float],
    weather_normal_z: Mapping[date, float],
    capacity_mw: float,
    horizon_days: Sequence[date],
    simulated_mwh: Sequence[float],
    calibration: PlattCalibration | None,
    calibration_accepted: bool,
    l2: float = LOGISTIC_L2,
) -> tuple[float, ...]:
    """Recursive forward probability, updating lags with the model's own expectations.

    The lag features of the days inside the horizon use the model's own *expected* indicator
    and the simulated expected MWh, so the recursion reflects the model's uncertainty instead
    of assuming that every remaining day is restricted.
    """
    month_rates, weekday_rates, overall_rate = seasonal_rates(history, index=len(history.days))
    rows = [
        feature_row(
            day=history.days[index],
            history=history,
            point_share=point_share,
            month_rate=month_rates.get(history.days[index].month, overall_rate),
            weekday_rate=weekday_rates.get(history.days[index].weekday(), overall_rate),
            weather_normal_z=weather_normal_z.get(history.days[index], 0.0),
            capacity_mw=capacity_mw,
        )
        for index in range(1, len(history.days))
    ]
    targets = [1 if flag else 0 for flag in history.restricted[1:]]
    model = fit_logistic_model(rows, targets, l2=l2)
    working_days = list(history.days)
    working_restricted: list[float] = [float(flag) for flag in history.restricted]
    working_mwh = list(history.curtailed_mwh)
    working_pressure = list(point_share)
    probabilities: list[float] = []
    for offset, day in enumerate(horizon_days):
        row = feature_row(
            day=day,
            history=PlantDailyHistory(
                asset_id=history.asset_id,
                days=tuple(working_days),
                restricted=tuple(working_restricted),
                curtailed_mwh=tuple(working_mwh),
            ),
            point_share=working_pressure,
            month_rate=month_rates.get(day.month, overall_rate),
            weekday_rate=weekday_rates.get(day.weekday(), overall_rate),
            weather_normal_z=weather_normal_z.get(day, 0.0),
            capacity_mw=capacity_mw,
        )
        probability = model.probability(row)
        if calibration is not None and calibration_accepted:
            probability = calibration.apply(probability)
        probabilities.append(round(probability, 6))
        working_days.append(day)
        working_restricted.append(probability)
        working_mwh.append(simulated_mwh[offset] if offset < len(simulated_mwh) else 0.0)
        working_pressure.append(probability)
    return tuple(probabilities)


# --------------------------------------------------------------------------------------
# ONS aggregates used by the simulation
# --------------------------------------------------------------------------------------


def _placeholders(values: Sequence[str]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


@dataclass(frozen=True)
class PlantAggregates:
    """Public aggregates of one plant inside the detailed half-hour base."""

    plant_id: str
    weather_column: str
    daily_restricted: Mapping[date, bool]
    daily_weather_mean: Mapping[date, float]
    month_hour_weather: Mapping[tuple[int, int], float]
    curve_bins: Mapping[float, float]
    last_interval_weather: float | None
    last_interval_accepted: float | None
    last_observed_at: datetime | None


def load_plant_aggregates(
    path: str,
    *,
    plant_ids: Sequence[str],
    weather_column: str,
    weather_flag_column: str,
    supervision_flag_column: str,
    window_start: date,
    window_end: date,
    bin_size: float,
    curve_quantile: float = POTENTIAL_QUANTILE,
) -> dict[str, PlantAggregates]:
    """Read every aggregate the point simulation needs in one pass over the detail base."""
    if not plant_ids:
        return {}
    source = f"read_parquet('{path}', union_by_name=true)"
    ids = _placeholders(plant_ids)
    window = (
        f"din_instante >= TIMESTAMP '{window_start.isoformat()} 00:00:00' "
        f"AND din_instante <= TIMESTAMP '{window_end.isoformat()} 23:59:59'"
    )
    valid = f"coalesce({weather_flag_column}, 0) = 0 AND coalesce({supervision_flag_column}, 0) = 0"
    query = f"""
        SELECT
            trim(id_ons) AS plant_id,
            din_instante::DATE AS day,
            extract(month FROM din_instante)::INTEGER AS month,
            (extract(hour FROM din_instante) * 2 + extract(minute FROM din_instante) / 30)::INTEGER
                AS slot,
            count(*) AS intervals,
            max(flg_geracaorestrita) AS restricted,
            avg({weather_column}) AS weather_mean,
            avg(val_geracaoverificada) AS accepted_mean,
            max(din_instante) AS last_observed_at
        FROM {source}
        WHERE trim(id_ons) IN ({ids}) AND {window}
        GROUP BY 1, 2, 3, 4
        ORDER BY 1, 2, 3, 4
    """
    with duckdb.connect() as connection:
        rows = connection.execute(query).fetchall()
        curve_query = f"""
            SELECT
                trim(id_ons) AS plant_id,
                floor({weather_column} / {bin_size}) * {bin_size} AS weather_bin,
                quantile_cont(val_geracaoverificada, {curve_quantile}) AS potential
            FROM {source}
            WHERE trim(id_ons) IN ({ids}) AND {window}
              AND flg_geracaorestrita = 0 AND val_geracaoverificada IS NOT NULL
              AND {weather_column} IS NOT NULL AND {valid}
            GROUP BY 1, 2
            HAVING count(*) >= 20
            ORDER BY 1, 2
        """
        curve_rows = connection.execute(curve_query).fetchall()
        last_query = f"""
            SELECT trim(id_ons) AS plant_id, {weather_column} AS weather,
                   val_geracaoverificada AS accepted, din_instante AS observed_at
            FROM {source}
            WHERE trim(id_ons) IN ({ids}) AND {window}
              AND din_instante = (SELECT max(din_instante) FROM {source}
                                  WHERE trim(id_ons) IN ({ids}) AND {window})
            ORDER BY 1
        """
        last_rows = connection.execute(last_query).fetchall()

    daily_restricted: dict[str, dict[date, bool]] = {}
    weather_sum: dict[str, dict[date, float]] = {}
    weather_count: dict[str, dict[date, int]] = {}
    month_hour: dict[str, dict[tuple[int, int], list[float]]] = {}
    intervals_by_plant: dict[str, int] = {}
    last_interval: dict[str, datetime] = {}
    for (
        plant_id,
        day,
        month,
        slot,
        intervals,
        restricted,
        weather_mean,
        _accepted,
        observed,
    ) in rows:
        # A day is restricted when any of its half-hour intervals is restricted, and its weather
        # value is the mean of its intervals. Both are accumulated instead of overwritten with the
        # last grouped row, so the result cannot depend on the order DuckDB returns the groups
        # (a GROUP BY has no guaranteed order). Without this, the simulated weather spread and the
        # published series changed between two runs of the same inputs.
        day_flags = daily_restricted.setdefault(plant_id, {})
        day_flags[day] = day_flags.get(day, False) or bool(restricted)
        intervals_by_plant[plant_id] = intervals_by_plant.get(plant_id, 0) + int(intervals)
        if weather_mean is not None:
            sums = weather_sum.setdefault(plant_id, {})
            counts = weather_count.setdefault(plant_id, {})
            sums[day] = sums.get(day, 0.0) + float(weather_mean)
            counts[day] = counts.get(day, 0) + 1
            month_hour.setdefault(plant_id, {}).setdefault((int(month), int(slot)), []).append(
                float(weather_mean)
            )
        if observed is not None:
            previous = last_interval.get(plant_id)
            if previous is None or observed > previous:
                last_interval[plant_id] = observed
    daily_weather: dict[str, dict[date, float]] = {
        plant_id: {day: total / weather_count[plant_id][day] for day, total in sums.items()}
        for plant_id, sums in weather_sum.items()
    }
    curves: dict[str, dict[float, float]] = {}
    for plant_id, weather_bin, potential in curve_rows:
        if potential is None:
            continue
        curves.setdefault(plant_id, {})[float(weather_bin)] = float(potential)
    telemetry: dict[str, tuple[float | None, float | None, datetime | None]] = {}
    for plant_id, weather, accepted, observed in last_rows:
        telemetry[plant_id] = (
            None if weather is None else float(weather),
            None if accepted is None else float(accepted),
            observed,
        )
    aggregates: dict[str, PlantAggregates] = {}
    for plant_id in plant_ids:
        weather_value, accepted_value, observed_at = telemetry.get(plant_id, (None, None, None))
        aggregates[plant_id] = PlantAggregates(
            plant_id=plant_id,
            weather_column=weather_column,
            daily_restricted=daily_restricted.get(plant_id, {}),
            daily_weather_mean=daily_weather.get(plant_id, {}),
            month_hour_weather={
                key: sum(values) / len(values)
                for key, values in month_hour.get(plant_id, {}).items()
            },
            curve_bins=curves.get(plant_id, {}),
            last_interval_weather=weather_value,
            last_interval_accepted=accepted_value,
            last_observed_at=observed_at,
        )
    return aggregates


def load_point_published_curtailment(
    paths: Sequence[str],
    *,
    group_ids: Sequence[str],
    window_start: date,
    window_end: date,
) -> dict[datetime, float]:
    """Published point curtailment per half-hour interval, summed once per group."""
    if not group_ids:
        return {}
    ids = _placeholders(group_ids)
    window = (
        f"din_instante >= TIMESTAMP '{window_start.isoformat()} 00:00:00' "
        f"AND din_instante <= TIMESTAMP '{window_end.isoformat()} 23:59:59'"
    )
    query = f"""
        SELECT din_instante, sum(coalesce(val_geracaonaorealizadaapurada, 0))
        FROM {{source}}
        WHERE trim(id_ons) IN ({ids}) AND {window} AND val_geracaolimitada IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """
    totals: dict[datetime, float] = {}
    with duckdb.connect() as connection:
        for path in paths:
            source = f"read_parquet('{path}', union_by_name=true)"
            for instant, value in connection.execute(query.format(source=source)).fetchall():
                totals[instant] = totals.get(instant, 0.0) + float(value or 0.0)
    return totals


def load_point_interval_potential(
    path: str,
    *,
    plant_ids: Sequence[str],
    weather_column: str,
    weather_flag_column: str,
    supervision_flag_column: str,
    curves: Mapping[str, Mapping[float, float]],
    bin_size: float,
    window_start: date,
    window_end: date,
) -> dict[datetime, float]:
    """Historical point potential per interval, using each plant's own potential curve."""
    if not plant_ids or not curves:
        return {}
    source = f"read_parquet('{path}', union_by_name=true)"
    values = ", ".join(
        f"('{plant_id}', {float(bin_value)}, {float(potential)})"
        for plant_id, bins in sorted(curves.items())
        for bin_value, potential in sorted(bins.items())
    )
    if not values:
        return {}
    window = (
        f"din_instante >= TIMESTAMP '{window_start.isoformat()} 00:00:00' "
        f"AND din_instante <= TIMESTAMP '{window_end.isoformat()} 23:59:59'"
    )
    query = f"""
        WITH curves(plant_id, weather_bin, potential) AS (VALUES {values}),
        observed AS (
            SELECT trim(id_ons) AS plant_id, din_instante,
                   floor({weather_column} / {bin_size}) * {bin_size} AS weather_bin
            FROM {source}
            WHERE trim(id_ons) IN ({_placeholders(plant_ids)}) AND {window}
              AND coalesce({weather_flag_column}, 0) = 0
              AND coalesce({supervision_flag_column}, 0) = 0
        )
        SELECT observed.din_instante, sum(coalesce(curves.potential, 0))
        FROM observed
        LEFT JOIN curves
          ON curves.plant_id = observed.plant_id AND curves.weather_bin = observed.weather_bin
        GROUP BY 1
        ORDER BY 1
    """
    with duckdb.connect() as connection:
        return {
            instant: float(value or 0.0) for instant, value in connection.execute(query).fetchall()
        }


# --------------------------------------------------------------------------------------
# artifact assembly
# --------------------------------------------------------------------------------------


def _curve_from_bins(bins: Mapping[float, float]) -> history_module.GenerationCurve:
    centers = tuple(sorted(bins))
    return history_module.GenerationCurve(
        centers, tuple(max(bins[center], 0.0) for center in centers)
    )


def _weather_normal_z(
    outlook: PointWeatherOutlook | None, *, days: Sequence[date]
) -> dict[date, float]:
    if outlook is None or not outlook.era5_monthly:
        return {}
    values = [mean for _, mean in outlook.era5_monthly]
    mean = sum(values) / len(values)
    deviation = statistics.pstdev(values) if len(values) > 1 else 0.0
    if deviation <= 1e-9:
        return {}
    monthly = {month: (value - mean) / deviation for month, value in outlook.era5_monthly}
    return {day: monthly.get(day.month, 0.0) for day in days}


def _plant_share_series(
    *, plant_id: str, point_restricted: Mapping[str, Mapping[date, bool]], days: Sequence[date]
) -> tuple[float, ...]:
    others = [series for other, series in sorted(point_restricted.items()) if other != plant_id]
    if not others:
        return tuple(0.0 for _ in days)
    shares: list[float] = []
    for day in days:
        flags = [series.get(day) for series in others if day in series]
        shares.append(sum(1 for flag in flags if flag) / len(flags) if flags else 0.0)
    return tuple(shares)


def probability_distribution(probabilities: Sequence[float]) -> dict[str, Any]:
    """Min, median, max and how many days sit above the alert thresholds."""
    if not probabilities:
        return {
            "min": 0.0,
            "median": 0.0,
            "max": 0.0,
            "days": 0,
            "days_above_95_pct": 0,
            "days_at_or_above_99_pct": 0,
            "distinct_values": 0,
            "saturated": False,
        }
    ordered = sorted(probabilities)
    above = sum(1 for value in ordered if value > PROBABILITY_ALERT_THRESHOLD)
    return {
        "min": round(ordered[0], 6),
        "median": round(statistics.median(ordered), 6),
        "max": round(ordered[-1], 6),
        "days": len(ordered),
        "days_above_95_pct": above,
        "days_at_or_above_99_pct": sum(
            1 for value in ordered if value >= PROBABILITY_EXTREME_THRESHOLD
        ),
        "distinct_values": len({round(float(value), 4) for value in ordered}),
        "saturated": above == len(ordered),
    }


def series_is_saturated(probabilities: Sequence[float]) -> bool:
    """True when every day sits above the alert threshold, i.e. the series says nothing."""
    return bool(probabilities) and all(
        value > PUBLISHED_SATURATION_THRESHOLD for value in probabilities
    )


def count_outside_support(
    probabilities: Sequence[float], *, support_low: float | None, support_high: float | None
) -> int:
    """Days of a series whose probability leaves the frozen validation support.

    The support is the closed interval ``[support_low, support_high]`` of the raw probabilities
    the model produced on the validation paths used for selection and calibration. When the
    support is undefined (no validation paths) every day counts as outside, because nothing was
    validated.
    """
    if support_low is None or support_high is None:
        return len(probabilities)
    return sum(
        1
        for value in probabilities
        if float(value) < support_low or float(value) > support_high
    )


def candidate_eligibility(
    *,
    name: str,
    probabilities: Sequence[float],
    support_low: float | None,
    support_high: float | None,
    calibration_applied: bool = True,
) -> dict[str, Any]:
    """Decide whether one publishable series may be published, without touching its numbers.

    Three independent refusals, each evaluated on the series that would actually be published:

    * the calibrated model when its map was fitted on a probability range that does not cover the
      horizon (``calibration_applied`` is ``False``);
    * any series with all days above the alert threshold (saturated);
    * the raw or the calibrated model when the horizon leaves, materially, the probability
      support frozen on the validation paths. A trajectory systematically above the validated
      range is extrapolation even when the numbers look plausible.

    The constant baselines are first-class candidates and are never refused by the support rule:
    they are the honest fallback when the model extrapolates, not a model output.
    """
    distribution = probability_distribution(probabilities)
    outside = count_outside_support(
        probabilities, support_low=support_low, support_high=support_high
    )
    is_model = name in (CANDIDATE_MODEL_RAW, CANDIDATE_MODEL_CALIBRATED)
    if name == CANDIDATE_MODEL_CALIBRATED and not calibration_applied:
        eligible = False
        reason = (
            "a calibração foi ajustada numa faixa de probabilidade que não cobre o horizonte; "
            "aplicá-la aqui seria extrapolação"
        )
    elif distribution["saturated"]:
        eligible = False
        reason = (
            f"a série de {distribution['days']} dias ficou inteiramente acima de 95% (saturada)"
        )
    elif is_model and outside > OUT_OF_SUPPORT_TOLERANCE_DAYS:
        eligible = False
        reason = (
            "a trajetória futura sai do suporte de probabilidade congelado na validação em "
            f"{outside} de {distribution['days']} dias (suporte "
            f"[{support_low}, {support_high}]); extrapolação não defensável"
        )
    else:
        eligible = True
        reason = "série dentro do suporte validado e não saturada"
    return {
        "eligible": eligible,
        "reason": reason,
        "distribution": distribution,
        "outside_support_days": outside,
        "frozen_support_low": support_low,
        "frozen_support_high": support_high,
    }


def enforce_published_series(
    plant_id: str,
    probabilities: Sequence[float],
    *,
    out_of_support_days: int = 0,
) -> dict[str, Any]:
    """Validate the series that will actually be published, without touching its numbers.

    Two hard failures, both on the published series itself: a 60-day series entirely above the
    alert threshold, and a series with dozens of days above it that come from an out-of-support
    extrapolation. No clamp, jitter or cosmetic threshold is applied — an ineligible series is
    replaced by a defensible source upstream.
    """
    if not probabilities:
        raise ValueError(f"a usina {plant_id} não produziu pontos de previsão")
    for value in probabilities:
        if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
            raise ValueError(f"a usina {plant_id} produziu probabilidade inválida: {value}")
    distribution = probability_distribution(probabilities)
    if distribution["saturated"]:
        raise ValueError(
            f"a usina {plant_id} produziu probabilidade acima de 95% em todos os "
            f"{distribution['days']} dias; a materialização foi interrompida"
        )
    if (
        distribution["days_above_95_pct"] >= PUBLISHED_DOZENS_ABOVE_95
        and out_of_support_days > OUT_OF_SUPPORT_TOLERANCE_DAYS
    ):
        raise ValueError(
            f"a usina {plant_id} publicaria {distribution['days_above_95_pct']} dias acima de 95% "
            f"com {out_of_support_days} dias fora do suporte congelado na validação; a "
            "materialização foi interrompida"
        )
    return distribution


@dataclass(frozen=True)
class PlantForecastInputs:
    """Everything the assembly needs about one selected plant and its point."""

    asset_id: str
    name: str
    technology: str
    state: str
    ceg: str
    ons_group_id: str
    ons_group_name: str
    connection_point: str
    capacity_mw: float
    history: PlantDailyHistory


def build_plant_forecast(
    *,
    plant: PlantForecastInputs,
    spec: PointSimulationSpec,
    samples: ScenarioSamples,
    schedule: MaintenanceSchedule,
    days: Sequence[date],
    weather_normal_z: Mapping[date, float],
    point_share: Sequence[float],
    backtest_plan: BacktestPlan,
    weather_source: str,
    weather_unit: str,
    scenario_count: int,
) -> dict[str, Any]:
    """Run the three maintenance scenarios and assemble one plant's forecast payload."""
    no_maintenance = simulate_point(
        spec,
        days=days,
        samples=samples,
        schedule=None,
        scenario=SCENARIO_NO_MAINTENANCE,
    )
    scheduled = simulate_point(
        spec,
        days=days,
        samples=samples,
        schedule=schedule,
        scenario=SCENARIO_SCHEDULED_MAINTENANCE,
        record_plant_totals=True,
    )
    scheduled_daily = scenario_daily_mwh(scheduled.selected_curtailed_mw)
    no_maintenance_daily = scenario_daily_mwh(no_maintenance.selected_curtailed_mw)
    expected, lower, upper = mean_and_quantiles(scheduled_daily)
    available_daily = scenario_daily_mwh(scheduled.selected_available_mw)
    available_expected, _, _ = mean_and_quantiles(available_daily)
    scenario_probability = scenario_event_probability(scheduled_daily)
    scheduled_metrics = window_metrics(scheduled.selected_curtailed_mw)
    critical = select_critical_windows(scheduled_metrics, count=CRITICAL_WINDOW_COUNT)
    if len(critical) != CRITICAL_WINDOW_COUNT:
        raise ValueError(
            f"a usina {plant.asset_id} não produziu três janelas críticas não sobrepostas"
        )
    candidate = candidate_maintenance_window(
        plant_id=plant.asset_id, start_day=critical[0].start_interval // INTERVALS_PER_DAY
    )
    candidate_result = simulate_point(
        spec,
        days=days,
        samples=samples,
        schedule=schedule.with_candidate(candidate),
        scenario=SCENARIO_CANDIDATE_MAINTENANCE,
    )

    backtest = run_backtest(
        history=plant.history,
        point_share=point_share,
        weather_normal_z=weather_normal_z,
        capacity_mw=plant.capacity_mw,
        plan=backtest_plan,
    )
    model_raw_forward = forward_probabilities(
        history=plant.history,
        point_share=point_share,
        weather_normal_z=weather_normal_z,
        capacity_mw=plant.capacity_mw,
        horizon_days=days,
        simulated_mwh=expected,
        calibration=None,
        calibration_accepted=False,
        l2=backtest.l2_penalty,
    )
    model_calibrated_forward, calibration_applied = (
        apply_calibration_with_support(backtest.calibration, model_raw_forward)
        if backtest.calibration is not None and backtest.calibration_accepted
        else (list(model_raw_forward), False)
    )
    baseline_forward = baseline_forward_series(plant.history, horizon_days=days)
    forward_series: dict[str, list[float]] = {
        CANDIDATE_MODEL_RAW: list(model_raw_forward),
        CANDIDATE_MODEL_CALIBRATED: list(model_calibrated_forward),
        **{f"baseline_{name}": list(series) for name, series in baseline_forward.items()},
    }
    eligibility: dict[str, dict[str, Any]] = {
        name: candidate_eligibility(
            name=name,
            probabilities=series,
            support_low=backtest.frozen_support_low,
            support_high=backtest.frozen_support_high,
            calibration_applied=calibration_applied,
        )
        for name, series in forward_series.items()
    }
    published_candidate = next(
        (item for item in backtest.candidates if eligibility[item.name]["eligible"]), None
    )
    if published_candidate is None:
        raise ValueError(f"nenhuma fonte de probabilidade elegível para a usina {plant.asset_id}")
    probabilities = forward_series[published_candidate.name]
    published_outside = count_outside_support(
        probabilities,
        support_low=backtest.frozen_support_low,
        support_high=backtest.frozen_support_high,
    )
    distribution = enforce_published_series(
        plant.asset_id, probabilities, out_of_support_days=published_outside
    )
    published = {
        "candidate": published_candidate.name,
        "probability_source": SOURCE_BY_CANDIDATE[published_candidate.name],
        "probability_status": STATUS_BY_CANDIDATE[published_candidate.name],
        "validation_brier": published_candidate.validation_brier,
        "validation_reliability_gap": published_candidate.validation_reliability_gap,
        "test_brier": published_candidate.test_brier,
        "test_reliability_gap": published_candidate.test_reliability_gap,
        "calibration_applied": calibration_applied,
        "selection_basis": "validation_only_policy_with_support_and_saturation_guard",
        "frozen_support": {
            "low": backtest.frozen_support_low,
            "high": backtest.frozen_support_high,
            "days": backtest.frozen_support_days,
            "basis": "validation_paths",
        },
        "future_days": len(probabilities),
        "future_days_outside_support": published_outside,
        "eligibility": eligibility,
        "ranked_candidates": [item.to_payload() for item in backtest.candidates],
    }
    published_note = _published_source_note(backtest, published)

    no_maintenance_by_day = _daily_expectation(no_maintenance_daily)
    scheduled_by_day = _daily_expectation(scheduled_daily)
    expected_mwh_by_day = expected
    point_excess_no_maintenance = _daily_expectation(
        scenario_daily_mwh(no_maintenance.point_excess_mw)
    )
    point_excess_scheduled = _daily_expectation(scenario_daily_mwh(scheduled.point_excess_mw))
    envelope_series = tuple(
        tuple(
            max(available - curtailed, 0.0)
            for available, curtailed in zip(
                scheduled.selected_available_mw[index],
                scheduled.selected_curtailed_mw[index],
                strict=True,
            )
        )
        for index in range(scenario_count)
    )
    envelope_expected, _, _ = mean_and_quantiles(scenario_daily_mwh(envelope_series))
    weather_values = _daily_weather_values(
        plant_id=plant.asset_id,
        spec=spec,
        samples=samples,
        days=days,
    )
    forecasts: list[dict[str, Any]] = []
    for index, day in enumerate(days):
        relief = round(no_maintenance_by_day[index] - scheduled_by_day[index], 6)
        risk_reduction = round(
            (scenario_event_probability(no_maintenance_daily)[index] - scenario_probability[index])
            * 100.0,
            4,
        )
        forecasts.append(
            {
                "forecast_date": day.isoformat(),
                "display_label": format_display_label(day),
                "expected_curtailed_mwh": round(expected_mwh_by_day[index], 6),
                "lower_mwh": round(lower[index], 6),
                "upper_mwh": round(upper[index], 6),
                "curtailment_probability": probabilities[index],
                "scenario_event_probability": scenario_probability[index],
                "potential_generation_mwh": round(available_expected[index], 6),
                "accepted_generation_envelope_mwh": round(envelope_expected[index], 6),
                "scheduled_maintenance_relief_mwh": max(relief, 0.0),
                "avoided_curtailment_mwh": max(
                    round(point_excess_no_maintenance[index] - point_excess_scheduled[index], 6),
                    0.0,
                ),
                "risk_reduction_percentage_points": max(risk_reduction, 0.0),
                "weather_value": round(weather_values[index], 6),
                "weather_unit": weather_unit,
                "weather_source": weather_source,
            }
        )
    windows = [
        _window_payload(
            rank=rank,
            start_day=days[0],
            window=window,
            scheduled=scheduled.selected_curtailed_mw,
            no_maintenance=no_maintenance.selected_curtailed_mw,
            candidate=candidate_result.selected_curtailed_mw,
            scheduled_point_excess=scheduled.point_excess_mw,
            no_maintenance_point_excess=no_maintenance.point_excess_mw,
        )
        for rank, window in enumerate(critical, start=1)
    ]
    point_context = _point_context_payload(
        spec=spec,
        scheduled=scheduled,
        no_maintenance=no_maintenance,
        schedule=schedule,
    )
    return {
        "asset_id": plant.asset_id,
        "name": plant.name,
        "entity_level": "plant",
        "ons_group_id": plant.ons_group_id,
        "ons_group_name": plant.ons_group_name,
        "connection_point": plant.connection_point,
        "technology": plant.technology,
        "state": plant.state,
        "ceg": plant.ceg,
        "capacity_mw": plant.capacity_mw,
        "origin": ORIGIN_SIMULATED,
        "simulation_method": SIMULATION_METHOD,
        "weather_source": weather_source,
        "probability_status": published["probability_status"],
        "probability_source": published["probability_source"],
        "probability_source_note": published_note,
        "point_context": point_context,
        "simulated_telemetry": _simulated_telemetry(
            plant=plant,
            spec=spec,
            scheduled=scheduled,
            weather_values=weather_values,
            weather_unit=weather_unit,
        ),
        "probability_diagnostics": {
            **distribution,
            "published": published,
            "event_rate_history": round(plant.history.event_rate, 6),
            "model_forward_probabilities": list(model_raw_forward),
            "model_calibrated_forward_probabilities": list(model_calibrated_forward),
            "baseline_forward_probabilities": list(baseline_forward["seasonal_blend"]),
            "baseline_forward_series": {
                name: list(series) for name, series in baseline_forward.items()
            },
            "backtest": backtest.to_payload(),
        },
        "forecasts": forecasts,
        "critical_windows_72h": windows,
    }


def _published_source_note(backtest: BacktestResult, published: Mapping[str, Any]) -> str:
    """Explain, in the artifact, which probability was published and why.

    The ranking that produced the choice comes from the validation paths only; the test columns
    are reproduced here as information, never as the criterion.
    """
    candidate = str(published["candidate"])
    ineligible = {
        name: info for name, info in published["eligibility"].items() if not info["eligible"]
    }
    note = (
        "Política congelada na validação: cada fonte candidata (modelo bruto, modelo calibrado "
        "e os baselines de frequência histórica, persistência, sazonalidade e mistura sazonal, "
        "constantes inclusive) foi ordenada pelo Brier e pela confiabilidade da validação. "
        f"Fonte publicada: {candidate} (Brier na validação {published['validation_brier']:.6f}, "
        f"confiabilidade {published['validation_reliability_gap']:.6f}; no teste, Brier "
        f"{published['test_brier']:.6f} e confiabilidade {published['test_reliability_gap']:.6f})."
        " Suporte de probabilidade congelado nos caminhos de validação usados na seleção e na "
        f"calibração: [{published['frozen_support']['low']}, "
        f"{published['frozen_support']['high']}] em {published['frozen_support']['days']} dias; o "
        f"horizonte publicado tem {published['future_days_outside_support']} de "
        f"{published['future_days']} dias fora desse suporte."
    )
    if ineligible:
        note += " Fontes inelegíveis para o horizonte: " + "; ".join(
            f"{name} ({info['reason']})" for name, info in sorted(ineligible.items())
        )
    else:
        note += " Nenhuma fonte foi excluída pelo guarda de saturação."
    if candidate == CANDIDATE_MODEL_CALIBRATED:
        note += (
            " A calibração foi ajustada e aceita apenas na validação e sua aplicação ao "
            "horizonte respeitou o suporte em que foi ajustada."
        )
    elif candidate == CANDIDATE_MODEL_RAW:
        note += (
            " A probabilidade publicada é a do modelo bruto; a calibração não foi aceita na "
            "validação ou não era aplicável ao horizonte sem extrapolação, e a trajetória "
            "permaneceu dentro do suporte congelado na validação."
        )
    else:
        note += (
            " A probabilidade publicada é um baseline declarado explicitamente, escolhido na "
            "validação, em vez de uma série saturada; cada data mantém sua linha e seu rótulo."
        )
    return note


def _daily_expectation(daily: tuple[tuple[float, ...], ...]) -> tuple[float, ...]:
    expected, _, _ = mean_and_quantiles(daily)
    return expected


def _daily_weather_values(
    *,
    plant_id: str,
    spec: PointSimulationSpec,
    samples: ScenarioSamples,
    days: Sequence[date],
) -> tuple[float, ...]:
    """Mean simulated weather value of the selected plant, per day."""
    plant = spec.plant(plant_id)
    values: list[float] = []
    for offset, day in enumerate(days):
        month_hour = (day.month - 1) * INTERVALS_PER_DAY
        total = 0.0
        for scenario_index in range(samples.scenario_count):
            factor = samples.day_factors[scenario_index][offset]
            noise = samples.plant_noise[plant_id][scenario_index]
            total += (
                sum(
                    plant.month_hour_climatology[month_hour + slot] * factor * noise
                    for slot in range(INTERVALS_PER_DAY)
                )
                / INTERVALS_PER_DAY
            )
        values.append(total / samples.scenario_count)
    return tuple(values)


def _simulated_telemetry(
    *,
    plant: PlantForecastInputs,
    spec: PointSimulationSpec,
    scheduled: PointSimulationResult,
    weather_values: Sequence[float],
    weather_unit: str,
) -> dict[str, Any]:
    """Simulated operating state of the plant at the reference interval."""
    available = scheduled.plant_mean_available_mw.get(plant.asset_id, 0.0)
    curtailed = scheduled.plant_mean_curtailed_mw.get(plant.asset_id, 0.0)
    capacity = plant.capacity_mw
    return {
        "generation_mw": round(available - curtailed, 6),
        "potential_generation_mw": round(available, 6),
        "availability_mw": round(capacity, 6),
        "operational_capacity_mw": round(available, 6),
        "accepted_generation_limit_mw": round(max(available - curtailed, 0.0), 6),
        "weather_value": round(weather_values[0], 6) if weather_values else 0.0,
        "weather_unit": weather_unit,
        "origin": ORIGIN_SIMULATED,
    }


def _point_context_payload(
    *,
    spec: PointSimulationSpec,
    scheduled: PointSimulationResult,
    no_maintenance: PointSimulationResult,
    schedule: MaintenanceSchedule,
) -> dict[str, Any]:
    relief = round(no_maintenance.point_mean_excess_mw - scheduled.point_mean_excess_mw, 6)
    entities = []
    for plant in sorted(spec.plants, key=lambda item: item.plant_id):
        windows = [window for window in schedule.windows if window.plant_id == plant.plant_id]
        entities.append(
            {
                "plant_id": plant.plant_id,
                "name": plant.name,
                "technology": plant.technology,
                "capacity_mw": round(plant.capacity_mw, 6),
                "mean_available_generation_mw": round(
                    scheduled.plant_mean_available_mw.get(plant.plant_id, 0.0), 6
                ),
                "mean_curtailed_generation_mw": round(
                    scheduled.plant_mean_curtailed_mw.get(plant.plant_id, 0.0), 6
                ),
                "restricted_day_share": round(plant.restricted_day_share, 6),
                "scheduled_maintenance_intervals": sum(window.interval_count for window in windows),
                "scheduled_maintenance_derate": (
                    round(min(window.derate for window in windows), 6) if windows else 1.0
                ),
                "operational_data_status": "simulated",
                "origin": ORIGIN_SIMULATED,
            }
        )
    return {
        "point_id": spec.point_id,
        "entity_count": len(spec.plants),
        "installed_capacity_mw": round(spec.installed_capacity_mw, 6),
        "potential_generation_mw": round(scheduled.point_mean_potential_mw, 6),
        "accepted_generation_envelope_mw": round(scheduled.point_mean_envelope_mw, 6),
        "estimated_excess_mw": round(scheduled.point_mean_excess_mw, 6),
        "scheduled_maintenance_relief_mw": max(relief, 0.0),
        "envelope": {
            "intercept_mw": round(spec.envelope_intercept_mw, 6),
            "slope": round(spec.envelope_slope, 6),
        },
        "scheduled_maintenance_window_count": len(schedule.windows),
        "simulated_entities": entities,
        "origin": ORIGIN_SIMULATED,
    }


def _window_payload(
    *,
    rank: int,
    start_day: date,
    window: Any,
    scheduled: tuple[tuple[float, ...], ...],
    no_maintenance: tuple[tuple[float, ...], ...],
    candidate: tuple[tuple[float, ...], ...],
    scheduled_point_excess: tuple[tuple[float, ...], ...],
    no_maintenance_point_excess: tuple[tuple[float, ...], ...],
) -> dict[str, Any]:
    starts_at, ends_at = format_window_bounds(start_day, window)
    scheduled_mwh = window_expected_mwh(scheduled, window)
    no_maintenance_mwh = window_expected_mwh(no_maintenance, window)
    candidate_mwh = window_expected_mwh(candidate, window)
    point_scheduled = window_expected_mwh(scheduled_point_excess, window)
    point_no_maintenance = window_expected_mwh(no_maintenance_point_excess, window)
    return {
        "rank": rank,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "start_date": (
            start_day + timedelta(days=window.start_interval // INTERVALS_PER_DAY)
        ).isoformat(),
        "end_date": (
            start_day + timedelta(days=(window.end_interval - 1) // INTERVALS_PER_DAY)
        ).isoformat(),
        "interval_count": window.interval_count,
        "expected_curtailed_mwh": round(scheduled_mwh, 6),
        "curtailment_probability": round(window.probability, 6),
        "scheduled_maintenance_relief_mwh": max(round(no_maintenance_mwh - scheduled_mwh, 6), 0.0),
        "avoided_curtailment_mwh": max(round(point_no_maintenance - point_scheduled, 6), 0.0),
        "candidate_maintenance_relief_mwh": max(round(scheduled_mwh - candidate_mwh, 6), 0.0),
    }


def materialize(
    *,
    catalog_path: str | Path,
    history_path: str | Path,
    relationship: str,
    capacity: str,
    wind_aggregate: str,
    solar_aggregate: str,
    wind_detail: str,
    solar_detail: str,
    weather_snapshot: str,
    weather_snapshot_solar: str | None = None,
    window_start: date,
    window_end: date,
    horizon_start: date,
    horizon_days: int = HORIZON_DAYS,
    cutoff: str,
    scenario_count: int = DEFAULT_SCENARIO_COUNT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the individual plant forecast and the simulated maintenance agenda."""
    catalog = history_module.load_bundled_history(history_path)
    with open(catalog_path, encoding="utf-8") as stream:
        plant_catalog = json.load(stream)
    selected = {plant["asset_id"]: plant for plant in plant_catalog["plants"]}
    histories = {
        plant["asset_id"]: PlantDailyHistory(
            asset_id=plant["asset_id"],
            days=tuple(date.fromisoformat(row["date"]) for row in plant["series"]),
            restricted=tuple(bool(row["restricted_day"]) for row in plant["series"]),
            curtailed_mwh=tuple(float(row["curtailed_mwh"]) for row in plant["series"]),
        )
        for plant in catalog["plants"]
    }
    capacities = history_module.load_plant_capacities(capacity)
    group_points = history_module.load_group_points([wind_aggregate, solar_aggregate])
    selected_points = sorted({plant["connection_point"] for plant in selected.values()})
    point_group_ids = {
        point_id: sorted(
            group for group, published in group_points.items() if published == point_id
        )
        for point_id in selected_points
    }
    point_groups = sorted(
        {group for groups_of_point in point_group_ids.values() for group in groups_of_point}
    )
    point_plants = history_module.load_group_plants(relationship, group_ids=point_groups)
    technology_by_group: dict[str, str] = {}
    for plant in selected.values():
        technology_by_group[plant["ons_group_id"]] = plant["technology"]

    days = tuple(horizon_start + timedelta(days=offset) for offset in range(horizon_days))
    outlooks: dict[str, PointWeatherOutlook] = {}
    for snapshot, technology in (
        (weather_snapshot, "wind"),
        (weather_snapshot_solar or weather_snapshot, "solar"),
    ):
        for point_id, outlook in load_weather_snapshot(snapshot, variable=technology).items():
            outlooks.setdefault(point_id, outlook)

    plants: list[dict[str, Any]] = []
    contexts: dict[str, Any] = {}
    schedule_payloads: dict[str, Any] = {}
    point_restricted: dict[str, dict[str, Mapping[date, bool]]] = {}
    for point_id in selected_points:
        point_group_list = point_group_ids[point_id]
        technology = _point_technology(point_group_list, technology_by_group)
        detail_path, weather_column, flag, supervision = _technology_columns(
            technology, wind_detail, solar_detail
        )
        plant_ids = sorted(
            plant_id for group in point_group_list for plant_id in point_plants.get(group, {})
        )
        bin_size = 0.5 if technology == "wind" else 5.0
        aggregates = load_plant_aggregates(
            detail_path,
            plant_ids=plant_ids,
            weather_column=weather_column,
            weather_flag_column=flag,
            supervision_flag_column=supervision,
            window_start=window_start,
            window_end=window_end,
            bin_size=bin_size,
        )
        point_restricted[point_id] = {
            plant_id: item.daily_restricted for plant_id, item in aggregates.items()
        }
        specs, installed = _build_point_specs(
            point_id=point_id,
            point_group_list=point_group_list,
            point_plants=point_plants,
            capacities=capacities,
            aggregates=aggregates,
            selected_asset_ids={
                plant["asset_id"]
                for plant in selected.values()
                if plant["connection_point"] == point_id
            },
            technology=technology,
        )
        outlook = outlooks.get(point_id) or climatology_outlook(point_id)
        if technology == "wind" and outlook.source == WEATHER_SOURCE_CLIMATOLOGY:
            weather_source = WEATHER_SOURCE_CLIMATOLOGY
        else:
            weather_source = outlook.source
        weather_unit = WEATHER_UNIT_WIND if technology == "wind" else WEATHER_UNIT_SOLAR
        envelope = _fit_point_envelope(
            point_id=point_id,
            point_group_list=point_group_list,
            aggregates=aggregates,
            capacities=capacities,
            point_plants=point_plants,
            detail_path=detail_path,
            weather_column=weather_column,
            flag=flag,
            supervision=supervision,
            bin_size=bin_size,
            wind_aggregate=wind_aggregate,
            solar_aggregate=solar_aggregate,
            window_start=window_start,
            window_end=window_end,
        )
        for selected_plant in [
            plant for plant in selected.values() if plant["connection_point"] == point_id
        ]:
            spec = PointSimulationSpec(
                point_id=point_id,
                plants=specs,
                envelope_intercept_mw=envelope[0],
                envelope_slope=envelope[1],
                installed_capacity_mw=installed,
                selected_asset_id=selected_plant["asset_id"],
            )
            samples = build_scenario_samples(
                spec, days=days, outlook=outlook, scenario_count=scenario_count
            )
            schedule = build_maintenance_schedule(spec, days=days, seed=0)
            if schedule.origin != ORIGIN_SIMULATED:
                raise ValueError("a agenda de manutenção precisa ser simulada")
            history = histories[selected_plant["asset_id"]]
            plan = default_backtest_plan(len(history.days))
            share = _plant_share_series(
                plant_id=selected_plant["asset_id"],
                point_restricted=point_restricted[point_id],
                days=history.days,
            )
            payload = build_plant_forecast(
                plant=PlantForecastInputs(
                    asset_id=selected_plant["asset_id"],
                    name=selected_plant["name"],
                    technology=selected_plant["technology"],
                    state=selected_plant["state"],
                    ceg=selected_plant["ceg"],
                    ons_group_id=selected_plant["ons_group_id"],
                    ons_group_name=selected_plant["ons_group_name"],
                    connection_point=point_id,
                    capacity_mw=float(selected_plant["capacity_mw"]),
                    history=history,
                ),
                spec=spec,
                samples=samples,
                schedule=schedule,
                days=days,
                weather_normal_z=_weather_normal_z(outlook, days=days),
                point_share=share,
                backtest_plan=plan,
                weather_source=weather_source,
                weather_unit=weather_unit,
                scenario_count=scenario_count,
            )
            plants.append(payload)
            contexts[point_id] = payload["point_context"]
            existing = schedule_payloads.get(point_id)
            if existing is None:
                schedule_payloads[point_id] = _schedule_payload(
                    point_id=point_id,
                    spec=spec,
                    schedule=schedule,
                    days=days,
                    candidate_asset_ids=[selected_plant["asset_id"]],
                )
            else:
                existing["candidate_asset_ids"].append(selected_plant["asset_id"])
    plants.sort(key=lambda item: item["asset_id"])
    if len(plants) != len(selected):
        raise ValueError("a materialização precisa de uma previsão por usina selecionada")
    distributions = {plant["asset_id"]: plant["probability_diagnostics"] for plant in plants}
    return (
        {
            "schema": SCHEMA,
            "source": ONS_ORIGIN,
            "calculation": PROXY_ORIGIN,
            "simulation": ORIGIN_SIMULATED,
            "cutoff": cutoff,
            "window": {"start": days[0].isoformat(), "end": days[-1].isoformat()},
            "interval_series": {
                "resolution_minutes": 30,
                "intervals_per_day": INTERVALS_PER_DAY,
                "scenario_count": scenario_count,
            },
            "method": {
                "probability": (
                    "Regressão logística temporal sobre taxas históricas da própria usina, "
                    "sazonalidade, defasagens com shift(1), pressão das demais usinas do ponto "
                    "e normal climatológica da meteorologia."
                ),
                "severity": (
                    "Simulação de meia hora de todas as usinas ativas do ponto contra o "
                    "envelope de geração aceita estimado do curtailment publicado, com três "
                    "cenários de manutenção sobre as mesmas amostras meteorológicas."
                ),
                "envelope": (
                    "Envelope = min(potencial, intercepto + inclinação * potencial) com "
                    "inclinação em [0, 1], ajustado ao curtailment publicado do ponto."
                ),
            },
            "limitations": list(LIMITATIONS),
            "backtest": {
                "plants": {
                    plant["asset_id"]: plant["probability_diagnostics"]["backtest"]
                    for plant in plants
                }
            },
            "probability_distribution": distributions,
            "checks": {
                "all_plants_have_days_below_95_pct": all(
                    plant["probability_diagnostics"]["days_above_95_pct"]
                    < plant["probability_diagnostics"]["days"]
                    for plant in plants
                ),
                "published_series_never_saturated": all(
                    not plant["probability_diagnostics"]["saturated"] for plant in plants
                ),
                "published_series_within_validated_support": all(
                    plant["probability_diagnostics"]["published"]["future_days_outside_support"]
                    <= OUT_OF_SUPPORT_TOLERANCE_DAYS
                    for plant in plants
                    if plant["probability_diagnostics"]["published"]["candidate"]
                    in (CANDIDATE_MODEL_RAW, CANDIDATE_MODEL_CALIBRATED)
                ),
                "saturation_rule": (
                    "uma série publicada com os 60 dias acima de 95% falha a materialização"
                ),
                "support_rule": (
                    "um modelo publicado não pode deixar, de forma material, o suporte de "
                    "probabilidade congelado nos caminhos de validação usados na seleção"
                ),
                "plant_count": len(plants),
                "point_count": len(contexts),
            },
            "point_contexts": contexts,
            "maintenance_schedule": schedule_payloads,
            "plants": plants,
        },
        {
            "schema": "curtailless.simulated_point_maintenance_schedule.v1",
            "origin": ORIGIN_SIMULATED,
            "cutoff": cutoff,
            "window": {"start": days[0].isoformat(), "end": days[-1].isoformat()},
            "method": (
                "Agendas simuladas das usinas participantes do ponto, geradas de forma "
                "determinística a partir do identificador da usina."
            ),
            "limitations": [
                "As agendas são simuladas nesta etapa e não representam coordenação real.",
                "A aba Manutenção não consome esta agenda.",
            ],
            "points": schedule_payloads,
        },
    )


def _point_technology(group_ids: Sequence[str], technology_by_group: Mapping[str, str]) -> str:
    for group in group_ids:
        if group in technology_by_group:
            return technology_by_group[group]
    return "wind"


def _technology_columns(
    technology: str, wind_detail: str, solar_detail: str
) -> tuple[str, str, str, str]:
    if technology == "wind":
        return (
            wind_detail,
            "val_ventoverificado",
            "flg_dadoventoinvalido",
            "flg_dadoventosupervisaoinvalido",
        )
    return (
        solar_detail,
        "val_irradianciaverificado",
        "flg_dadoirradianciainvalido",
        "flg_dadoirradianciasupervisaoinvalido",
    )


def _build_point_specs(
    *,
    point_id: str,
    point_group_list: Sequence[str],
    point_plants: Mapping[str, Mapping[str, tuple[str, str]]],
    capacities: Mapping[str, float],
    aggregates: Mapping[str, PlantAggregates],
    selected_asset_ids: set[str],
    technology: str,
) -> tuple[tuple[PlantSimulationSpec, ...], float]:
    specs: list[PlantSimulationSpec] = []
    installed = 0.0
    for group in point_group_list:
        for plant_id, (name, ceg) in sorted(point_plants.get(group, {}).items()):
            item = aggregates.get(plant_id)
            if item is None:
                continue
            capacity = float(capacities.get(ceg, 0.0))
            installed += capacity
            curve = _curve_from_bins(item.curve_bins)
            lookup_maximum = 40.0 if technology == "wind" else 1400.0
            lookup_step = 0.05 if technology == "wind" else 1.0
            climatology = [0.0] * (12 * INTERVALS_PER_DAY)
            for (month, slot), value in item.month_hour_weather.items():
                climatology[(month - 1) * INTERVALS_PER_DAY + slot] = value
            specs.append(
                PlantSimulationSpec(
                    plant_id=plant_id,
                    name=name,
                    capacity_mw=capacity,
                    technology=technology,
                    month_hour_climatology=tuple(climatology),
                    potential_lookup=build_potential_lookup(
                        curve,
                        capacity_mw=capacity,
                        maximum=lookup_maximum,
                        step=lookup_step,
                    ),
                    lookup_step=lookup_step,
                    relative_spread=_relative_spread(item.daily_weather_mean),
                    availability_mean=0.985,
                    availability_spread=0.02,
                    restricted_day_share=(
                        sum(1 for flag in item.daily_restricted.values() if flag)
                        / len(item.daily_restricted)
                        if item.daily_restricted
                        else 0.0
                    ),
                )
            )
    if not specs:
        raise ValueError(f"o ponto {point_id} não tem usinas com histórico detalhado")
    return tuple(specs), installed


def _relative_spread(daily_weather: Mapping[date, float]) -> float:
    values = [value for value in daily_weather.values() if value is not None]
    if len(values) < 2:
        return 0.15
    mean = sum(values) / len(values)
    if mean <= 0:
        return 0.15
    deviation = statistics.pstdev(values)
    return min(max(deviation / mean, 0.05), 0.6)


def _fit_point_envelope(
    *,
    point_id: str,
    point_group_list: Sequence[str],
    aggregates: Mapping[str, PlantAggregates],
    capacities: Mapping[str, float],
    point_plants: Mapping[str, Mapping[str, tuple[str, str]]],
    detail_path: str,
    weather_column: str,
    flag: str,
    supervision: str,
    bin_size: float,
    wind_aggregate: str,
    solar_aggregate: str,
    window_start: date,
    window_end: date,
) -> tuple[float, float]:
    curves: dict[str, dict[float, float]] = {}
    plant_ids: list[str] = []
    for group in point_group_list:
        for plant_id, (_name, _ceg) in sorted(point_plants.get(group, {}).items()):
            item = aggregates.get(plant_id)
            if item is None or not item.curve_bins:
                continue
            curves[plant_id] = dict(item.curve_bins)
            plant_ids.append(plant_id)
    if not plant_ids:
        raise ValueError(f"o ponto {point_id} não tem curvas para ajustar o envelope")
    potential_by_interval = load_point_interval_potential(
        detail_path,
        plant_ids=plant_ids,
        weather_column=weather_column,
        weather_flag_column=flag,
        supervision_flag_column=supervision,
        curves=curves,
        bin_size=bin_size,
        window_start=window_start,
        window_end=window_end,
    )
    published = load_point_published_curtailment(
        [wind_aggregate, solar_aggregate],
        group_ids=point_group_list,
        window_start=window_start,
        window_end=window_end,
    )
    if not published:
        raise ValueError(f"o ponto {point_id} não tem curtailment publicado para calibrar")
    potentials: list[float] = []
    observations: list[float] = []
    for index, (instant, potential) in enumerate(sorted(potential_by_interval.items())):
        if index % 8 != 0:
            continue
        potentials.append(potential)
        observations.append(published.get(instant, 0.0))
    if len(potentials) < 200:
        raise ValueError(f"o ponto {point_id} não tem amostras suficientes para o envelope")
    return fit_acceptance_envelope(
        point_potential_mw=potentials, published_curtailment_mw=observations
    )


def _schedule_payload(
    *,
    point_id: str,
    spec: PointSimulationSpec,
    schedule: MaintenanceSchedule,
    days: Sequence[date],
    candidate_asset_ids: Sequence[str],
) -> dict[str, Any]:
    windows = [
        {
            "plant_id": window.plant_id,
            "start_date": (
                days[0] + timedelta(days=window.start_interval // INTERVALS_PER_DAY)
            ).isoformat(),
            "end_date": (
                days[0] + timedelta(days=(window.end_interval - 1) // INTERVALS_PER_DAY)
            ).isoformat(),
            "start_interval": window.start_interval,
            "interval_count": window.interval_count,
            "derate": window.derate,
            "origin": ORIGIN_SIMULATED,
        }
        for window in schedule.windows
    ]
    return {
        "point_id": point_id,
        "plant_count": len(spec.plants),
        "windows": windows,
        "candidate_asset_id": candidate_asset_ids[0] if candidate_asset_ids else "",
        "candidate_asset_ids": list(candidate_asset_ids),
        "origin": schedule.origin,
        "method": schedule.method,
    }


def load_bundled_forecast(path: str | Path) -> dict[str, Any]:
    """Read and validate the bundled individual plant forecast."""
    with open(path, encoding="utf-8") as stream:
        payload = json.load(stream)
    validate_forecast_artifact(payload)
    return payload


def validate_forecast_artifact(payload: Mapping[str, Any]) -> None:
    """Enforce the plan contract for the individual plant forecast artifact."""
    if payload.get("schema") != SCHEMA:
        raise ValueError("schema de previsão individual não suportado")
    if payload.get("simulation") != ORIGIN_SIMULATED:
        raise ValueError("a previsão individual precisa ser simulada")
    plants = payload.get("plants")
    if not isinstance(plants, list) or len(plants) != 5:
        raise ValueError("a previsão individual precisa de exatamente cinco usinas")
    contexts = payload.get("point_contexts") or {}
    if len(contexts) != 5:
        raise ValueError("a previsão individual precisa de um contexto por ponto")
    for plant in plants:
        asset_id = str(plant.get("asset_id", ""))
        if not asset_id or asset_id.startswith("CJU_"):
            raise ValueError(f"a previsão individual não pode conter o conjunto {asset_id}")
        if plant.get("entity_level") != "plant":
            raise ValueError(f"a previsão de {asset_id} precisa ter entity_level 'plant'")
        if plant.get("probability_source") not in {
            PROBABILITY_SOURCE_MODEL_CALIBRATED,
            PROBABILITY_SOURCE_MODEL_RAW,
            PROBABILITY_SOURCE_BASELINE,
        }:
            raise ValueError(f"a usina {asset_id} precisa declarar a origem da probabilidade")
        if plant.get("connection_point") not in contexts:
            raise ValueError(f"a usina {asset_id} não tem contexto do seu ponto")
        forecasts = plant.get("forecasts")
        if not isinstance(forecasts, list) or len(forecasts) != HORIZON_DAYS:
            raise ValueError(f"a usina {asset_id} precisa de exatamente 60 pontos diários")
        dates = [row["forecast_date"] for row in forecasts]
        if dates != sorted(set(dates)):
            raise ValueError(f"as datas de {asset_id} precisam ser ordenadas e únicas")
        expected_days = [
            (date.fromisoformat(dates[0]) + timedelta(days=offset)).isoformat()
            for offset in range(HORIZON_DAYS)
        ]
        if dates != expected_days:
            raise ValueError(f"as datas de {asset_id} precisam ser consecutivas")
        for row in forecasts:
            if not row.get("display_label"):
                raise ValueError(f"cada ponto diário de {asset_id} precisa de rótulo")
            probability = float(row["curtailment_probability"])
            if not 0.0 <= probability <= 1.0:
                raise ValueError(f"probabilidade fora de [0, 1] em {asset_id}")
            if not (
                float(row["lower_mwh"])
                <= float(row["expected_curtailed_mwh"])
                <= float(row["upper_mwh"])
            ):
                raise ValueError(f"intervalo inconsistente em {asset_id}")
            if float(row["expected_curtailed_mwh"]) < 0.0:
                raise ValueError(f"energia negativa em {asset_id}")
            for key in (
                "potential_generation_mwh",
                "accepted_generation_envelope_mwh",
                "scheduled_maintenance_relief_mwh",
                "avoided_curtailment_mwh",
            ):
                if float(row[key]) < 0.0:
                    raise ValueError(f"{key} negativo em {asset_id}")
        windows = plant.get("critical_windows_72h")
        if not isinstance(windows, list) or len(windows) != CRITICAL_WINDOW_COUNT:
            raise ValueError(f"a usina {asset_id} precisa de três janelas críticas")
        bounds: list[tuple[int, int]] = []
        for window in windows:
            if int(window["interval_count"]) != 144:
                raise ValueError(
                    f"cada janela de {asset_id} precisa de 144 intervalos de meia hora"
                )
            bounds.append((int(window["rank"]), int(window["interval_count"])))
        if sorted(rank for rank, _ in bounds) != [1, 2, 3]:
            raise ValueError(f"as janelas de {asset_id} precisam ser ranqueadas de 1 a 3")
        diagnostics = plant.get("probability_diagnostics") or {}
        published = diagnostics.get("published") or {}
        frozen_support = published.get("frozen_support") or {}
        if (
            frozen_support.get("low") is not None
            and frozen_support.get("high") is not None
            and float(frozen_support["high"]) < float(frozen_support["low"])
        ):
            raise ValueError(f"o suporte congelado de {asset_id} é inválido")
        out_of_support_days = int(published.get("future_days_outside_support") or 0)
        enforce_published_series(
            asset_id,
            [row["curtailment_probability"] for row in forecasts],
            out_of_support_days=out_of_support_days,
        )
    checks = payload.get("checks") or {}
    if not checks.get("all_plants_have_days_below_95_pct"):
        raise ValueError("nenhuma usina pode ter os 60 dias acima de 95% de probabilidade")
    if checks.get("published_series_within_validated_support") is False:
        raise ValueError(
            "uma série de modelo publicada deixou o suporte de probabilidade congelado na validação"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materializa a previsão de 60 dias por usina individual e a agenda simulada "
            "de manutenção dos pontos de conexão."
        )
    )
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--history", required=True)
    parser.add_argument("--relationship", required=True)
    parser.add_argument("--capacity", required=True)
    parser.add_argument("--wind-aggregate", required=True)
    parser.add_argument("--solar-aggregate", required=True)
    parser.add_argument("--wind-detail", required=True)
    parser.add_argument("--solar-detail", required=True)
    parser.add_argument("--weather-snapshot", required=True)
    parser.add_argument("--weather-snapshot-solar")
    parser.add_argument("--window-start", default="2024-04-01")
    parser.add_argument("--window-end", default="2026-09-25")
    parser.add_argument("--horizon-start", required=True)
    parser.add_argument("--horizon-days", type=int, default=HORIZON_DAYS)
    parser.add_argument("--scenarios", type=int, default=DEFAULT_SCENARIO_COUNT)
    parser.add_argument("--cutoff", default="2026-09-25 23:30:00")
    parser.add_argument("--output", required=True)
    parser.add_argument("--schedule-output", required=True)
    args = parser.parse_args(argv)

    forecast, schedule = materialize(
        catalog_path=args.catalog,
        history_path=args.history,
        relationship=args.relationship,
        capacity=args.capacity,
        wind_aggregate=args.wind_aggregate,
        solar_aggregate=args.solar_aggregate,
        wind_detail=args.wind_detail,
        solar_detail=args.solar_detail,
        weather_snapshot=args.weather_snapshot,
        weather_snapshot_solar=args.weather_snapshot_solar,
        window_start=date.fromisoformat(args.window_start),
        window_end=date.fromisoformat(args.window_end),
        horizon_start=date.fromisoformat(args.horizon_start),
        horizon_days=args.horizon_days,
        cutoff=args.cutoff,
        scenario_count=args.scenarios,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(forecast, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    schedule_output = Path(args.schedule_output)
    schedule_output.parent.mkdir(parents=True, exist_ok=True)
    schedule_output.write_text(
        json.dumps(schedule, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"previsão individual: {len(forecast['plants'])} usinas -> {output}")
    for plant in forecast["plants"]:
        diagnostics = plant["probability_diagnostics"]
        print(
            f"  {plant['asset_id']:8s} p(min/med/max)="
            f"{diagnostics['min']:.4f}/{diagnostics['median']:.4f}/{diagnostics['max']:.4f} "
            f">95%={diagnostics['days_above_95_pct']:2d} "
            f"status={plant['probability_status']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
