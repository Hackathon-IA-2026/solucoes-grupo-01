from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import curtailess.main as main
from curtailess.plant_state import build_plant_state

AS_OF = datetime(2026, 9, 27, 3, 30, tzinfo=UTC)


class FakeExposureRepository:
    def __init__(self, *, stale: bool = False, asset_profiles: bool = True):
        self.stale = stale
        self.asset_profiles = asset_profiles
        self.asset = {
            "asset_id": "CJU_TEST",
            "period": "2026-08",
            "technology": "wind",
            "state": "RN",
            "generation_mwh": 300,
            "availability_mwh": 450,
            "reference_generation_mwh": 500,
            "limited_generation_mwh": 300,
            "availability_limited_mwh": 400,
            "curtailed_mwh": 50,
            "source_key": "raw/ons/restricao/august.parquet",
            "source_sha256": "a" * 64,
            "source_fingerprint": "1" * 64,
        }
        self.identity = {
            "asset_id": "CJU_TEST",
            "period": "identity#relationship#2020-01-01#GROUP_TEST",
            "ons_group_id": "GROUP_TEST",
            "technology_name": "EOLIELÉTRICA",
            "state": "RN",
            "ceg": "CEG-TEST",
            "source_key": "raw/ons/usina_conjunto/snapshot.parquet",
            "source_sha256": "b" * 64,
            "source_fingerprint": "2" * 64,
            "capacity": {
                "asset_id": "ceg:CEG-TEST",
                "period": "identity#capacity#snapshot",
                "active_capacity_mw": 100,
                "capacity_as_of": "2026-09-27",
                "source_key": "raw/ons/capacidade/snapshot.parquet",
                "source_sha256": "c" * 64,
                "source_fingerprint": "3" * 64,
            },
        }
        self.forecast = {
            "program_entity_id": "CJU_TEST",
            "program_entity_name": "Teste",
            "valid_at": "2026-09-27T00:30:00-03:00",
            "forecast_mw": 80,
            "programmed_mw": 75,
            "publication_timestamp": (AS_OF - timedelta(hours=72 if stale else 2)).isoformat(),
            "publication_time_status": "source_object_last_modified_proxy",
            "source_key": "raw/ons/programacao/forecast.parquet",
            "source_sha256": "d" * 64,
            "source_fingerprint": "4" * 64,
        }
        self.profile = {
            "asset_id": "CJU_TEST" if asset_profiles else "GROUP_TEST",
            "period": "generation#2026-08",
            "season": "winter",
            "mean_generation_mw": 60,
            "hour_of_day_profile": {"00": {"mean_mw": 65, "observation_count": 31}},
            "source_key": "raw/ons/geracao/august.parquet",
            "source_sha256": "e" * 64,
            "source_fingerprint": "5" * 64,
        }

    def get_asset(self, asset_id):
        return self.asset if asset_id == "CJU_TEST" else None

    def get_identity(self, asset_id, as_of):
        return self.identity if asset_id == "CJU_TEST" else None

    def get_forecast(self, program_entity_id, valid_at):
        del valid_at
        return self.forecast if program_entity_id == "CJU_TEST" else None

    def get_generation_profiles(self, asset_id, start_period=None, end_period=None):
        del start_period, end_period
        expected = "CJU_TEST" if self.asset_profiles else "GROUP_TEST"
        return [self.profile] if asset_id == expected else []


class FakeSnapshotRepository:
    def __init__(self):
        self.items = {}

    def put_snapshot(self, response):
        payload = response.model_dump(mode="json")
        previous = self.items.setdefault(response.snapshot_id, payload)
        if previous != payload:
            raise RuntimeError("snapshot conflict")
        return response

    def get_snapshot(self, snapshot_id):
        return self.items.get(snapshot_id)


def test_equal_inputs_produce_identical_simulated_state_and_snapshot() -> None:
    source = FakeExposureRepository()
    snapshots = FakeSnapshotRepository()

    first = build_plant_state("CJU_TEST", AS_OF, source, snapshots, max_forecast_age_hours=48)
    second = build_plant_state("CJU_TEST", AS_OF, source, snapshots, max_forecast_age_hours=48)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.status == "SIMULATED"
    assert first.fallback_level == "asset"
    assert first.generation_mw.origin == "SIMULADO"
    assert first.availability_mw.origin == "SIMULADO"
    assert first.reference_generation_mw.origin == "SIMULADO"
    assert first.generation_limit_mw.origin == "SIMULADO"
    assert first.public_forecast_mw.origin == "ONS_PUBLICO"
    assert (
        0
        <= first.generation_mw.value
        <= first.generation_limit_mw.value
        <= first.availability_mw.value
        <= 100
    )
    assert first.snapshot_id in snapshots.items


def test_group_fallback_is_recorded() -> None:
    response = build_plant_state(
        "CJU_TEST",
        AS_OF,
        FakeExposureRepository(asset_profiles=False),
        FakeSnapshotRepository(),
        max_forecast_age_hours=48,
    )

    assert response.status == "SIMULATED"
    assert response.fallback_level == "ons_group"


def test_stale_forecast_returns_review_required_without_simulated_values() -> None:
    response = build_plant_state(
        "CJU_TEST",
        AS_OF,
        FakeExposureRepository(stale=True),
        FakeSnapshotRepository(),
        max_forecast_age_hours=48,
    )

    assert response.status == "REVIEW_REQUIRED"
    assert response.generation_mw is None
    assert response.public_forecast_mw is None
    assert "desatualizada" in " ".join(response.limitations).lower()


def test_plant_state_api_returns_deterministic_snapshot(monkeypatch) -> None:
    source = FakeExposureRepository()
    snapshots = FakeSnapshotRepository()
    monkeypatch.setattr(main, "repository", source)
    monkeypatch.setattr(main, "plant_state_repository", snapshots)
    client = TestClient(main.app)

    response = client.get(
        "/v1/assets/CJU_TEST/plant-state",
        params={"as_of": AS_OF.isoformat()},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "SIMULATED"
    assert payload["generation_mw"]["origin"] == "SIMULADO"
    assert payload["public_forecast_mw"]["origin"] == "ONS_PUBLICO"
