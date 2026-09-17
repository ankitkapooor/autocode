from pathlib import Path


def test_runtime_repositories_do_not_read_raw_reference_files() -> None:
    repository_root = Path(__file__).resolve().parents[1] / "app" / "repositories"
    forbidden = ("ZipFile(", "read_excel(", "REFERENCE_DATA_PATH", "reference_data_path", ".xlsx", ".csv")
    for path in repository_root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"Runtime repository {path.name} crossed the raw-data boundary with {marker}"
