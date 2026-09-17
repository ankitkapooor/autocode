from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ReferenceImportRun(TimestampMixin, Base):
    __tablename__ = "reference_import_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    source_root: Mapped[str] = mapped_column(Text)
    release_name: Mapped[str] = mapped_column(String(128))
    parser_version: Mapped[str] = mapped_column(String(64))
    source_manifest_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    issues: Mapped[list[ReferenceImportIssue]] = relationship(
        back_populates="import_run", cascade="all, delete-orphan"
    )


class RawReferenceFile(TimestampMixin, Base):
    __tablename__ = "raw_reference_files"
    __table_args__ = (
        UniqueConstraint("import_run_id", "relative_path", name="uq_raw_file_run_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    import_run_id: Mapped[str] = mapped_column(
        ForeignKey("reference_import_runs.id", ondelete="CASCADE"), index=True
    )
    original_filename: Mapped[str] = mapped_column(String(512))
    relative_path: Mapped[str] = mapped_column(String(1024))
    source_family: Mapped[str] = mapped_column(String(64), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    release_name: Mapped[str | None] = mapped_column(String(128))
    release_effective_from: Mapped[date | None] = mapped_column(Date)
    release_effective_to: Mapped[date | None] = mapped_column(Date)
    file_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ReferenceImportIssue(TimestampMixin, Base):
    __tablename__ = "reference_import_issues"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    import_run_id: Mapped[str] = mapped_column(
        ForeignKey("reference_import_runs.id", ondelete="CASCADE"), index=True
    )
    severity: Mapped[str] = mapped_column(String(16), index=True)
    code: Mapped[str] = mapped_column(String(96), index=True)
    source_family: Mapped[str | None] = mapped_column(String(64), index=True)
    source_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("raw_reference_files.id", ondelete="SET NULL")
    )
    message: Mapped[str] = mapped_column(Text)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    import_run: Mapped[ReferenceImportRun] = relationship(back_populates="issues")


class CodebookRelease(TimestampMixin, Base):
    __tablename__ = "codebook_releases"
    __table_args__ = (
        UniqueConstraint("name", "source_manifest_sha256", name="uq_release_manifest"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    import_run_id: Mapped[str] = mapped_column(
        ForeignKey("reference_import_runs.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="staged", index=True)
    scope: Mapped[str] = mapped_column(String(64), default="professional_orthopedic")
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_manifest_sha256: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(64))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    validation_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CodeEntry(TimestampMixin, Base):
    __tablename__ = "code_entries"
    __table_args__ = (
        UniqueConstraint(
            "codebook_release_id", "code_system", "code_key", name="uq_code_release_system_key"
        ),
        Index("ix_code_active_dates", "codebook_release_id", "effective_from", "effective_to"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    codebook_release_id: Mapped[str] = mapped_column(
        ForeignKey("codebook_releases.id", ondelete="CASCADE"), index=True
    )
    code_system: Mapped[str] = mapped_column(String(24), index=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    code_key: Mapped[str] = mapped_column(String(32), index=True)
    short_description: Mapped[str | None] = mapped_column(Text)
    long_description: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    billable: Mapped[bool | None] = mapped_column(Boolean)
    category: Mapped[str | None] = mapped_column(String(128))
    chapter: Mapped[str | None] = mapped_column(String(128))
    parent_code: Mapped[str | None] = mapped_column(String(32))
    anatomic_region: Mapped[str | None] = mapped_column(String(64))
    laterality_supported: Mapped[bool | None] = mapped_column(Boolean)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_version: Mapped[str] = mapped_column(String(128))
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("raw_reference_files.id", ondelete="RESTRICT"), index=True
    )


class ModifierEntry(TimestampMixin, Base):
    __tablename__ = "modifier_entries"
    __table_args__ = (
        UniqueConstraint("codebook_release_id", "modifier_key", name="uq_modifier_release_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    codebook_release_id: Mapped[str] = mapped_column(
        ForeignKey("codebook_releases.id", ondelete="CASCADE"), index=True
    )
    modifier: Mapped[str] = mapped_column(String(8))
    modifier_key: Mapped[str] = mapped_column(String(8), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(String(32), default="HCPCS_LEVEL_II")
    compatible_code_families: Mapped[list[str]] = mapped_column(JSON, default=list)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_version: Mapped[str] = mapped_column(String(128))
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("raw_reference_files.id", ondelete="RESTRICT"), index=True
    )


class PfsProcedureAttribute(TimestampMixin, Base):
    __tablename__ = "pfs_procedure_attributes"
    __table_args__ = (
        UniqueConstraint("codebook_release_id", "code_key", "modifier", name="uq_pfs_release_code_mod"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    codebook_release_id: Mapped[str] = mapped_column(
        ForeignKey("codebook_releases.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(16))
    code_key: Mapped[str] = mapped_column(String(16), index=True)
    modifier: Mapped[str] = mapped_column(String(8), default="")
    status_code: Mapped[str | None] = mapped_column(String(8))
    work_rvu: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    practice_expense_rvu: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    facility_practice_expense_rvu: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    malpractice_rvu: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    global_surgery_indicator: Mapped[str | None] = mapped_column(String(8))
    multiple_procedure_indicator: Mapped[str | None] = mapped_column(String(8))
    bilateral_surgery_indicator: Mapped[str | None] = mapped_column(String(8))
    assistant_surgery_indicator: Mapped[str | None] = mapped_column(String(8))
    co_surgeon_indicator: Mapped[str | None] = mapped_column(String(8))
    team_surgery_indicator: Mapped[str | None] = mapped_column(String(8))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("raw_reference_files.id", ondelete="RESTRICT"), index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class NcciPtpEdit(TimestampMixin, Base):
    __tablename__ = "ncci_ptp_edits"
    __table_args__ = (
        UniqueConstraint(
            "codebook_release_id",
            "setting",
            "revision_key",
            name="uq_ncci_release_setting_revision",
        ),
        Index("ix_ncci_lookup", "codebook_release_id", "setting", "column_1_code_key", "column_2_code_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    codebook_release_id: Mapped[str] = mapped_column(
        ForeignKey("codebook_releases.id", ondelete="CASCADE"), index=True
    )
    setting: Mapped[str] = mapped_column(String(32), index=True)
    revision_key: Mapped[str] = mapped_column(String(64), default=new_id)
    column_1_code: Mapped[str] = mapped_column(String(16))
    column_1_code_key: Mapped[str] = mapped_column(String(16), index=True)
    column_2_code: Mapped[str] = mapped_column(String(16))
    column_2_code_key: Mapped[str] = mapped_column(String(16), index=True)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    deletion_date: Mapped[date | None] = mapped_column(Date)
    modifier_indicator: Mapped[str | None] = mapped_column(String(8))
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("raw_reference_files.id", ondelete="RESTRICT"), index=True
    )
    source_record: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MueEdit(TimestampMixin, Base):
    __tablename__ = "mue_edits"
    __table_args__ = (
        UniqueConstraint("codebook_release_id", "setting", "code_key", name="uq_mue_release_setting_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    codebook_release_id: Mapped[str] = mapped_column(
        ForeignKey("codebook_releases.id", ondelete="CASCADE"), index=True
    )
    setting: Mapped[str] = mapped_column(String(32), index=True)
    code: Mapped[str] = mapped_column(String(16))
    code_key: Mapped[str] = mapped_column(String(16), index=True)
    mue_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    mai: Mapped[str | None] = mapped_column(String(128))
    rationale: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("raw_reference_files.id", ondelete="RESTRICT"), index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AddonCodeRelation(TimestampMixin, Base):
    __tablename__ = "addon_code_relations"
    __table_args__ = (
        UniqueConstraint(
            "codebook_release_id",
            "addon_code_key",
            "primary_code_key",
            "effective_from",
            name="uq_addon_release_pair_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    codebook_release_id: Mapped[str] = mapped_column(
        ForeignKey("codebook_releases.id", ondelete="CASCADE"), index=True
    )
    addon_code: Mapped[str] = mapped_column(String(32))
    addon_code_key: Mapped[str] = mapped_column(String(32), index=True)
    primary_code: Mapped[str] = mapped_column(String(128))
    primary_code_key: Mapped[str] = mapped_column(String(128), index=True)
    relationship_type: Mapped[str] = mapped_column(String(32))
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("raw_reference_files.id", ondelete="RESTRICT"), index=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class RuleSourceDocument(TimestampMixin, Base):
    __tablename__ = "rule_source_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    codebook_release_id: Mapped[str] = mapped_column(
        ForeignKey("codebook_releases.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(512))
    publisher: Mapped[str] = mapped_column(String(128), default="CMS")
    release: Mapped[str] = mapped_column(String(128))
    effective_from: Mapped[date | None] = mapped_column(Date)
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    source_file_id: Mapped[str] = mapped_column(
        ForeignKey("raw_reference_files.id", ondelete="RESTRICT"), index=True
    )
    document_type: Mapped[str] = mapped_column(String(64))


class CodeSearchDocument(TimestampMixin, Base):
    __tablename__ = "code_search_documents"
    __table_args__ = (
        UniqueConstraint("codebook_release_id", "code_entry_id", name="uq_search_release_entry"),
        Index("ix_code_search_text", "codebook_release_id", "code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    codebook_release_id: Mapped[str] = mapped_column(
        ForeignKey("codebook_releases.id", ondelete="CASCADE"), index=True
    )
    code_entry_id: Mapped[str] = mapped_column(
        ForeignKey("code_entries.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    synonyms: Mapped[list[str]] = mapped_column(JSON, default=list)
    anatomic_region: Mapped[str | None] = mapped_column(String(64))
    procedure_family: Mapped[str | None] = mapped_column(String(64))
    search_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(JSON)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_type: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str] = mapped_column(String(128))
    entity_id: Mapped[str | None] = mapped_column(String(128), index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
