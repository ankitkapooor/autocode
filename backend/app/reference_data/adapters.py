from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Iterator
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from app.reference_data.types import DiscoveredFile, ParsedBundle, ValidationIssue
from app.reference_data.utils import canonical_code, date_from_name, parse_date


def _issue(
    code: str,
    message: str,
    *,
    severity: str = "warning",
    family: str | None = None,
    source_id: str | None = None,
    **context: Any,
) -> ValidationIssue:
    return ValidationIssue(severity, code, message, family, source_id, context)


def _payloads(
    files: Iterable[DiscoveredFile], suffixes: set[str]
) -> Iterator[tuple[DiscoveredFile, str, bytes]]:
    for source in files:
        suffix = source.path.suffix.lower()
        if suffix == ".zip":
            try:
                with ZipFile(source.path) as archive:
                    for name in archive.namelist():
                        if Path(name).suffix.lower() in suffixes and not name.endswith("/"):
                            yield source, name, archive.read(name)
            except BadZipFile:
                continue
        elif suffix in suffixes:
            yield source, source.path.name, source.path.read_bytes()


def _text(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def _decimal(value: object) -> Decimal | None:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _normalized(row: dict[str, Any]) -> dict[str, str]:
    return {
        re.sub(r"[^a-z0-9]+", "_", str(key).strip().lower()).strip("_"): str(value or "").strip()
        for key, value in row.items()
        if key is not None
    }


def _first(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value:
            return value
    return ""


def _delimited_rows(payload: bytes, required_hint: str | None = None) -> Iterator[dict[str, str]]:
    lines = _text(payload).splitlines()
    start = 0
    if required_hint:
        hint = required_hint.lower()
        start = next(
            (index for index, line in enumerate(lines) if hint in line.lower()), len(lines)
        )
    lines = lines[start:]
    if not lines:
        return
    sample = "\n".join(lines[:10])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="\t,|")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = "\t" if "\t" in lines[0] else ","
    yield from csv.DictReader(lines, delimiter=delimiter)


def _xlsx_rows(payload: bytes) -> Iterator[list[str]]:
    """Read basic cell values without adding a heavyweight spreadsheet dependency."""
    with ZipFile(io.BytesIO(payload)) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root]
        sheets = sorted(
            name
            for name in archive.namelist()
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        )
        for sheet in sheets:
            root = ET.fromstring(archive.read(sheet))
            for row_node in root.iter():
                if not row_node.tag.endswith("}row"):
                    continue
                values: dict[int, str] = {}
                for cell in row_node:
                    if not cell.tag.endswith("}c"):
                        continue
                    ref = cell.attrib.get("r", "A1")
                    letters = re.match(r"[A-Z]+", ref)
                    if letters is None:
                        continue
                    column = 0
                    for letter in letters.group(0):
                        column = column * 26 + ord(letter) - 64
                    cell_type = cell.attrib.get("t")
                    value_node = next((item for item in cell if item.tag.endswith("}v")), None)
                    if cell_type == "inlineStr":
                        value = "".join(cell.itertext())
                    elif value_node is None or value_node.text is None:
                        value = ""
                    elif cell_type == "s":
                        index = int(value_node.text)
                        value = shared[index] if index < len(shared) else ""
                    else:
                        value = value_node.text
                    values[column - 1] = value.strip()
                if values:
                    yield [values.get(index, "") for index in range(max(values) + 1)]


def _table_rows(source: DiscoveredFile, name: str, payload: bytes) -> Iterator[dict[str, str]]:
    suffix = Path(name).suffix.lower()
    if suffix == ".xlsx":
        rows = _xlsx_rows(payload)
        header: list[str] | None = None
        for values in rows:
            nonempty = sum(bool(value.strip()) for value in values)
            if header is None:
                if nonempty < 2:
                    continue
                header = values
                continue
            yield _normalized(dict(zip(header, values, strict=False)))
        return
    for row in _delimited_rows(payload):
        yield _normalized(row)


def parse_icd10cm(files: list[DiscoveredFile], effective_from: date) -> ParsedBundle:
    result = ParsedBundle()
    for source, name, payload in _payloads(files, {".xml"}):
        if "tabular" not in name.lower():
            continue
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            result.issues.append(
                _issue(
                    "ICD10CM_XML_INVALID",
                    str(exc),
                    severity="error",
                    family="icd10cm",
                    source_id=source.id,
                )
            )
            continue
        release_date = date_from_name(name, source.effective_from or effective_from)
        for chapter in root.iter():
            if not chapter.tag.endswith("chapter"):
                continue
            chapter_desc = next(
                ("".join(node.itertext()).strip() for node in chapter if node.tag.endswith("desc")),
                None,
            )

            def visit(
                node: ET.Element,
                parent: str | None = None,
                *,
                current_release_date: date = release_date,
                current_chapter: str | None = chapter_desc,
                current_source: DiscoveredFile = source,
            ) -> None:
                if not node.tag.endswith("diag"):
                    return
                code = next(
                    (
                        "".join(item.itertext()).strip()
                        for item in node
                        if item.tag.endswith("name")
                    ),
                    "",
                )
                description = next(
                    (
                        "".join(item.itertext()).strip()
                        for item in node
                        if item.tag.endswith("desc")
                    ),
                    "",
                )
                children = [item for item in node if item.tag.endswith("diag")]
                if code:
                    result.code_entries.append(
                        {
                            "code_system": "ICD10CM",
                            "code": code,
                            "code_key": canonical_code(code),
                            "short_description": description or None,
                            "long_description": description or None,
                            "effective_from": current_release_date,
                            "effective_to": None,
                            "billable": not children,
                            "category": code[:3],
                            "chapter": current_chapter,
                            "parent_code": parent,
                            "metadata_json": {},
                            "source_version": str(current_release_date.year),
                            "source_file_id": current_source.id,
                        }
                    )
                for child in children:
                    visit(child, code or parent)

            for item in chapter.iter():
                if item.tag.endswith("diag") and not any(
                    parent.tag.endswith("diag") and item in list(parent)
                    for parent in chapter.iter()
                ):
                    visit(item)
    if not result.code_entries:
        result.issues.append(
            _issue(
                "ICD10CM_NOT_FOUND", "No ICD-10-CM tabular XML records were found", family="icd10cm"
            )
        )
    return result


def parse_icd10pcs(files: list[DiscoveredFile], effective_from: date) -> ParsedBundle:
    result = ParsedBundle()
    for source, name, payload in _payloads(files, {".txt"}):
        if "order" not in name.lower() and "code" not in name.lower():
            continue
        release_date = date_from_name(name, source.effective_from or effective_from)
        for line in _text(payload).splitlines():
            stripped = line.strip()
            match = re.match(r"^(?:\d{5}\s+)?([0-9A-HJ-NP-Z]{7})\s+(.+)$", stripped)
            if not match:
                continue
            code, description = match.groups()
            result.code_entries.append(
                {
                    "code_system": "ICD10PCS",
                    "code": code,
                    "code_key": canonical_code(code),
                    "short_description": description.strip(),
                    "long_description": description.strip(),
                    "effective_from": release_date,
                    "effective_to": None,
                    "billable": True,
                    "category": code[:3],
                    "metadata_json": {},
                    "source_version": str(release_date.year),
                    "source_file_id": source.id,
                }
            )
    return result


def parse_hcpcs(files: list[DiscoveredFile], effective_from: date) -> ParsedBundle:
    result = ParsedBundle()
    for source, name, payload in _payloads(files, {".txt", ".csv"}):
        if name.lower().endswith(".csv"):
            rows = _delimited_rows(payload)
            records = []
            for raw in rows:
                row = _normalized(raw)
                records.append(
                    (
                        _first(row, "hcpcs_code", "code", "hcpc"),
                        _first(row, "record_type", "type"),
                        _first(row, "long_description", "long_desc", "description"),
                        _first(row, "short_description", "short_desc"),
                    )
                )
        else:
            records = [
                (line[:5].strip(), line[10:11].strip(), line[11:91].strip(), line[91:119].strip())
                for line in _text(payload).splitlines()
                if line.strip()
            ]
        release_date = date_from_name(name, source.effective_from or effective_from)
        for code, record_type, long_description, short_description in records:
            key = canonical_code(code)
            if not key:
                continue
            if record_type == "7" or len(key) <= 2:
                result.modifiers.append(
                    {
                        "modifier": code.upper(),
                        "modifier_key": key,
                        "description": long_description or short_description or None,
                        "type": "HCPCS_LEVEL_II",
                        "compatible_code_families": [],
                        "effective_from": release_date,
                        "effective_to": None,
                        "metadata_json": {},
                        "source_version": str(release_date.year),
                        "source_file_id": source.id,
                    }
                )
            elif key.isdigit():
                continue
            else:
                result.code_entries.append(
                    {
                        "code_system": "HCPCS",
                        "code": code.upper(),
                        "code_key": key,
                        "short_description": short_description or long_description or None,
                        "long_description": long_description or short_description or None,
                        "effective_from": release_date,
                        "effective_to": None,
                        "billable": True,
                        "category": code[:1].upper(),
                        "metadata_json": {},
                        "source_version": str(release_date.year),
                        "source_file_id": source.id,
                    }
                )
    return result


def parse_cpt(files: list[DiscoveredFile], effective_from: date) -> ParsedBundle:
    result = ParsedBundle()
    for source, name, payload in _payloads(files, {".txt", ".tsv"}):
        lower_name = name.lower()
        if "consolidatedcodelist" in lower_name or "consolidated code" in lower_name:
            for raw in _delimited_rows(payload, "CPT Code"):
                row = _normalized(raw)
                code = _first(row, "cpt_code", "code").upper()
                if not canonical_code(code):
                    continue
                long_description = _first(row, "long", "long_description", "medium", "short")
                descriptor_date = parse_date(_first(row, "current_descriptor_effective_date"))
                if code.endswith("T"):
                    category = "Category III"
                elif code.endswith("M"):
                    category = "Category II"
                else:
                    category = "Category I"
                chapter = "Surgery" if code.isdigit() and 10000 <= int(code) <= 69999 else None
                result.code_entries.append(
                    {
                        "code_system": "CPT",
                        "code": code,
                        "code_key": canonical_code(code),
                        "short_description": _first(row, "short", "medium", "long") or None,
                        "long_description": long_description or None,
                        "effective_from": date(effective_from.year, 1, 1),
                        "effective_to": None,
                        "billable": True,
                        "category": category,
                        "chapter": chapter,
                        "metadata_json": {
                            "licensed_boundary": True,
                            "descriptor_effective_date": descriptor_date.isoformat()
                            if descriptor_date
                            else None,
                        },
                        "source_version": str(effective_from.year),
                        "source_file_id": source.id,
                    }
                )
        elif "modifier" in lower_name:
            for raw in _delimited_rows(payload, "Modifier Code"):
                row = _normalized(raw)
                modifier = _first(row, "modifier_code", "modifier").upper()
                if not canonical_code(modifier):
                    continue
                level = _first(row, "level_i_ii", "level")
                result.modifiers.append(
                    {
                        "modifier": modifier,
                        "modifier_key": canonical_code(modifier),
                        "description": _first(row, "modifier_description", "modifier_name") or None,
                        "type": "CPT_LEVEL_I" if level.upper() in {"I", "1"} else "HCPCS_LEVEL_II",
                        "compatible_code_families": [],
                        "effective_from": date(effective_from.year, 1, 1),
                        "effective_to": None,
                        "metadata_json": {"licensed_boundary": True},
                        "source_version": str(effective_from.year),
                        "source_file_id": source.id,
                    }
                )
    if result.code_entries and len(result.code_entries) < 10_000:
        result.issues.append(
            _issue(
                "CPT_ROW_COUNT_TOO_LOW",
                f"Licensed CPT annual file contained only {len(result.code_entries):,} code rows",
                severity="error",
                family="cpt_licensed",
            )
        )
    return result


def parse_pfs(files: list[DiscoveredFile], effective_from: date) -> ParsedBundle:
    result = ParsedBundle()
    for source, name, payload in _payloads(files, {".csv", ".txt"}):
        if "ortho_cpt_codes" in name.lower():
            continue
        for row in _table_rows(source, name, payload):
            code = _first(row, "hcpcs", "hcpcs_code", "code")
            key = canonical_code(code)
            if not key or len(key) > 7:
                continue
            result.pfs_attributes.append(
                {
                    "code": code.upper(),
                    "code_key": key,
                    "modifier": _first(row, "modifier", "mod").upper(),
                    "status_code": _first(row, "status_code", "status") or None,
                    "work_rvu": _decimal(_first(row, "work_rvu", "work_rvu_value")),
                    "practice_expense_rvu": _decimal(
                        _first(row, "non_fac_pe_rvu", "practice_expense_rvu")
                    ),
                    "facility_practice_expense_rvu": _decimal(_first(row, "facility_pe_rvu")),
                    "malpractice_rvu": _decimal(_first(row, "mp_rvu", "malpractice_rvu")),
                    "global_surgery_indicator": _first(
                        row, "global_days", "global_surgery_indicator"
                    )
                    or None,
                    "multiple_procedure_indicator": _first(
                        row, "multiple_proc", "multiple_procedure_indicator"
                    )
                    or None,
                    "bilateral_surgery_indicator": _first(
                        row, "bilat_surg", "bilateral_surgery_indicator"
                    )
                    or None,
                    "assistant_surgery_indicator": _first(
                        row, "asst_surg", "assistant_surgery_indicator"
                    )
                    or None,
                    "co_surgeon_indicator": _first(row, "co_surg", "co_surgeon_indicator") or None,
                    "team_surgery_indicator": _first(row, "team_surg", "team_surgery_indicator")
                    or None,
                    "effective_from": source.effective_from or effective_from,
                    "effective_to": None,
                    "source_file_id": source.id,
                    "metadata_json": {},
                }
            )
    return result


def _ncci_setting(path: str) -> str:
    lower = path.lower()
    if "practitioner" in lower or "pra" in Path(lower).name:
        return "practitioner"
    if "outpatient" in lower or "hospital" in lower or "oph" in Path(lower).name:
        return "outpatient_hospital"
    return "unknown"


def iter_ncci_ptp(files: list[DiscoveredFile], effective_from: date) -> Iterator[dict[str, Any]]:
    """Yield NCCI rows without retaining the multi-million-row corpus in memory."""
    for source, name, payload in _payloads(files, {".txt", ".csv", ".xlsx"}):
        if "ptp" not in name.lower() and not any(
            token in name.lower() for token in ("ccipra", "ccioph")
        ):
            continue
        setting = _ncci_setting(f"{source.relative_path}/{name}")
        for row in _table_rows(source, name, payload):
            first = _first(row, "column_1", "column_1_code", "column1")
            second = _first(row, "column_2", "column_2_code", "column2")
            if not canonical_code(first) or not canonical_code(second):
                continue
            start = parse_date(_first(row, "effective_date", "effective"))
            prior = _first(row, "in_existence_prior_to_1996", "prior_to_1996")
            if start is None and prior == "*":
                start = date.min
            deletion = parse_date(_first(row, "deletion_date", "deletion"))
            yield {
                "setting": setting,
                "column_1_code": first,
                "column_1_code_key": canonical_code(first),
                "column_2_code": second,
                "column_2_code_key": canonical_code(second),
                "effective_from": start or effective_from,
                "effective_to": deletion,
                "deletion_date": deletion,
                "modifier_indicator": _first(row, "modifier", "modifier_indicator") or None,
                "source_file_id": source.id,
                "source_record": row,
            }


def parse_ncci_ptp(files: list[DiscoveredFile], effective_from: date) -> ParsedBundle:
    result = ParsedBundle()
    result.ncci_edits.extend(iter_ncci_ptp(files, effective_from))
    return result


def parse_mue(files: list[DiscoveredFile], effective_from: date) -> ParsedBundle:
    result = ParsedBundle()
    for source, name, payload in _payloads(files, {".txt", ".csv", ".xlsx"}):
        setting = _ncci_setting(f"{source.relative_path}/{name}")
        for row in _table_rows(source, name, payload):
            code = _first(row, "hcpcs_cpt_code", "hcpcs_code", "code")
            value = _decimal(_first(row, "mue_value", "mue"))
            if not canonical_code(code) or value is None:
                continue
            result.mue_edits.append(
                {
                    "setting": setting,
                    "code": code,
                    "code_key": canonical_code(code),
                    "mue_value": value,
                    "mai": _first(row, "mue_adjudication_indicator_mai", "mai") or None,
                    "rationale": _first(row, "mue_rationale", "rationale") or None,
                    "effective_from": source.effective_from or effective_from,
                    "effective_to": None,
                    "source_file_id": source.id,
                    "metadata_json": {},
                }
            )
    return result


def parse_addon(files: list[DiscoveredFile], effective_from: date) -> ParsedBundle:
    result = ParsedBundle()
    for source, name, payload in _payloads(files, {".txt", ".csv", ".xlsx"}):
        if "add" not in name.lower() and "aoc" not in name.lower():
            continue
        for row in _table_rows(source, name, payload):
            addon = _first(row, "add_on_code", "addon_code", "aoc_code")
            primary = _first(row, "primary_code", "primary_code_s", "primary_codes")
            if not canonical_code(addon) or not primary:
                continue
            result.addon_relations.append(
                {
                    "addon_code": addon,
                    "addon_code_key": canonical_code(addon),
                    "primary_code": primary,
                    "primary_code_key": canonical_code(primary),
                    "relationship_type": "explicit_primary"
                    if re.fullmatch(r"[A-Z0-9.]+", primary, re.I)
                    else "range_or_family",
                    "effective_from": parse_date(
                        _first(row, "effective_date"), source.effective_from or effective_from
                    ),
                    "effective_to": parse_date(_first(row, "deletion_date")),
                    "source_file_id": source.id,
                    "metadata_json": {},
                }
            )
    return result


def parse_rule_documents(files: list[DiscoveredFile], effective_from: date) -> ParsedBundle:
    result = ParsedBundle()
    for source in files:
        if source.path.suffix.lower() != ".pdf":
            continue
        result.rule_documents.append(
            {
                "title": source.path.stem.replace("_", " ").replace("-", " "),
                "publisher": "CMS",
                "release": str((source.effective_from or effective_from).year),
                "effective_from": source.effective_from or effective_from,
                "checksum": source.sha256,
                "source_file_id": source.id,
                "document_type": "policy_manual",
            }
        )
    return result
