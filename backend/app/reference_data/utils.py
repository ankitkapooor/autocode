from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path


def canonical_code(value: object) -> str:
    """Return the case-insensitive lookup form without losing leading zeroes."""
    if value is None:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).strip().upper())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_sha256(items: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for relative_path, checksum in sorted(items):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(checksum.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def parse_date(value: object, default: date | None = None) -> date | None:
    if value is None or isinstance(value, str) and value.strip() in {"", "*", "N/A", "NA"}:
        return default
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%m%d%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    if text.isdigit() and len(text) == 7:
        try:
            return datetime.strptime(text, "%Y%j").date()
        except ValueError:
            pass
    return default


def date_from_name(name: str, default: date) -> date:
    normalized = name.replace("_", "-")
    match = re.search(
        r"(?i)(january|february|march|april|may|june|july|august|"
        r"september|october|november|december)[ -](\d{1,2})[ -](20\d{2})",
        normalized,
    )
    if match:
        return datetime.strptime(" ".join(match.groups()), "%B %d %Y").date()
    match = re.search(r"(?<!\d)(20\d{2})[- ](\d{1,2})[- ](\d{1,2})(?!\d)", normalized)
    if match:
        return date(*(int(part) for part in match.groups()))
    return default
