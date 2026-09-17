from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.reference import TimestampMixin, new_id


class Chart(TimestampMixin, Base):
    __tablename__ = "charts"
    __table_args__ = (
        UniqueConstraint("sha256", "service_date", name="uq_chart_hash_service_date"),
        Index("ix_chart_queue", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    original_filename: Mapped[str] = mapped_column(String(512))
    content_type: Mapped[str] = mapped_column(String(128), default="application/pdf")
    storage_key: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    file_size: Mapped[int] = mapped_column(Integer)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    setting: Mapped[str] = mapped_column(String(32), default="practitioner")
    deidentified: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", index=True)
    stage: Mapped[str] = mapped_column(String(64), default="uploaded")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    assigned_to: Mapped[str | None] = mapped_column(String(128), index=True)
    error_code: Mapped[str | None] = mapped_column(String(96))
    error_message: Mapped[str | None] = mapped_column(Text)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    pages: Mapped[list[ChartPage]] = relationship(
        back_populates="chart", cascade="all, delete-orphan", order_by="ChartPage.page_number"
    )


class ChartPage(TimestampMixin, Base):
    __tablename__ = "chart_pages"
    __table_args__ = (UniqueConstraint("chart_id", "page_number", name="uq_chart_page"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chart_id: Mapped[str] = mapped_column(ForeignKey("charts.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    text_sha256: Mapped[str] = mapped_column(String(64))
    extraction_method: Mapped[str] = mapped_column(String(32), default="embedded_text")
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)

    chart: Mapped[Chart] = relationship(back_populates="pages")


class Encounter(TimestampMixin, Base):
    __tablename__ = "encounters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chart_id: Mapped[str] = mapped_column(ForeignKey("charts.id", ondelete="CASCADE"), index=True)
    service_date: Mapped[date] = mapped_column(Date, index=True)
    setting: Mapped[str] = mapped_column(String(32))
    specialty: Mapped[str] = mapped_column(String(64), default="orthopedics")
    status: Mapped[str] = mapped_column(String(32), default="extracted")


class EvidenceSpan(TimestampMixin, Base):
    __tablename__ = "evidence_spans"
    __table_args__ = (Index("ix_evidence_chart_kind", "chart_id", "kind"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chart_id: Mapped[str] = mapped_column(ForeignKey("charts.id", ondelete="CASCADE"), index=True)
    encounter_id: Mapped[str | None] = mapped_column(
        ForeignKey("encounters.id", ondelete="CASCADE"), index=True
    )
    chart_page_id: Mapped[str] = mapped_column(
        ForeignKey("chart_pages.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64), index=True)
    text: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(32), default="document")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)


class ClinicalFact(TimestampMixin, Base):
    __tablename__ = "clinical_facts"
    __table_args__ = (Index("ix_fact_encounter_type", "encounter_id", "fact_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    encounter_id: Mapped[str] = mapped_column(
        ForeignKey("encounters.id", ondelete="CASCADE"), index=True
    )
    fact_type: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(Text)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    assertion: Mapped[str] = mapped_column(String(32), default="present")
    confidence: Mapped[float] = mapped_column(Float)
    evidence_span_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CandidateCode(TimestampMixin, Base):
    __tablename__ = "candidate_codes"
    __table_args__ = (
        UniqueConstraint("encounter_id", "code_system", "code", name="uq_candidate_encounter_code"),
        Index("ix_candidate_encounter_rank", "encounter_id", "retrieval_rank"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    encounter_id: Mapped[str] = mapped_column(
        ForeignKey("encounters.id", ondelete="CASCADE"), index=True
    )
    code_entry_id: Mapped[str] = mapped_column(
        ForeignKey("code_entries.id", ondelete="RESTRICT"), index=True
    )
    code_system: Mapped[str] = mapped_column(String(24))
    code: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    retrieval_query: Mapped[str] = mapped_column(Text)
    retrieval_rank: Mapped[int] = mapped_column(Integer)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    model_confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str | None] = mapped_column(Text)
    evidence_span_ids: Mapped[list[str]] = mapped_column(JSON, default=list)


class ModelRun(TimestampMixin, Base):
    __tablename__ = "model_runs"
    __table_args__ = (Index("ix_model_run_chart_stage", "chart_id", "stage"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chart_id: Mapped[str] = mapped_column(ForeignKey("charts.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="running")
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    input_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    token_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    store_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CodingResult(TimestampMixin, Base):
    __tablename__ = "coding_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chart_id: Mapped[str] = mapped_column(ForeignKey("charts.id", ondelete="CASCADE"), index=True)
    encounter_id: Mapped[str] = mapped_column(
        ForeignKey("encounters.id", ondelete="CASCADE"), index=True
    )
    codebook_release_id: Mapped[str] = mapped_column(
        ForeignKey("codebook_releases.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="needs_review", index=True)
    confidence_state: Mapped[str] = mapped_column(String(16), default="RED")
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    summary: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    jev_provider: Mapped[str] = mapped_column(String(64), default="mock")
    jev_output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    autonomous_eligible: Mapped[bool] = mapped_column(Boolean, default=False)

    lines: Mapped[list[CodingLine]] = relationship(
        back_populates="result", cascade="all, delete-orphan", order_by="CodingLine.position"
    )


class CodingLine(TimestampMixin, Base):
    __tablename__ = "coding_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    coding_result_id: Mapped[str] = mapped_column(
        ForeignKey("coding_results.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    code_system: Mapped[str] = mapped_column(String(24))
    code: Mapped[str] = mapped_column(String(32), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    units: Mapped[int] = mapped_column(Integer, default=1)
    modifiers: Mapped[list[str]] = mapped_column(JSON, default=list)
    diagnosis_pointers: Mapped[list[str]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text)
    evidence_span_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(32), default="reasoning_model")

    result: Mapped[CodingResult] = relationship(back_populates="lines")


class RuleDecision(TimestampMixin, Base):
    __tablename__ = "rule_decisions"
    __table_args__ = (Index("ix_rule_decision_result_outcome", "coding_result_id", "outcome"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    coding_result_id: Mapped[str] = mapped_column(
        ForeignKey("coding_results.id", ondelete="CASCADE"), index=True
    )
    coding_line_id: Mapped[str | None] = mapped_column(
        ForeignKey("coding_lines.id", ondelete="CASCADE"), index=True
    )
    rule_type: Mapped[str] = mapped_column(String(64), index=True)
    outcome: Mapped[str] = mapped_column(String(16), index=True)
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Review(TimestampMixin, Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    coding_result_id: Mapped[str] = mapped_column(
        ForeignKey("coding_results.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="in_progress", index=True)
    reviewer_id: Mapped[str | None] = mapped_column(String(128), index=True)
    disposition: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewChange(TimestampMixin, Base):
    __tablename__ = "review_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    coding_line_id: Mapped[str | None] = mapped_column(
        ForeignKey("coding_lines.id", ondelete="SET NULL"), index=True
    )
    field_name: Mapped[str] = mapped_column(String(64))
    previous_value: Mapped[Any | None] = mapped_column(JSON)
    new_value: Mapped[Any | None] = mapped_column(JSON)
    rationale: Mapped[str | None] = mapped_column(Text)


class GoldEncounter(TimestampMixin, Base):
    __tablename__ = "gold_encounters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    chart_id: Mapped[str | None] = mapped_column(ForeignKey("charts.id", ondelete="SET NULL"), index=True)
    dataset: Mapped[str] = mapped_column(String(128), index=True)
    expected_codes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(64), default="reviewer")


class EvaluationRun(TimestampMixin, Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    dataset: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationMetric(TimestampMixin, Base):
    __tablename__ = "evaluation_metrics"
    __table_args__ = (UniqueConstraint("evaluation_run_id", "name", name="uq_eval_run_metric"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    evaluation_run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    value: Mapped[float] = mapped_column(Float)
    numerator: Mapped[int | None] = mapped_column(Integer)
    denominator: Mapped[int | None] = mapped_column(Integer)
    breakdown: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
