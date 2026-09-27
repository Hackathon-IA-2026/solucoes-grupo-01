#!/usr/bin/env python3
"""Materialize the individual plant cohort used by the Exposure screen.

The tool proves, from public ONS datasets, which individual plants belong to the five
current group contexts (Rio do Vento, Laranjeiras, Serra da Babilônia, Monte Verde Solar
and Luzia) and writes exactly one verified individual plant per context.

Inputs are explicit public ONS artifacts:

* ``restricao_coff_eolica_detail_tm`` / ``restricao_coff_fotovoltaica_detail_tm`` — the
  half-hour per-plant detail base (restriction flag, generation and weather variables);
* ``usina_conjunto`` — the plant/group cadastral relationship with its validity window;
* ``capacidade-geracao`` — the registered effective capacity per generating unit;
* ``restricao_coff_eolica_tm`` / ``restricao_coff_fotovoltaica_tm`` — the aggregate base,
  read only to recover the published connection point of each group.

No identifier or name is invented. A context without a verifiable individual plant fails
with a candidate report instead of publishing a fabricated plant.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

SCHEMA = "curtailless.individual_plant_catalog.v1"
GROUP_ENTITY_PREFIX = "CJU_"
SOURCE_STATUS = "ONS_PUBLICO"
OPERATIONAL_DATA_STATUS = "simulated"
DEFAULT_WINDOW_START = date(2024, 4, 1)
DEFAULT_WINDOW_END = date(2026, 9, 25)

WIND_TECHNOLOGY_NAMES = frozenset({"eolielétrica", "eolica", "eólica"})
SOLAR_TECHNOLOGY_NAMES = frozenset({"fotovoltaica"})


class CohortError(RuntimeError):
    """Raised when the cohort cannot be proven from the public data."""


@dataclass(frozen=True)
class Context:
    """One current Exposure context: a group entity plus its expected technology."""

    group_id: str
    group_name: str
    technology: str


CONTEXTS: tuple[Context, ...] = (
    Context("CJU_RNRDV", "Rio do Vento", "wind"),
    Context("CJU_BALRA", "Laranjeiras", "wind"),
    Context("CJU_BASDB", "Serra da Babilônia", "wind"),
    Context("CJU_RNMVS", "Monte Verde Solar", "solar"),
    Context("CJU_PBLZA", "Luzia", "solar"),
)

LINK_UNAMBIGUOUS = "unambiguous_active"
LINK_AMBIGUOUS = "ambiguous"
LINK_INACTIVE = "inactive"
LINK_GROUP_ENTITY = "group_entity"


def normalize_technology(name: str) -> str | None:
    token = (name or "").strip().casefold()
    if token in WIND_TECHNOLOGY_NAMES or "eoli" in token:
        return "wind"
    if token in SOLAR_TECHNOLOGY_NAMES or "fotovolt" in token or "solar" in token:
        return "solar"
    return None


@dataclass(frozen=True)
class RelationshipRecord:
    """One plant/group cadastral link from ``usina_conjunto``."""

    plant_id: str
    group_id: str
    plant_name: str
    group_name: str
    ceg: str
    technology_name: str
    state: str
    valid_from: str | None
    valid_to: str | None

    @property
    def active(self) -> bool:
        return not (self.valid_to or "").strip()

    @property
    def technology(self) -> str | None:
        return normalize_technology(self.technology_name)


@dataclass(frozen=True)
class CapacityRecord:
    """Registered effective capacity for one plant CEG from ``capacidade-geracao``."""

    ceg: str
    plant_name: str
    technology_name: str
    unit_count: int
    valued_unit_count: int
    capacity_mw: float
    valid_from: str | None
    active: bool

    @property
    def complete(self) -> bool:
        return (
            self.active
            and self.unit_count > 0
            and self.valued_unit_count == self.unit_count
            and self.capacity_mw > 0
        )


@dataclass(frozen=True)
class DetailCoverage:
    """Historical coverage of one plant inside the detailed half-hour base."""

    plant_id: str
    group_id: str
    interval_count: int
    observed_days: int
    restricted_days: int
    weather_interval_count: int
    first_observed_at: str | None
    last_observed_at: str | None


@dataclass(frozen=True)
class Candidate:
    """A ranked candidate plant for one context."""

    context: Context
    plant_id: str
    name: str
    ceg: str
    technology: str | None
    state: str
    valid_from: str | None
    valid_to: str | None
    capacity_mw: float
    capacity_units: int
    capacity_complete: bool
    link_status: str
    coverage_pct: float
    observed_days: int
    restricted_day_share_pct: float
    weather_coverage_pct: float

    @property
    def eligible(self) -> bool:
        return (
            self.link_status == LINK_UNAMBIGUOUS
            and self.capacity_complete
            and self.observed_days > 0
            and bool(self.ceg)
            and self.technology == self.context.technology
        )

    def rank(self) -> tuple[Any, ...]:
        """Plan priority order, then a documented deterministic tie-break."""
        return (
            0 if self.link_status == LINK_UNAMBIGUOUS else 1,
            -self.coverage_pct,
            -self.weather_coverage_pct,
            0 if self.capacity_complete else 1,
            -self.capacity_mw,
            self.valid_from or "9999-12-31",
            self.plant_id,
        )


def _window_days(window_days: int | None) -> int:
    if window_days is None or window_days <= 0:
        raise ValueError("window_days must be a positive integer")
    return window_days


def _link_status(plant_id: str, relationships: Sequence[RelationshipRecord]) -> str:
    if plant_id.startswith(GROUP_ENTITY_PREFIX):
        return LINK_GROUP_ENTITY
    active_groups = {
        record.group_id
        for record in relationships
        if record.plant_id.strip() == plant_id and record.active
    }
    if not active_groups:
        return LINK_INACTIVE
    if len(active_groups) > 1:
        return LINK_AMBIGUOUS
    return LINK_UNAMBIGUOUS


def classify_candidates(
    *,
    contexts: Sequence[Context],
    relationships: Sequence[RelationshipRecord],
    capacities: Mapping[str, CapacityRecord],
    coverage: Mapping[str, DetailCoverage],
    window_days: int | None,
) -> dict[str, list[Candidate]]:
    """Rank every plant linked to each context, recording why each one is eligible."""
    window = _window_days(window_days)
    result: dict[str, list[Candidate]] = {}
    for ctx in contexts:
        rows: list[Candidate] = []
        for record in relationships:
            if record.group_id != ctx.group_id:
                continue
            plant_id = record.plant_id.strip()
            capacity = capacities.get(record.ceg.strip())
            detail = coverage.get(plant_id)
            observed_days = detail.observed_days if detail else 0
            restricted_days = detail.restricted_days if detail else 0
            weather_pct = (
                round(100.0 * detail.weather_interval_count / detail.interval_count, 4)
                if detail and detail.interval_count > 0
                else 0.0
            )
            rows.append(
                Candidate(
                    context=ctx,
                    plant_id=plant_id,
                    name=record.plant_name.strip(),
                    ceg=record.ceg.strip(),
                    technology=record.technology,
                    state=record.state.strip(),
                    valid_from=record.valid_from,
                    valid_to=record.valid_to,
                    capacity_mw=round(capacity.capacity_mw, 6) if capacity else 0.0,
                    capacity_units=capacity.unit_count if capacity else 0,
                    capacity_complete=bool(capacity and capacity.complete),
                    link_status=_link_status(plant_id, relationships),
                    coverage_pct=round(100.0 * observed_days / window, 4),
                    observed_days=observed_days,
                    restricted_day_share_pct=(
                        round(100.0 * restricted_days / observed_days, 4) if observed_days else 0.0
                    ),
                    weather_coverage_pct=weather_pct,
                )
            )
        rows.sort(key=lambda candidate: candidate.rank())
        result[ctx.group_id] = rows
    return result


def _context_failure_reason(rows: Sequence[Candidate]) -> str:
    if not rows:
        return "sem usina individual vinculada na base cadastral"
    if any(row.link_status == LINK_GROUP_ENTITY for row in rows):
        return "apenas conjuntos (CJU_) vinculados; nenhuma usina individual"
    eligible_links = [row for row in rows if row.link_status == LINK_UNAMBIGUOUS]
    if not eligible_links:
        return "vínculo cadastral ambíguo ou não vigente"
    with_capacity = [row for row in eligible_links if row.capacity_complete]
    if not with_capacity:
        return "sem capacidade cadastrada completa"
    with_technology = [row for row in with_capacity if row.technology == row.context.technology]
    if not with_technology:
        return "tecnologia da usina diverge do contexto"
    return "sem cobertura histórica na base detalhada"


def select_cohort(
    candidates: Mapping[str, Sequence[Candidate]],
    *,
    contexts: Sequence[Context],
) -> list[dict[str, Any]]:
    """Select exactly one eligible plant per context, failing instead of inventing."""
    selected: list[dict[str, Any]] = []
    for ctx in contexts:
        rows = list(candidates.get(ctx.group_id, ()))
        eligible = [row for row in rows if row.eligible]
        if not eligible:
            reason = _context_failure_reason(rows)
            raise CohortError(f"contexto {ctx.group_name} sem usina verificável: {reason}")
        winner = eligible[0]
        if winner.plant_id.startswith(GROUP_ENTITY_PREFIX):
            raise CohortError(f"identificador de conjunto {winner.plant_id} não é selecionável")
        selected.append(
            {
                "asset_id": winner.plant_id,
                "name": winner.name,
                "entity_level": "plant",
                "ons_group_id": ctx.group_id,
                "ons_group_name": ctx.group_name,
                "technology": winner.technology,
                "state": winner.state,
                "capacity_mw": winner.capacity_mw,
                "ceg": winner.ceg,
                "valid_from": winner.valid_from,
                "valid_to": winner.valid_to,
                "operational_data_status": OPERATIONAL_DATA_STATUS,
                "selection": {
                    "link_status": winner.link_status,
                    "candidate_count": len(rows),
                    "observed_days": winner.observed_days,
                    "coverage_pct": winner.coverage_pct,
                    "restricted_day_share_pct": winner.restricted_day_share_pct,
                    "weather_coverage_pct": winner.weather_coverage_pct,
                    "capacity_units": winner.capacity_units,
                    "capacity_complete": winner.capacity_complete,
                    "justification": (
                        "Selecionada por vínculo cadastral inequívoco e vigente, cobertura "
                        f"histórica de {winner.coverage_pct:.2f}% ({winner.observed_days} dias), "
                        f"variável meteorológica em {winner.weather_coverage_pct:.2f}% dos "
                        "intervalos e capacidade cadastrada completa "
                        f"({winner.capacity_mw:.4f} MW em {winner.capacity_units} unidades)."
                    ),
                },
            }
        )
    return selected


def build_catalog(
    *,
    contexts: Sequence[Context],
    selected: Sequence[Mapping[str, Any]],
    window_start: str,
    window_end: str,
    group_points: Mapping[str, str],
    candidates: Mapping[str, Sequence[Candidate]] | None = None,
) -> dict[str, Any]:
    """Assemble the catalog artifact, attaching the published connection point per group."""
    plants: list[dict[str, Any]] = []
    for plant in selected:
        group_id = str(plant["ons_group_id"])
        point = group_points.get(group_id)
        if not point:
            raise CohortError(f"ponto de conexão público ausente para o conjunto {group_id}")
        enriched = dict(plant)
        enriched["connection_point"] = point
        plants.append(enriched)

    report_contexts = []
    for ctx in contexts:
        rows = list((candidates or {}).get(ctx.group_id, ()))
        report_contexts.append(
            {
                "group_id": ctx.group_id,
                "group_name": ctx.group_name,
                "technology": ctx.technology,
                "candidate_count": len(rows),
                "candidates": [
                    {
                        "plant_id": row.plant_id,
                        "name": row.name,
                        "ceg": row.ceg,
                        "link_status": row.link_status,
                        "capacity_mw": row.capacity_mw,
                        "capacity_complete": row.capacity_complete,
                        "coverage_pct": row.coverage_pct,
                        "weather_coverage_pct": row.weather_coverage_pct,
                        "eligible": row.eligible,
                    }
                    for row in rows
                ],
            }
        )

    return {
        "schema": SCHEMA,
        "source": SOURCE_STATUS,
        "entity_level": "plant",
        "window": {"start": window_start, "end": window_end},
        "limitations": [
            "Cada usina é uma entidade individual verificada no cadastro público do ONS; "
            "nenhum conjunto gerador (CJU_) é selecionável.",
            "A capacidade é a soma da potência efetiva cadastrada das unidades geradoras ativas.",
            "A cobertura histórica é contada na base detalhada de meia hora no período informado.",
            "O ponto de conexão é o publicado no nível do conjunto, não uma medida por usina.",
        ],
        "plants": plants,
        "candidate_report": {"contexts": report_contexts},
    }


def validate_catalog(catalog: Mapping[str, Any]) -> None:
    """Enforce the plan contract for the cohort catalog."""
    if catalog.get("schema") != SCHEMA:
        raise CohortError("schema de catálogo de usinas individuais não suportado")
    plants = catalog.get("plants")
    if not isinstance(plants, list):
        raise CohortError("o catálogo precisa de uma lista de usinas")
    for plant in plants:
        asset_id = str(plant.get("asset_id", ""))
        if asset_id.startswith(GROUP_ENTITY_PREFIX):
            raise CohortError(f"identificador de conjunto {asset_id} não é uma usina individual")
    if len(plants) != len(CONTEXTS):
        raise CohortError("o catálogo deve conter exatamente cinco usinas individuais")
    group_ids = [plant.get("ons_group_id") for plant in plants]
    expected = [ctx.group_id for ctx in CONTEXTS]
    if group_ids != expected:
        raise CohortError("cada contexto deve contribuir com exatamente uma usina individual")
    required = (
        "asset_id",
        "name",
        "entity_level",
        "ons_group_id",
        "ons_group_name",
        "connection_point",
        "technology",
        "state",
        "capacity_mw",
        "ceg",
        "operational_data_status",
    )
    for plant in plants:
        asset_id = str(plant.get("asset_id", ""))
        if asset_id.startswith(GROUP_ENTITY_PREFIX):
            raise CohortError(f"identificador de conjunto {asset_id} não é uma usina individual")
        if not asset_id:
            raise CohortError("a usina selecionável precisa de um identificador individual")
        missing = [field for field in required if plant.get(field) in (None, "")]
        if missing:
            raise CohortError(f"usina {asset_id} sem campos obrigatórios: {missing}")
        if plant.get("entity_level") != "plant":
            raise CohortError(f"usina {asset_id} precisa ter entity_level 'plant'")
        if float(plant.get("capacity_mw") or 0) <= 0:
            raise CohortError(f"usina {asset_id} sem capacidade cadastrada positiva")
        if plant.get("valid_to") is not None:
            raise CohortError(f"usina {asset_id} sem vínculo vigente")
    technologies = {plant.get("technology") for plant in plants}
    if technologies != {"wind", "solar"}:
        raise CohortError("a coorte precisa conter usinas eólicas e solares")


def load_bundled_catalog(path: str | Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as stream:
        payload = json.load(stream)
    validate_catalog(payload)
    return payload


def _read_parquet(connection: duckdb.DuckDBPyConnection, path: str, query: str):
    target = path if any(char in path for char in "*?[") else str(Path(path))
    source = f"read_parquet('{target}', union_by_name=true)"
    return connection.execute(query.format(source=source)).fetchall()


def load_relationships(path: str) -> list[RelationshipRecord]:
    query = """
        SELECT DISTINCT
            trim(id_ons_usina),
            trim(id_ons_conjunto),
            trim(nom_usina),
            trim(nom_conjunto),
            trim(ceg),
            trim(nom_tipousina),
            trim(estad_id),
            nullif(trim(dat_iniciorelacionamento), ''),
            nullif(trim(dat_fimrelacionamento), '')
        FROM {source}
        WHERE nullif(trim(id_ons_usina), '') IS NOT NULL
        ORDER BY 1, 2
    """
    with duckdb.connect() as connection:
        rows = _read_parquet(connection, path, query)
    return [
        RelationshipRecord(
            plant_id=row[0],
            group_id=row[1],
            plant_name=row[2],
            group_name=row[3],
            ceg=row[4],
            technology_name=row[5],
            state=row[6],
            valid_from=row[7],
            valid_to=row[8],
        )
        for row in rows
    ]


def load_capacities(path: str) -> dict[str, CapacityRecord]:
    query = """
        SELECT
            trim(ceg),
            any_value(trim(nom_usina)),
            any_value(trim(nom_tipousina)),
            count(*),
            count(val_potenciaefetiva),
            round(coalesce(sum(val_potenciaefetiva), 0), 6),
            min(nullif(trim(coalesce(dat_entradaoperacao, dat_entradateste)), '')),
            bool_and(nullif(trim(dat_desativacao), '') IS NULL)
        FROM {source}
        WHERE nullif(trim(ceg), '') IS NOT NULL
          AND nullif(trim(ceg), '') <> '-'
        GROUP BY 1
        ORDER BY 1
    """
    with duckdb.connect() as connection:
        rows = _read_parquet(connection, path, query)
    return {
        row[0]: CapacityRecord(
            ceg=row[0],
            plant_name=row[1],
            technology_name=row[2],
            unit_count=int(row[3]),
            valued_unit_count=int(row[4]),
            capacity_mw=float(row[5]),
            valid_from=row[6],
            active=bool(row[7]),
        )
        for row in rows
    }


def load_detail_coverage(
    path: str,
    *,
    group_aliases: Mapping[str, str],
    weather_column: str,
    window_start: str,
    window_end: str,
) -> dict[str, DetailCoverage]:
    """Coverage per plant, recovering the group when the detail base omits the id.

    In part of 2024 the solar detail base leaves ``id_ons_conjuntousina`` null; the group is
    then recovered from ``nom_conjuntousina``. No link is inferred from a name alone unless
    that name was already proven by the cadastral relationship for a declared context.
    """
    group_case = " ".join(
        f"WHEN '{alias.strip().casefold()}' THEN '{gid}'"
        for alias, gid in sorted(group_aliases.items())
    )
    query = f"""
        SELECT
            trim(id_ons),
            group_id,
            count(*),
            count(DISTINCT din_instante::DATE),
            count(DISTINCT din_instante::DATE) FILTER (WHERE flg_geracaorestrita = 1),
            count(*) FILTER (WHERE weather_value IS NOT NULL),
            min(din_instante),
            max(din_instante)
        FROM (
            SELECT
                id_ons,
                din_instante,
                flg_geracaorestrita,
                {weather_column} AS weather_value,
                coalesce(
                    nullif(trim(id_ons_conjuntousina), ''),
                    CASE lower(trim(nom_conjuntousina)) {group_case} END
                ) AS group_id
            FROM {{source}}
            WHERE din_instante >= TIMESTAMP '{window_start} 00:00:00'
              AND din_instante <= TIMESTAMP '{window_end} 23:59:59'
        )
        WHERE group_id IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1
    """
    with duckdb.connect() as connection:
        rows = _read_parquet(connection, path, query)
    coverage: dict[str, DetailCoverage] = {}
    for row in rows:
        plant_id = row[0]
        if plant_id.startswith(GROUP_ENTITY_PREFIX):
            continue
        coverage[plant_id] = DetailCoverage(
            plant_id=plant_id,
            group_id=row[1],
            interval_count=int(row[2]),
            observed_days=int(row[3]),
            restricted_days=int(row[4]),
            weather_interval_count=int(row[5]),
            first_observed_at=row[6].isoformat() if row[6] else None,
            last_observed_at=row[7].isoformat() if row[7] else None,
        )
    return coverage


def load_group_points(paths: Sequence[str]) -> dict[str, str]:
    """Recover the published connection point of each group from the aggregate base."""
    points: dict[str, str] = {}
    query = """
        SELECT trim(id_ons), any_value(nullif(trim(id_pontoconexao), ''))
        FROM {source}
        WHERE trim(id_ons) LIKE 'CJU_%'
        GROUP BY 1
        ORDER BY 1
    """
    with duckdb.connect() as connection:
        for path in paths:
            for row in _read_parquet(connection, path, query):
                if row[1]:
                    points.setdefault(row[0], row[1])
    return points


def materialize(
    *,
    wind_detail: str,
    solar_detail: str,
    relationship: str,
    capacity: str,
    wind_aggregate: str,
    solar_aggregate: str,
    window_start: date = DEFAULT_WINDOW_START,
    window_end: date = DEFAULT_WINDOW_END,
) -> dict[str, Any]:
    window = (window_end - window_start).days + 1
    relationships = load_relationships(relationship)
    capacities = load_capacities(capacity)
    group_aliases: dict[str, str] = {}
    for ctx in CONTEXTS:
        names = {
            record.group_name
            for record in relationships
            if record.group_id == ctx.group_id and record.group_name
        }
        for name in names:
            group_aliases[name] = ctx.group_id
    coverage = load_detail_coverage(
        wind_detail,
        group_aliases=group_aliases,
        weather_column="val_ventoverificado",
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
    )
    coverage.update(
        load_detail_coverage(
            solar_detail,
            group_aliases=group_aliases,
            weather_column="val_irradianciaverificado",
            window_start=window_start.isoformat(),
            window_end=window_end.isoformat(),
        )
    )
    group_points = load_group_points([wind_aggregate, solar_aggregate])
    candidates = classify_candidates(
        contexts=CONTEXTS,
        relationships=relationships,
        capacities=capacities,
        coverage=coverage,
        window_days=window,
    )
    selected = select_cohort(candidates, contexts=CONTEXTS)
    return build_catalog(
        contexts=CONTEXTS,
        selected=selected,
        window_start=window_start.isoformat(),
        window_end=window_end.isoformat(),
        group_points=group_points,
        candidates=candidates,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materializa a coorte de cinco usinas individuais a partir das bases públicas "
            "detalhadas e cadastrais do ONS."
        )
    )
    parser.add_argument(
        "--wind-detail", required=True, help="glob/arquivo parquet do detalhamento eólico"
    )
    parser.add_argument(
        "--solar-detail", required=True, help="glob/arquivo parquet do detalhamento solar"
    )
    parser.add_argument("--relationship", required=True, help="parquet de usina_conjunto")
    parser.add_argument("--capacity", required=True, help="parquet de capacidade-geracao")
    parser.add_argument(
        "--wind-aggregate", required=True, help="glob/arquivo parquet da base agregada eólica"
    )
    parser.add_argument(
        "--solar-aggregate", required=True, help="glob/arquivo parquet da base agregada solar"
    )
    parser.add_argument("--window-start", default=DEFAULT_WINDOW_START.isoformat())
    parser.add_argument("--window-end", default=DEFAULT_WINDOW_END.isoformat())
    parser.add_argument("--output", required=True, help="caminho do catálogo JSON")
    parser.add_argument("--report", help="caminho opcional do relatório de candidatas")
    args = parser.parse_args(argv)

    catalog = materialize(
        wind_detail=args.wind_detail,
        solar_detail=args.solar_detail,
        relationship=args.relationship,
        capacity=args.capacity,
        wind_aggregate=args.wind_aggregate,
        solar_aggregate=args.solar_aggregate,
        window_start=date.fromisoformat(args.window_start),
        window_end=date.fromisoformat(args.window_end),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.report:
        report = Path(args.report)
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(catalog["candidate_report"], ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"coorte materializada: {len(catalog['plants'])} usinas -> {output}")
    for plant in catalog["plants"]:
        print(
            f"  {plant['ons_group_id']} -> {plant['asset_id']} "
            f"({plant['name']}, {plant['capacity_mw']} MW)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
