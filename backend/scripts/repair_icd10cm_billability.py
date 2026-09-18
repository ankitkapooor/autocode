#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models.reference import (  # noqa: E402
    CodeEntry,
    CodeSearchDocument,
    RawReferenceFile,
    new_id,
)
from app.reference_data.adapters import parse_icd10cm_order_rows  # noqa: E402
from app.reference_data.pipeline import discover_files  # noqa: E402
from app.repositories import CodebookRepository  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Repair the active release from the authoritative ICD-10-CM order file, "
            "including billable seventh-character codes."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the repair. Without this flag the script performs a dry run.",
    )
    args = parser.parse_args()

    settings = get_settings()
    files = [
        item
        for item in discover_files(settings.reference_data_path)
        if item.source_family == "icd10cm"
    ]
    with SessionLocal() as session:
        release = CodebookRepository(session).active_release()
        authoritative = parse_icd10cm_order_rows(files, release.effective_from)
        existing = {
            entry.code_key: entry
            for entry in session.scalars(
                select(CodeEntry).where(
                    CodeEntry.codebook_release_id == release.id,
                    CodeEntry.code_system == "ICD10CM",
                )
            )
        }
        source_ids = set(session.scalars(select(RawReferenceFile.id)))
        missing_source_ids = {
            str(row["source_file_id"])
            for row in authoritative.values()
            if str(row["source_file_id"]) not in source_ids
        }
        if missing_source_ids:
            raise RuntimeError(
                "ICD repair is blocked because authoritative source files are not registered"
            )

        billable_updates = 0
        additions = 0
        for code_key, row in authoritative.items():
            entry = existing.get(code_key)
            if entry is not None:
                desired_billable = row.get("billable")
                if entry.billable != desired_billable:
                    billable_updates += 1
                    if args.apply:
                        entry.billable = desired_billable
                continue
            additions += 1
            if not args.apply:
                continue
            parent_key = code_key[:-1]
            while (
                len(parent_key) >= 3
                and parent_key not in existing
                and parent_key not in authoritative
            ):
                parent_key = parent_key[:-1]
            existing_parent = existing.get(parent_key)
            authoritative_parent = authoritative.get(parent_key)
            parent_code = (
                existing_parent.code
                if existing_parent is not None
                else (
                    str(authoritative_parent["code"])
                    if authoritative_parent is not None
                    else None
                )
            )
            chapter = existing_parent.chapter if existing_parent is not None else None
            entry_id = new_id()
            description = row.get("long_description") or row.get("short_description") or ""
            session.add(
                CodeEntry(
                    id=entry_id,
                    codebook_release_id=release.id,
                    code_system="ICD10CM",
                    code=str(row["code"]),
                    code_key=code_key,
                    short_description=row.get("short_description"),
                    long_description=row.get("long_description"),
                    effective_from=row.get("effective_from"),
                    effective_to=row.get("effective_to"),
                    billable=row.get("billable"),
                    category=row.get("category"),
                    chapter=chapter,
                    parent_code=parent_code,
                    anatomic_region=row.get("anatomic_region"),
                    laterality_supported=row.get("laterality_supported"),
                    metadata_json=row.get("metadata_json") or {},
                    source_version=str(row.get("source_version") or "unknown"),
                    source_file_id=str(row["source_file_id"]),
                )
            )
            session.add(
                CodeSearchDocument(
                    id=new_id(),
                    codebook_release_id=release.id,
                    code_entry_id=entry_id,
                    code=str(row["code"]),
                    description=description or None,
                    synonyms=[],
                    anatomic_region=row.get("anatomic_region"),
                    procedure_family=None,
                    search_text=f"{row['code']} {description}".lower().strip(),
                    embedding=None,
                )
            )
        if args.apply:
            session.commit()
        else:
            session.rollback()
        print(
            json.dumps(
                {
                    "release_id": release.id,
                    "mode": "apply" if args.apply else "dry_run",
                    "authoritative_codes": len(authoritative),
                    "billable_updates": billable_updates,
                    "codes_added": additions,
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
