#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.reference import (  # noqa: E402
    AddonCodeRelation,
    CodeEntry,
    CodebookRelease,
    MueEdit,
    NcciPtpEdit,
    PfsProcedureAttribute,
    RuleSourceDocument,
    utcnow,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    with SessionLocal() as session:
        release = session.get(CodebookRelease, args.release_id)
        if release is None:
            parser.error("Release not found")
        counts = {}
        models = {
            "codes": CodeEntry, "pfs": PfsProcedureAttribute, "ncci": NcciPtpEdit,
            "mue": MueEdit, "addon": AddonCodeRelation, "rules": RuleSourceDocument,
        }
        for name, model in models.items():
            counts[name] = session.scalar(select(func.count()).select_from(model).where(model.codebook_release_id == release.id)) or 0
        errors = [name for name, count in counts.items() if count == 0]
        release.validation_summary = {"record_counts": counts, "blocking_errors": len(errors), "empty_required_tables": errors}
        release.status = "rejected" if errors else "validated"
        release.validated_at = None if errors else utcnow()
        session.commit()
        print(release.validation_summary)
        return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
