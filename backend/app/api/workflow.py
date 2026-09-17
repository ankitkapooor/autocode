from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.coding.processing import process_chart
from app.config import Settings, get_settings
from app.database import get_session
from app.jobs import enqueue_chart_processing, get_job
from app.models.reference import AuditEvent, CodeEntry, CodebookRelease, new_id, utcnow
from app.models.workflow import (
    CandidateCode,
    Chart,
    ChartPage,
    ClinicalFact,
    CodingLine,
    CodingResult,
    Encounter,
    EvaluationMetric,
    EvaluationRun,
    EvidenceSpan,
    GoldEncounter,
    Review,
    ReviewChange,
    RuleDecision,
)
from app.repositories import CodebookRepository, NoPublishedReleaseError
from app.schemas import ChartSummary, EvaluationRequest, ReviewSubmit
from app.storage import chart_storage

router = APIRouter(prefix="/api")


@router.get("/dashboard")
def dashboard(session: Session = Depends(get_session)) -> dict[str, Any]:
    status_counts = dict(
        session.execute(select(Chart.status, func.count()).group_by(Chart.status)).all()
    )
    confidence_counts = dict(
        session.execute(
            select(CodingResult.confidence_state, func.count()).group_by(CodingResult.confidence_state)
        ).all()
    )
    recent = list(session.scalars(select(Chart).order_by(Chart.created_at.desc()).limit(8)))
    completed = session.scalar(
        select(func.count()).select_from(Chart).where(Chart.stage == "complete")
    ) or 0
    return {
        "queue": status_counts,
        "confidence": confidence_counts,
        "charts_total": sum(status_counts.values()),
        "processed_total": completed,
        "recent_charts": [_chart_dict(chart) for chart in recent],
    }


@router.post("/charts", status_code=status.HTTP_202_ACCEPTED)
async def upload_chart(
    background_tasks: BackgroundTasks,
    document: UploadFile = File(...),
    service_date: date = Form(...),
    setting: str = Form("practitioner"),
    external_id: str | None = Form(None),
    deidentified: bool = Form(False),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    _assert_coding_gate(session, service_date)
    if setting not in {"practitioner", "hospital"}:
        raise HTTPException(status_code=422, detail="setting must be practitioner or hospital")
    if not deidentified and not settings.phi_mode:
        raise HTTPException(
            status_code=422,
            detail="Development processing accepts only explicitly de-identified charts",
        )
    maximum = settings.max_upload_mb * 1024 * 1024
    content = await document.read(maximum + 1)
    if len(content) > maximum:
        raise HTTPException(status_code=413, detail=f"PDF exceeds the {settings.max_upload_mb} MB limit")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="Only PDF chart documents are accepted")
    digest = hashlib.sha256(content).hexdigest()
    duplicate = session.scalar(
        select(Chart).where(Chart.sha256 == digest, Chart.service_date == service_date)
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail={"message": "This chart was already uploaded for the service date", "chart_id": duplicate.id},
        )
    chart_id = new_id()
    storage_key = chart_storage(settings).put_pdf(chart_id, content)
    chart = Chart(
        id=chart_id,
        external_id=external_id.strip()[:128] if external_id else None,
        original_filename=(document.filename or "chart.pdf")[:512],
        content_type="application/pdf",
        storage_key=storage_key,
        sha256=digest,
        file_size=len(content),
        service_date=service_date,
        setting=setting,
        deidentified=deidentified,
        status="uploaded",
        stage="uploaded",
    )
    session.add(chart)
    session.add(
        AuditEvent(
            actor_type="user",
            action="chart.uploaded",
            entity_type="chart",
            entity_id=chart.id,
            details={"file_size": len(content), "service_date": service_date.isoformat(), "deidentified": deidentified},
        )
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate chart upload") from exc
    if settings.redis_url and settings.app_env.lower() == "production":
        job_id = enqueue_chart_processing(chart.id)
    else:
        background_tasks.add_task(process_chart, chart.id)
        job_id = None
    return {"chart": _chart_dict(chart), "job_id": job_id, "status": "queued"}


@router.get("/charts", response_model=list[ChartSummary])
def list_charts(
    chart_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[Chart]:
    statement = select(Chart).order_by(Chart.created_at.desc()).limit(limit)
    if chart_status:
        statement = statement.where(Chart.status == chart_status)
    return list(session.scalars(statement))


@router.get("/charts/{chart_id}")
def get_chart(chart_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    chart = _get_chart(session, chart_id)
    result = session.scalar(
        select(CodingResult).where(CodingResult.chart_id == chart.id).order_by(CodingResult.created_at.desc())
    )
    return {
        **_chart_dict(chart),
        "result": _result_summary(result) if result else None,
        "facts_count": session.scalar(
            select(func.count())
            .select_from(ClinicalFact)
            .where(
                ClinicalFact.encounter_id.in_(
                    select(Encounter.id).where(Encounter.chart_id == chart.id)
                )
            )
        ) or 0,
    }


@router.get("/charts/{chart_id}/status")
def chart_status(chart_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    chart = _get_chart(session, chart_id)
    return {
        "id": chart.id,
        "status": chart.status,
        "stage": chart.stage,
        "error_code": chart.error_code,
        "error_message": chart.error_message,
        "updated_at": chart.updated_at,
    }


@router.post("/charts/{chart_id}/process", status_code=status.HTTP_202_ACCEPTED)
def reprocess_chart(
    chart_id: str,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    chart = _get_chart(session, chart_id)
    if chart.status in {"processing", "reviewer_approved"}:
        raise HTTPException(status_code=409, detail=f"Chart cannot be processed from status {chart.status}")
    _assert_coding_gate(session, chart.service_date)
    chart.status = "uploaded"
    chart.stage = "queued"
    chart.error_code = None
    chart.error_message = None
    session.commit()
    if settings.redis_url and settings.app_env.lower() == "production":
        job_id = enqueue_chart_processing(chart.id)
    else:
        background_tasks.add_task(process_chart, chart.id)
        job_id = None
    return {"chart_id": chart.id, "status": "queued", "job_id": job_id}


@router.get("/charts/{chart_id}/pages")
def chart_pages(chart_id: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    _get_chart(session, chart_id)
    pages = list(
        session.scalars(select(ChartPage).where(ChartPage.chart_id == chart_id).order_by(ChartPage.page_number))
    )
    spans = list(
        session.scalars(select(EvidenceSpan).where(EvidenceSpan.chart_id == chart_id).order_by(EvidenceSpan.created_at))
    )
    by_page: dict[str, list[dict[str, Any]]] = {}
    for span in spans:
        by_page.setdefault(span.chart_page_id, []).append(
            {
                "id": span.id,
                "kind": span.kind,
                "text": span.text,
                "start_offset": span.start_offset,
                "end_offset": span.end_offset,
                "confidence": span.confidence,
            }
        )
    return [
        {
            "id": page.id,
            "page_number": page.page_number,
            "text": page.text,
            "extraction_method": page.extraction_method,
            "evidence": by_page.get(page.id, []),
        }
        for page in pages
    ]


@router.get("/charts/{chart_id}/facts")
def chart_facts(chart_id: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    result = session.scalar(
        select(CodingResult).where(CodingResult.chart_id == chart_id).order_by(CodingResult.created_at.desc())
    )
    if result is None:
        _get_chart(session, chart_id)
        return []
    facts = session.scalars(
        select(ClinicalFact).where(ClinicalFact.encounter_id == result.encounter_id).order_by(ClinicalFact.fact_type)
    )
    return [
        {
            "id": fact.id,
            "fact_type": fact.fact_type,
            "value": fact.value,
            "normalized_value": fact.normalized_value,
            "assertion": fact.assertion,
            "confidence": fact.confidence,
            "evidence_span_ids": fact.evidence_span_ids,
        }
        for fact in facts
    ]


@router.get("/charts/{chart_id}/candidates")
def chart_candidates(chart_id: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    result = session.scalar(
        select(CodingResult).where(CodingResult.chart_id == chart_id).order_by(CodingResult.created_at.desc())
    )
    if result is None:
        _get_chart(session, chart_id)
        return []
    candidates = session.scalars(
        select(CandidateCode)
        .where(CandidateCode.encounter_id == result.encounter_id)
        .order_by(CandidateCode.selected.desc(), CandidateCode.retrieval_rank)
    )
    return [
        {
            "id": item.id,
            "code_system": item.code_system,
            "code": item.code,
            "description": item.description,
            "retrieval_rank": item.retrieval_rank,
            "selected": item.selected,
            "model_confidence": item.model_confidence,
            "rationale": item.rationale,
            "evidence_span_ids": item.evidence_span_ids,
        }
        for item in candidates
    ]


@router.get("/charts/{chart_id}/coding")
def chart_coding(chart_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    _get_chart(session, chart_id)
    result = session.scalar(
        select(CodingResult).where(CodingResult.chart_id == chart_id).order_by(CodingResult.created_at.desc())
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Coding result is not available")
    lines = list(
        session.scalars(select(CodingLine).where(CodingLine.coding_result_id == result.id).order_by(CodingLine.position))
    )
    decisions = list(
        session.scalars(select(RuleDecision).where(RuleDecision.coding_result_id == result.id).order_by(RuleDecision.created_at))
    )
    reviews = list(
        session.scalars(select(Review).where(Review.coding_result_id == result.id).order_by(Review.created_at))
    )
    return {
        **_result_summary(result),
        "lines": [
            {
                "id": line.id,
                "position": line.position,
                "code_system": line.code_system,
                "code": line.code,
                "description": line.description,
                "units": line.units,
                "modifiers": line.modifiers,
                "diagnosis_pointers": line.diagnosis_pointers,
                "confidence": line.confidence,
                "rationale": line.rationale,
                "evidence_span_ids": line.evidence_span_ids,
            }
            for line in lines
        ],
        "rule_decisions": [
            {
                "id": item.id,
                "coding_line_id": item.coding_line_id,
                "rule_type": item.rule_type,
                "outcome": item.outcome,
                "message": item.message,
                "details": item.details,
            }
            for item in decisions
        ],
        "reviews": [
            {
                "id": review.id,
                "status": review.status,
                "reviewer_id": review.reviewer_id,
                "disposition": review.disposition,
                "notes": review.notes,
                "completed_at": review.completed_at,
            }
            for review in reviews
        ],
    }


@router.post("/charts/{chart_id}/reviews", status_code=status.HTTP_201_CREATED)
def submit_review(
    chart_id: str,
    payload: ReviewSubmit,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    chart = _get_chart(session, chart_id)
    result = session.scalar(
        select(CodingResult).where(CodingResult.chart_id == chart_id).order_by(CodingResult.created_at.desc())
    )
    if result is None:
        raise HTTPException(status_code=409, detail="No coding result is available for review")
    lines = {
        line.id: line
        for line in session.scalars(select(CodingLine).where(CodingLine.coding_result_id == result.id))
    }
    review = Review(
        id=new_id(),
        coding_result_id=result.id,
        status="complete",
        reviewer_id=payload.reviewer_id,
        disposition=payload.disposition,
        notes=payload.notes,
        completed_at=utcnow(),
    )
    session.add(review)
    session.flush()
    for change in payload.changes:
        line = lines.get(change.coding_line_id or "")
        if change.coding_line_id and line is None:
            raise HTTPException(status_code=422, detail="A review change references an unknown coding line")
        previous = None
        if line is not None and change.field_name not in {"add_line", "remove_line"}:
            previous = getattr(line, change.field_name)
        elif line is not None and change.field_name == "remove_line":
            previous = {"code_system": line.code_system, "code": line.code, "units": line.units, "modifiers": line.modifiers}
        session.add(
            ReviewChange(
                id=new_id(),
                review_id=review.id,
                coding_line_id=change.coding_line_id,
                field_name=change.field_name,
                previous_value=previous,
                new_value=change.new_value,
                rationale=change.rationale,
            )
        )
    result.status = "reviewer_rejected" if payload.disposition == "rejected" else "reviewer_approved"
    chart.status = result.status
    session.add(
        AuditEvent(
            actor_type="reviewer",
            actor_id=payload.reviewer_id,
            action="coding.review.completed",
            entity_type="coding_result",
            entity_id=result.id,
            details={"disposition": payload.disposition, "change_count": len(payload.changes)},
        )
    )
    session.commit()
    return {"id": review.id, "status": review.status, "disposition": review.disposition}


@router.get("/jobs/{job_id}/chart")
def chart_job_status(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/evaluations/runs")
def list_evaluations(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    runs = list(session.scalars(select(EvaluationRun).order_by(EvaluationRun.created_at.desc()).limit(100)))
    return [_evaluation_dict(session, run) for run in runs]


@router.post("/evaluations/runs", status_code=status.HTTP_201_CREATED)
def run_evaluation(payload: EvaluationRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    gold = list(session.scalars(select(GoldEncounter).where(GoldEncounter.dataset == payload.dataset)))
    if not gold:
        raise HTTPException(status_code=409, detail="The requested gold dataset is empty")
    run = EvaluationRun(
        id=new_id(),
        dataset=payload.dataset,
        status="running",
        configuration={"comparison": "exact code-system/code set"},
        sample_count=len(gold),
        started_at=utcnow(),
    )
    session.add(run)
    session.flush()
    exact = predicted_total = expected_total = true_positive = 0
    evaluated = 0
    for item in gold:
        if not item.chart_id:
            continue
        result = session.scalar(
            select(CodingResult).where(CodingResult.chart_id == item.chart_id).order_by(CodingResult.created_at.desc())
        )
        if result is None:
            continue
        predicted = {
            (line.code_system, line.code)
            for line in session.scalars(select(CodingLine).where(CodingLine.coding_result_id == result.id))
        }
        expected = {
            (str(row.get("code_system", "CPT")), str(row.get("code", "")))
            for row in item.expected_codes
            if row.get("code")
        }
        exact += predicted == expected
        true_positive += len(predicted & expected)
        predicted_total += len(predicted)
        expected_total += len(expected)
        evaluated += 1
    metrics = {
        "exact_match_rate": exact / evaluated if evaluated else 0,
        "code_precision": true_positive / predicted_total if predicted_total else 0,
        "code_recall": true_positive / expected_total if expected_total else 0,
        "coverage": evaluated / len(gold),
    }
    for name, value in metrics.items():
        session.add(
            EvaluationMetric(
                id=new_id(),
                evaluation_run_id=run.id,
                name=name,
                value=value,
                denominator=evaluated if name == "exact_match_rate" else None,
                breakdown={},
            )
        )
    run.status = "complete"
    run.completed_at = utcnow()
    session.commit()
    return _evaluation_dict(session, run)


def _assert_coding_gate(session: Session, service_date: date) -> CodebookRelease:
    try:
        release = CodebookRepository(session).active_release(service_date)
    except NoPublishedReleaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    cpt_count = session.scalar(
        select(func.count())
        .select_from(CodeEntry)
        .where(CodeEntry.codebook_release_id == release.id, CodeEntry.code_system == "CPT")
    ) or 0
    if cpt_count == 0:
        raise HTTPException(status_code=409, detail="Coding gate is blocked: active release has no licensed CPT records")
    return release


def _get_chart(session: Session, chart_id: str) -> Chart:
    chart = session.get(Chart, chart_id)
    if chart is None:
        raise HTTPException(status_code=404, detail="Chart not found")
    return chart


def _chart_dict(chart: Chart) -> dict[str, Any]:
    return {
        "id": chart.id,
        "external_id": chart.external_id,
        "original_filename": chart.original_filename,
        "service_date": chart.service_date,
        "setting": chart.setting,
        "status": chart.status,
        "stage": chart.stage,
        "page_count": chart.page_count,
        "assigned_to": chart.assigned_to,
        "error_code": chart.error_code,
        "error_message": chart.error_message,
        "created_at": chart.created_at,
        "updated_at": chart.updated_at,
    }


def _result_summary(result: CodingResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "status": result.status,
        "confidence_state": result.confidence_state,
        "confidence_score": result.confidence_score,
        "summary": result.summary,
        "warnings": result.warnings,
        "jev_provider": result.jev_provider,
        "jev_output": result.jev_output,
        "autonomous_eligible": result.autonomous_eligible,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
    }


def _evaluation_dict(session: Session, run: EvaluationRun) -> dict[str, Any]:
    metrics = session.scalars(
        select(EvaluationMetric).where(EvaluationMetric.evaluation_run_id == run.id)
    )
    return {
        "id": run.id,
        "dataset": run.dataset,
        "status": run.status,
        "sample_count": run.sample_count,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "metrics": {metric.name: metric.value for metric in metrics},
    }
