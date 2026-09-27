"""Focused tests for the individual plant exposure history (plan Task 2)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from curtailess.plant_exposure_history import (
    CONSERVATION_TOLERANCE_MWH,
    METHOD_CAPACITY_FALLBACK,
    METHOD_NO_CURTAILMENT,
    METHOD_POTENTIAL_LOSS,
    METHOD_UNALLOCATED,
    PlantDayProxy,
    PlantInterval,
    PlantSeries,
    UnreconciledGroupTotalError,
    allocate_group_curtailment,
    build_group_history,
    build_point_context,
    build_point_contexts,
    daily_occurrence,
    energy_usable,
    fit_generation_curve,
    load_bundled_history,
    normalize_intervals,
    plant_daily_proxy,
    reconcile_group_day,
)

BUNDLED = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "curtailess"
    / "data"
    / "individual_plant_history.json"
)


def interval(
    *,
    plant_id: str = "P1",
    group_id: str = "CJU_TEST",
    day: str = "2024-04-01",
    hour: int = 0,
    minute: int = 0,
    restricted: bool | None = False,
    accepted: float | None = 10.0,
    weather: float | None = 8.0,
    weather_invalid: bool = False,
    supervision_invalid: bool = False,
) -> PlantInterval:
    return PlantInterval(
        plant_id=plant_id,
        group_id=group_id,
        observed_at=datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00"),
        restricted=restricted,
        accepted_mw=accepted,
        weather_value=weather,
        weather_invalid=weather_invalid,
        supervision_invalid=supervision_invalid,
    )


def test_occurrence_comes_from_the_restriction_flag() -> None:
    intervals, _ = normalize_intervals(
        [
            interval(hour=0, restricted=False),
            interval(hour=1, restricted=True),
            interval(hour=2, restricted=False),
            interval(day="2024-04-02", hour=0, restricted=False),
        ]
    )
    occurrence = daily_occurrence(intervals)

    assert occurrence[date(2024, 4, 1)] is True
    assert occurrence[date(2024, 4, 2)] is False


def test_invalid_and_duplicate_intervals_are_excluded() -> None:
    deduped, quality = normalize_intervals(
        [
            interval(hour=0, restricted=False),
            interval(hour=0, restricted=False),
            interval(hour=1, weather_invalid=True),
            interval(hour=2, supervision_invalid=True),
            interval(hour=3, restricted=None),
            interval(hour=4, accepted=None),
            interval(hour=5, weather=None),
            interval(hour=6, restricted=True),
        ]
    )

    assert [item.observed_at.hour for item in deduped] == [0, 1, 2, 3, 4, 5, 6]
    assert [item.observed_at.hour for item in energy_usable(deduped)] == [0, 6]
    assert quality.total == 8
    assert quality.valid == 2
    assert quality.duplicate == 1
    assert quality.excluded_invalid_flag == 2
    assert quality.excluded_unknown_restriction == 1
    assert quality.excluded_missing_measurement == 2


def test_occurrence_does_not_depend_on_weather_validity() -> None:
    deduped, quality = normalize_intervals(
        [
            interval(hour=0, restricted=True, weather_invalid=True),
            interval(hour=1, restricted=True, supervision_invalid=True),
        ]
    )

    # A discarded weather reading never hides a restriction event that the operator flagged.
    assert daily_occurrence(deduped)[date(2024, 4, 1)] is True
    assert energy_usable(deduped) == []
    assert quality.valid == 0
    assert quality.excluded_invalid_flag == 2


def test_generation_curve_trains_only_on_non_restricted_intervals() -> None:
    unrestricted = [
        interval(hour=hour, restricted=False, accepted=10.0, weather=5.0) for hour in range(6)
    ]
    restricted = [
        interval(hour=hour, restricted=True, accepted=0.0, weather=5.0) for hour in range(6)
    ]

    curve_a = fit_generation_curve(normalize_intervals(unrestricted)[0])
    curve_b = fit_generation_curve(normalize_intervals(unrestricted + restricted)[0])

    assert curve_a.potential(5.0) == pytest.approx(10.0)
    assert curve_b.potential(5.0) == pytest.approx(curve_a.potential(5.0))


def test_potential_is_monotone_in_weather_and_non_negative() -> None:
    unrestricted, _ = normalize_intervals(
        [
            interval(hour=0, accepted=0.0, weather=0.0),
            interval(hour=1, accepted=10.0, weather=5.0),
            interval(hour=2, accepted=30.0, weather=10.0),
        ]
    )
    curve = fit_generation_curve(unrestricted)

    assert curve.potential(0.0) == pytest.approx(0.0)
    assert curve.potential(5.0) == pytest.approx(10.0)
    assert curve.potential(10.0) == pytest.approx(30.0)
    assert curve.potential(-5.0) >= 0.0
    assert curve.potential(5.0) <= curve.potential(10.0)


def test_raw_loss_uses_the_curve_and_only_restricted_intervals() -> None:
    intervals, _ = normalize_intervals(
        [
            interval(hour=0, accepted=10.0, weather=5.0, restricted=True),
            interval(hour=1, accepted=10.0, weather=5.0, restricted=False),
            interval(hour=2, accepted=10.0, weather=5.0, restricted=False),
        ]
    )
    curve = fit_generation_curve([item for item in intervals if not item.restricted])
    proxy = plant_daily_proxy(intervals, curve, capacity_mw=50.0)

    # The curve is potential(5)=10 and the restricted interval already generated 10, so the
    # loss is zero; the non-restricted intervals never contribute to the loss.
    assert proxy[date(2024, 4, 1)].restricted is True
    assert proxy[date(2024, 4, 1)].raw_loss_mwh == pytest.approx(0.0)


def test_raw_loss_is_positive_when_generation_is_below_the_curve() -> None:
    intervals, _ = normalize_intervals(
        [
            interval(hour=0, accepted=10.0, weather=5.0, restricted=False),
            interval(hour=1, accepted=10.0, weather=5.0, restricted=False),
            interval(hour=2, accepted=2.0, weather=5.0, restricted=True),
            interval(hour=3, accepted=0.0, weather=5.0, restricted=True),
        ]
    )
    curve = fit_generation_curve([item for item in intervals if not item.restricted])
    proxy = plant_daily_proxy(intervals, curve, capacity_mw=50.0)

    # potential(5)=10; restricted accepted 2 and 0 -> (8 + 10) * 0.5 = 9.0 MWh
    assert proxy[date(2024, 4, 1)].raw_loss_mwh == pytest.approx(9.0)


def test_weights_follow_individual_potential_loss() -> None:
    entries = [
        PlantDayProxy("A", True, 10.0, 30.0),
        PlantDayProxy("B", True, 10.0, 10.0),
    ]
    result = allocate_group_curtailment(40.0, entries)

    assert result.method == METHOD_POTENTIAL_LOSS
    assert result.allocated_mwh["A"] == pytest.approx(30.0)
    assert result.allocated_mwh["B"] == pytest.approx(10.0)
    assert result.residual_mwh == pytest.approx(0.0, abs=CONSERVATION_TOLERANCE_MWH)


def test_capacity_fallback_applies_only_among_restricted_plants() -> None:
    entries = [
        PlantDayProxy("A", True, 10.0, 0.0),
        PlantDayProxy("B", True, 30.0, 0.0),
        PlantDayProxy("C", False, 100.0, 0.0),
    ]
    result = allocate_group_curtailment(40.0, entries)

    assert result.method == METHOD_CAPACITY_FALLBACK
    assert result.allocated_mwh["A"] == pytest.approx(10.0)
    assert result.allocated_mwh["B"] == pytest.approx(30.0)
    assert result.allocated_mwh.get("C") is None


def test_positive_group_total_without_indication_is_unreconciled() -> None:
    entries = [PlantDayProxy("A", False, 10.0, 0.0)]
    result = allocate_group_curtailment(40.0, entries)

    assert result.method == METHOD_UNALLOCATED
    assert result.allocated_mwh == {}
    with pytest.raises(UnreconciledGroupTotalError):
        reconcile_group_day(40.0, result)


def test_zero_group_total_is_not_an_error() -> None:
    entries = [PlantDayProxy("A", False, 10.0, 0.0)]
    result = allocate_group_curtailment(0.0, entries)

    assert result.method == METHOD_NO_CURTAILMENT
    reconcile_group_day(0.0, result)
    assert result.residual_mwh == pytest.approx(0.0)


def test_group_history_conserves_the_public_total() -> None:
    plant_a = PlantSeries(
        plant_id="A",
        name="A",
        group_id="CJU_TEST",
        capacity_mw=30.0,
        intervals=tuple(
            [
                interval(plant_id="A", hour=hour, accepted=10.0, weather=5.0, restricted=False)
                for hour in range(4)
            ]
            + [
                interval(plant_id="A", hour=hour, accepted=2.0, weather=5.0, restricted=True)
                for hour in range(4, 8)
            ]
        ),
    )
    plant_b = PlantSeries(
        plant_id="B",
        name="B",
        group_id="CJU_TEST",
        capacity_mw=20.0,
        intervals=tuple(
            [
                interval(plant_id="B", hour=hour, accepted=10.0, weather=5.0, restricted=False)
                for hour in range(4)
            ]
            + [
                interval(plant_id="B", hour=hour, accepted=5.0, weather=5.0, restricted=True)
                for hour in range(4, 8)
            ]
        ),
    )
    history = build_group_history(
        group_id="CJU_TEST",
        plants=(plant_a, plant_b),
        group_public_by_day={date(2024, 4, 1): 20.0},
    )

    allocated = [
        row.allocated_mwh
        for rows in history.rows_by_plant.values()
        for row in rows
        if row.allocated_mwh is not None
    ]
    assert abs(sum(allocated) - 20.0) <= CONSERVATION_TOLERANCE_MWH
    assert history.max_residual_mwh <= CONSERVATION_TOLERANCE_MWH
    assert history.allocation_coverage_pct == pytest.approx(100.0)
    # A's proxy loss is (8+8+8+8)*0.5 = 16, B's is (5+5+5+5)*0.5 = 10.
    assert history.rows_by_plant["A"][0].allocated_mwh == pytest.approx(20.0 * 16.0 / 26.0)
    assert history.rows_by_plant["B"][0].allocated_mwh == pytest.approx(20.0 * 10.0 / 26.0)


def test_non_restricted_plant_receives_no_energy() -> None:
    plant_a = PlantSeries(
        plant_id="A",
        name="A",
        group_id="CJU_TEST",
        capacity_mw=30.0,
        intervals=tuple(
            interval(plant_id="A", hour=hour, accepted=2.0, weather=5.0, restricted=True)
            for hour in range(4)
        ),
    )
    plant_b = PlantSeries(
        plant_id="B",
        name="B",
        group_id="CJU_TEST",
        capacity_mw=30.0,
        intervals=tuple(
            interval(plant_id="B", hour=hour, accepted=10.0, weather=5.0, restricted=False)
            for hour in range(4)
        ),
    )
    history = build_group_history(
        group_id="CJU_TEST",
        plants=(plant_a, plant_b),
        group_public_by_day={date(2024, 4, 1): 12.0},
    )

    assert history.rows_by_plant["B"][0].allocated_mwh == pytest.approx(0.0)
    assert history.rows_by_plant["A"][0].allocated_mwh == pytest.approx(12.0)


def test_point_context_derives_group_totals_without_double_counting() -> None:
    context = build_point_context(
        point_id="POINT-1",
        group_totals_mwh={"CJU_TEST": 12.0, "CJU_TEST2": 8.0},
        plant_ids_by_group={"CJU_TEST": ("A", "B"), "CJU_TEST2": ("C",)},
        selected_asset_ids=("A",),
    )

    assert context["point_public_mwh"] == pytest.approx(20.0)
    assert context["group_public_mwh"] == {"CJU_TEST": 12.0, "CJU_TEST2": 8.0}
    assert context["point_public_mwh"] == pytest.approx(sum(context["group_public_mwh"].values()))
    assert context["entity_count"] == 3
    assert context["entities"] == ["A", "B", "C"]
    assert context["entity_level"] == "plant"
    assert context["origin"] == "PROXY_CALCULADO"
    assert context["selected_asset_ids"] == ["A"]
    assert context["plant_count_by_group"] == {"CJU_TEST": 2, "CJU_TEST2": 1}


def test_point_contexts_keep_points_separate_and_count_each_group_once() -> None:
    contexts = build_point_contexts(
        point_group_ids={"POINT-1": ("CJU_TEST",), "POINT-2": ("CJU_TEST2",)},
        group_totals_mwh={"CJU_TEST": 12.0, "CJU_TEST2": 8.0},
        plant_ids_by_group={"CJU_TEST": ("A",), "CJU_TEST2": ("B",)},
        selected_by_group={"CJU_TEST": "A", "CJU_TEST2": "B"},
    )

    # The five selected plants belong to five different points, so no total may be mixed.
    assert set(contexts) == {"POINT-1", "POINT-2"}
    assert contexts["POINT-1"]["entities"] == ["A"]
    assert contexts["POINT-1"]["point_public_mwh"] == pytest.approx(12.0)
    assert contexts["POINT-2"]["entities"] == ["B"]
    assert contexts["POINT-2"]["point_public_mwh"] == pytest.approx(8.0)
    assert contexts["POINT-1"]["group_ids"] == ["CJU_TEST"]
    assert contexts["POINT-2"]["group_ids"] == ["CJU_TEST2"]
    assert sum(context["point_public_mwh"] for context in contexts.values()) == pytest.approx(20.0)


def test_point_contexts_reject_group_entities_and_repeated_groups() -> None:
    with pytest.raises(UnreconciledGroupTotalError):
        build_point_context(
            point_id="POINT-1",
            group_totals_mwh={"CJU_TEST": 1.0},
            plant_ids_by_group={"CJU_TEST": ("CJU_TEST",)},
        )

    with pytest.raises(UnreconciledGroupTotalError):
        build_point_contexts(
            point_group_ids={"POINT-1": ("CJU_TEST",), "POINT-2": ("CJU_TEST",)},
            group_totals_mwh={"CJU_TEST": 1.0},
            plant_ids_by_group={"CJU_TEST": ("A",)},
            selected_by_group={"CJU_TEST": "A"},
        )


def test_point_context_counts_a_shared_plant_link_only_once() -> None:
    context = build_point_context(
        point_id="POINT-1",
        group_totals_mwh={"CJU_TEST": 1.0, "CJU_TEST2": 2.0},
        plant_ids_by_group={"CJU_TEST": ("A",), "CJU_TEST2": ("A", "B")},
    )

    assert context["entities"] == ["A", "B"]
    assert context["entity_count"] == 2
    assert context["duplicate_plant_links"] == ["A"]


@pytest.mark.skipif(not BUNDLED.exists(), reason="plant history not materialized yet")
def test_bundled_history_has_five_reconciled_plant_series() -> None:
    history = load_bundled_history(BUNDLED)

    plants = history["plants"]
    assert len(plants) == 5
    assert all(not plant["asset_id"].startswith("CJU_") for plant in plants)
    for plant in plants:
        assert plant["entity_level"] == "plant"
        assert plant["origin"] == "PROXY_CALCULADO"
        assert plant["allocation_coverage_pct"] == pytest.approx(100.0)
        assert plant["max_reconciliation_residual_mwh"] <= CONSERVATION_TOLERANCE_MWH
        assert len(plant["series"]) == plant["calendar_days"]
        assert plant["total_curtailed_mwh"] >= 0.0
        days = [row["date"] for row in plant["series"]]
        assert days == sorted(set(days))
    assert history["conservation"]["max_residual_mwh"] <= CONSERVATION_TOLERANCE_MWH
    contexts = history["point_contexts"]
    assert len(contexts) == 5
    assert history["point_coverage"]["point_count"] == 5
    assert history["point_coverage"]["point_public_mwh"] == pytest.approx(
        sum(context["point_public_mwh"] for context in contexts.values())
    )
    # Each selected plant belongs to its own connection point: no two plants share one.
    assert {plant["connection_point"] for plant in plants} == set(contexts)
    for plant in plants:
        context = contexts[plant["connection_point"]]
        assert plant["asset_id"] in context["entities"]
        assert plant["asset_id"] in context["selected_asset_ids"]
        assert context["entity_level"] == "plant"
        assert context["entity_count"] == len(context["entities"])
        assert context["group_count"] == len(context["group_ids"])
        assert all(not entity.startswith("CJU_") for entity in context["entities"])
        assert context["point_public_mwh"] == pytest.approx(
            sum(context["group_public_mwh"].values())
        )
        assert set(context["group_public_mwh"]) == set(context["group_ids"])
        assert plant["point_entity_count"] == context["entity_count"]
        assert plant["point_public_mwh"] == context["point_public_mwh"]
    # No group is counted in two points and no total is the sum of five mixed groups.
    all_groups = [group for context in contexts.values() for group in context["group_ids"]]
    assert len(all_groups) == len(set(all_groups))
    selected_groups = {plant["ons_group_id"] for plant in plants}
    assert len(selected_groups) == 5
    for context in contexts.values():
        assert len(set(context["group_ids"]) & selected_groups) <= 1

    with BUNDLED.open(encoding="utf-8") as stream:
        raw = json.load(stream)
    assert raw["schema"] == "curtailless.individual_plant_history.v1"
    assert raw["calculation"] == "PROXY_CALCULADO"
    assert "point_context" not in raw
