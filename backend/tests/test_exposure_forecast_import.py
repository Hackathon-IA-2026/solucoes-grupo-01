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
        == "506d5edded7592019e0920c631c08b506deffc31ffa6b313e3d729a81394e0e1"
    )
    assert sum(len(asset["forecasts"]) for asset in bundled["assets"]) == 300


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
