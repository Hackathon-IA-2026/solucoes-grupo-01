from __future__ import annotations

import argparse
import sys

from curtailess.config import get_settings
from curtailess.data_access import create_exposure_repository
from curtailess.exposure_narrative import SECTION_IDS, generate_exposure_narrative
from curtailess.exposure_narrative_repository import (
    create_exposure_narrative_repository,
    merge_narrative_sections,
    resolve_cached_sections,
    section_evidence_digests,
)
from curtailess.exposure_view import APPROVED_ASSET_IDS, build_exposure_view


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materializa narrativas validadas da aba Exposição no DynamoDB."
    )
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--asset-id", choices=APPROVED_ASSET_IDS)
    selection.add_argument("--all", action="store_true")
    return parser


def materialize_asset(asset_id: str, settings, data_repository, narrative_repository) -> str:
    """Resolve compatible sections, generate only what is missing, and persist the merge."""

    view = build_exposure_view(asset_id, data_repository)
    evidence_digests = section_evidence_digests(view)
    cached = resolve_cached_sections(view, narrative_repository)
    missing = [section_id for section_id in SECTION_IDS if section_id not in cached]
    model_id: str | None = None
    generated = None
    if missing:
        generated, model_id = generate_exposure_narrative(view, settings=settings)
    narrative = merge_narrative_sections(view, cached, generated)
    version = narrative_repository.save(
        asset_id,
        view.input_digest,
        narrative,
        model_id,
        section_evidence_digests=evidence_digests,
    )
    cached_count = len(SECTION_IDS) - len(missing)
    return f"{asset_id}: stored {version} cached={cached_count} generated={len(missing)}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    if not settings.exposure_narratives_table:
        print(
            "EXPOSURE_NARRATIVES_TABLE não configurada; nenhuma chamada Bedrock foi feita.",
            file=sys.stderr,
        )
        return 2
    data_repository = create_exposure_repository(settings.exposure_table, settings.aws_region)
    narrative_repository = create_exposure_narrative_repository(
        settings.exposure_narratives_table, settings.aws_region
    )
    identifiers = APPROVED_ASSET_IDS if args.all else (args.asset_id,)
    for asset_id in identifiers:
        print(materialize_asset(asset_id, settings, data_repository, narrative_repository))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
