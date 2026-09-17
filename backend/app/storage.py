from __future__ import annotations

from pathlib import Path

from app.config import Settings


class LocalChartStorage:
    """Private local storage for de-identified development charts only."""

    def __init__(self, settings: Settings):
        configured = settings.local_storage_path
        backend_root = Path(__file__).resolve().parents[1]
        self.root = (configured if configured.is_absolute() else backend_root / configured).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_pdf(self, chart_id: str, content: bytes) -> str:
        key = f"{chart_id}/source.pdf"
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o600)
        return key

    def path_for(self, key: str) -> Path:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError("Stored chart document was not found")
        return path

    def _path(self, key: str) -> Path:
        candidate = (self.root / key).resolve()
        if self.root not in candidate.parents:
            raise ValueError("Invalid storage key")
        return candidate


def chart_storage(settings: Settings) -> LocalChartStorage:
    if settings.storage_provider == "local" or settings.app_env.lower() in {"development", "test"}:
        return LocalChartStorage(settings)
    raise RuntimeError(
        "Private object storage is required outside development; configure the production R2 adapter"
    )
