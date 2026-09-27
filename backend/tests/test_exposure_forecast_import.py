import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path

import pytest

from curtailess.exposure_forecast_import import (
    convert_forecast_artifact,
    convert_individual_forecast,
    convert_individual_forecast_payload,
    validate_converted_forecast,
)
from curtailess.exposure_view import APPROVED_ASSET_IDS, load_forecast_artifact

SOURCE = Path(
    "/run/media/carloshnp/D/Programming/hackaton-coppe-ia-11092026/"
    "estrategia/temp/simulacao-portfolio-cinco-ativos-60d-v1.json"
)


def _bundled_plant_payloads():
    base = files("curtailess").joinpath("data")
    forecast = json.loads(
        base.joinpath("individual_plant_forecast.json").read_text(encoding="utf-8")
    )
    history = json.loads(base.joinpath("individual_plant_history.json").read_text(encoding="utf-8"))
    return forecast, history


def test_bundled_forecast_has_verified_source_hash_and_count():
    bundled_path = files("curtailess").joinpath("data/five_asset_forecast.json")
    bundled = json.loads(bundled_path.read_text(encoding="utf-8"))

    validate_converted_forecast(bundled)
    assert (
        bundled["source_sha256"]
        == "642c34eb14099c0a2e8f962794d4962f8c38c0bf3dfb012a3492d0e452997cf0"
    )
    assert sum(len(asset["forecasts"]) for asset in bundled["assets"]) == 300


def test_rio_do_vento_probability_targets_a_material_historical_event():
    bundled_path = files("curtailess").joinpath("data/five_asset_forecast.json")
    bundled = json.loads(bundled_path.read_text(encoding="utf-8"))
    rio_do_vento = next(asset for asset in bundled["assets"] if asset["asset_id"] == "CJU_RNRDV")

    assert rio_do_vento["material_event"] == {
        "definition": (
            "daily curtailed-energy proxy at or above the asset historical 75th percentile"
        ),
        "percentile": 0.75,
        "probability_status": "empirical_uncalibrated",
        "threshold_mwh": 1962.0995,
    }
    probabilities = [row["curtailment_probability"] for row in rio_do_vento["forecasts"]]
    assert min(probabilities) == pytest.approx(0.357472)
    assert max(probabilities) == pytest.approx(0.557741)


@pytest.mark.skipif(
    not SOURCE.exists(), reason="strategy source is outside the deployable repository"
)
def test_importer_reproduces_bundled_canonical_forecast():
    converted = convert_forecast_artifact(SOURCE)
    bundled_path = files("curtailess").joinpath("data/five_asset_forecast.json")
    bundled = json.loads(bundled_path.read_text(encoding="utf-8"))

    validate_converted_forecast(converted)
    assert converted == bundled


def test_importer_rejects_unknown_schema(tmp_path):
    source = tmp_path / "invalid.json"
    source.write_text('{"artifact_schema":"unknown","assets":[]}', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported"):
        convert_forecast_artifact(source)


def test_individual_conversion_builds_the_five_plant_contract():
    forecast, history = _bundled_plant_payloads()

    converted = convert_individual_forecast_payload(forecast, history)

    identifiers = [asset["asset_id"] for asset in converted["assets"]]
    assert sorted(identifiers) == sorted(APPROVED_ASSET_IDS)
    assert len(identifiers) == 5
    assert all(asset["entity_level"] == "plant" for asset in converted["assets"])
    assert all(not asset["asset_id"].startswith("CJU_") for asset in converted["assets"])
    for asset in converted["assets"]:
        assert asset["ons_group_id"].startswith("CJU_")
        assert asset["ons_group_name"]
        assert asset["ceg"]
        assert asset["allocation_coverage"] == 100.0
        assert asset["material_event"] == {
            "definition": (
                "at least one half-hour interval flagged by flg_geracaorestrita on the forecast day"
            ),
            "percentile": 0.0,
            "probability_status": asset["probability_status"],
            "threshold_mwh": 0.0,
        }
        assert len(asset["forecasts"]) == 60
        assert all(point["display_label"] for point in asset["forecasts"])
        windows = asset["critical_windows_72h"]
        assert len(windows) == 3
        assert all(window["interval_count"] == 144 for window in windows)
        ordered = sorted(windows, key=lambda window: window["start_date"])
        for previous, following in zip(ordered, ordered[1:], strict=False):
            assert following["start_date"] > previous["end_date"]


def test_individual_conversion_publishes_source_and_history_provenance():
    forecast, history = _bundled_plant_payloads()

    converted = convert_individual_forecast_payload(forecast, history)

    assert converted["source_artifact_schema"] == "curtailless.individual_plant_forecast.v1"
    assert len(converted["source_sha256"]) == 64
    assert len(converted["history_sha256"]) == 64
    assert converted["input_manifest"]["digest"] == forecast["input_manifest"]["digest"]


def test_individual_conversion_rejects_a_group_identifier():
    forecast, history = _bundled_plant_payloads()
    forecast["plants"][0]["asset_id"] = "CJU_ZZZZ"

    with pytest.raises(ValueError, match="conjunto"):
        convert_individual_forecast_payload(forecast, history)


def test_individual_conversion_rejects_an_identifier_outside_the_catalog():
    forecast, history = _bundled_plant_payloads()
    original = forecast["plants"][0]["asset_id"]
    forecast["plants"][0]["asset_id"] = "ZZZZ99"
    for plant in history["plants"]:
        if plant["asset_id"] == original:
            plant["asset_id"] = "ZZZZ99"

    with pytest.raises(ValueError, match="approved plants"):
        convert_individual_forecast_payload(forecast, history)


def test_bundled_individual_artifacts_are_reproduced_by_the_importer():
    base = files("curtailess").joinpath("data")

    converted = convert_individual_forecast(
        str(base.joinpath("individual_plant_forecast.json")),
        str(base.joinpath("individual_plant_history.json")),
    )

    assert converted == load_forecast_artifact()


def test_individual_conversion_validates_the_telemetry_and_point_context():
    forecast, history = _bundled_plant_payloads()
    converted = convert_individual_forecast_payload(deepcopy(forecast), deepcopy(history))
    asset = converted["assets"][0]

    assert asset["simulated_telemetry"]["origin"] == "SIMULADO"
    assert asset["simulated_telemetry"]["potentially_curtailed_mw"] >= 0
    assert asset["simulated_telemetry"]["restricted"] in (True, False)
    assert asset["point_context"]["envelope"]["intercept_mw"] >= 0
    assert asset["point_context"]["entity_count"] == len(
        asset["point_context"]["simulated_entities"]
    )
    entities = asset["point_context"]["simulated_entities"]
    assert entities
    # Every point entity carries its own authoritative ONS group, and the selected plant's
    # own entity carries the group of the selected asset.
    assert all(entity["ons_group_id"] for entity in entities)
    assert any(entity["ons_group_id"] == asset["ons_group_id"] for entity in entities)
