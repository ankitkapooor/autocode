#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.reference_data.ncci_index import build_ncci_source_index  # noqa: E402
from app.reference_data.pipeline import discover_files  # noqa: E402
from app.reference_data.utils import manifest_sha256  # noqa: E402


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Build the compact runtime byte-range index for licensed NCCI PTP files"
    )
    parser.add_argument("--source-root", type=Path, default=settings.reference_data_path)
    parser.add_argument("--output", type=Path, default=settings.ncci_index_path)
    args = parser.parse_args()

    files = discover_files(args.source_root)
    fingerprint = manifest_sha256([(item.relative_path, item.sha256) for item in files])
    report = build_ncci_source_index(
        files,
        args.source_root,
        args.output,
        source_manifest_sha256=fingerprint,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
