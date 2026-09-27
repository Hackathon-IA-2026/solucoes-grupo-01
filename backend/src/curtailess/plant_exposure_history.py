"""Individual plant exposure history reconciled with the published group total.

The module answers two different questions with two different quantities:

* occurrence — ``plant_curtailed_day`` is true when at least one valid half-hour interval
  of that plant carries ``flg_geracaorestrita = 1``;
* energy — the plant potential loss is ``max(0, potential - accepted)`` per restricted
  interval, and the group's published curtailment is allocated to the restricted plants by
  their individual proxy weight, falling back to the registered capacity share among the
  restricted plants only.

The published group total is a control total: the allocated parts must sum back to it within
``CONSERVATION_TOLERANCE_MWH``. A positive group total with no valid plant indication is never
spread silently across every plant; it stays unallocated and the reconciliation fails.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any

import duckdb

SCHEMA = "curtailless.individual_plant_history.v1"
ONS_ORIGIN = "ONS_PUBLICO"
PROXY_ORIGIN = "PROXY_CALCULADO"
CONSERVATION_TOLERANCE_MWH = 1e-6
INTERVAL_HOURS = 0.5
CURVE_BIN_COUNT = 20
SIMULATION_METHOD = "SIMULADO_FROM_ONS_HISTORY"

METHOD_POTENTIAL_LOSS = "potential_loss_proxy"
METHOD_CAPACITY_FALLBACK = "capacity_fallback"
METHOD_UNALLOCATED = "unallocated"
METHOD_NO_CURTAILMENT = "no_curtailment"

METHOD_DESCRIPTIONS = {
    METHOD_POTENTIAL_LOSS: (
        "Rateio do total publicado do conjunto pelo peso da perda potencial individual "
        "das usinas marcadas como restritas."
    ),
    METHOD_CAPACITY_FALLBACK: (
        "Rateio pela participação da capacidade entre as usinas marcadas como restritas, "
        "usado quando os proxies individuais não sustentam pesos."
    ),
    METHOD_UNALLOCATED: (
        "Total publicado do conjunto sem indicação individual válida; permanece não alocado."
    ),
    METHOD_NO_CURTAILMENT: "Sem energia restringida publicada no conjunto para o dia.",
}


class UnreconciledGroupTotalError(RuntimeError):
    """Raised when the allocated parts do not conserve the published group total."""


@dataclass(frozen=True, slots=True)
class PlantInterval:
    """One half-hour record of a plant from the detailed public ONS base."""

    plant_id: str
    group_id: str
    observed_at: datetime
    restricted: bool | None
    accepted_mw: float | None
    weather_value: float | None
    weather_invalid: bool = False
    supervision_invalid: bool = False

    @property
    def energy_usable(self) -> bool:
        """Usable for the energy proxy: restriction known, measurement and weather valid.

        The restriction flag itself never depends on weather validity, so an interval with a
        discarded weather reading still proves that the plant was restricted.
        """
        return (
            not self.weather_invalid
            and not self.supervision_invalid
            and self.restricted is not None
            and self.accepted_mw is not None
            and self.weather_value is not None
        )

    @property
    def energy_point(self) -> tuple[float, float] | None:
        """The ``(weather, accepted)`` pair used by the curve, or ``None`` when unusable."""
        if not self.energy_usable:
            return None
        assert self.weather_value is not None and self.accepted_mw is not None
        return (self.weather_value, self.accepted_mw)


@dataclass(frozen=True)
class IntervalQuality:
    """Counts that explain which raw intervals were dropped and why."""

    total: int
    valid: int
    duplicate: int
    excluded_invalid_flag: int
    excluded_unknown_restriction: int
    excluded_missing_measurement: int


def normalize_intervals(
    intervals: Iterable[PlantInterval],
) -> tuple[list[PlantInterval], IntervalQuality]:
    """Drop duplicate records, keeping one interval per plant and instant.

    The returned list is the deduplicated series; the quality counts describe which of those
    intervals are unusable for the energy proxy and why.
    """
    seen: set[tuple[str, datetime]] = set()
    deduped: list[PlantInterval] = []
    duplicate = 0
    for item in intervals:
        key = (item.plant_id, item.observed_at)
        if key in seen:
            duplicate += 1
            continue
        seen.add(key)
        deduped.append(item)

    invalid_flag = unknown_restriction = missing_measurement = 0
    valid = 0
    for item in deduped:
        if item.weather_invalid or item.supervision_invalid:
            invalid_flag += 1
        elif item.restricted is None:
            unknown_restriction += 1
        elif item.accepted_mw is None or item.weather_value is None:
            missing_measurement += 1
        else:
            valid += 1
    quality = IntervalQuality(
        total=len(deduped) + duplicate,
        valid=valid,
        duplicate=duplicate,
        excluded_invalid_flag=invalid_flag,
        excluded_unknown_restriction=unknown_restriction,
        excluded_missing_measurement=missing_measurement,
    )
    return deduped, quality


def energy_usable(intervals: Iterable[PlantInterval]) -> list[PlantInterval]:
    """Intervals that can carry the energy proxy."""
    return [item for item in intervals if item.energy_usable]


def daily_occurrence(intervals: Iterable[PlantInterval]) -> dict[date, bool]:
    """Day is restricted when at least one interval carries the restriction flag."""
    occurrence: dict[date, bool] = {}
    for item in intervals:
        day = item.observed_at.date()
        occurrence[day] = occurrence.get(day, False) or item.restricted is True
    return occurrence


@dataclass(frozen=True)
class GenerationCurve:
    """Empirical weather-to-generation curve fitted on non-restricted intervals only."""

    centers: tuple[float, ...]
    values: tuple[float, ...]

    def potential(self, weather_value: float | None) -> float:
        if weather_value is None or not self.centers:
            return 0.0
        if weather_value <= self.centers[0]:
            return max(0.0, self.values[0])
        if weather_value >= self.centers[-1]:
            return max(0.0, self.values[-1])
        for index in range(1, len(self.centers)):
            if weather_value <= self.centers[index]:
                low, high = self.centers[index - 1], self.centers[index]
                low_value, high_value = self.values[index - 1], self.values[index]
                if high <= low:
                    return max(0.0, high_value)
                ratio = (weather_value - low) / (high - low)
                return max(0.0, low_value + ratio * (high_value - low_value))
        return max(0.0, self.values[-1])


def fit_generation_curve(
    intervals: Sequence[PlantInterval], *, bin_count: int = CURVE_BIN_COUNT
) -> GenerationCurve:
    """Fit the plant's own curve using only valid intervals without restriction."""
    points: list[tuple[float, float]] = []
    for item in intervals:
        point = item.energy_point
        if point is None or item.restricted:
            continue
        points.append(point)
    points.sort()
    if not points:
        return GenerationCurve((), ())
    bins = min(bin_count, len(points))
    centers: list[float] = []
    values: list[float] = []
    for index in range(bins):
        start = round(index * len(points) / bins)
        end = round((index + 1) * len(points) / bins)
        chunk = points[start:end]
        if not chunk:
            continue
        centers.append(float(median(point[0] for point in chunk)))
        values.append(float(median(point[1] for point in chunk)))
    # Collapse equal weather centers so interpolation never divides by zero.
    collapsed_centers: list[float] = []
    collapsed_values: list[float] = []
    for center, value in zip(centers, values, strict=True):
        if collapsed_centers and center == collapsed_centers[-1]:
            collapsed_values[-1] = (collapsed_values[-1] + value) / 2.0
            continue
        collapsed_centers.append(center)
        collapsed_values.append(value)
    return GenerationCurve(tuple(collapsed_centers), tuple(collapsed_values))


@dataclass(frozen=True, slots=True)
class PlantDayProxy:
    """Daily proxy of one plant used as the allocation weight."""

    plant_id: str
    restricted: bool
    capacity_mw: float
    raw_loss_mwh: float


def plant_daily_proxy(
    intervals: Sequence[PlantInterval],
    curve: GenerationCurve,
    *,
    capacity_mw: float,
) -> dict[date, PlantDayProxy]:
    """Aggregate the half-hour proxy loss to the day.

    The restriction flag comes from every interval with a known restriction state; the loss
    only sums the restricted intervals whose measurement and weather are usable.
    """
    if not intervals:
        return {}
    plant_id = intervals[0].plant_id
    accumulator: dict[date, dict[str, Any]] = {}
    for item in intervals:
        day = item.observed_at.date()
        entry = accumulator.setdefault(day, {"restricted": False, "loss": 0.0})
        if item.restricted is not True:
            continue
        entry["restricted"] = True
        point = item.energy_point
        if point is None:
            continue
        potential = curve.potential(point[0])
        if capacity_mw > 0:
            potential = min(potential, capacity_mw)
        entry["loss"] += max(0.0, potential - point[1]) * INTERVAL_HOURS
    return {
        day: PlantDayProxy(
            plant_id=plant_id,
            restricted=bool(entry["restricted"]),
            capacity_mw=capacity_mw,
            raw_loss_mwh=round(float(entry["loss"]), 6),
        )
        for day, entry in accumulator.items()
    }


@dataclass(frozen=True)
class AllocationResult:
    """Result of allocating one day of published group curtailment."""

    method: str
    allocated_mwh: Mapping[str, float]
    coverage_pct: float
    residual_mwh: float


def allocate_group_curtailment(
    group_public_mwh: float, entries: Sequence[PlantDayProxy]
) -> AllocationResult:
    """Allocate the published group total to the restricted plants only."""
    total = float(group_public_mwh)
    if total < 0:
        raise ValueError("group curtailment cannot be negative")
    restricted = [entry for entry in entries if entry.restricted]
    if total == 0.0:
        return AllocationResult(METHOD_NO_CURTAILMENT, {}, 100.0, 0.0)
    if not restricted:
        return AllocationResult(METHOD_UNALLOCATED, {}, 0.0, total)

    loss_total = sum(max(entry.raw_loss_mwh, 0.0) for entry in restricted)
    if loss_total > 0:
        weights = {
            entry.plant_id: max(entry.raw_loss_mwh, 0.0) / loss_total for entry in restricted
        }
        method = METHOD_POTENTIAL_LOSS
    else:
        capacity_total = sum(max(entry.capacity_mw, 0.0) for entry in restricted)
        if capacity_total <= 0:
            return AllocationResult(METHOD_UNALLOCATED, {}, 0.0, total)
        weights = {
            entry.plant_id: max(entry.capacity_mw, 0.0) / capacity_total for entry in restricted
        }
        method = METHOD_CAPACITY_FALLBACK

    allocated = {plant_id: total * weight for plant_id, weight in weights.items()}
    residual = total - sum(allocated.values())
    return AllocationResult(method, allocated, 100.0, residual)


def reconcile_group_day(group_public_mwh: float, result: AllocationResult) -> None:
    """Fail when the allocated parts do not conserve the published group total."""
    total = float(group_public_mwh)
    if result.method == METHOD_UNALLOCATED:
        if total > CONSERVATION_TOLERANCE_MWH:
            raise UnreconciledGroupTotalError(
                f"total publicado de {total:.6f} MWh sem indicação individual válida"
            )
        return
    allocated = sum(result.allocated_mwh.values())
    if abs(allocated - total) > CONSERVATION_TOLERANCE_MWH:
        raise UnreconciledGroupTotalError(
            f"rateio de {allocated:.6f} MWh não conserva o total de {total:.6f} MWh"
        )


@dataclass(frozen=True)
class PlantDailyRow:
    """One reconciled day of one plant."""

    day: date
    restricted: bool
    raw_loss_mwh: float
    allocated_mwh: float
    allocation_method: str


@dataclass(frozen=True)
class GroupHistory:
    """Reconciled daily history of every plant of one group."""

    group_id: str
    days: tuple[date, ...]
    group_public_by_day: Mapping[date, float]
    rows_by_plant: Mapping[str, tuple[PlantDailyRow, ...]]
    allocation_methods: Mapping[date, str]
    allocation_coverage_pct: float
    total_public_mwh: float
    total_allocated_mwh: float
    max_residual_mwh: float
    method_counts: Mapping[str, int]


def build_group_history_from_proxies(
    *,
    group_id: str,
    proxies_by_plant: Mapping[str, Mapping[date, PlantDayProxy]],
    group_public_by_day: Mapping[date, float],
) -> GroupHistory:
    """Allocate every published day across the group's plants and verify conservation."""
    public = {day: float(value) for day, value in group_public_by_day.items()}
    days = sorted(set(public) | {day for series in proxies_by_plant.values() for day in series})
    rows: dict[str, list[PlantDailyRow]] = {plant_id: [] for plant_id in proxies_by_plant}
    methods: dict[date, str] = {}
    method_counts: dict[str, int] = {}
    total_public = 0.0
    total_allocated = 0.0
    max_residual = 0.0
    for day in days:
        published = public.get(day, 0.0)
        entries = [series[day] for series in proxies_by_plant.values() if day in series]
        result = allocate_group_curtailment(published, entries)
        reconcile_group_day(published, result)
        methods[day] = result.method
        method_counts[result.method] = method_counts.get(result.method, 0) + 1
        total_public += published
        total_allocated += sum(result.allocated_mwh.values())
        max_residual = max(max_residual, abs(result.residual_mwh))
        for plant_id, series in proxies_by_plant.items():
            proxy = series.get(day)
            rows[plant_id].append(
                PlantDailyRow(
                    day=day,
                    restricted=bool(proxy and proxy.restricted),
                    raw_loss_mwh=proxy.raw_loss_mwh if proxy else 0.0,
                    allocated_mwh=result.allocated_mwh.get(plant_id, 0.0),
                    allocation_method=result.method,
                )
            )
    coverage = 100.0 if total_public <= 0 else 100.0 * total_allocated / total_public
    return GroupHistory(
        group_id=group_id,
        days=tuple(days),
        group_public_by_day=public,
        rows_by_plant={plant_id: tuple(items) for plant_id, items in rows.items()},
        allocation_methods=methods,
        allocation_coverage_pct=round(coverage, 6),
        total_public_mwh=round(total_public, 6),
        total_allocated_mwh=round(total_allocated, 6),
        max_residual_mwh=max_residual,
        method_counts=method_counts,
    )


@dataclass(frozen=True)
class PlantSeries:
    """One plant with its raw half-hour intervals, as consumed by the builder."""

    plant_id: str
    name: str
    group_id: str
    capacity_mw: float
    intervals: tuple[PlantInterval, ...]


def build_group_history(
    *,
    group_id: str,
    plants: Sequence[PlantSeries],
    group_public_by_day: Mapping[date, float],
) -> GroupHistory:
    """Fit each plant's own curve and reconcile the group's published total."""
    proxies: dict[str, Mapping[date, PlantDayProxy]] = {}
    for plant in plants:
        intervals, _ = normalize_intervals(plant.intervals)
        curve = fit_generation_curve(intervals)
        proxies[plant.plant_id] = plant_daily_proxy(intervals, curve, capacity_mw=plant.capacity_mw)
    return build_group_history_from_proxies(
        group_id=group_id,
        proxies_by_plant=proxies,
        group_public_by_day=group_public_by_day,
    )


def build_point_context(
    *,
    point_id: str,
    groups: Sequence[GroupHistory],
    entity_ids: Sequence[str],
) -> dict[str, Any]:
    """Aggregate the point by deriving group totals once, without double counting."""
    group_totals = {group.group_id: round(group.total_public_mwh, 6) for group in groups}
    return {
        "point_id": point_id,
        "entity_count": len(entity_ids),
        "entities": sorted(entity_ids),
        "group_ids": [group.group_id for group in groups],
        "group_public_mwh": group_totals,
        "point_public_mwh": round(sum(group_totals.values()), 6),
        "group_count": len(groups),
        "origin": PROXY_ORIGIN,
        "note": (
            "Os totais de conjunto são derivados das usinas correspondentes e somados uma "
            "única vez; nenhum conjunto é somado duas vezes."
        ),
    }


def load_bundled_history(path: str | Path) -> dict[str, Any]:
    """Read and validate the bundled plant history artifact."""
    with open(path, encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("schema") != SCHEMA:
        raise ValueError("schema de histórico individual não suportado")
    if payload.get("calculation") != PROXY_ORIGIN:
        raise ValueError("o histórico individual precisa ser um proxy calculado")
    plants = payload.get("plants")
    if not isinstance(plants, list) or not plants:
        raise ValueError("o histórico precisa de usinas")
    for plant in plants:
        asset_id = str(plant.get("asset_id", ""))
        if asset_id.startswith("CJU_"):
            raise ValueError(f"histórico individual não pode conter o conjunto {asset_id}")
        if plant.get("entity_level") != "plant":
            raise ValueError(f"histórico de {asset_id} precisa ter entity_level 'plant'")
    return payload


def _placeholders(values: Sequence[str]) -> str:
    return ", ".join("'" + value.replace("'", "''") + "'" for value in values)


def load_group_public_daily(
    path: str,
    *,
    group_ids: Sequence[str],
    window_start: date,
    window_end: date,
) -> dict[str, dict[date, float]]:
    """Daily published curtailment per group from the aggregate ONS base."""
    query = f"""
        SELECT
            trim(id_ons),
            din_instante::DATE,
            sum(
                CASE WHEN val_geracaolimitada IS NOT NULL
                     THEN coalesce(val_geracaonaorealizadaapurada, 0) * {INTERVAL_HOURS}
                     ELSE 0 END
            )
        FROM {{source}}
        WHERE trim(id_ons) IN ({_placeholders(group_ids)})
          AND din_instante >= TIMESTAMP '{window_start.isoformat()} 00:00:00'
          AND din_instante <= TIMESTAMP '{window_end.isoformat()} 23:59:59'
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    source = f"read_parquet('{path}', union_by_name=true)"
    daily: dict[str, dict[date, float]] = {}
    with duckdb.connect() as connection:
        for group_id, day, value in connection.execute(query.format(source=source)).fetchall():
            daily.setdefault(group_id, {})[day] = round(float(value or 0.0), 6)
    return daily


def iter_plant_intervals(
    path: str,
    *,
    plant_ids: Sequence[str],
    weather_column: str,
    weather_flag_column: str,
    supervision_flag_column: str,
    window_start: date,
    window_end: date,
    batch_size: int = 20000,
) -> Iterator[tuple[str, list[PlantInterval]]]:
    """Stream the detailed base plant by plant, ordered so one plant is held at a time."""
    query = f"""
        SELECT
            trim(id_ons),
            din_instante,
            flg_geracaorestrita,
            val_geracaoverificada,
            {weather_column},
            coalesce({weather_flag_column}, 0),
            coalesce({supervision_flag_column}, 0)
        FROM {{source}}
        WHERE trim(id_ons) IN ({_placeholders(plant_ids)})
          AND din_instante >= TIMESTAMP '{window_start.isoformat()} 00:00:00'
          AND din_instante <= TIMESTAMP '{window_end.isoformat()} 23:59:59'
        ORDER BY 1, 2
    """
    source = f"read_parquet('{path}', union_by_name=true)"
    with duckdb.connect() as connection:
        cursor = connection.execute(query.format(source=source))
        current: str | None = None
        buffer: list[PlantInterval] = []
        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            for row in rows:
                plant_id = row[0]
                if plant_id != current:
                    if current is not None:
                        yield current, buffer
                    current = plant_id
                    buffer = []
                buffer.append(
                    PlantInterval(
                        plant_id=plant_id,
                        group_id="",
                        observed_at=row[1],
                        restricted=None if row[2] is None else bool(row[2]),
                        accepted_mw=None if row[3] is None else float(row[3]),
                        weather_value=None if row[4] is None else float(row[4]),
                        weather_invalid=bool(row[5]),
                        supervision_invalid=bool(row[6]),
                    )
                )
        if current is not None:
            yield current, buffer


def load_group_plants(
    path: str, *, group_ids: Sequence[str]
) -> dict[str, dict[str, tuple[str, str]]]:
    """Map each declared group to its individual plants: plant id -> (name, ceg)."""
    query = f"""
        SELECT DISTINCT
            trim(id_ons_conjunto),
            trim(id_ons_usina),
            trim(nom_usina),
            trim(ceg)
        FROM {{source}}
        WHERE trim(id_ons_conjunto) IN ({_placeholders(group_ids)})
          AND nullif(trim(id_ons_usina), '') IS NOT NULL
          AND trim(id_ons_usina) NOT LIKE 'CJU_%'
          AND nullif(trim(dat_fimrelacionamento), '') IS NULL
        ORDER BY 1, 2
    """
    source = f"read_parquet('{path}', union_by_name=true)"
    groups: dict[str, dict[str, tuple[str, str]]] = {}
    with duckdb.connect() as connection:
        for group_id, plant_id, name, ceg in connection.execute(
            query.format(source=source)
        ).fetchall():
            groups.setdefault(group_id, {})[plant_id] = (name, ceg)
    return groups


def load_plant_capacities(path: str) -> dict[str, float]:
    """Registered effective capacity per CEG from the cadastral base."""
    query = """
        SELECT trim(ceg), round(coalesce(sum(val_potenciaefetiva), 0), 6)
        FROM {source}
        WHERE nullif(trim(ceg), '') IS NOT NULL
          AND nullif(trim(ceg), '') <> '-'
          AND nullif(trim(dat_desativacao), '') IS NULL
        GROUP BY 1
    """
    source = f"read_parquet('{path}', union_by_name=true)"
    with duckdb.connect() as connection:
        return {
            row[0]: float(row[1])
            for row in connection.execute(query.format(source=source)).fetchall()
        }


def materialize(
    *,
    catalog_path: str | Path,
    relationship: str,
    capacity: str,
    wind_aggregate: str,
    solar_aggregate: str,
    wind_detail: str,
    solar_detail: str,
    window_start: date,
    window_end: date,
    cutoff: str,
) -> dict[str, Any]:
    """Build the individual history artifact from the public ONS bases."""
    with open(catalog_path, encoding="utf-8") as stream:
        catalog = json.load(stream)
    selected = {plant["ons_group_id"]: plant for plant in catalog["plants"]}
    group_ids = list(selected)
    groups = load_group_plants(relationship, group_ids=group_ids)
    capacities = load_plant_capacities(capacity)

    public: dict[str, dict[date, float]] = {}
    for path, ids in (
        (wind_aggregate, [gid for gid, plant in selected.items() if plant["technology"] == "wind"]),
        (
            solar_aggregate,
            [gid for gid, plant in selected.items() if plant["technology"] == "solar"],
        ),
    ):
        public.update(
            load_group_public_daily(
                path, group_ids=ids, window_start=window_start, window_end=window_end
            )
        )

    proxies_by_group: dict[str, dict[str, Mapping[date, PlantDayProxy]]] = {
        group_id: {} for group_id in group_ids
    }
    quality_by_plant: dict[str, IntervalQuality] = {}
    for path, weather_column, weather_flag, supervision_flag, technology in (
        (
            wind_detail,
            "val_ventoverificado",
            "flg_dadoventoinvalido",
            "flg_dadoventosupervisaoinvalido",
            "wind",
        ),
        (
            solar_detail,
            "val_irradianciaverificado",
            "flg_dadoirradianciainvalido",
            "flg_dadoirradianciasupervisaoinvalido",
            "solar",
        ),
    ):
        plant_group = {
            plant_id: group_id
            for group_id, plant in selected.items()
            if plant["technology"] == technology
            for plant_id in groups.get(group_id, {})
        }
        if not plant_group:
            continue
        for plant_id, intervals in iter_plant_intervals(
            path,
            plant_ids=list(plant_group),
            weather_column=weather_column,
            weather_flag_column=weather_flag,
            supervision_flag_column=supervision_flag,
            window_start=window_start,
            window_end=window_end,
        ):
            intervals, quality = normalize_intervals(intervals)
            curve = fit_generation_curve(intervals)
            capacity_mw = capacities.get(groups[plant_group[plant_id]][plant_id][1], 0.0)
            proxies_by_group[plant_group[plant_id]][plant_id] = plant_daily_proxy(
                intervals, curve, capacity_mw=capacity_mw
            )
            quality_by_plant[plant_id] = quality

    histories: list[GroupHistory] = []
    plant_payloads: list[dict[str, Any]] = []
    for group_id in group_ids:
        history = build_group_history_from_proxies(
            group_id=group_id,
            proxies_by_plant=proxies_by_group[group_id],
            group_public_by_day=public.get(group_id, {}),
        )
        histories.append(history)
        plant = selected[group_id]
        plant_id = plant["asset_id"]
        rows = history.rows_by_plant.get(plant_id, ())
        series = [
            {
                "date": row.day.isoformat(),
                "curtailed_mwh": round(row.allocated_mwh, 6),
                "restricted_day": row.restricted,
                "allocation_method": row.allocation_method,
            }
            for row in rows
        ]
        restricted_days = sum(1 for row in rows if row.restricted)
        total = round(sum(row.allocated_mwh for row in rows), 6)
        observed = len(rows)
        plant_payloads.append(
            {
                "asset_id": plant_id,
                "name": plant["name"],
                "entity_level": "plant",
                "ons_group_id": group_id,
                "ons_group_name": plant["ons_group_name"],
                "connection_point": plant["connection_point"],
                "technology": plant["technology"],
                "state": plant["state"],
                "capacity_mw": plant["capacity_mw"],
                "ceg": plant["ceg"],
                "period_start": rows[0].day.isoformat() if rows else window_start.isoformat(),
                "period_end": rows[-1].day.isoformat() if rows else window_end.isoformat(),
                "calendar_days": observed,
                "daily_rows": observed,
                "total_curtailed_mwh": total,
                "event_day_share_pct": (
                    round(100.0 * restricted_days / observed, 4) if observed else 0.0
                ),
                "allocation_coverage_pct": history.allocation_coverage_pct,
                "allocation_method": _dominant_method(history.method_counts),
                "max_reconciliation_residual_mwh": history.max_residual_mwh,
                "origin": PROXY_ORIGIN,
                "simulation_method": SIMULATION_METHOD,
                "series": series,
            }
        )

    point_id = selected[group_ids[0]]["connection_point"]
    context = build_point_context(
        point_id=point_id,
        groups=histories,
        entity_ids=group_ids,
    )
    total_public = round(sum(history.total_public_mwh for history in histories), 6)
    total_allocated = round(sum(history.total_allocated_mwh for history in histories), 6)
    return {
        "schema": SCHEMA,
        "source": ONS_ORIGIN,
        "calculation": PROXY_ORIGIN,
        "cutoff": cutoff,
        "window": {"start": window_start.isoformat(), "end": window_end.isoformat()},
        "method": (
            "Ocorrência diária por flg_geracaorestrita; energia individual por perda "
            "potencial sobre curva própria treinada só em intervalos sem restrição, "
            "rateada contra o total publicado do conjunto."
        ),
        "limitations": [
            "A energia individual é um proxy reconciliado, não uma medição direta do ONS.",
            "O rateio conserva o total publicado do conjunto dentro da tolerância numérica.",
            "Quando os proxies não sustentam pesos, o fallback usa a capacidade apenas "
            "entre as usinas marcadas como restritas.",
            "Sem indicação individual válida, o total do conjunto permanece não alocado.",
            "O ponto de conexão é o publicado no nível do conjunto.",
            "A base detalhada solar omite id_ons_conjuntousina em parte de 2024; o vínculo "
            "foi recuperado pelo nome cadastral do conjunto.",
        ],
        "conservation": {
            "tolerance_mwh": CONSERVATION_TOLERANCE_MWH,
            "total_group_public_mwh": total_public,
            "total_allocated_mwh": total_allocated,
            "max_residual_mwh": max(
                (history.max_residual_mwh for history in histories), default=0.0
            ),
        },
        "point_context": context,
        "groups": [
            {
                "group_id": history.group_id,
                "group_name": selected[history.group_id]["ons_group_name"],
                "point_id": selected[history.group_id]["connection_point"],
                "plant_count": len(history.rows_by_plant),
                "calendar_days": len(history.days),
                "total_public_mwh": history.total_public_mwh,
                "total_allocated_mwh": history.total_allocated_mwh,
                "allocation_coverage_pct": history.allocation_coverage_pct,
                "max_residual_mwh": history.max_residual_mwh,
                "origin": PROXY_ORIGIN,
                "allocation_methods": history.method_counts,
                "allocation_method_descriptions": METHOD_DESCRIPTIONS,
            }
            for history in histories
        ],
        "plants": plant_payloads,
        "interval_quality": {
            plant_id: {
                "total": quality.total,
                "valid": quality.valid,
                "duplicate": quality.duplicate,
                "excluded_invalid_flag": quality.excluded_invalid_flag,
                "excluded_unknown_restriction": quality.excluded_unknown_restriction,
                "excluded_missing_measurement": quality.excluded_missing_measurement,
            }
            for plant_id, quality in quality_by_plant.items()
        },
    }


def _dominant_method(counts: Mapping[str, int]) -> str:
    if not counts:
        return METHOD_NO_CURTAILMENT
    return max(counts.items(), key=lambda item: (item[1], item[0]))[0]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materializa o histórico diário por usina reconciliado com o total público "
            "do conjunto a partir das bases ONS."
        )
    )
    parser.add_argument("--catalog", required=True, help="catálogo de usinas individuais")
    parser.add_argument("--relationship", required=True, help="parquet de usina_conjunto")
    parser.add_argument("--capacity", required=True, help="parquet de capacidade-geracao")
    parser.add_argument("--wind-aggregate", required=True)
    parser.add_argument("--solar-aggregate", required=True)
    parser.add_argument("--wind-detail", required=True)
    parser.add_argument("--solar-detail", required=True)
    parser.add_argument("--window-start", default="2024-04-01")
    parser.add_argument("--window-end", default="2026-09-25")
    parser.add_argument("--cutoff", default="2026-09-25 23:30:00")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    payload = materialize(
        catalog_path=args.catalog,
        relationship=args.relationship,
        capacity=args.capacity,
        wind_aggregate=args.wind_aggregate,
        solar_aggregate=args.solar_aggregate,
        wind_detail=args.wind_detail,
        solar_detail=args.solar_detail,
        window_start=date.fromisoformat(args.window_start),
        window_end=date.fromisoformat(args.window_end),
        cutoff=args.cutoff,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"histórico individual: {len(payload['plants'])} usinas -> {output}")
    for plant in payload["plants"]:
        print(
            f"  {plant['asset_id']:8s} {plant['total_curtailed_mwh']:14.3f} MWh "
            f"dias={plant['calendar_days']} restritos={plant['event_day_share_pct']}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
