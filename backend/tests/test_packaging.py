from pathlib import Path


def test_reference_data_application_package_is_not_ignored() -> None:
    backend_root = Path(__file__).resolve().parents[1]
    package = backend_root / "app" / "reference_data"
    assert (package / "pipeline.py").is_file()
    dockerignore = (backend_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "reference_data" not in {line.strip() for line in dockerignore}
