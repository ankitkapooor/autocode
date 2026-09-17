from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ImportRequest(BaseModel):
    source_root: str | None = None
    release_name: str | None = None
    effective_from: date | None = None
    dry_run: bool = False
    publish: bool = False
    materialize_ncci: bool | None = None


class ImportAccepted(BaseModel):
    status: str
    message: str
    report: dict[str, Any] | None = None


class PublishRequest(BaseModel):
    confirmation: str = Field(pattern="^publish$")


class CodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    code_system: str
    code: str
    short_description: str | None
    long_description: str | None
    effective_from: date | None
    effective_to: date | None
    billable: bool | None
    category: str | None
    chapter: str | None
    parent_code: str | None


class ModifierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    modifier: str
    description: str | None
    type: str
    compatible_code_families: list[str]
    effective_from: date | None
    effective_to: date | None


class ReleaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    effective_from: date
    effective_to: date | None
    source_manifest_sha256: str
    parser_version: str
    validation_summary: dict[str, Any]
    validated_at: datetime | None
    published_at: datetime | None
