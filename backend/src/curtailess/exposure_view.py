from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
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
    ExposureQuality,
    ExposureRecurrence,
    ExposureViewResponse,
)

APPROVED_ASSET_IDS = (
    "CJU_RNRDV",
    "CJU_BALRA",
    "CJU_BASDB",
    "CJU_RNMVS",
    "CJU_PBLZA",
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


def load_forecast_artifact(path: str | None = None) -> dict[str, Any]:
    artifact_path = (
        path
        if path is not None
        else str(files("curtailess").joinpath("data/five_asset_forecast.json"))
    )
    with open(artifact_path, encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("schema") != "curtailless.exposure_forecast.v1":
        raise ValueError("unsupported exposure forecast schema")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("forecast artifact assets must be a list")
    identifiers = tuple(asset.get("asset_id") for asset in assets)
    if set(identifiers) != set(APPROVED_ASSET_IDS) or len(identifiers) != len(APPROVED_ASSET_IDS):
        raise ValueError("forecast artifact must contain the five approved assets exactly once")
    for asset in assets:
        points = asset.get("forecasts")
        if not isinstance(points, list) or len(points) != 60:
            raise ValueError("each asset requires exactly 60 forecast points")
        validated = tuple(ExposureForecastPoint.model_validate(point) for point in points)
        dates = tuple(point.forecast_date for point in validated)
        if dates != tuple(sorted(set(dates))):
            raise ValueError("forecast dates must be sorted and unique")
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


def _catalog_asset(
    payload: dict[str, Any], repository: ExposureDataRepository | None
) -> ExposureDisplayAsset:
    capacity_mw: float | None = None
    if repository is not None:
        identity = repository.get_identity(
            payload["asset_id"], date.fromisoformat(payload["history"]["last_observed_date"])
        )
        capacity = (identity or {}).get("capacity", {})
        for key in ("capacity_mw", "val_potenciaefetiva"):
            if capacity.get(key) is not None:
                capacity_mw = float(capacity[key])
                break
    return ExposureDisplayAsset(
        asset_id=payload["asset_id"],
        name=payload["name"],
        technology=payload["technology"],
        state=payload["state"],
        connection_point=payload["connection_point"],
        capacity_mw=capacity_mw,
        connected_asset_count=int(payload["connected_asset_count"]),
        operational_data_status="simulated",
    )


def list_exposure_assets(repository: ExposureDataRepository | None = None) -> ExposureAssetCatalog:
    payloads = _asset_payloads(load_forecast_artifact())
    return ExposureAssetCatalog(
        items=tuple(
            _catalog_asset(payloads[asset_id], repository) for asset_id in APPROVED_ASSET_IDS
        )
    )


def _forecast(payload: dict[str, Any]) -> ExposureForecast60d:
    points = tuple(ExposureForecastPoint.model_validate(point) for point in payload["forecasts"])
    candidate_windows: list[ExposureForecastWindow] = []
    for offset in range(0, 60 - 6, 7):
        window = points[offset : offset + 7]
        candidate_windows.append(
            ExposureForecastWindow(
                start=window[0].forecast_date,
                end=window[-1].forecast_date,
                expected_curtailed_mwh=round(
                    sum(point.expected_curtailed_mwh for point in window), 3
                ),
                mean_probability=round(
                    sum(point.curtailment_probability for point in window) / len(window), 6
                ),
            )
        )
    top_windows = tuple(
        sorted(
            candidate_windows,
            key=lambda window: (-window.expected_curtailed_mwh, window.start),
        )[:3]
    )
    accumulated = payload["forecast_60d_total_interval_mwh"]
    return ExposureForecast60d(
        status="demonstrative_simulation",
        start=points[0].forecast_date,
        end=points[-1].forecast_date,
        points=points,
        total_expected_mwh=round(sum(point.expected_curtailed_mwh for point in points), 3),
        total_lower_mwh=float(accumulated["lower"]),
        total_upper_mwh=float(accumulated["upper"]),
        top_windows=top_windows,
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
    history_start = date.fromisoformat(payload["history"]["first_observed_date"])
    history_end = date.fromisoformat(payload["history"]["last_observed_date"])
    if not records:
        return (
            ExposureObservedImpact(
                total_curtailed_energy=ExposureDisplayMetric(value=None, unit="MWh"),
                characterized_share=ExposureDisplayMetric(value=None, unit="%"),
                simultaneous_share=ExposureDisplayMetric(value=None, unit="%"),
                exclusive_share=ExposureDisplayMetric(value=None, unit="%"),
                period_start=history_start,
                period_end=history_end,
            ),
            ExposureAssociatedConditions(),
            ExposureRecurrence(),
            ExposureQuality(
                coverage=ExposureDisplayMetric(value=None, unit="%"),
                update_delay=ExposureDisplayMetric(value=None, unit="dias"),
                missing_rate=ExposureDisplayMetric(value=None, unit="%"),
                duplicate_count=ExposureDisplayMetric(value=None, unit="intervalos"),
            ),
            datetime.combine(history_end, datetime.min.time(), tzinfo=UTC),
        )

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
    return (
        ExposureObservedImpact(
            total_curtailed_energy=ExposureDisplayMetric(value=float(total), unit="MWh"),
            characterized_share=ExposureDisplayMetric(
                value=_percentage(characterized, total), unit="%"
            ),
            simultaneous_share=ExposureDisplayMetric(value=simultaneous_share, unit="%"),
            exclusive_share=ExposureDisplayMetric(value=exclusive_share, unit="%"),
            period_start=earliest_start,
            period_end=latest_end,
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
        "restringida no período analisado."
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
        "A recorrência temporal usa intervalos históricos convertidos para o horário de Brasília."
        if recurrence.weekdays or recurrence.hours
        else "A base mensal disponível não sustenta uma distribuição por dia da semana ou horário."
    )
    quality_text = (
        f"A cobertura calculada da série materializada é {quality.coverage.value:.1f}%."
        if quality.coverage.value is not None
        else "Os indicadores de cobertura dependem da leitura da base histórica materializada."
    )
    return ExposureNarrative.model_validate(
        {
            "secao-ativo": [
                f"{asset.name} é um conjunto "
                f"{('eólico' if asset.technology == 'wind' else 'solar')} conectado "
                f"ao ponto {asset.connection_point}.",
                "O estado operacional mostrado nesta demonstração é uma estimativa "
                "baseada em dados públicos, não telemetria privada da usina.",
            ],
            "secao-resumo": [observed_text],
            "secao-previsao": [
                f"A projeção demonstrativa cobre {len(forecast.points)} dias e expressa "
                "uma possibilidade estimada, não um corte futuro confirmado.",
                "A faixa estimada representa a incerteza do cenário e não uma "
                "garantia de cobertura uniforme.",
            ],
            "secao-razao-origem": [reason_text],
            "secao-recorrencia": [recurrence_text],
            "secao-qualidade": [quality_text],
        }
    )


def build_exposure_view(
    asset_id: str,
    repository: ExposureDataRepository | None = None,
    narrative: ExposureNarrative | None = None,
) -> ExposureViewResponse:
    payloads = _asset_payloads(load_forecast_artifact())
    if asset_id not in payloads:
        raise UnknownExposureAssetError(asset_id)
    payload = payloads[asset_id]
    asset = _catalog_asset(payload, repository)
    forecast = _forecast(payload)
    observed, conditions, recurrence, quality, last_update = _history(payload, repository)
    deterministic_payload = {
        "asset": asset.model_dump(mode="json"),
        "last_data_update": last_update.isoformat(),
        "observed_impact": observed.model_dump(mode="json"),
        "forecast_60d": forecast.model_dump(mode="json"),
        "associated_conditions": conditions.model_dump(mode="json"),
        "recurrence": recurrence.model_dump(mode="json"),
        "quality": quality.model_dump(mode="json"),
    }
    input_digest = hashlib.sha256(
        json.dumps(deterministic_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    selected_narrative = narrative or deterministic_narrative(
        asset, observed, forecast, conditions, recurrence, quality
    )
    return ExposureViewResponse(
        **deterministic_payload,
        input_digest=input_digest,
        narrative=selected_narrative,
        limitations=(
            "A previsão de 60 dias é uma simulação demonstrativa baseada em histórico público.",
            "O estado da usina não representa telemetria Supervisory Control and Data Acquisition.",
            "A base histórica mensal não sustenta recorrência por dia da semana ou horário.",
        ),
    )
