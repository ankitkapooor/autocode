from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.reference_data.adapters import parse_ncci_ptp
from app.reference_data.types import DiscoveredFile
from app.reference_data.utils import canonical_code, parse_date


@dataclass(slots=True, frozen=True)
class IndexedNcciEdit:
    setting: str
    column_1_code: str
    column_1_code_key: str
    column_2_code: str
    column_2_code_key: str
    effective_from: date
    effective_to: date | None
    deletion_date: date | None
    modifier_indicator: str | None


def build_ncci_source_index(
    files: list[DiscoveredFile],
    source_root: Path,
    output_path: Path,
    *,
    source_manifest_sha256: str,
) -> dict[str, Any]:
    del source_root  # Paths are deliberately not copied into the runtime index.
    parsed = parse_ncci_ptp(files, date.today())
    records = [
        [
            row["setting"],
            row["column_1_code"],
            row["column_2_code"],
            row["effective_from"].isoformat() if row.get("effective_from") else "",
            row["effective_to"].isoformat() if row.get("effective_to") else "",
            row.get("modifier_indicator") or "",
        ]
        for row in parsed.ncci_edits
    ]
    records.sort(key=lambda row: (row[0], canonical_code(row[1]), canonical_code(row[2]), row[3]))
    payload = {"v": 1, "m": source_manifest_sha256, "r": records}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return {
        "record_count": len(records),
        "file_size": output_path.stat().st_size,
        "path": str(output_path),
        "source_manifest_sha256": source_manifest_sha256,
    }


class NcciSourceIndex:
    def __init__(self, path: Path, source_root: Path):
        self.path = path
        self.source_root = source_root
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.version = int(payload.get("v", 0))
        self.source_manifest_sha256 = str(payload.get("m", ""))
        self._records: list[list[str]] = payload.get("r", [])
        self.record_count = len(self._records)

    def is_compatible(self, source_manifest_sha256: str) -> bool:
        return self.version == 1 and self.source_manifest_sha256 == source_manifest_sha256

    def lookup(
        self,
        setting: str,
        column_1_code: str,
        column_2_code: str,
        service_date: date,
    ) -> IndexedNcciEdit | None:
        first_key = canonical_code(column_1_code)
        second_key = canonical_code(column_2_code)
        candidates: list[IndexedNcciEdit] = []
        for current_setting, first, second, start_text, end_text, indicator in self._records:
            if current_setting != setting:
                continue
            if canonical_code(first) != first_key or canonical_code(second) != second_key:
                continue
            start = parse_date(start_text, date.min) or date.min
            end = parse_date(end_text)
            if start <= service_date and (end is None or end >= service_date):
                candidates.append(
                    IndexedNcciEdit(
                        setting=current_setting,
                        column_1_code=first,
                        column_1_code_key=first_key,
                        column_2_code=second,
                        column_2_code_key=second_key,
                        effective_from=start,
                        effective_to=end,
                        deletion_date=end,
                        modifier_indicator=indicator or None,
                    )
                )
        return max(candidates, key=lambda item: item.effective_from, default=None)


def get_ncci_source_index(path: str, source_root: str) -> NcciSourceIndex | None:
    index_path = Path(path)
    if not index_path.is_file():
        return None
    try:
        return NcciSourceIndex(index_path, Path(source_root))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def get_configured_ncci_source_index() -> NcciSourceIndex | None:
    from app.config import get_settings

    settings = get_settings()
    return get_ncci_source_index(
        str(settings.ncci_index_path.resolve()),
        str(settings.reference_data_path.resolve()),
    )
