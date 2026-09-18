from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from app.reference_data import adapters
from app.reference_data.types import DiscoveredFile
from app.reference_data.utils import canonical_code, parse_date

logger = logging.getLogger(__name__)
INDEX_VERSION = 2
INSERT_BATCH_SIZE = 5_000
PROGRESS_INTERVAL = 100_000


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


def _index_row(
    row: dict[str, Any],
) -> tuple[str, str, str, str, str, str, str | None, str | None]:
    start = row.get("effective_from")
    end = row.get("effective_to")
    return (
        str(row["setting"]),
        str(row["column_1_code"]),
        str(row["column_1_code_key"]),
        str(row["column_2_code"]),
        str(row["column_2_code_key"]),
        start.isoformat() if start else date.min.isoformat(),
        end.isoformat() if end else None,
        str(row.get("modifier_indicator")) if row.get("modifier_indicator") else None,
    )


def build_ncci_source_index(
    files: list[DiscoveredFile],
    source_root: Path,
    output_path: Path,
    *,
    source_manifest_sha256: str,
) -> dict[str, Any]:
    del source_root  # Paths are deliberately not copied into the runtime index.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.is_file():
        try:
            existing = NcciSourceIndex(output_path, output_path.parent)
        except (OSError, ValueError, sqlite3.DatabaseError):
            existing = None
        if existing is not None and existing.is_compatible(source_manifest_sha256):
            logger.info("Reusing completed NCCI index: %s rows", f"{existing.record_count:,}")
            return {
                "format": "sqlite",
                "record_count": existing.record_count,
                "file_size": output_path.stat().st_size,
                "path": str(output_path),
                "source_manifest_sha256": source_manifest_sha256,
                "settings": existing.settings,
            }
    temporary_path = output_path.with_name(f"{output_path.name}.tmp")
    temporary_path.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary_path)
    record_count = 0
    settings: set[str] = set()
    batch: list[tuple[str, str, str, str, str, str, str | None, str | None]] = []
    insert_sql = """
        INSERT INTO ncci_edits (
            setting, column_1_code, column_1_code_key, column_2_code,
            column_2_code_key, effective_from, effective_to, modifier_indicator
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("PRAGMA temp_store=FILE")
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute(
            """
            CREATE TABLE ncci_edits (
                setting TEXT NOT NULL,
                column_1_code TEXT NOT NULL,
                column_1_code_key TEXT NOT NULL,
                column_2_code TEXT NOT NULL,
                column_2_code_key TEXT NOT NULL,
                effective_from TEXT NOT NULL,
                effective_to TEXT,
                modifier_indicator TEXT
            )
            """
        )
        logger.info("Building disk-backed NCCI index (0 rows processed)")
        for row in adapters.iter_ncci_ptp(files, date.today()):
            batch.append(_index_row(row))
            settings.add(str(row["setting"]))
            record_count += 1
            if len(batch) >= INSERT_BATCH_SIZE:
                connection.executemany(insert_sql, batch)
                batch.clear()
            if record_count % PROGRESS_INTERVAL == 0:
                logger.info("NCCI index: %s rows processed", f"{record_count:,}")
        if batch:
            connection.executemany(insert_sql, batch)
        logger.info("NCCI rows loaded; creating lookup index")
        connection.execute(
            """
            CREATE INDEX ix_ncci_lookup ON ncci_edits (
                setting, column_1_code_key, column_2_code_key,
                effective_from, effective_to
            )
            """
        )
        connection.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            (
                ("version", str(INDEX_VERSION)),
                ("source_manifest_sha256", source_manifest_sha256),
                ("record_count", str(record_count)),
            ),
        )
        connection.commit()
    except Exception:
        connection.close()
        temporary_path.unlink(missing_ok=True)
        raise
    connection.close()
    temporary_path.replace(output_path)
    logger.info("NCCI index complete: %s rows", f"{record_count:,}")
    return {
        "format": "sqlite",
        "record_count": record_count,
        "file_size": output_path.stat().st_size,
        "path": str(output_path),
        "source_manifest_sha256": source_manifest_sha256,
        "settings": sorted(settings),
    }


class NcciSourceIndex:
    def __init__(self, path: Path, source_root: Path):
        self.path = path
        self.source_root = source_root
        with sqlite3.connect(path) as connection:
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            self.settings = sorted(
                row[0] for row in connection.execute("SELECT DISTINCT setting FROM ncci_edits")
            )
        self.version = int(metadata.get("version", "0"))
        self.source_manifest_sha256 = metadata.get("source_manifest_sha256", "")
        self.record_count = int(metadata.get("record_count", "0"))

    def is_compatible(self, source_manifest_sha256: str) -> bool:
        return (
            self.version == INDEX_VERSION and self.source_manifest_sha256 == source_manifest_sha256
        )

    def lookup(
        self,
        setting: str,
        column_1_code: str,
        column_2_code: str,
        service_date: date,
    ) -> IndexedNcciEdit | None:
        first_key = canonical_code(column_1_code)
        second_key = canonical_code(column_2_code)
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                """
                SELECT setting, column_1_code, column_1_code_key, column_2_code,
                       column_2_code_key, effective_from, effective_to, modifier_indicator
                FROM ncci_edits
                WHERE setting = ?
                  AND column_1_code_key = ?
                  AND column_2_code_key = ?
                  AND effective_from <= ?
                  AND (effective_to IS NULL OR effective_to >= ?)
                ORDER BY effective_from DESC
                LIMIT 1
                """,
                (
                    setting,
                    first_key,
                    second_key,
                    service_date.isoformat(),
                    service_date.isoformat(),
                ),
            ).fetchone()
        if row is None:
            return None
        start = parse_date(row[5], date.min) or date.min
        end = parse_date(row[6])
        return IndexedNcciEdit(
            setting=row[0],
            column_1_code=row[1],
            column_1_code_key=row[2],
            column_2_code=row[3],
            column_2_code_key=row[4],
            effective_from=start,
            effective_to=end,
            deletion_date=end,
            modifier_indicator=row[7],
        )


def get_ncci_source_index(path: str, source_root: str) -> NcciSourceIndex | None:
    index_path = Path(path)
    if not index_path.is_file():
        return None
    try:
        return NcciSourceIndex(index_path, Path(source_root))
    except (OSError, ValueError, sqlite3.DatabaseError):
        return None


def get_configured_ncci_source_index() -> NcciSourceIndex | None:
    from app.config import get_settings

    settings = get_settings()
    return get_ncci_source_index(
        str(settings.ncci_index_path.resolve()),
        str(settings.reference_data_path.resolve()),
    )
