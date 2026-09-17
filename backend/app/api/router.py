from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_session
from app.jobs import enqueue_reference_import, get_job, run_reference_import_job
from app.models.reference import (
    AddonCodeRelation,
    CodeEntry,
    CodebookRelease,
    ModifierEntry,
    MueEdit,
    NcciPtpEdit,
    PfsProcedureAttribute,
    RawReferenceFile,
    ReferenceImportIssue,
    ReferenceImportRun,
    RuleSourceDocument,
)
from app.reference_data.pipeline import discover_files, publish_release
from app.reference_data.ncci_index import get_ncci_source_index
from app.repositories import CodebookRepository, NoPublishedReleaseError
from app.schemas import (
    CodeResponse,
    ImportAccepted,
    ImportRequest,
    ModifierResponse,
    PublishRequest,
    ReleaseResponse,
)

router = APIRouter(prefix="/api")


@router.get("/admin/reference-data/overview")
def reference_overview(
    session: Session = Depends(get_session), settings: Settings = Depends(get_settings)
) -> dict[str, Any]:
    releases = list(session.scalars(select(CodebookRelease).order_by(CodebookRelease.created_at.desc())))
    runs = list(session.scalars(select(ReferenceImportRun).order_by(ReferenceImportRun.created_at.desc()).limit(10)))
    try:
        discovered = discover_files(settings.reference_data_path)
        files_by_family = dict(Counter(item.source_family for item in discovered))
        discovery_error = None
    except (FileNotFoundError, PermissionError) as exc:
        discovered = []
        files_by_family = {}
        discovery_error = str(exc)
    active = next((release for release in releases if release.status == "published"), None)
    latest = releases[0] if releases else None
    counts: dict[str, int] = {}
    ncci_runtime = {"mode": "unavailable", "record_count": 0, "path": None}
    if latest:
        for name, model in (
            ("code_entries", CodeEntry),
            ("modifiers", ModifierEntry),
            ("pfs_attributes", PfsProcedureAttribute),
            ("ncci_ptp_edits", NcciPtpEdit),
            ("mue_edits", MueEdit),
            ("addon_relations", AddonCodeRelation),
            ("rule_documents", RuleSourceDocument),
        ):
            counts[name] = session.scalar(
                select(func.count()).select_from(model).where(model.codebook_release_id == latest.id)
            ) or 0
        if counts.get("ncci_ptp_edits", 0):
            ncci_runtime = {
                "mode": "materialized_sql",
                "record_count": counts["ncci_ptp_edits"],
                "path": None,
            }
        else:
            source_index = get_ncci_source_index(
                str(settings.ncci_index_path.resolve()), str(settings.reference_data_path.resolve())
            )
            if source_index is not None and source_index.is_compatible(latest.source_manifest_sha256):
                counts["ncci_ptp_edits"] = source_index.record_count
                ncci_runtime = {
                    "mode": "source_index",
                    "record_count": source_index.record_count,
                    "path": str(settings.ncci_index_path),
                }
    licensed_cpt_records = 0
    if active:
        licensed_cpt_records = session.scalar(
            select(func.count())
            .select_from(CodeEntry)
            .where(CodeEntry.codebook_release_id == active.id, CodeEntry.code_system == "CPT")
        ) or 0
    coding_gate_ready = active is not None and licensed_cpt_records > 0
    return {
        "phase": 0,
        "gate": "ready" if coding_gate_ready else "blocked",
        "autonomous_coding_enabled": settings.autonomous_coding_enabled and coding_gate_ready,
        "licensed_cpt_records": licensed_cpt_records,
        "active_release": _release_dict(active),
        "latest_release": _release_dict(latest),
        "record_counts": counts,
        "ncci_runtime": ncci_runtime,
        "source_inventory": {
            "root": str(settings.reference_data_path),
            "files_discovered": len(discovered),
            "files_by_family": files_by_family,
            "error": discovery_error,
        },
        "recent_runs": [_run_dict(run) for run in runs],
    }


@router.post(
    "/admin/reference-data/import",
    response_model=ImportAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_reference_import(
    request: ImportRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> ImportAccepted:
    payload = request.model_dump(mode="json")
    payload["source_root"] = payload.get("source_root") or str(settings.reference_data_path)
    payload["release_name"] = payload.get("release_name") or settings.reference_release_name
    payload["effective_from"] = payload.get("effective_from") or settings.reference_release_effective_from
    if settings.redis_url:
        job_id = enqueue_reference_import(payload)
        return ImportAccepted(status="queued", message=f"Reference import queued as job {job_id}", report={"job_id": job_id})
    background_tasks.add_task(run_reference_import_job, payload)
    return ImportAccepted(status="queued", message="Reference import queued in the development worker")


@router.post(
    "/admin/reference-data/normalize",
    response_model=ImportAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def normalize_reference_data(
    request: ImportRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
) -> ImportAccepted:
    return start_reference_import(request, background_tasks, settings)


@router.get("/admin/reference-data/imports")
def list_imports(session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    runs = session.scalars(select(ReferenceImportRun).order_by(ReferenceImportRun.created_at.desc()).limit(100))
    return [_run_dict(run) for run in runs]


@router.get("/admin/reference-data/imports/{run_id}")
def get_import(run_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    run = session.get(ReferenceImportRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Import run not found")
    issues = session.scalars(
        select(ReferenceImportIssue).where(ReferenceImportIssue.import_run_id == run_id).order_by(ReferenceImportIssue.severity, ReferenceImportIssue.created_at)
    )
    files = session.scalars(
        select(RawReferenceFile).where(RawReferenceFile.import_run_id == run_id).order_by(RawReferenceFile.source_family, RawReferenceFile.relative_path)
    )
    return {
        **_run_dict(run),
        "summary": run.summary,
        "issues": [
            {"id": issue.id, "severity": issue.severity, "code": issue.code, "source_family": issue.source_family, "message": issue.message, "context": issue.context}
            for issue in issues
        ],
        "files": [
            {"id": item.id, "relative_path": item.relative_path, "source_family": item.source_family, "file_size": item.file_size, "sha256": item.sha256}
            for item in files
        ],
    }


@router.get("/admin/reference-data/releases", response_model=list[ReleaseResponse])
def list_releases(session: Session = Depends(get_session)) -> list[CodebookRelease]:
    return list(session.scalars(select(CodebookRelease).order_by(CodebookRelease.created_at.desc())))


@router.post("/admin/reference-data/releases/{release_id}/publish", response_model=ReleaseResponse)
def publish_reference_release(
    release_id: str, _request: PublishRequest, session: Session = Depends(get_session)
) -> CodebookRelease:
    try:
        return publish_release(session, release_id, actor_id="api-admin")
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or Redis is not configured")
    return job


@router.get("/codes/search", response_model=list[CodeResponse])
def search_codes(
    q: str = Query(min_length=1, max_length=200),
    system: str | None = None,
    service_date: date | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[CodeEntry]:
    try:
        return CodebookRepository(session).search_codes(q, system=system, service_date=service_date, limit=limit)
    except NoPublishedReleaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/codes/{system}/{code}", response_model=CodeResponse)
def get_code(system: str, code: str, service_date: date | None = None, session: Session = Depends(get_session)) -> CodeEntry:
    try:
        entry = CodebookRepository(session).get_code(system, code, service_date)
    except NoPublishedReleaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if entry is None:
        raise HTTPException(status_code=404, detail="Code not found in the active release for the requested date")
    return entry


@router.get("/modifiers/search", response_model=list[ModifierResponse])
def search_modifiers(
    q: str = Query(min_length=1, max_length=200),
    service_date: date | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[ModifierEntry]:
    try:
        return CodebookRepository(session).search_modifiers(
            q, service_date=service_date, limit=limit
        )
    except NoPublishedReleaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _release_dict(release: CodebookRelease | None) -> dict[str, Any] | None:
    if release is None:
        return None
    return {
        "id": release.id,
        "name": release.name,
        "status": release.status,
        "scope": release.scope,
        "effective_from": release.effective_from,
        "validated_at": release.validated_at,
        "published_at": release.published_at,
        "validation_summary": release.validation_summary,
    }


def _run_dict(run: ReferenceImportRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "release_name": run.release_name,
        "parser_version": run.parser_version,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "published": run.published,
        "blocking_errors": run.summary.get("blocking_errors", 0) if run.summary else 0,
        "warnings": run.summary.get("warnings", 0) if run.summary else 0,
    }
