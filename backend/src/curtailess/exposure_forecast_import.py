from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from curtailess.exposure_view import APPROVED_ASSET_IDS, load_forecast_artifact

SOURCE_SCHEMA = "curtailless.five_asset_demo.v1"
TARGET_SCHEMA = "curtailless.exposure_forecast.v1"


def convert_forecast_artifact(source_path: str | Path) -> dict[str, Any]:
    source = Path(source_path)
    raw = source.read_bytes()
    payload = json.loads(raw)
    if payload.get("artifact_schema") != SOURCE_SCHEMA:
        raise ValueError("unsupported source forecast schema")
    assets = payload.get("assets")
    if not isinstance(assets, list):
        raise ValueError("source forecast assets must be a list")
    identifiers = [asset.get("id_ons") for asset in assets]
    if set(identifiers) != set(APPROVED_ASSET_IDS) or len(identifiers) != len(APPROVED_ASSET_IDS):
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
    for asset_id in APPROVED_ASSET_IDS:
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
