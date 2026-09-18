from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env", "backend/.env.local", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    phi_mode: bool = False
    jwt_secret: str | None = None

    database_url: str = "sqlite:///./orthocode.db"
    redis_url: str | None = None

    storage_provider: str = "local"
    storage_bucket: str | None = None
    r2_endpoint: str | None = None
    local_storage_path: Path = Path(".data/charts")
    max_upload_mb: int = 25

    llm_provider: str = "openai"
    llm_model: str | None = None
    llm_reasoning_effort: str = "high"
    extraction_model: str | None = None
    vision_model: str | None = None
    openai_api_key: str | None = None
    autonomous_coding_enabled: bool = False

    coding_decision_engine: Literal["legacy_llm", "jev_shadow", "jev_primary"] = "legacy_llm"
    jev_enabled: bool = False
    jev_api_key: str | None = None
    jev_base_url: str | None = None
    jev_model: str | None = None
    jev_phi_allowed: bool = False
    jev_accept_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    jev_review_threshold: float = Field(default=0.50, ge=0.0, le=1.0)

    reference_data_path: Path = Path("../ortho_coding_reference_bundle/reference_data")
    ncci_index_path: Path = Path(".data/reference/ncci-index.json")
    licensed_codebook_data_path: Path | None = None
    reference_normalization_required: bool = True
    active_reference_release: str | None = None
    reference_release_name: str = "2026-Q3"
    reference_release_effective_from: str = "2026-07-01"

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3010",
            "http://127.0.0.1:3010",
        ]
    )

    @model_validator(mode="after")
    def enforce_phi_boundary(self) -> "Settings":
        if self.jev_review_threshold > self.jev_accept_threshold:
            raise ValueError("JEV_REVIEW_THRESHOLD cannot exceed JEV_ACCEPT_THRESHOLD")
        if not self.phi_mode:
            return self
        missing: list[str] = []
        if self.app_env.lower() != "production":
            missing.append("APP_ENV=production")
        if not self.jwt_secret or len(self.jwt_secret) < 32:
            missing.append("JWT_SECRET (at least 32 characters)")
        if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
            missing.append("production PostgreSQL DATABASE_URL")
        if not self.redis_url:
            missing.append("REDIS_URL")
        if self.storage_provider == "local" or not self.storage_bucket:
            missing.append("approved private object storage")
        if missing:
            raise ValueError(
                "PHI_MODE startup blocked; missing production safeguards: " + ", ".join(missing)
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
