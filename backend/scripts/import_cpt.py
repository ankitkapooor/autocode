#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.reference import (  # noqa: E402
    CodeEntry,
    CodeSearchDocument,
    CodebookRelease,
    RawReferenceFile,
    new_id,
)
from app.reference_data.utils import canonical_code, parse_date, sha256_file  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Import separately licensed CPT data into a staged release")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error("Licensed CPT source file does not exist")

    with SessionLocal() as session:
        release = session.get(CodebookRelease, args.release_id)
        if release is None:
            parser.error("Release not found")
        if release.status not in {"staged", "rejected"}:
            parser.error("Licensed CPT can only be added to a staged or rejected release")
        raw_id = new_id()
        session.add(
            RawReferenceFile(
                id=raw_id,
                import_run_id=release.import_run_id,
                original_filename=args.source.name,
                relative_path=f"LICENSED_CODEBOOK_DATA/{args.source.name}",
                source_family="cpt_licensed",
                release_name=release.name,
                release_effective_from=release.effective_from,
                file_size=args.source.stat().st_size,
                sha256=sha256_file(args.source),
                parser_version="licensed-cpt-csv-v1",
                metadata_json={"licensed_boundary": True},
            )
        )
        session.flush()
        count = 0
        with args.source.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            required = {"code", "short_description"}
            if not required.issubset(reader.fieldnames or []):
                parser.error("CPT CSV requires code and short_description columns")
            for row in reader:
                code = row["code"].strip().upper()
                key = canonical_code(code)
                if not key:
                    continue
                exists = session.scalar(
                    select(CodeEntry.id).where(
                        CodeEntry.codebook_release_id == release.id,
                        CodeEntry.code_system == "CPT",
                        CodeEntry.code_key == key,
                    )
                )
                if exists:
                    continue
                entry_id = new_id()
                description = row.get("long_description") or row["short_description"]
                session.add(
                    CodeEntry(
                        id=entry_id,
                        codebook_release_id=release.id,
                        code_system="CPT",
                        code=code,
                        code_key=key,
                        short_description=row["short_description"].strip(),
                        long_description=description.strip(),
                        effective_from=parse_date(row.get("effective_from"), release.effective_from),
                        effective_to=parse_date(row.get("effective_to")),
                        billable=str(row.get("billable", "true")).lower() in {"1", "true", "yes"},
                        category=row.get("category") or None,
                        metadata_json={"licensed_boundary": True},
                        source_version=release.name,
                        source_file_id=raw_id,
                    )
                )
                session.add(
                    CodeSearchDocument(
                        id=new_id(), codebook_release_id=release.id, code_entry_id=entry_id,
                        code=code, description=description.strip(), synonyms=[],
                        search_text=f"{code} {description}".lower(), embedding=None,
                    )
                )
                count += 1
        release.status = "staged"
        session.commit()
    print(f"Imported {count} licensed CPT rows into staged release {args.release_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
