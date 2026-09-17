#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.reference_data.pipeline import publish_release  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        release = publish_release(session, args.release_id, actor_id="cli")
        print(f"Published {release.name} ({release.id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
