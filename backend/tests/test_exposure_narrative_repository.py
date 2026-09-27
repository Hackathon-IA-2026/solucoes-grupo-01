import json

import pytest

from curtailess.exposure_narrative import SECTION_IDS, deterministic_exposure_narrative
from curtailess.exposure_narrative_repository import (
    NARRATIVE_SCHEMA_VERSION,
    InMemoryExposureNarrativeRepository,
    merge_narrative_sections,
    resolve_cached_sections,
    resolve_exposure_narrative,
    section_content_digest,
    section_evidence_digests,
)
from curtailess.exposure_view import build_exposure_view
from curtailess.schemas import ExposureNarrative, ExposureNarrativeSection

ASSET_ID = "RNEM13"
_NEUTRAL = "A leitura desta seção usa somente os fatos fornecidos para ela."
_ALT_NEUTRAL = "Este bloco interpreta apenas a evidência da própria seção."
_UNSUPPORTED = "A energia restringida total foi de 987654.321 MWh."


def _narrative(overrides=None, mode="bedrock") -> ExposureNarrative:
    payload = {
        section_id: {"paragraphs": [_NEUTRAL], "generation_mode": mode}
        for section_id in SECTION_IDS
    }
    payload.update(overrides or {})
    return ExposureNarrative.model_validate(payload)


def _section(narrative, section_id):
    return getattr(narrative, section_id.replace("-", "_"))


def _mode(narrative, section_id):
    return _section(narrative, section_id).generation_mode


def _paragraphs(narrative, section_id):
    return _section(narrative, section_id).paragraphs


def _seed(repository, view, narrative, model_id="model-primary"):
    return repository.save(
        view.asset.asset_id,
        view.input_digest,
        narrative,
        model_id,
        section_evidence_digests=section_evidence_digests(view),
    )


def _drop_section_records(repository, asset_id):
    for key in [key for key in repository.items if key[1].startswith("SECTION#")]:
        repository.items.pop(key)


def test_repository_saves_immutable_version_current_pointer_and_digests():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    narrative = _narrative()
    digests = section_evidence_digests(view)

    version = _seed(repository, view, narrative)
    current = repository.get_current_record(view.asset.asset_id)

    assert version == f"VERSION#{NARRATIVE_SCHEMA_VERSION}#{view.input_digest}"
    assert repository.get_exact(view.asset.asset_id, view.input_digest) == narrative
    assert current is not None
    assert current["version_key"] == version
    assert current["schema_version"] == NARRATIVE_SCHEMA_VERSION
    assert current["input_digest"] == view.input_digest
    assert current["section_evidence_digests"] == digests
    assert current["section_content_digests"] == {
        section_id: section_content_digest(_section(narrative, section_id))
        for section_id in SECTION_IDS
    }


def test_repository_replays_same_version_and_rejects_different_content():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    narrative = _narrative()
    _seed(repository, view, narrative)
    _seed(repository, view, narrative)

    changed = narrative.model_copy(
        update={
            "secao_resumo": ExposureNarrativeSection(
                paragraphs=("Um texto incompatível com a versão imutável.",),
                generation_mode="bedrock",
            )
        }
    )
    with pytest.raises(ValueError, match="immutable"):
        repository.save(
            view.asset.asset_id,
            view.input_digest,
            changed,
            None,
            section_evidence_digests=section_evidence_digests(view),
        )


def test_section_versions_are_keyed_by_the_exact_evidence_digest():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    narrative = _narrative()
    _seed(repository, view, narrative)
    digests = section_evidence_digests(view)

    stored = repository.get_section(view.asset.asset_id, "secao-ativo", digests["secao-ativo"])
    assert stored is not None
    assert stored.generation_mode == "bedrock"
    assert stored.paragraphs == (_NEUTRAL,)
    # A different (stale) evidence digest has no compatible version.
    assert repository.get_section(view.asset.asset_id, "secao-ativo", "0" * 64) is None


def test_tampered_section_record_is_rejected_by_its_content_digest():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    _seed(repository, view, _narrative())
    digests = section_evidence_digests(view)
    key = (
        view.asset.asset_id,
        f"SECTION#{NARRATIVE_SCHEMA_VERSION}#secao-ativo#{digests['secao-ativo']}",
    )
    repository.items[key]["section"]["paragraphs"] = [_UNSUPPORTED]

    with pytest.raises(ValueError, match="content digest"):
        repository.get_section(view.asset.asset_id, "secao-ativo", digests["secao-ativo"])


def test_immutable_section_rejects_different_content_for_the_same_evidence():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    _seed(repository, view, _narrative())
    other = _narrative(
        {"secao-ativo": {"paragraphs": [_ALT_NEUTRAL], "generation_mode": "bedrock"}}
    )

    with pytest.raises(ValueError, match="immutable narrative section"):
        repository.save(
            view.asset.asset_id,
            "f" * 64,
            other,
            "model-primary",
            section_evidence_digests=section_evidence_digests(view),
        )


def test_exact_replay_returns_cached_bedrock_sections():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    narrative = _narrative()
    _seed(repository, view, narrative)

    resolved = resolve_exposure_narrative(view, repository)

    for section_id in SECTION_IDS:
        assert _mode(resolved, section_id) == "cached_bedrock"
        assert _paragraphs(resolved, section_id) == (_NEUTRAL,)


def test_safe_mixed_merge_keeps_five_valid_sections_for_one_invalid():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    narrative = _narrative(
        {"secao-previsao": {"paragraphs": [_NEUTRAL], "generation_mode": "deterministic_fallback"}}
    )
    _seed(repository, view, narrative)

    cached = resolve_cached_sections(view, repository)
    resolved = merge_narrative_sections(view, cached)

    assert _mode(resolved, "secao-previsao") == "deterministic_fallback"
    for section_id in SECTION_IDS:
        if section_id == "secao-previsao":
            continue
        assert _mode(resolved, section_id) == "cached_bedrock"
        assert _paragraphs(resolved, section_id) == (_NEUTRAL,)
    # The five cached sections keep their exact persisted content, never the fallback text.
    fallback = deterministic_exposure_narrative(view)
    assert _paragraphs(resolved, "secao-ativo") == _paragraphs(narrative, "secao-ativo")
    assert _paragraphs(resolved, "secao-ativo") != _paragraphs(fallback, "secao-ativo")


def test_deterministic_fallback_when_no_compatible_bedrock_exists():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)

    resolved = resolve_exposure_narrative(view, repository)

    assert resolved == deterministic_exposure_narrative(view)
    assert all(
        _mode(resolved, section_id) == "deterministic_fallback" for section_id in SECTION_IDS
    )


def test_current_pointer_sections_are_reused_only_when_they_still_validate():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    _seed(repository, view, _narrative())
    _drop_section_records(repository, view.asset.asset_id)

    resolved = resolve_exposure_narrative(view, repository)

    for section_id in SECTION_IDS:
        assert _mode(resolved, section_id) == "cached_bedrock"
        assert _paragraphs(resolved, section_id) == (_NEUTRAL,)


def test_current_pointer_rejects_one_stale_section_without_discarding_siblings():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    stale = _narrative(
        {"secao-qualidade": {"paragraphs": [_UNSUPPORTED], "generation_mode": "bedrock"}}
    )
    _seed(repository, view, stale)
    _drop_section_records(repository, view.asset.asset_id)

    resolved = resolve_exposure_narrative(view, repository)

    assert _mode(resolved, "secao-qualidade") == "deterministic_fallback"
    for section_id in SECTION_IDS:
        if section_id == "secao-qualidade":
            continue
        assert _mode(resolved, section_id) == "cached_bedrock"
        assert _paragraphs(resolved, section_id) == (_NEUTRAL,)


def test_exact_section_version_is_preferred_over_the_current_pointer():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    narrative = _narrative()
    _seed(repository, view, narrative)
    other = _narrative(
        {"secao-ativo": {"paragraphs": [_ALT_NEUTRAL], "generation_mode": "bedrock"}}
    )
    repository.items[(view.asset.asset_id, "CURRENT")] = {
        **repository.items[(view.asset.asset_id, "CURRENT")],
        "narrative": other.model_dump(mode="json", by_alias=True),
    }

    resolved = resolve_exposure_narrative(view, repository)

    assert _paragraphs(resolved, "secao-ativo") == (_NEUTRAL,)
    assert _mode(resolved, "secao-ativo") == "cached_bedrock"


def test_persisted_item_stays_below_the_dynamodb_size_limit():
    repository = InMemoryExposureNarrativeRepository()
    view = build_exposure_view(ASSET_ID)
    _seed(repository, view, _narrative())

    for item in repository.items.values():
        assert len(json.dumps(item, ensure_ascii=False)) < 350_000
