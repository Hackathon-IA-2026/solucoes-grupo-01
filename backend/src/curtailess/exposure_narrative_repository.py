"""Versioned, section-scoped persistence for validated Exposure narratives.

Every persisted key carries the section-level ``NARRATIVE_SCHEMA_VERSION``, so a record
written under an older layout can never be read as if it were current. The consolidated
version record keeps the canonical ``input_digest`` plus the per-section evidence and
content digests. Each accepted Bedrock section is also stored on its own, keyed by its
evidence digest, so a later view that exposes the exact same section evidence replays it
as ``cached_bedrock`` without another Bedrock call. Sections with no compatible Bedrock
version fall back deterministically, one section at a time: a single invalid section never
discards the valid siblings. The current pointer only moves after a complete validated
narrative is persisted.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import boto3
from botocore.exceptions import ClientError

from curtailess.canonical import canonical_json
from curtailess.exposure_narrative import (
    _SECTION_FIELDS,
    SECTION_IDS,
    _section_evidence_payloads,
    deterministic_exposure_narrative,
    validate_section_narrative,
)
from curtailess.schemas import (
    ExposureNarrative,
    ExposureNarrativeSection,
    ExposureViewResponse,
)

logger = logging.getLogger(__name__)

# Section-level narrative schema. Bumped from the consolidated-only layout so that every
# key, digest and section record is unambiguous about the shape it stores.
NARRATIVE_SCHEMA_VERSION = "exposure-narrative-v2"

_CACHED_MODES = ("bedrock", "cached_bedrock")
_SECTION_PREFIX = "SECTION"


def _digest(value: Any) -> str:
    return sha256(canonical_json(value).encode()).hexdigest()


def _version_sort_key(input_digest: str) -> str:
    return f"VERSION#{NARRATIVE_SCHEMA_VERSION}#{input_digest}"


def _section_sort_key(section_id: str, evidence_digest: str) -> str:
    return f"{_SECTION_PREFIX}#{NARRATIVE_SCHEMA_VERSION}#{section_id}#{evidence_digest}"


def section_evidence_digests(
    view: ExposureViewResponse | Mapping[str, Any],
) -> dict[str, str]:
    """Per-section evidence digest of the facts the section is allowed to cite."""

    evidence = _section_evidence_payloads(view)
    return {section_id: _digest(evidence[section_id]) for section_id in SECTION_IDS}


def section_content_digest(section: ExposureNarrativeSection) -> str:
    """Content digest over the paragraphs only, so relabeling a cached section is stable."""

    return _digest({"paragraphs": list(section.paragraphs)})


def _section_of(narrative: ExposureNarrative, section_id: str) -> ExposureNarrativeSection:
    return getattr(narrative, _SECTION_FIELDS[section_id])


def _narrative_generation_mode(narrative: ExposureNarrative) -> str:
    modes = {_section_of(narrative, section_id).generation_mode for section_id in SECTION_IDS}
    if "bedrock" in modes:
        return "bedrock"
    if "cached_bedrock" in modes:
        return "cached_bedrock"
    return "deterministic_fallback"


def _version_item(
    asset_id: str,
    input_digest: str,
    narrative: ExposureNarrative,
    model_id: str | None,
    evidence_digests: Mapping[str, str],
    created_at: str,
) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "version": _version_sort_key(input_digest),
        "input_digest": input_digest,
        "schema_version": NARRATIVE_SCHEMA_VERSION,
        "narrative": narrative.model_dump(mode="json", by_alias=True),
        "generation_mode": _narrative_generation_mode(narrative),
        "model_id": model_id,
        "validation_status": "validated",
        "section_evidence_digests": {
            section_id: evidence_digests[section_id] for section_id in SECTION_IDS
        },
        "section_content_digests": {
            section_id: section_content_digest(_section_of(narrative, section_id))
            for section_id in SECTION_IDS
        },
        "created_at": created_at,
    }


def _section_item(
    asset_id: str,
    section_id: str,
    section: ExposureNarrativeSection,
    evidence_digest: str,
    model_id: str | None,
    created_at: str,
) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "version": _section_sort_key(section_id, evidence_digest),
        "section_id": section_id,
        "schema_version": NARRATIVE_SCHEMA_VERSION,
        "evidence_digest": evidence_digest,
        "content_digest": section_content_digest(section),
        "section": section.model_dump(mode="json", by_alias=True),
        "generation_mode": section.generation_mode,
        "model_id": model_id,
        "created_at": created_at,
    }


def _validate_section_record(
    item: Mapping[str, Any], section_id: str, evidence_digest: str
) -> ExposureNarrativeSection | None:
    if item.get("schema_version") != NARRATIVE_SCHEMA_VERSION:
        return None
    if item.get("section_id") != section_id or item.get("evidence_digest") != evidence_digest:
        raise ValueError("stored exposure narrative section does not match its key")
    section = ExposureNarrativeSection.model_validate(item["section"])
    if section_content_digest(section) != item.get("content_digest"):
        raise ValueError("stored exposure narrative section content digest mismatch")
    return section


class ExposureNarrativeRepository:
    def __init__(self, table: Any):
        self.table = table

    def get_exact(self, asset_id: str, input_digest: str) -> ExposureNarrative | None:
        response = self.table.get_item(
            Key={"asset_id": asset_id, "version": _version_sort_key(input_digest)},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            return None
        if item.get("input_digest") != input_digest:
            raise ValueError("stored exposure narrative digest does not match its key")
        if item.get("schema_version") != NARRATIVE_SCHEMA_VERSION:
            return None
        return ExposureNarrative.model_validate(item["narrative"])

    def get_current_record(self, asset_id: str) -> dict[str, Any] | None:
        response = self.table.get_item(
            Key={"asset_id": asset_id, "version": "CURRENT"},
            ConsistentRead=True,
        )
        item = response.get("Item")
        return dict(item) if item is not None else None

    def get_section(
        self, asset_id: str, section_id: str, evidence_digest: str
    ) -> ExposureNarrativeSection | None:
        response = self.table.get_item(
            Key={
                "asset_id": asset_id,
                "version": _section_sort_key(section_id, evidence_digest),
            },
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            return None
        return _validate_section_record(item, section_id, evidence_digest)

    def save(
        self,
        asset_id: str,
        input_digest: str,
        narrative: ExposureNarrative,
        model_id: str | None,
        *,
        section_evidence_digests: Mapping[str, str],
    ) -> str:
        created_at = datetime.now(UTC).isoformat()
        item = _version_item(
            asset_id, input_digest, narrative, model_id, section_evidence_digests, created_at
        )
        self._save_sections(asset_id, narrative, model_id, section_evidence_digests, created_at)
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression=(
                    "attribute_not_exists(asset_id) AND attribute_not_exists(version)"
                ),
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            stored = self.get_exact(asset_id, input_digest)
            if stored != narrative:
                raise ValueError(
                    "immutable narrative version already contains different content"
                ) from exc
        self.table.put_item(
            Item={
                **item,
                "version": "CURRENT",
                "version_key": item["version"],
            }
        )
        return item["version"]

    def _save_sections(
        self,
        asset_id: str,
        narrative: ExposureNarrative,
        model_id: str | None,
        evidence_digests: Mapping[str, str],
        created_at: str,
    ) -> None:
        for section_id in SECTION_IDS:
            section = _section_of(narrative, section_id)
            if section.generation_mode not in _CACHED_MODES:
                continue
            section_item = _section_item(
                asset_id,
                section_id,
                section,
                evidence_digests[section_id],
                model_id,
                created_at,
            )
            try:
                self.table.put_item(
                    Item=section_item,
                    ConditionExpression=(
                        "attribute_not_exists(asset_id) AND attribute_not_exists(version)"
                    ),
                )
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise
                existing = self.table.get_item(
                    Key={"asset_id": asset_id, "version": section_item["version"]},
                    ConsistentRead=True,
                ).get("Item")
                if (
                    existing is None
                    or existing.get("content_digest") != section_item["content_digest"]
                ):
                    raise ValueError(
                        "immutable narrative section "
                        f"{section_id} already contains different content"
                    ) from exc


class InMemoryExposureNarrativeRepository:
    def __init__(self):
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def get_exact(self, asset_id: str, input_digest: str) -> ExposureNarrative | None:
        item = self.items.get((asset_id, _version_sort_key(input_digest)))
        if item is None or item.get("schema_version") != NARRATIVE_SCHEMA_VERSION:
            return None
        return ExposureNarrative.model_validate(item["narrative"])

    def get_current_record(self, asset_id: str) -> dict[str, Any] | None:
        item = self.items.get((asset_id, "CURRENT"))
        return dict(item) if item else None

    def get_section(
        self, asset_id: str, section_id: str, evidence_digest: str
    ) -> ExposureNarrativeSection | None:
        item = self.items.get((asset_id, _section_sort_key(section_id, evidence_digest)))
        if item is None:
            return None
        return _validate_section_record(item, section_id, evidence_digest)

    def save(
        self,
        asset_id: str,
        input_digest: str,
        narrative: ExposureNarrative,
        model_id: str | None,
        *,
        section_evidence_digests: Mapping[str, str],
    ) -> str:
        created_at = datetime.now(UTC).isoformat()
        item = _version_item(
            asset_id, input_digest, narrative, model_id, section_evidence_digests, created_at
        )
        section_items = [
            _section_item(
                asset_id,
                section_id,
                _section_of(narrative, section_id),
                section_evidence_digests[section_id],
                model_id,
                created_at,
            )
            for section_id in SECTION_IDS
            if _section_of(narrative, section_id).generation_mode in _CACHED_MODES
        ]
        for section_item in section_items:
            stored = self.items.get((asset_id, section_item["version"]))
            if stored is not None and stored["content_digest"] != section_item["content_digest"]:
                raise ValueError(
                    "immutable narrative section "
                    f"{section_item['section_id']} already contains different content"
                )
        existing = self.items.get((asset_id, item["version"]))
        if existing is not None and existing["narrative"] != item["narrative"]:
            raise ValueError("immutable narrative version already contains different content")
        for section_item in section_items:
            self.items[(asset_id, section_item["version"])] = section_item
        self.items[(asset_id, item["version"])] = item
        self.items[(asset_id, "CURRENT")] = {
            **item,
            "version": "CURRENT",
            "version_key": item["version"],
        }
        return item["version"]


def _relabel_cached(section: ExposureNarrativeSection) -> ExposureNarrativeSection:
    if section.generation_mode == "bedrock":
        return section.model_copy(update={"generation_mode": "cached_bedrock"})
    return section


def _current_sections(repository: Any, asset_id: str) -> dict[str, ExposureNarrativeSection]:
    try:
        record = repository.get_current_record(asset_id)
        if not record or record.get("validation_status") != "validated":
            return {}
        if record.get("schema_version") != NARRATIVE_SCHEMA_VERSION:
            return {}
        narrative = ExposureNarrative.model_validate(record["narrative"])
    except (KeyError, TypeError, ValueError):
        return {}
    return {section_id: _section_of(narrative, section_id) for section_id in SECTION_IDS}


def _compatible_current_section(
    section: ExposureNarrativeSection | None, section_id: str, evidence: Mapping[str, Any]
) -> ExposureNarrativeSection | None:
    """Accept a current-pointer section only when it still validates against today's facts."""

    if section is None or section.generation_mode not in _CACHED_MODES:
        return None
    try:
        return validate_section_narrative(
            section_id, section.paragraphs, evidence, generation_mode="cached_bedrock"
        )
    except ValueError as exc:
        logger.warning(
            "Seção %s armazenada é incompatível com a evidência atual: %s", section_id, exc
        )
        return None


def _asset_id(view: ExposureViewResponse | Mapping[str, Any]) -> str:
    if isinstance(view, ExposureViewResponse):
        return view.asset.asset_id
    return str((view.get("asset") or {})["asset_id"])


def resolve_cached_sections(
    view: ExposureViewResponse | Mapping[str, Any], repository: Any
) -> dict[str, ExposureNarrativeSection]:
    """Resolve each section independently: exact compatible version, then compatible current."""

    asset_id = _asset_id(view)
    evidence = _section_evidence_payloads(view)
    digests = {section_id: _digest(evidence[section_id]) for section_id in SECTION_IDS}
    cached: dict[str, ExposureNarrativeSection] = {}
    for section_id in SECTION_IDS:
        try:
            section = repository.get_section(asset_id, section_id, digests[section_id])
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Seção %s armazenada é inválida: %s", section_id, exc)
            section = None
        if section is not None:
            cached[section_id] = _relabel_cached(section)
    missing = [section_id for section_id in SECTION_IDS if section_id not in cached]
    if missing:
        current = _current_sections(repository, asset_id)
        for section_id in missing:
            section = _compatible_current_section(
                current.get(section_id), section_id, evidence[section_id]
            )
            if section is not None:
                cached[section_id] = section
    return cached


def merge_narrative_sections(
    view: ExposureViewResponse | Mapping[str, Any],
    cached: Mapping[str, ExposureNarrativeSection],
    generated: ExposureNarrative | None = None,
) -> ExposureNarrative:
    """Merge section by section: cached Bedrock wins, then generated, then deterministic.

    A missing or invalid section only affects itself; the valid siblings are preserved.
    """

    fallback = generated if generated is not None else deterministic_exposure_narrative(view)
    merged = {
        section_id: cached.get(section_id) or _section_of(fallback, section_id)
        for section_id in SECTION_IDS
    }
    return ExposureNarrative.model_validate(merged)


def resolve_exposure_narrative(
    view: ExposureViewResponse | Mapping[str, Any],
    repository: Any,
    generated: ExposureNarrative | None = None,
) -> ExposureNarrative:
    """Public resolution used by the API and the materialization command."""

    return merge_narrative_sections(view, resolve_cached_sections(view, repository), generated)


def create_exposure_narrative_repository(
    table_name: str | None, region_name: str
) -> ExposureNarrativeRepository | InMemoryExposureNarrativeRepository:
    if not table_name:
        return InMemoryExposureNarrativeRepository()
    table = boto3.resource("dynamodb", region_name=region_name).Table(  # type: ignore[attr-defined]
        table_name
    )
    return ExposureNarrativeRepository(table)
