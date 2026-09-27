"""Plant-level exposure view assembled from the individual plant forecast.

The catalog and the view are driven by the bundled individual plant catalog, so the five
selectable identifiers are read from the artifact instead of being written here. Generation
groups (``CJU_*``) are systemic context, never a selectable entity, and their energy is never
attributed to the selected plant.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import lru_cache
from importlib.resources import files
from typing import Any, Protocol

from curtailess.schemas import (
    ExposureAssetCatalog,
    ExposureAssociatedConditions,
    ExposureDisplayAsset,
    ExposureDisplayMetric,
    ExposureDistributionPoint,
    ExposureForecast60d,
    ExposureForecastPoint,
    ExposureForecastWindow,
    ExposureNarrative,
    ExposureObservedImpact,
    ExposurePointContext,
    ExposureQuality,
    ExposureRecurrence,
    ExposureSimulatedTelemetry,
    ExposureViewResponse,
)

PLANT_CATALOG_SCHEMA = "curtailless.individual_plant_catalog.v1"
TARGET_SCHEMA = "curtailless.exposure_forecast.v1"
PLANT_CATALOG_RESOURCE = "data/individual_plant_catalog.json"
INDIVIDUAL_FORECAST_RESOURCE = "data/individual_plant_forecast.json"
INDIVIDUAL_HISTORY_RESOURCE = "data/individual_plant_history.json"
WINDOW_DEFINITION = (
    "Três janelas críticas de 144 intervalos de meia hora (72 horas), "
    "selecionadas sem sobreposição."
)


class ExposureDataRepository(Protocol):
    def get_asset(self, asset_id: str) -> dict[str, Any] | None: ...

    def get_asset_history(self, asset_id: str) -> list[dict[str, Any]]: ...

    def get_point_context(
        self, asset_id: str, asset: dict[str, Any] | None = None
    ) -> dict[str, Any] | None: ...

    def get_identity(self, asset_id: str, as_of: date) -> dict[str, Any] | None: ...


class UnknownExposureAssetError(ValueError):
    pass


def _read_resource(relative_path: str) -> dict[str, Any]:
    with open(str(files("curtailess").joinpath(relative_path)), encoding="utf-8") as stream:
        return json.load(stream)


def load_plant_catalog(path: str | None = None) -> dict[str, Any]:
    """Load the bundled individual plant catalog and enforce its plant-level contract."""
    catalog_path = (
        path if path is not None else str(files("curtailess").joinpath(PLANT_CATALOG_RESOURCE))
    )
    with open(catalog_path, encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("schema") != PLANT_CATALOG_SCHEMA:
        raise ValueError("unsupported individual plant catalog schema")
    if payload.get("entity_level") != "plant":
        raise ValueError("the plant catalog must declare plant entities")
    plants = payload.get("plants")
    if not isinstance(plants, list) or len(plants) != 5:
        raise ValueError("the plant catalog must contain exactly five plants")
    identifiers = tuple(plant.get("asset_id") for plant in plants)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("the plant catalog must not repeat a plant")
    for plant in plants:
        asset_id = str(plant.get("asset_id") or "")
        if not asset_id or asset_id.startswith("CJU_"):
            raise ValueError("the plant catalog cannot contain a generation group")
        if plant.get("entity_level") != "plant":
            raise ValueError("every catalog entry must be a plant")
        if not plant.get("ons_group_id") or not plant.get("ceg"):
            raise ValueError("every plant must declare its ONS group and CEG")
    return payload


def approved_asset_ids() -> tuple[str, ...]:
    """The selectable plant identifiers, in product order, read from the bundled catalog."""
    return tuple(plant["asset_id"] for plant in load_plant_catalog()["plants"])


APPROVED_ASSET_IDS = approved_asset_ids()


def _validate_target_schema(payload: dict[str, Any]) -> None:
    if payload.get("schema") != TARGET_SCHEMA:
        raise ValueError("unsupported exposure forecast schema")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("forecast artifact assets must be a list")
    for asset in assets:
        points = asset.get("forecasts")
        if not isinstance(points, list) or len(points) != 60:
            raise ValueError("each asset requires exactly 60 forecast points")
        validated = tuple(ExposureForecastPoint.model_validate(point) for point in points)
        dates = tuple(point.forecast_date for point in validated)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("forecast dates must be sorted and unique")


def _validate_plant_cohort(payload: dict[str, Any]) -> None:
    identifiers = tuple(asset.get("asset_id") for asset in payload["assets"])
    if set(identifiers) != set(APPROVED_ASSET_IDS) or len(identifiers) != len(APPROVED_ASSET_IDS):
        raise ValueError("forecast artifact must contain the five approved plants exactly once")
    for asset in payload["assets"]:
        if asset.get("entity_level") != "plant":
            raise ValueError("every exposure asset must be an individual plant")


@lru_cache(maxsize=1)
def _bundled_forecast_artifact() -> dict[str, Any]:
    from curtailess.exposure_forecast_import import convert_individual_forecast_payload

    forecast = _read_resource(INDIVIDUAL_FORECAST_RESOURCE)
    history = _read_resource(INDIVIDUAL_HISTORY_RESOURCE)
    return convert_individual_forecast_payload(forecast, history)


def load_forecast_artifact(path: str | None = None) -> dict[str, Any]:
    """Load the internal exposure contract, converting the bundled plant artifacts when needed."""
    if path is None:
        payload = _bundled_forecast_artifact()
        _validate_target_schema(payload)
        _validate_plant_cohort(payload)
    else:
        with open(path, encoding="utf-8") as stream:
            payload = json.load(stream)
        _validate_target_schema(payload)
    return payload


def _asset_payloads(artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(asset["asset_id"]): asset for asset in artifact["assets"]}


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _percentage(value: Decimal, total: Decimal) -> float | None:
    return round(float(value * Decimal("100") / total), 2) if total > 0 else None


def _distribution(
    values: dict[str, Decimal], total: Decimal
) -> tuple[ExposureDistributionPoint, ...]:
    if total <= 0:
        return ()
    return tuple(
        ExposureDistributionPoint(label=label, value=round(float(value * 100 / total), 2))
        for label, value in sorted(values.items(), key=lambda item: (-item[1], item[0]))
        if value > 0
    )


def _metric(value: Any, unit: str) -> ExposureDisplayMetric:
    return ExposureDisplayMetric(value=None if value is None else float(value), unit=unit)


def _catalog_asset(
    payload: dict[str, Any], repository: ExposureDataRepository | None
) -> ExposureDisplayAsset:
    capacity_mw: float | None = (
        float(payload["capacity_mw"]) if payload.get("capacity_mw") is not None else None
    )
    if repository is not None:
        identity = repository.get_identity(
            payload["asset_id"], date.fromisoformat(payload["history"]["last_observed_date"])
        )
        capacity = (identity or {}).get("capacity", {})
        for key in ("capacity_mw", "val_potenciaefetiva"):
            if capacity.get(key) is not None:
                capacity_mw = float(capacity[key])
                break
    coverage = payload.get("allocation_coverage")
    return ExposureDisplayAsset(
        asset_id=payload["asset_id"],
        name=payload["name"],
        entity_level=payload.get("entity_level", "plant"),
        technology=payload["technology"],
        state=payload["state"],
        connection_point=payload["connection_point"],
        capacity_mw=capacity_mw,
        connected_asset_count=int(payload["connected_asset_count"]),
        operational_data_status=payload.get("operational_data_status", "simulated"),
        ons_group_id=payload.get("ons_group_id"),
        ons_group_name=payload.get("ons_group_name"),
        ceg=payload.get("ceg"),
        allocation_coverage=None if coverage is None else _metric(coverage, "%"),
    )


def list_exposure_assets(repository: ExposureDataRepository | None = None) -> ExposureAssetCatalog:
    payloads = _asset_payloads(load_forecast_artifact())
    return ExposureAssetCatalog(
        items=tuple(
            _catalog_asset(payloads[asset_id], repository) for asset_id in APPROVED_ASSET_IDS
        )
    )


def _window(payload: dict[str, Any]) -> ExposureForecastWindow:
    interval_count = int(payload["interval_count"])
    probability = float(payload["curtailment_probability"])
    return ExposureForecastWindow(
        start=date.fromisoformat(payload["start_date"]),
        end=date.fromisoformat(payload["end_date"]),
        expected_curtailed_mwh=float(payload["expected_curtailed_mwh"]),
        mean_probability=probability,
        rank=int(payload["rank"]),
        starts_at=datetime.fromisoformat(payload["starts_at"]),
        ends_at=datetime.fromisoformat(payload["ends_at"]),
        interval_count=interval_count,
        window_hours=round(interval_count * 0.5, 6),
        curtailment_probability=probability,
        scheduled_maintenance_relief_mwh=float(payload["scheduled_maintenance_relief_mwh"]),
        avoided_curtailment_mwh=float(payload["avoided_curtailment_mwh"]),
        candidate_maintenance_relief_mwh=float(payload["candidate_maintenance_relief_mwh"]),
    )


def _forecast(payload: dict[str, Any]) -> ExposureForecast60d:
    points = tuple(ExposureForecastPoint.model_validate(point) for point in payload["forecasts"])
    accumulated = payload["forecast_60d_total_interval_mwh"]
    return ExposureForecast60d(
        status="demonstrative_simulation",
        start=points[0].forecast_date,
        end=points[-1].forecast_date,
        points=points,
        total_expected_mwh=round(sum(point.expected_curtailed_mwh for point in points), 3),
        total_lower_mwh=float(accumulated["lower"]),
        total_upper_mwh=float(accumulated["upper"]),
        event_threshold_mwh=float(payload["material_event"]["threshold_mwh"]),
        event_percentile=float(payload["material_event"]["percentile"]),
        probability_status=payload["probability_status"],
        probability_source=payload["probability_source"],
        simulation_method=payload.get("simulation_method"),
        window_definition=WINDOW_DEFINITION,
        critical_windows_72h=tuple(_window(window) for window in payload["critical_windows_72h"]),
    )


def _bundled_history(
    payload: dict[str, Any],
    latest_metric: ExposureDisplayMetric,
    trailing_7_metric: ExposureDisplayMetric,
    trailing_30_metric: ExposureDisplayMetric,
) -> tuple[
    ExposureObservedImpact,
    ExposureAssociatedConditions,
    ExposureRecurrence,
    ExposureQuality,
    datetime,
]:
    summary = payload["history_summary"]
    summary_end = date.fromisoformat(summary["period_end"])
    weekdays = tuple(
        ExposureDistributionPoint.model_validate(point)
        for point in summary["weekday_energy_share_pct"]
    )
    return (
        ExposureObservedImpact(
            total_curtailed_energy=_metric(summary["total_curtailed_mwh"], "MWh"),
            event_day_share=_metric(summary["event_day_share_pct"], "%"),
            latest_daily_curtailed_energy=latest_metric,
            trailing_7_day_mean=trailing_7_metric,
            trailing_30_day_mean=trailing_30_metric,
            characterized_share=ExposureDisplayMetric(value=None, unit="%"),
            simultaneous_share=ExposureDisplayMetric(value=None, unit="%"),
            exclusive_share=ExposureDisplayMetric(value=None, unit="%"),
            period_start=date.fromisoformat(summary["period_start"]),
            period_end=summary_end,
            curtailed_day_share=_metric(summary["event_day_share_pct"], "%"),
            allocation_coverage=_metric(summary["coverage_pct"], "%"),
        ),
        ExposureAssociatedConditions(),
        ExposureRecurrence(weekdays=weekdays),
        ExposureQuality(
            coverage=_metric(summary["coverage_pct"], "%"),
            update_delay=_metric(max((datetime.now(UTC).date() - summary_end).days, 0), "dias"),
            missing_rate=_metric(summary["missing_day_rate_pct"], "%"),
            duplicate_count=_metric(summary["duplicate_day_count"], "dias"),
        ),
        datetime.combine(summary_end, datetime.min.time(), tzinfo=UTC),
    )


def _history(
    payload: dict[str, Any], repository: ExposureDataRepository | None
) -> tuple[
    ExposureObservedImpact,
    ExposureAssociatedConditions,
    ExposureRecurrence,
    ExposureQuality,
    datetime,
]:
    records = repository.get_asset_history(payload["asset_id"]) if repository is not None else []
    current = payload["current_state"]
    latest_metric = ExposureDisplayMetric(
        value=float(current["latest_curtailed_mwh"]), unit="MWh/dia"
    )
    trailing_7_metric = ExposureDisplayMetric(
        value=float(current["trailing_7_observed_days_mean_curtailed_mwh"]), unit="MWh/dia"
    )
    trailing_30_metric = ExposureDisplayMetric(
        value=float(current["trailing_30_calendar_days_mean_curtailed_mwh"]), unit="MWh/dia"
    )
    if not records:
        return _bundled_history(payload, latest_metric, trailing_7_metric, trailing_30_metric)

    total = sum((_decimal(record.get("curtailed_mwh")) for record in records), Decimal("0"))
    reason_values: dict[str, Decimal] = defaultdict(Decimal)
    origin_counts: dict[str, Decimal] = defaultdict(Decimal)
    duplicates = 0
    intervals = 0
    missing = 0
    point_context = (
        repository.get_point_context(payload["asset_id"], records[-1]) if repository else None
    )
    for record in records:
        reasons = record.get("curtailed_mwh_by_reason_exact") or record.get(
            "curtailed_mwh_by_reason", {}
        )
        for key, value in reasons.items():
            reason_values[str(key)] += _decimal(value)
        for key, value in record.get("limited_interval_count_by_origin", {}).items():
            origin_counts[str(key)] += _decimal(value)
        duplicates += int(record.get("duplicate_interval_count", 0))
        intervals += int(record.get("interval_count", 0))
        missing += sum(int(value) for value in record.get("null_counts", {}).values())
    characterized = sum(reason_values.values(), Decimal("0"))
    simultaneous_share = None
    if point_context and point_context.get("entity_count"):
        simultaneous_share = round(
            100
            * max(int(point_context.get("limited_entity_count", 1)) - 1, 0)
            / int(point_context["entity_count"]),
            2,
        )
    exclusive_share = None if simultaneous_share is None else round(100 - simultaneous_share, 2)
    latest_end = max(date.fromisoformat(record["period_end"][:10]) for record in records)
    earliest_start = min(date.fromisoformat(record["period_start"][:10]) for record in records)
    coverage = min(
        100.0, round(intervals / (48 * max((latest_end - earliest_start).days + 1, 1)) * 100, 2)
    )
    null_denominator = max(intervals * 6, 1)
    allocation = payload["history_summary"].get("coverage_pct")
    return (
        ExposureObservedImpact(
            total_curtailed_energy=ExposureDisplayMetric(value=float(total), unit="MWh"),
            event_day_share=ExposureDisplayMetric(value=None, unit="%"),
            latest_daily_curtailed_energy=latest_metric,
            trailing_7_day_mean=trailing_7_metric,
            trailing_30_day_mean=trailing_30_metric,
            characterized_share=ExposureDisplayMetric(
                value=_percentage(characterized, total), unit="%"
            ),
            simultaneous_share=ExposureDisplayMetric(value=simultaneous_share, unit="%"),
            exclusive_share=ExposureDisplayMetric(value=exclusive_share, unit="%"),
            period_start=earliest_start,
            period_end=latest_end,
            allocation_coverage=None if allocation is None else _metric(allocation, "%"),
        ),
        ExposureAssociatedConditions(
            reasons=_distribution(reason_values, characterized),
            origins=_distribution(origin_counts, sum(origin_counts.values(), Decimal("0"))),
            modalities=(),
        ),
        ExposureRecurrence(),
        ExposureQuality(
            coverage=ExposureDisplayMetric(value=coverage, unit="%"),
            update_delay=ExposureDisplayMetric(
                value=max((datetime.now(UTC).date() - latest_end).days, 0), unit="dias"
            ),
            missing_rate=ExposureDisplayMetric(
                value=round(missing / null_denominator * 100, 2), unit="%"
            ),
            duplicate_count=ExposureDisplayMetric(value=duplicates, unit="intervalos"),
        ),
        datetime.combine(latest_end, datetime.min.time(), tzinfo=UTC),
    )


def deterministic_narrative(
    asset: ExposureDisplayAsset,
    observed: ExposureObservedImpact,
    forecast: ExposureForecast60d,
    conditions: ExposureAssociatedConditions,
    recurrence: ExposureRecurrence,
    quality: ExposureQuality,
) -> ExposureNarrative:
    total = observed.total_curtailed_energy.value
    observed_text = (
        f"O histórico materializado registra {total:.1f} MWh de energia "
        "restringida da própria usina no período analisado."
        if total is not None
        else "O histórico detalhado ainda não está materializado neste ambiente local."
    )
    reason_text = (
        "As categorias publicadas pelo Operador Nacional do Sistema Elétrico "
        "descrevem as condições associadas aos cortes observados."
        if conditions.reasons
        else (
            "A distribuição por razão ficará disponível após a materialização do histórico público."
        )
    )
    recurrence_text = (
        "A distribuição por dia da semana usa a estimativa diária calculada "
        "a partir do histórico público da usina."
        if recurrence.weekdays
        else "A série disponível não sustenta uma distribuição temporal."
    )
    quality_text = (
        f"A cobertura calculada da série materializada é {quality.coverage.value:.1f}%."
        if quality.coverage.value is not None
        else "Os indicadores de cobertura dependem da leitura da base histórica materializada."
    )
    technology = "eólica" if asset.technology == "wind" else "solar"
    group_context = (
        f", vinculada ao conjunto {asset.ons_group_name} ({asset.ons_group_id})"
        if asset.ons_group_name and asset.ons_group_id
        else ""
    )
    return ExposureNarrative.model_validate(
        {
            "secao-ativo": [
                f"{asset.name} é uma usina {technology} conectada ao ponto "
                f"{asset.connection_point}{group_context}.",
                "O estado operacional mostrado nesta demonstração é uma estimativa "
                "baseada em dados públicos, não telemetria privada da usina.",
            ],
            "secao-resumo": [observed_text],
            "secao-previsao": [
                f"A projeção demonstrativa cobre {len(forecast.points)} dias e usa o "
                "histórico diário da própria usina, os últimos 30 dias, os últimos sete "
                "dias e o dia anterior.",
                "A energia esperada é estimada diretamente pelas médias históricas da "
                "usina e não representa uma ordem operacional futura do ONS.",
                "A energia do conjunto e do ponto de conexão aparece somente como "
                "contexto e nunca é atribuída à usina selecionada.",
            ],
            "secao-razao-origem": [reason_text],
            "secao-recorrencia": [recurrence_text],
            "secao-qualidade": [quality_text],
        }
    )


def _provenance(artifact: dict[str, Any]) -> dict[str, Any]:
    manifest = artifact.get("input_manifest") or {}
    return {
        "source_artifact_schema": artifact.get("source_artifact_schema"),
        "source_sha256": artifact.get("source_sha256"),
        "history_sha256": artifact.get("history_sha256"),
        "input_manifest_digest": manifest.get("digest"),
    }


def build_exposure_view(
    asset_id: str,
    repository: ExposureDataRepository | None = None,
    narrative: ExposureNarrative | None = None,
) -> ExposureViewResponse:
    artifact = load_forecast_artifact()
    payloads = _asset_payloads(artifact)
    if asset_id not in payloads:
        raise UnknownExposureAssetError(asset_id)
    payload = payloads[asset_id]
    asset = _catalog_asset(payload, repository)
    forecast = _forecast(payload)
    observed, conditions, recurrence, quality, last_update = _history(payload, repository)
    point_context = (
        ExposurePointContext.model_validate(payload["point_context"])
        if payload.get("point_context")
        else None
    )
    simulated_telemetry = (
        ExposureSimulatedTelemetry.model_validate(payload["simulated_telemetry"])
        if payload.get("simulated_telemetry")
        else None
    )
    deterministic_payload = {
        "asset": asset.model_dump(mode="json"),
        "last_data_update": last_update.isoformat(),
        "observed_impact": observed.model_dump(mode="json"),
        "forecast_60d": forecast.model_dump(mode="json"),
        "associated_conditions": conditions.model_dump(mode="json"),
        "recurrence": recurrence.model_dump(mode="json"),
        "quality": quality.model_dump(mode="json"),
        "point_context": point_context.model_dump(mode="json") if point_context else None,
        "simulated_telemetry": (
            simulated_telemetry.model_dump(mode="json") if simulated_telemetry else None
        ),
    }
    input_digest = hashlib.sha256(
        json.dumps(
            {"view": deterministic_payload, "provenance": _provenance(artifact)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    selected_narrative = narrative or deterministic_narrative(
        asset, observed, forecast, conditions, recurrence, quality
    )
    return ExposureViewResponse(
        **deterministic_payload,
        input_digest=input_digest,
        narrative=selected_narrative,
        limitations=(
            "A previsão de 60 dias é uma simulação demonstrativa baseada no histórico público.",
            (
                "O estado da usina é uma estimativa simulada e não representa telemetria "
                "Supervisory Control and Data Acquisition."
            ),
            "A energia do conjunto e do ponto de conexão é contexto sistêmico e não é "
            "atribuída à usina selecionada.",
            "A série diária sustenta recorrência por dia da semana, mas não por horário.",
        ),
    )
