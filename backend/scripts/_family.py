from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from app.reference_data import adapters
from app.reference_data.pipeline import discover_files


PARSERS = {
    "icd10cm": ("icd10cm", adapters.parse_icd10cm, "code_entries"),
    "icd10pcs": ("icd10pcs", adapters.parse_icd10pcs, "code_entries"),
    "hcpcs": ("hcpcs", adapters.parse_hcpcs, "code_entries"),
    "modifiers": ("hcpcs", adapters.parse_hcpcs, "modifiers"),
    "pfs": ("pfs", adapters.parse_pfs, "pfs_attributes"),
    "ncci_ptp": ("ncci", adapters.parse_ncci_ptp, "ncci_edits"),
    "ncci_mue": ("mue", adapters.parse_mue, "mue_edits"),
    "ncci_addon": ("ncci", adapters.parse_addon, "addon_relations"),
    "rule_documents": ("rules", adapters.parse_rule_documents, "rule_documents"),
}


def family_main(family: str) -> int:
    parser = argparse.ArgumentParser(description=f"Inspect and validate the {family} source adapter")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--effective-from", type=date.fromisoformat, default=date(2026, 7, 1))
    args = parser.parse_args()
    source_family, adapter, collection = PARSERS[family]
    files = [item for item in discover_files(args.source_root) if item.source_family == source_family]
    parsed = adapter(files, args.effective_from)
    report = {
        "adapter": family,
        "files": len(files),
        "records": len(getattr(parsed, collection)),
        "issues": [asdict(issue) for issue in parsed.issues],
    }
    print(json.dumps(report, indent=2, default=str))
    return 1 if any(issue.severity == "error" for issue in parsed.issues) else 0
