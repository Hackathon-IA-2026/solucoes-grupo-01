import json
from importlib.resources import files
from pathlib import Path

import pytest

from curtailess.exposure_forecast_import import (
    convert_forecast_artifact,
    validate_converted_forecast,
)

SOURCE = Path(
    "/run/media/carloshnp/D/Programming/hackaton-coppe-ia-11092026/"
    "estrategia/temp/simulacao-portfolio-cinco-ativos-60d-v1.json"
)


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
