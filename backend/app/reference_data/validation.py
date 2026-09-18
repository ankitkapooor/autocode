from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from app.reference_data.types import ParsedBundle, ValidationIssue
from app.reference_data.utils import canonical_code


def _deduplicate(
    rows: list[dict[str, Any]], key: Callable[[dict[str, Any]], tuple[object, ...]]
) -> tuple[list[dict[str, Any]], int]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[object, ...]] = set()
    duplicates = 0
    for row in rows:
        identity = key(row)
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        unique.append(row)
    return unique, duplicates


def _duplicate_warning(code: str, label: str, count: int) -> ValidationIssue:
    return ValidationIssue(
        "warning",
        code,
        f"Removed {count:,} duplicate {label} rows",
        context={"duplicates_removed": count},
    )


def validate_bundle(
    bundle: ParsedBundle, *, ncci_settings: set[str] | None = None
) -> list[ValidationIssue]:
    """Validate and deterministically de-duplicate a parsed release."""
    issues: list[ValidationIssue] = []

    bundle.code_entries, duplicate_count = _deduplicate(
        bundle.code_entries,
        lambda row: (row.get("code_system"), canonical_code(row.get("code"))),
    )
    if duplicate_count:
        issues.append(
            _duplicate_warning("DUPLICATE_CANONICAL_CODES", "canonical code", duplicate_count)
        )

    bundle.modifiers, duplicate_count = _deduplicate(
        bundle.modifiers, lambda row: (canonical_code(row.get("modifier")),)
    )
    if duplicate_count:
        issues.append(_duplicate_warning("DUPLICATE_MODIFIERS", "modifier", duplicate_count))

    bundle.pfs_attributes, duplicate_count = _deduplicate(
        bundle.pfs_attributes,
        lambda row: (canonical_code(row.get("code")), row.get("modifier") or ""),
    )
    if duplicate_count:
        issues.append(
            _duplicate_warning(
                "DUPLICATE_PFS_ATTRIBUTES", "PFS procedure attribute", duplicate_count
            )
        )

    bundle.mue_edits, duplicate_count = _deduplicate(
        bundle.mue_edits,
        lambda row: (row.get("setting"), canonical_code(row.get("code"))),
    )
    if duplicate_count:
        issues.append(_duplicate_warning("DUPLICATE_MUE_EDITS", "MUE edit", duplicate_count))

    bundle.addon_relations, duplicate_count = _deduplicate(
        bundle.addon_relations,
        lambda row: (
            canonical_code(row.get("addon_code")),
            canonical_code(row.get("primary_code")),
            row.get("effective_from"),
        ),
    )
    if duplicate_count:
        issues.append(
            _duplicate_warning("DUPLICATE_ADDON_RELATIONS", "add-on relation", duplicate_count)
        )

    systems = Counter(str(row.get("code_system")) for row in bundle.code_entries)
    if systems.get("CPT", 0) == 0:
        issues.append(
            ValidationIssue(
                "error",
                "MISSING_LICENSED_CPT",
                "A licensed CPT annual file is required before this release can be published",
                source_family="cpt_licensed",
            )
        )

    if ncci_settings is None:
        ncci_settings = {str(row.get("setting")) for row in bundle.ncci_edits}
    for setting in ("practitioner", "outpatient_hospital"):
        if setting not in ncci_settings:
            issues.append(
                ValidationIssue(
                    "error",
                    "MISSING_NCCI_SETTING",
                    f"NCCI PTP data is missing for {setting}",
                    source_family="ncci",
                    context={"setting": setting},
                )
            )

    for row in bundle.code_entries:
        if not canonical_code(row.get("code")):
            issues.append(
                ValidationIssue(
                    "error",
                    "BLANK_CODE",
                    "A code row has no canonical identifier",
                    source_family=str(row.get("code_system") or "unknown").lower(),
                )
            )
        start, end = row.get("effective_from"), row.get("effective_to")
        if start is not None and end is not None and start > end:
            issues.append(
                ValidationIssue(
                    "error",
                    "INVALID_EFFECTIVE_RANGE",
                    f"Code {row.get('code')} has an end date before its start date",
                )
            )

    for row in bundle.mue_edits:
        value = row.get("mue_value")
        if value is not None and value <= 0:
            issues.append(
                ValidationIssue(
                    "error",
                    "INVALID_MUE_VALUE",
                    f"MUE value for {row.get('code')} must be positive",
                    source_family="mue",
                )
            )

    bundle.issues.extend(issues)
    return issues
