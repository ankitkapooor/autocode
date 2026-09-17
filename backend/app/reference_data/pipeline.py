from __future__ import annotations

import csv
import hashlib
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.reference import (
    AddonCodeRelation,
    CodebookRelease,
    CodeEntry,
    CodeSearchDocument,
    ModifierEntry,
    MueEdit,
    NcciPtpEdit,
    PfsProcedureAttribute,
    RawReferenceFile,
    ReferenceImportIssue,
    ReferenceImportRun,
    RuleSourceDocument,
    new_id,
    utcnow,
)
from app.reference_data import adapters
from app.reference_data.ncci_index import build_ncci_source_index
from app.reference_data.types import DiscoveredFile, ParsedBundle
from app.reference_data.utils import canonical_code, manifest_sha256, parse_date, sha256_file
from app.reference_data.validation import validate_bundle

PARSER_VERSION = "orthocode-reference-v1"


def _family(relative_path: str) -> str | None:
    parts = Path(relative_path).parts
    if not parts:
        return None
    root = parts[0].lower()
    lower = relative_path.lower()
    if root == "cpt":
        if "consolidatedcodelist" in lower or "modifiers.txt" in lower or "cpt standard" in lower:
            return "cpt_licensed"
        return "pfs"
    return {
        "icd10cm": "icd10cm",
        "icd10pcs": "icd10pcs",
        "hcpcs": "hcpcs",
        "ncci": "ncci",
        "mue": "mue",
        "rules": "rules",
    }.get(root)


def _manifest_metadata(source_root: Path) -> dict[str, dict[str, str]]:
    manifest = source_root.parent / "MANIFEST.csv"
    if not manifest.is_file():
        return {}
    metadata: dict[str, dict[str, str]] = {}
    try:
        with manifest.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                local = str(row.get("local_path") or "").replace("\\", "/")
                marker = "reference_data/"
                relative = local.split(marker, 1)[-1] if marker in local else local
                if relative:
                    metadata[relative] = row
    except (OSError, csv.Error):
        return {}
    return metadata


def discover_files(source_root: Path) -> list[DiscoveredFile]:
    source_root = source_root.expanduser().resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(f"Reference-data directory does not exist: {source_root}")
    metadata = _manifest_metadata(source_root)
    discovered: list[DiscoveredFile] = []
    for path in sorted(source_root.rglob("*")):
        if (
            not path.is_file()
            or path.name.startswith(".")
            or path.suffix.lower() in {".part", ".tmp"}
        ):
            continue
        relative = path.relative_to(source_root).as_posix()
        family = _family(relative)
        if family is None:
            continue
        manifest_row = metadata.get(relative, {})
        checksum = sha256_file(path)
        discovered.append(
            DiscoveredFile(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"orthocode:{relative}:{checksum}")),
                path=path,
                relative_path=relative,
                source_family=family,
                size=path.stat().st_size,
                sha256=checksum,
                source_url=manifest_row.get("source_url") or None,
                effective_from=parse_date(manifest_row.get("effective_date")),
                metadata={
                    key: value
                    for key, value in manifest_row.items()
                    if key not in {"source_url", "effective_date"} and value
                },
            )
        )
    return discovered


def _parse(files: list[DiscoveredFile], effective_from: date) -> ParsedBundle:
    by_family: dict[str, list[DiscoveredFile]] = {}
    for item in files:
        by_family.setdefault(item.source_family, []).append(item)
    parsed = ParsedBundle()
    for family, parser in (
        ("icd10cm", adapters.parse_icd10cm),
        ("icd10pcs", adapters.parse_icd10pcs),
        ("hcpcs", adapters.parse_hcpcs),
        ("cpt_licensed", adapters.parse_cpt),
        ("pfs", adapters.parse_pfs),
        ("ncci", adapters.parse_ncci_ptp),
        ("mue", adapters.parse_mue),
        ("ncci", adapters.parse_addon),
        ("rules", adapters.parse_rule_documents),
    ):
        parsed.extend(parser(by_family.get(family, []), effective_from))
    return parsed


def _report(files: list[DiscoveredFile], parsed: ParsedBundle, fingerprint: str) -> dict[str, Any]:
    counts = {
        "code_entries": len(parsed.code_entries),
        "modifiers": len(parsed.modifiers),
        "pfs_attributes": len(parsed.pfs_attributes),
        "ncci_ptp_edits": len(parsed.ncci_edits),
        "mue_edits": len(parsed.mue_edits),
        "addon_relations": len(parsed.addon_relations),
        "rule_documents": len(parsed.rule_documents),
    }
    return {
        "source_manifest_sha256": fingerprint,
        "files_discovered": len(files),
        "files_by_family": dict(Counter(item.source_family for item in files)),
        "record_counts": counts,
        "blocking_errors": sum(issue.severity == "error" for issue in parsed.issues),
        "warnings": sum(issue.severity == "warning" for issue in parsed.issues),
        "issues": [asdict(issue) for issue in parsed.issues],
    }


def import_reference_bundle(
    session: Session | None,
    source_root: Path,
    release_name: str,
    effective_from: date,
    *,
    dry_run: bool = False,
    publish: bool = False,
    materialize_ncci: bool = True,
    ncci_index_path: Path | None = None,
) -> dict[str, Any]:
    files = discover_files(source_root)
    fingerprint = manifest_sha256((item.relative_path, item.sha256) for item in files)
    parsed = _parse(files, effective_from)
    validate_bundle(parsed)
    report = _report(files, parsed, fingerprint)
    if dry_run:
        return report
    if session is None:
        raise ValueError("A database session is required unless dry_run=True")

    run = ReferenceImportRun(
        id=new_id(),
        status="running",
        dry_run=False,
        source_root=str(source_root.resolve()),
        release_name=release_name,
        parser_version=PARSER_VERSION,
        source_manifest_sha256=fingerprint,
        started_at=utcnow(),
        summary={},
    )
    session.add(run)
    session.flush()
    for item in files:
        session.add(
            RawReferenceFile(
                id=item.id,
                import_run_id=run.id,
                original_filename=item.path.name,
                relative_path=item.relative_path,
                source_family=item.source_family,
                source_url=item.source_url,
                release_name=release_name,
                release_effective_from=item.effective_from or effective_from,
                file_size=item.size,
                sha256=item.sha256,
                parser_version=PARSER_VERSION,
                metadata_json=item.metadata,
            )
        )
    session.flush()

    release = CodebookRelease(
        id=new_id(),
        import_run_id=run.id,
        name=release_name,
        status="rejected" if report["blocking_errors"] else "validated",
        effective_from=effective_from,
        source_manifest_sha256=fingerprint,
        parser_version=PARSER_VERSION,
        validated_at=None if report["blocking_errors"] else utcnow(),
        validation_summary=report,
    )
    session.add(release)
    session.flush()
    _persist_bundle(session, release.id, parsed, materialize_ncci=materialize_ncci)

    for issue in parsed.issues:
        session.add(
            ReferenceImportIssue(
                id=new_id(),
                import_run_id=run.id,
                severity=issue.severity,
                code=issue.code,
                source_family=issue.source_family,
                source_file_id=issue.source_file_id,
                message=issue.message,
                context=issue.context,
            )
        )
    if not materialize_ncci and ncci_index_path is not None:
        ncci_report = build_ncci_source_index(
            [item for item in files if item.source_family == "ncci"],
            source_root,
            ncci_index_path,
            source_manifest_sha256=fingerprint,
        )
        report["ncci_source_index"] = ncci_report
        release.validation_summary = report
    run.status = release.status
    run.completed_at = utcnow()
    run.summary = report
    session.commit()

    if publish:
        if report["blocking_errors"]:
            raise ValueError(
                "Reference release has blocking validation errors and cannot be published"
            )
        publish_release(session, release.id)
        report["published"] = True
    else:
        report["published"] = False
    report["run_id"] = run.id
    report["release_id"] = release.id
    return report


def _persist_bundle(
    session: Session,
    release_id: str,
    parsed: ParsedBundle,
    *,
    materialize_ncci: bool,
) -> None:
    for row in parsed.code_entries:
        entry_id = new_id()
        entry = CodeEntry(
            id=entry_id,
            codebook_release_id=release_id,
            code_system=str(row["code_system"]),
            code=str(row["code"]),
            code_key=str(row.get("code_key") or canonical_code(row["code"])),
            short_description=row.get("short_description"),
            long_description=row.get("long_description"),
            effective_from=row.get("effective_from"),
            effective_to=row.get("effective_to"),
            billable=row.get("billable"),
            category=row.get("category"),
            chapter=row.get("chapter"),
            parent_code=row.get("parent_code"),
            anatomic_region=row.get("anatomic_region"),
            laterality_supported=row.get("laterality_supported"),
            metadata_json=row.get("metadata_json") or {},
            source_version=str(row.get("source_version") or "unknown"),
            source_file_id=str(row["source_file_id"]),
        )
        session.add(entry)
        description = entry.long_description or entry.short_description or ""
        session.add(
            CodeSearchDocument(
                id=new_id(),
                codebook_release_id=release_id,
                code_entry_id=entry_id,
                code=entry.code,
                description=description or None,
                synonyms=[],
                anatomic_region=entry.anatomic_region,
                procedure_family=None,
                search_text=f"{entry.code} {description}".lower().strip(),
                embedding=None,
            )
        )
    for row in parsed.modifiers:
        session.add(ModifierEntry(id=new_id(), codebook_release_id=release_id, **row))
    for row in parsed.pfs_attributes:
        session.add(PfsProcedureAttribute(id=new_id(), codebook_release_id=release_id, **row))
    if materialize_ncci:
        for row in parsed.ncci_edits:
            revision = "|".join(
                str(row.get(key) or "")
                for key in (
                    "setting",
                    "column_1_code_key",
                    "column_2_code_key",
                    "effective_from",
                    "effective_to",
                    "modifier_indicator",
                )
            )
            session.add(
                NcciPtpEdit(
                    id=new_id(),
                    codebook_release_id=release_id,
                    revision_key=hashlib.sha256(revision.encode()).hexdigest(),
                    **row,
                )
            )
    for row in parsed.mue_edits:
        session.add(MueEdit(id=new_id(), codebook_release_id=release_id, **row))
    for row in parsed.addon_relations:
        session.add(AddonCodeRelation(id=new_id(), codebook_release_id=release_id, **row))
    for row in parsed.rule_documents:
        session.add(RuleSourceDocument(id=new_id(), codebook_release_id=release_id, **row))


def publish_release(
    session: Session, release_id: str, *, actor_id: str = "system"
) -> CodebookRelease:
    release = session.get(CodebookRelease, release_id)
    if release is None:
        raise LookupError("Reference release not found")
    if release.status == "published":
        return release
    if release.status != "validated" or release.validation_summary.get("blocking_errors", 0):
        raise ValueError("Only a validated release without blocking errors can be published")
    existing = session.scalars(
        select(CodebookRelease).where(
            CodebookRelease.status == "published", CodebookRelease.id != release.id
        )
    )
    now = utcnow()
    for current in existing:
        current.status = "superseded"
        if current.effective_to is None or current.effective_to >= release.effective_from:
            current.effective_to = release.effective_from
    release.status = "published"
    release.published_at = now
    run = session.get(ReferenceImportRun, release.import_run_id)
    if run is not None:
        run.status = "published"
        run.published = True
        run.completed_at = run.completed_at or now
    session.commit()
    session.refresh(release)
    return release
