"""Focused tests for the individual plant cohort materialization (plan Task 1)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from build_individual_plant_cohort import (  # noqa: E402
    CONTEXTS,
    CapacityRecord,
    CohortError,
    Context,
    DetailCoverage,
    RelationshipRecord,
    build_catalog,
    classify_candidates,
    load_bundled_catalog,
    select_cohort,
    validate_catalog,
)

BUNDLED = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "curtailess"
    / "data"
    / "individual_plant_catalog.json"
)


def context(group_id: str) -> Context:
    return next(item for item in CONTEXTS if item.group_id == group_id)


def relationship(
    plant_id: str,
    group_id: str,
    *,
    name: str = "Usina",
    ceg: str = "EOL.CV.RN.000000-0.01",
    technology: str = "Eolielétrica",
    state: str = "RN",
    valid_from: str = "2021-01-01",
    valid_to: str | None = None,
) -> RelationshipRecord:
    return RelationshipRecord(
        plant_id=plant_id,
        group_id=group_id,
        plant_name=name,
        group_name="Conj. Contexto",
        ceg=ceg,
        technology_name=technology,
        state=state,
        valid_from=valid_from,
        valid_to=valid_to,
    )


def capacity(
    ceg: str,
    *,
    capacity_mw: float = 30.0,
    unit_count: int = 2,
    valued_unit_count: int | None = None,
    active: bool = True,
    plant_name: str = "Usina",
    technology: str = "Eolielétrica",
) -> CapacityRecord:
    return CapacityRecord(
        ceg=ceg,
        plant_name=plant_name,
        technology_name=technology,
        unit_count=unit_count,
        valued_unit_count=unit_count if valued_unit_count is None else valued_unit_count,
        capacity_mw=capacity_mw,
        valid_from="2021-01-01",
        active=active,
    )


def coverage(
    plant_id: str,
    group_id: str,
    *,
    observed_days: int = 900,
    restricted_days: int = 500,
    weather_interval_count: int = 43200,
    interval_count: int = 43200,
) -> DetailCoverage:
    return DetailCoverage(
        plant_id=plant_id,
        group_id=group_id,
        interval_count=interval_count,
        observed_days=observed_days,
        restricted_days=restricted_days,
        weather_interval_count=weather_interval_count,
        first_observed_at="2024-04-01T00:00:00",
        last_observed_at="2026-09-25T23:30:00",
    )


def test_rejects_group_identifiers_as_selectable_plants() -> None:
    ctx = context("CJU_RNRDV")
    candidates = classify_candidates(
        contexts=(ctx,),
        relationships=[relationship("CJU_RNRDV", "CJU_RNRDV")],
        capacities={},
        coverage={},
        window_days=900,
    )
    with pytest.raises(CohortError, match="CJU_"):
        select_cohort(candidates, contexts=(ctx,))


def test_requires_mandatory_fields_on_every_selected_plant() -> None:
    ctx = context("CJU_RNRDV")
    candidates = classify_candidates(
        contexts=(ctx,),
        relationships=[relationship("RNEM13", "CJU_RNRDV", name="Ventos de Santa Martina 13")],
        capacities={"EOL.CV.RN.000000-0.01": capacity("EOL.CV.RN.000000-0.01", capacity_mw=0.0)},
        coverage={"RNEM13": coverage("RNEM13", "CJU_RNRDV")},
        window_days=900,
    )
    with pytest.raises(CohortError, match="capacidade"):
        select_cohort(candidates, contexts=(ctx,))


def test_ambiguous_link_is_not_selectable() -> None:
    ctx = context("CJU_RNRDV")
    relationships = [
        relationship("RNEM13", "CJU_RNRDV"),
        relationship("RNEM13", "CJU_RNRVE"),
    ]
    candidates = classify_candidates(
        contexts=(ctx,),
        relationships=relationships,
        capacities={"EOL.CV.RN.000000-0.01": capacity("EOL.CV.RN.000000-0.01")},
        coverage={"RNEM13": coverage("RNEM13", "CJU_RNRDV")},
        window_days=900,
    )
    assert candidates[ctx.group_id][0].link_status == "ambiguous"
    with pytest.raises(CohortError, match="ambígu"):
        select_cohort(candidates, contexts=(ctx,))


def test_inactive_link_is_not_selectable() -> None:
    ctx = context("CJU_RNRDV")
    candidates = classify_candidates(
        contexts=(ctx,),
        relationships=[relationship("RNEM13", "CJU_RNRDV", valid_to="2024-01-01")],
        capacities={"EOL.CV.RN.000000-0.01": capacity("EOL.CV.RN.000000-0.01")},
        coverage={"RNEM13": coverage("RNEM13", "CJU_RNRDV")},
        window_days=900,
    )
    assert candidates[ctx.group_id][0].link_status == "inactive"
    with pytest.raises(CohortError, match="vigente"):
        select_cohort(candidates, contexts=(ctx,))


def test_selection_prefers_coverage_then_weather_then_capacity() -> None:
    ctx = context("CJU_RNRDV")
    candidates = classify_candidates(
        contexts=(ctx,),
        relationships=[
            relationship("RNEMA", "CJU_RNRDV", name="A", ceg="CEG-A"),
            relationship("RNEMB", "CJU_RNRDV", name="B", ceg="CEG-B"),
            relationship("RNEMC", "CJU_RNRDV", name="C", ceg="CEG-C"),
        ],
        capacities={
            "CEG-A": capacity("CEG-A", capacity_mw=99.0),
            "CEG-B": capacity("CEG-B", capacity_mw=50.0),
            "CEG-C": capacity("CEG-C", capacity_mw=10.0),
        },
        coverage={
            "RNEMA": coverage(
                "RNEMA", "CJU_RNRDV", observed_days=900, weather_interval_count=43200
            ),
            "RNEMB": coverage(
                "RNEMB", "CJU_RNRDV", observed_days=700, weather_interval_count=43200
            ),
            "RNEMC": coverage(
                "RNEMC", "CJU_RNRDV", observed_days=900, weather_interval_count=21600
            ),
        },
        window_days=900,
    )
    selected = select_cohort(candidates, contexts=(ctx,))
    assert [plant["asset_id"] for plant in selected] == ["RNEMA"]


def test_capacity_breaks_a_coverage_and_weather_tie() -> None:
    ctx = context("CJU_RNRDV")
    candidates = classify_candidates(
        contexts=(ctx,),
        relationships=[
            relationship("RNEMA", "CJU_RNRDV", name="A", ceg="CEG-A"),
            relationship("RNEMB", "CJU_RNRDV", name="B", ceg="CEG-B"),
        ],
        capacities={
            "CEG-A": capacity("CEG-A", capacity_mw=10.0),
            "CEG-B": capacity("CEG-B", capacity_mw=80.0),
        },
        coverage={
            "RNEMA": coverage("RNEMA", "CJU_RNRDV"),
            "RNEMB": coverage("RNEMB", "CJU_RNRDV"),
        },
        window_days=900,
    )
    selected = select_cohort(candidates, contexts=(ctx,))
    assert [plant["asset_id"] for plant in selected] == ["RNEMB"]


def test_missing_context_candidate_fails_instead_of_inventing() -> None:
    wind = context("CJU_RNRDV")
    solar = context("CJU_RNMVS")
    candidates = classify_candidates(
        contexts=(wind, solar),
        relationships=[relationship("RNEM13", "CJU_RNRDV")],
        capacities={"EOL.CV.RN.000000-0.01": capacity("EOL.CV.RN.000000-0.01")},
        coverage={"RNEM13": coverage("RNEM13", "CJU_RNRDV")},
        window_days=900,
    )
    with pytest.raises(CohortError, match="Monte Verde Solar"):
        select_cohort(candidates, contexts=(wind, solar))


def test_catalog_holds_exactly_five_plants_one_per_context() -> None:
    contexts = CONTEXTS
    relationships: list[RelationshipRecord] = []
    capacities: dict[str, CapacityRecord] = {}
    detail: dict[str, DetailCoverage] = {}
    for index, ctx in enumerate(contexts):
        plant_id = f"PLANT{index}"
        ceg = f"CEG-{index}"
        relationships.append(
            relationship(
                plant_id,
                ctx.group_id,
                name=f"Usina {index}",
                ceg=ceg,
                technology="Fotovoltaica" if ctx.technology == "solar" else "Eolielétrica",
            )
        )
        capacities[ceg] = capacity(ceg, capacity_mw=10.0 + index)
        detail[plant_id] = coverage(plant_id, ctx.group_id)

    candidates = classify_candidates(
        contexts=contexts,
        relationships=relationships,
        capacities=capacities,
        coverage=detail,
        window_days=900,
    )
    selected = select_cohort(candidates, contexts=contexts)
    catalog = build_catalog(
        contexts=contexts,
        selected=selected,
        window_start="2024-04-01",
        window_end="2026-09-25",
        group_points={ctx.group_id: f"POINT-{ctx.group_id}" for ctx in contexts},
    )

    validate_catalog(catalog)
    assert len(catalog["plants"]) == 5
    assert {plant["ons_group_id"] for plant in catalog["plants"]} == {
        ctx.group_id for ctx in contexts
    }
    assert all(not plant["asset_id"].startswith("CJU_") for plant in catalog["plants"])
    assert {plant["entity_level"] for plant in catalog["plants"]} == {"plant"}


def test_catalog_validation_rejects_group_entity() -> None:
    catalog = {
        "schema": "curtailless.individual_plant_catalog.v1",
        "plants": [
            {
                "asset_id": "CJU_RNRDV",
                "name": "Rio do Vento",
                "entity_level": "plant",
                "ons_group_id": "CJU_RNRDV",
                "ons_group_name": "Rio do Vento",
                "connection_point": "RNCMM-500-A",
                "technology": "wind",
                "state": "RN",
                "capacity_mw": 100.0,
                "ceg": "CEG",
                "valid_from": "2021-01-01",
                "valid_to": None,
                "operational_data_status": "simulated",
            }
        ],
    }
    with pytest.raises(CohortError, match="CJU_"):
        validate_catalog(catalog)


@pytest.mark.skipif(not BUNDLED.exists(), reason="cohort catalog not materialized yet")
def test_bundled_catalog_is_a_verified_five_plant_cohort() -> None:
    catalog = load_bundled_catalog(BUNDLED)
    validate_catalog(catalog)

    plants = catalog["plants"]
    assert len(plants) == 5
    assert [plant["ons_group_id"] for plant in plants] == [ctx.group_id for ctx in CONTEXTS]
    assert all(not plant["asset_id"].startswith("CJU_") for plant in plants)
    for plant in plants:
        assert plant["entity_level"] == "plant"
        assert plant["asset_id"] and plant["name"]
        assert plant["ceg"].startswith(("EOL.", "UFV."))
        assert plant["capacity_mw"] > 0
        assert plant["connection_point"]
        assert plant["state"]
        assert plant["valid_to"] is None
        assert plant["selection"]["coverage_pct"] > 0

    with BUNDLED.open(encoding="utf-8") as stream:
        raw = json.load(stream)
    assert raw["schema"] == "curtailless.individual_plant_catalog.v1"
    assert len(raw["candidate_report"]["contexts"]) == 5
