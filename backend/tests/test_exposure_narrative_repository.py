import pytest

from curtailess.exposure_narrative_repository import InMemoryExposureNarrativeRepository
from curtailess.exposure_view import build_exposure_view


def test_repository_saves_immutable_version_and_current_pointer():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view("CJU_RNRDV")

    version = repository.save(
        view.asset.asset_id,
        view.input_digest,
        view.narrative,
        "model-primary",
    )

    current = repository.get_current_record(view.asset.asset_id)
    assert version.endswith(view.input_digest)
    assert repository.get_exact(view.asset.asset_id, view.input_digest) == view.narrative
    assert current is not None
    assert current["version_key"] == version


def test_repository_replays_same_version_and_rejects_different_content():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view("CJU_RNRDV")
    repository.save(view.asset.asset_id, view.input_digest, view.narrative, None)
    repository.save(view.asset.asset_id, view.input_digest, view.narrative, None)

    changed = view.narrative.model_copy(
        update={"secao_resumo": ("Um texto incompatível com a versão imutável.",)}
    )
    with pytest.raises(ValueError, match="immutable"):
        repository.save(view.asset.asset_id, view.input_digest, changed, None)
