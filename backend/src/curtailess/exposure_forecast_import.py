"""Import and convert the individual plant forecast into the exposure contract.

Two source contracts are supported:

* ``curtailless.five_asset_demo.v1`` — the legacy demonstrative cohort artifact, whose
  entities are ONS generation groups (``CJU_*``).
* ``curtailless.individual_plant_forecast.v1`` — the current artifact, whose entities are
  individual plants and whose windows are three non-overlapping 72-hour periods.

Both are converted into the internal ``curtailless.exposure_forecast.v1`` contract consumed
by :mod:`curtailess.exposure_view`. Technical labels stay in this internal contract; the
frontend only ever sees the mapped display fields.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from statistics import mean
from typing import Any

from curtailess.exposure_view import APPROVED_ASSET_IDS, load_forecast_artifact

SOURCE_SCHEMA = "curtailless.five_asset_demo.v1"
LEGACY_BUNDLED_RESOURCE = "data/five_asset_forecast.json"
INDIVIDUAL_SCHEMA = "curtailless.individual_plant_forecast.v1"
HISTORY_SCHEMA = "curtailless.individual_plant_history.v1"
TARGET_SCHEMA = "curtailless.exposure_forecast.v1"
MATERIAL_EVENT_DEFINITION = (
    "at least one half-hour interval flagged by flg_geracaorestrita on the forecast day"
)
WEEKDAY_LABELS = ("seg", "ter", "qua", "qui", "sex", "sáb", "dom")


def _weekday_share(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals = [0.0] * 7
    for row in series:
        from datetime import date as _date

        weekday = _date.fromisoformat(row["date"]).weekday()
        totals[weekday] += float(row["curtailed_mwh"])
    total = sum(totals)
    if total <= 0:
        return []
    return [
        {"label": label, "value": round(value * 100 / total, 4)}
        for label, value in zip(WEEKDAY_LABELS, totals, strict=True)
    ]


def convert_individual_forecast_payload(
    forecast: dict[str, Any], history: dict[str, Any]
) -> dict[str, Any]:
    """Convert the individual plant forecast plus its history into the internal contract."""
    from curtailess.plant_exposure_forecast import validate_forecast_artifact

    if forecast.get("schema") != INDIVIDUAL_SCHEMA:
        raise ValueError("unsupported individual plant forecast schema")
    if history.get("schema") != HISTORY_SCHEMA:
        raise ValueError("unsupported individual plant history schema")
    validate_forecast_artifact(forecast)
    histories = {plant["asset_id"]: plant for plant in history["plants"]}
    contexts = forecast.get("point_contexts") or {}
    assets: list[dict[str, Any]] = []
    for plant in forecast["plants"]:
        asset_id = plant["asset_id"]
        observed = histories.get(asset_id)
        if observed is None:
            raise ValueError(f"a usina {asset_id} não tem histórico individual materializado")
        series = observed["series"]
        context = contexts.get(plant["connection_point"], {})
        windows = plant.get("critical_windows_72h") or []
        backtest = plant["probability_diagnostics"]["backtest"]
        trailing = [float(row["curtailed_mwh"]) for row in series[-7:]]
        trailing_30 = [float(row["curtailed_mwh"]) for row in series[-30:]]
        assets.append(
            {
                "asset_id": asset_id,
                "name": plant["name"],
                "entity_level": "plant",
                "ons_group_id": plant["ons_group_id"],
                "ons_group_name": plant["ons_group_name"],
                "technology": plant["technology"],
                "state": plant["state"],
                "connection_point": plant["connection_point"],
                "capacity_mw": float(plant["capacity_mw"]),
                "ceg": plant.get("ceg"),
                "allocation_coverage": observed["allocation_coverage_pct"],
                "connected_asset_count": max(int(context.get("entity_count", 1)) - 1, 0),
                "operational_data_status": "simulated",
                "probability_status": plant["probability_status"],
                "probability_source": plant["probability_source"],
                "probability_source_note": plant["probability_source_note"],
                "simulation_method": plant["simulation_method"],
                "current_state": {
                    "latest_curtailed_mwh": float(series[-1]["curtailed_mwh"]),
                    "trailing_7_observed_days_mean_curtailed_mwh": round(mean(trailing), 6),
                    "trailing_30_calendar_days_mean_curtailed_mwh": round(mean(trailing_30), 6),
                },
                "history": {
                    "last_observed_date": observed["period_end"],
                    "period_start": observed["period_start"],
                    "period_end": observed["period_end"],
                    "calendar_days": observed["calendar_days"],
                    "daily_rows": observed["daily_rows"],
                },
                "history_summary": {
                    "period_start": observed["period_start"],
                    "period_end": observed["period_end"],
                    "total_curtailed_mwh": observed["total_curtailed_mwh"],
                    "event_day_share_pct": observed["event_day_share_pct"],
                    "coverage_pct": observed["allocation_coverage_pct"],
                    "missing_day_rate_pct": round(
                        max(
                            int(observed["calendar_days"]) - int(observed["daily_rows"]),
                            0,
                        )
                        * 100
                        / max(int(observed["calendar_days"]), 1),
                        4,
                    ),
                    "duplicate_day_count": 0,
                    "weekday_energy_share_pct": _weekday_share(series),
                },
                "material_event": {
                    "definition": MATERIAL_EVENT_DEFINITION,
                    "percentile": 0.0,
                    "threshold_mwh": 0.0,
                    "probability_status": plant["probability_status"],
                },
                "probability_evidence": {
                    "status": backtest["probability_status"],
                    "probability_source": backtest["probability_source"],
                    "probability_decision_note": backtest["probability_decision_note"],
                    "test_brier": backtest["brier_raw"],
                    "test_brier_calibrated": backtest["brier_calibrated"],
                    "validation_brier": backtest["validation_brier_raw"],
                    "validation_brier_calibrated": backtest["validation_brier_calibrated"],
                    "test_event_rate": backtest["event_rate_test"],
                    "validation_event_rate": backtest["event_rate_validation"],
                    "train_event_rate": backtest["event_rate_train"],
                    "test_days": backtest["test_days"],
                    "validation_days": backtest["validation_days"],
                    "brier_best_baseline": backtest["brier_best_baseline"],
                    "brier_best_varying_baseline": backtest["brier_best_varying_baseline"],
                    "beats_baseline": backtest["beats_baseline"],
                    "baseline_briers": backtest["baseline_briers"],
                    "reliability_bins": backtest["reliability_bins"],
                    "reliability_gap_raw": backtest["reliability_gap_raw"],
                    "reliability_gap_calibrated": backtest["reliability_gap_calibrated"],
                    "l2_penalty": backtest["l2_penalty"],
                },
                "forecast_60d_total_interval_mwh": {
                    "lower": round(sum(float(row["lower_mwh"]) for row in plant["forecasts"]), 6),
                    "upper": round(sum(float(row["upper_mwh"]) for row in plant["forecasts"]), 6),
                },
                "critical_windows_72h": windows,
                "point_context": plant["point_context"],
                "simulated_telemetry": plant["simulated_telemetry"],
                "forecasts": [
                    {
                        "forecast_date": row["forecast_date"],
                        "display_label": row["display_label"],
                        "expected_curtailed_mwh": row["expected_curtailed_mwh"],
                        "lower_mwh": row["lower_mwh"],
                        "upper_mwh": row["upper_mwh"],
                        "curtailment_probability": row["curtailment_probability"],
                        "potential_generation_mwh": row["potential_generation_mwh"],
                        "accepted_generation_envelope_mwh": row["accepted_generation_envelope_mwh"],
                        "scheduled_maintenance_relief_mwh": row["scheduled_maintenance_relief_mwh"],
                        "avoided_curtailment_mwh": row["avoided_curtailment_mwh"],
                        "risk_reduction_percentage_points": row["risk_reduction_percentage_points"],
                    }
                    for row in plant["forecasts"]
                ],
            }
        )
    assets.sort(key=lambda item: item["asset_id"])
    identifiers = tuple(asset["asset_id"] for asset in assets)
    if set(identifiers) != set(APPROVED_ASSET_IDS) or len(identifiers) != len(APPROVED_ASSET_IDS):
        raise ValueError(
            "the individual forecast must contain the five approved plants exactly once"
        )
    return {
        "schema": TARGET_SCHEMA,
        "source_artifact_schema": INDIVIDUAL_SCHEMA,
        "source_sha256": hashlib.sha256(
            json.dumps(forecast, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "history_sha256": hashlib.sha256(
            json.dumps(history, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "input_manifest": forecast.get("input_manifest"),
        "cutoff": forecast["cutoff"],
        "simulation": forecast["simulation"],
        "status": "demonstrative_simulation",
        "interval_series": forecast["interval_series"],
        "method": forecast["method"],
        "limitations": forecast["limitations"],
        "checks": forecast["checks"],
        "maintenance_schedule": forecast.get("maintenance_schedule", {}),
        "assets": assets,
    }


def convert_individual_forecast(
    forecast_path: str | Path, history_path: str | Path
) -> dict[str, Any]:
    """Read both individual artifacts from disk and convert them."""
    with open(forecast_path, encoding="utf-8") as stream:
        forecast = json.load(stream)
    with open(history_path, encoding="utf-8") as stream:
        history = json.load(stream)
    return convert_individual_forecast_payload(forecast, history)


@lru_cache(maxsize=1)
def legacy_cohort_ids() -> tuple[str, ...]:
    """Identifiers of the legacy generation-group cohort, read from its bundled artifact.

    The legacy demonstrative artifact is a generation-group (``CJU_*``) contract and must not be
    confused with the five individual plants of the current catalog.
    """
    with open(
        str(files("curtailess").joinpath(LEGACY_BUNDLED_RESOURCE)), encoding="utf-8"
    ) as stream:
        payload = json.load(stream)
    return tuple(asset["asset_id"] for asset in payload["assets"])


def convert_forecast_artifact(source_path: str | Path) -> dict[str, Any]:
    source = Path(source_path)
    raw = source.read_bytes()
    payload = json.loads(raw)
    if payload.get("artifact_schema") != SOURCE_SCHEMA:
        raise ValueError("unsupported source forecast schema")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("source forecast assets must be a list")
    cohort = legacy_cohort_ids()
    identifiers = [asset.get("id_ons") for asset in assets]
    if set(identifiers) != set(cohort) or len(identifiers) != len(cohort):
        raise ValueError("source forecast must contain the approved five-asset cohort exactly once")
    result: dict[str, Any] = {
        "schema": TARGET_SCHEMA,
        "source_artifact_schema": payload["artifact_schema"],
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "cutoff": payload["cutoff"],
        "status": payload["status"],
        "limitations": payload["limitations"],
        "assets": [],
    }
    by_id = {asset["id_ons"]: asset for asset in assets}
    for asset_id in cohort:
        asset = by_id[asset_id]
        result["assets"].append(
            {
                "asset_id": asset_id,
                "name": asset["name"],
                "technology": "solar" if asset["technology"] == "solar" else "wind",
                "connection_point": asset["connection_point"],
                "state": asset["topology_context"]["state"],
                "latitude": asset["topology_context"].get("latitude"),
                "longitude": asset["topology_context"].get("longitude"),
                "connected_asset_count": asset["topology_context"]["peers_besides_selected"],
                "current_state": asset["current_state"],
                "history": asset["history"],
                "material_event": asset["material_event"],
                "probability_evidence": {
                    "status": asset["backtest"]["probability_calibration"]["status"],
                    "test_brier": asset["backtest"]["probability_calibration"]["test_raw_brier"],
                    "test_event_rate": asset["backtest"]["test"]["metrics"]["event_rate"],
                    "test_origins": asset["backtest"]["test"]["n_origins"],
                    "test_daily_predictions": asset["backtest"]["test"]["n_daily_predictions"],
                },
                "forecast_60d_total_interval_mwh": asset["forecast_60d_total_interval_mwh"],
                "forecasts": [
                    {
                        "forecast_date": point["forecast_date"],
                        "expected_curtailed_mwh": point["expected_curtailed_mwh"],
                        "lower_mwh": point["calibrated_interval_mwh"]["lower"],
                        "upper_mwh": point["calibrated_interval_mwh"]["upper"],
                        "curtailment_probability": point["curtailment_probability"],
                    }
                    for point in asset["forecasts"]
                ],
            }
        )
    return result


def validate_converted_forecast(payload: dict[str, Any]) -> None:
    from tempfile import NamedTemporaryFile

    with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json") as stream:
        json.dump(payload, stream, ensure_ascii=False)
        stream.flush()
        load_forecast_artifact(stream.name)
