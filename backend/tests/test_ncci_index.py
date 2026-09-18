from __future__ import annotations

from datetime import date
from pathlib import Path

from app.reference_data.ncci_index import NcciSourceIndex, build_ncci_source_index
from app.reference_data.types import DiscoveredFile
from app.reference_data.utils import sha256_file


def test_compact_ncci_source_index_supports_directional_effective_date_lookup(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "reference_data"
    source_path = (
        source_root
        / "ncci"
        / "practitioner_ptp_extracted"
        / "ccipra-test-f1"
        / "ccipra-test-f1.txt"
    )
    source_path.parent.mkdir(parents=True)
    source_path.write_text(
        "Column 1\tColumn 2\t*=in existence prior to 1996\tEffective Date\t"
        "Deletion Date\tModifier\tPTP Edit Rationale\n"
        "29827\t29826\t\t20200101\t20241231\t0\tHistorical edit\n"
        "29827\t29826\t\t20250101\t*\t1\tDistinct service allowed\n"
        "29827\t73030\t*\t\t*\t0\tPrior edit\n"
        "29828\t29826\t\t20200101\t*\t0\tBundled\n",
        encoding="utf-8",
    )
    discovered = DiscoveredFile(
        id="source-1",
        path=source_path,
        relative_path=source_path.relative_to(source_root).as_posix(),
        source_family="ncci",
        size=source_path.stat().st_size,
        sha256=sha256_file(source_path),
    )
    index_path = tmp_path / "ncci-index.json"

    report = build_ncci_source_index(
        [discovered],
        source_root,
        index_path,
        source_manifest_sha256="manifest-1",
    )
    index = NcciSourceIndex(index_path, source_root)

    assert report["record_count"] == 4
    assert report["format"] == "sqlite"
    assert report["settings"] == ["practitioner"]
    assert report["file_size"] < 100_000
    assert index.is_compatible("manifest-1")
    current = index.lookup("practitioner", "29827", "29826", date(2026, 9, 1))
    assert current is not None
    assert current.modifier_indicator == "1"
    historical = index.lookup("practitioner", "29827", "29826", date(2024, 9, 1))
    assert historical is not None
    assert historical.modifier_indicator == "0"
    assert index.lookup("practitioner", "29826", "29827", date(2026, 9, 1)) is None
    prior = index.lookup("practitioner", "29827", "73030", date(2026, 9, 1))
    assert prior is not None
    assert prior.effective_from == date.min
