from __future__ import annotations

from collections import Counter

from app.reference_data.types import ParsedBundle, ValidationIssue
from app.reference_data.utils import canonical_code


def validate_bundle(
    bundle: ParsedBundle, *, ncci_settings: set[str] | None = None
) -> list[ValidationIssue]:
    """Validate and deterministically de-duplicate a parsed release."""
    issues: list[ValidationIssue] = []

    unique_codes: list[dict[str, object]] = []
    seen_codes: set[tuple[object, object, object, object]] = set()
    duplicate_count = 0
    for row in bundle.code_entries:
        key = (
            row.get("code_system"),
            canonical_code(row.get("code")),
            row.get("effective_from"),
            row.get("effective_to"),
        )
        if key in seen_codes:
            duplicate_count += 1
            continue
        seen_codes.add(key)
        unique_codes.append(row)
    bundle.code_entries = unique_codes
    if duplicate_count:
        issues.append(
            ValidationIssue(
                "warning",
                "DUPLICATE_CANONICAL_CODES",
                f"Removed {duplicate_count:,} duplicate canonical code rows",
                context={"duplicates_removed": duplicate_count},
            )
        )

    unique_modifiers: list[dict[str, object]] = []
    seen_modifiers: set[tuple[object, object]] = set()
    for row in bundle.modifiers:
        key = (canonical_code(row.get("modifier")), row.get("effective_from"))
        if key not in seen_modifiers:
            seen_modifiers.add(key)
            unique_modifiers.append(row)
    bundle.modifiers = unique_modifiers

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
