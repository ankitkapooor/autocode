#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.reference_data.pipeline import import_reference_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize a complete OrthoCode reference-data bundle")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--release-name", default="2026-Q3")
    parser.add_argument("--effective-from", type=date.fromisoformat, default=date(2026, 7, 1))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--publish", action="store_true")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Validate but do not materialize the multi-million-row NCCI corpus",
    )
    args = parser.parse_args()

    if args.dry_run:
        report = import_reference_bundle(
            None, args.source_root, args.release_name, args.effective_from, dry_run=True
        )
    else:
        Base.metadata.create_all(bind=engine)
        settings = get_settings()
        with SessionLocal() as session:
            report = import_reference_bundle(
                session,
                args.source_root,
                args.release_name,
                args.effective_from,
                publish=args.publish,
                materialize_ncci=not args.preview,
                ncci_index_path=settings.ncci_index_path if args.preview else None,
            )
    print(json.dumps(report, indent=2, default=str))
    return 1 if report["blocking_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
