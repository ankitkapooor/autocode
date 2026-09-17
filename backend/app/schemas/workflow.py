from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChartSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_id: str | None
    original_filename: str
    service_date: date
    setting: str
    status: str
    stage: str
    page_count: int
    assigned_to: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ReviewChangeInput(BaseModel):
    coding_line_id: str | None = None
    field_name: Literal["code", "units", "modifiers", "diagnosis_pointers", "add_line", "remove_line"]
    new_value: Any = None
    rationale: str | None = Field(default=None, max_length=2000)


class ReviewSubmit(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=128)
    disposition: Literal["approved", "approved_with_changes", "rejected"]
    notes: str | None = Field(default=None, max_length=4000)
    changes: list[ReviewChangeInput] = Field(default_factory=list, max_length=100)


class EvaluationRequest(BaseModel):
    dataset: str = Field(min_length=1, max_length=128)
