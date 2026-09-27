from __future__ import annotations

import argparse
import json
from pathlib import Path

from curtailess.exposure_forecast_import import (
    convert_forecast_artifact,
    validate_converted_forecast,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Valida e converte o artefato de previsão da aba Exposição."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = convert_forecast_artifact(args.source)
    validate_converted_forecast(payload)
    if args.output is None:
        print(f"validated {payload['source_sha256']} {len(payload['assets'])} assets")
        return 0
    if args.output.exists() and not args.force:
        raise SystemExit("output already exists; pass --force to replace it")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"stored {args.output} {payload['source_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
