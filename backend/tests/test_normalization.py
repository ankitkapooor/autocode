from __future__ import annotations

from datetime import date
from pathlib import Path
from zipfile import ZipFile

from app.reference_data.adapters import parse_cpt, parse_hcpcs, parse_icd10cm
from app.reference_data.types import DiscoveredFile, ParsedBundle
from app.reference_data.utils import canonical_code, sha256_file
from app.reference_data.validation import validate_bundle


def discovered(path: Path, family: str) -> DiscoveredFile:
    return DiscoveredFile(
        id=f"file-{family}",
        path=path,
        relative_path=f"{family}/{path.name}",
        source_family=family,
        size=path.stat().st_size,
        sha256=sha256_file(path),
    )


def test_canonical_code_preserves_leading_zeroes() -> None:
    assert canonical_code("  M75.102 ") == "M75102"
    assert canonical_code("0071U") == "0071U"


def test_icd10cm_parser_preserves_hierarchy_and_leaf_status(tmp_path: Path) -> None:
    archive = tmp_path / "icd10cm-xml.zip"
    xml = """<?xml version='1.0'?>
    <ICD10CM.tabular><version>2026</version><chapter><name>13</name><desc>Musculoskeletal</desc>
    <section><diag><name>M75</name><desc>Shoulder lesions</desc>
    <diag><name>M75.102</name><desc>Unspecified rotator cuff tear, left shoulder</desc></diag>
    </diag></section></chapter></ICD10CM.tabular>"""
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("icd10c-tabular-April-1-2026.xml", xml)
    parsed = parse_icd10cm([discovered(archive, "icd10cm")], date(2026, 7, 1))
    by_code = {row["code"]: row for row in parsed.code_entries}
    assert by_code["M75"]["billable"] is False
    assert by_code["M75.102"]["billable"] is True
    assert by_code["M75.102"]["parent_code"] == "M75"
    assert by_code["M75.102"]["effective_from"] == date(2026, 4, 1)


def test_hcpcs_parser_excludes_numeric_level_one_rows(tmp_path: Path) -> None:
    archive = tmp_path / "hcpcs.zip"

    def line(code: str, record_type: str, long: str, short: str = "") -> str:
        value = f"{code:<5}{'':<5}{record_type}{long:<80}{short:<28}"
        return value.ljust(320)

    payload = "\n".join(
        [
            line("A1234", "3", "Orthopedic supply", "Ortho supply"),
            line("29827", "3", "Licensed CPT description", "CPT"),
            line("   LT", "7", "Left side", "Left"),
        ]
    )
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("HCPC2026_JUL_ANWEB.txt", payload)
    parsed = parse_hcpcs([discovered(archive, "hcpcs")], date(2026, 7, 1))
    assert [row["code"] for row in parsed.code_entries] == ["A1234"]
    assert [row["modifier"] for row in parsed.modifiers] == ["LT"]


def test_cpt_current_format_parser_skips_license_preamble(tmp_path: Path) -> None:
    current = tmp_path / "2026 CPT Standard Annual Update" / "Current Format" / "Primary Data Files"
    current.mkdir(parents=True)
    consolidated = current / "ConsolidatedCodeList.txt"
    consolidated.write_text(
        "Licensed CPT preamble\n\n"
        "Concept Id\tCPT Code\tLong\tMedium\tShort\tConsumer\tSpanish Consumer\t"
        "Current Descriptor Effective Date\tTest Name\tLab Name\tManufacturer Name\n"
        "101\t29827\tArthroscopy procedure\tARTHROSCOPY\tARTHROSCOPY\t\t\t20260101\t\t\t\n"
        "102\t0001T\tEmerging procedure\tEMERGING\tEMERGING\t\t\t\t\t\t\n",
        encoding="utf-8",
    )
    modifiers = current / "Modifiers.txt"
    modifiers.write_text(
        "Licensed CPT preamble\n\n"
        "ConceptID\tModifier Code\tLevel I/II\tModifier Descriptor Effective\t"
        "Modifier Name\tModifier Description\tSection (Main Section)\n"
        "201\t51\tI\t20260101\tMultiple procedures\tMultiple procedures\tSurgery\n",
        encoding="utf-8",
    )
    parsed = parse_cpt(
        [discovered(consolidated, "cpt_licensed"), discovered(modifiers, "cpt_licensed")],
        date(2026, 7, 1),
    )
    assert [row["code"] for row in parsed.code_entries] == ["29827", "0001T"]
    assert parsed.code_entries[0]["effective_from"] == date(2026, 1, 1)
    assert parsed.code_entries[0]["chapter"] == "Surgery"
    assert parsed.code_entries[1]["category"] == "Category III"
    assert parsed.modifiers[0]["type"] == "CPT_LEVEL_I"
    assert any(issue.code == "CPT_ROW_COUNT_TOO_LOW" for issue in parsed.issues)


def test_validation_rejects_missing_ptp_and_deduplicates_codes() -> None:
    bundle = ParsedBundle(
        code_entries=[
            {"id": "1", "code_system": "ICD10CM", "code": "M75.1", "code_key": "M751", "effective_from": date(2026, 1, 1), "effective_to": None},
            {"id": "2", "code_system": "ICD10CM", "code": "M75.1", "code_key": "M751", "effective_from": date(2026, 1, 1), "effective_to": None},
            {"id": "3", "code_system": "HCPCS", "code": "L1234", "code_key": "L1234", "effective_from": date(2026, 1, 1), "effective_to": None},
        ],
        pfs_attributes=[{"code_key": "29827", "effective_from": date(2026, 1, 1), "effective_to": None}],
        mue_edits=[
            {"setting": "practitioner", "code_key": "29827", "mue_value": 1, "effective_from": date(2026, 1, 1), "effective_to": None},
            {"setting": "outpatient_hospital", "code_key": "29827", "mue_value": 1, "effective_from": date(2026, 1, 1), "effective_to": None},
        ],
        addon_relations=[{"effective_from": date(2026, 1, 1), "effective_to": None}],
        rule_documents=[{"id": "rule"}],
    )
    issues = validate_bundle(bundle)
    assert len(bundle.code_entries) == 2
    assert any(issue.code == "DUPLICATE_CANONICAL_CODES" for issue in issues)
    assert any(issue.code == "MISSING_NCCI_SETTING" for issue in issues)
