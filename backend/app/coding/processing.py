from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.coding.document import (
    DocumentExtractionError,
    DocumentExtractor,
    PypdfDocumentExtractor,
    evidence_blocks,
)
from app.coding.providers import (
    ClinicalReasoningProvider,
    JevProvider,
    ProviderResult,
    get_jev_provider,
    get_reasoning_provider,
)
from app.coding.rules import RuleFinding, evaluate_coding_lines
from app.config import Settings, get_settings
from app.database import SessionLocal
from app.models.reference import AuditEvent, CodeEntry, CodebookRelease, new_id, utcnow
from app.models.workflow import (
    CandidateCode,
    Chart,
    ChartPage,
    ClinicalFact,
    CodingLine,
    CodingResult,
    Encounter,
    EvidenceSpan,
    ModelRun,
    Review,
    ReviewChange,
    RuleDecision,
)
from app.reference_data.utils import canonical_code
from app.repositories import CodebookRepository, NoPublishedReleaseError
from app.storage import chart_storage


class ChartProcessor:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        provider: ClinicalReasoningProvider | None = None,
        jev_provider: JevProvider | None = None,
        document_extractor: DocumentExtractor | None = None,
    ):
        self.session = session
        self.settings = settings
        self.provider = provider
        self.jev_provider = jev_provider or get_jev_provider(settings)
        self.document_extractor = document_extractor or PypdfDocumentExtractor()

    def process(self, chart_id: str) -> dict[str, Any]:
        chart = self.session.get(Chart, chart_id)
        if chart is None:
            raise LookupError("Chart not found")
        if not chart.deidentified and not self.settings.phi_mode:
            raise RuntimeError("Chart processing is blocked unless the upload is confirmed de-identified")
        try:
            release = self._coding_release(chart)
            self._clear_derived(chart.id)
            self._stage(chart, "document_extraction")
            pages = self.document_extractor.extract(chart_storage(self.settings).path_for(chart.storage_key))
            if sum(len(page.text) for page in pages) < 40:
                raise DocumentExtractionError(
                    "No usable embedded text was found; an approved OCR provider is required"
                )
            page_rows = self._persist_pages(chart, pages)
            encounter = Encounter(
                id=new_id(),
                chart_id=chart.id,
                service_date=chart.service_date,
                setting=chart.setting,
                specialty="orthopedics",
                status="extracted",
            )
            self.session.add(encounter)
            self.session.flush()
            spans = self._persist_evidence(chart, encounter, page_rows)
            self.session.commit()

            self._stage(chart, "clinical_fact_extraction")
            provider = self.provider or get_reasoning_provider(self.settings)
            facts, queries, extraction_summary = self._extract_facts(chart, encounter, spans, provider)
            self.session.commit()

            self._stage(chart, "candidate_retrieval")
            candidates = self._retrieve_candidates(encounter, facts, queries, chart.service_date)
            self.session.commit()

            self._stage(chart, "coding_reasoning")
            coding_output = self._select_codes(
                chart, facts, candidates, provider, extraction_summary
            )
            result, lines, pipeline_warnings = self._persist_result(
                chart, encounter, release, candidates, coding_output
            )
            self.session.commit()

            self._stage(chart, "deterministic_rules")
            findings = evaluate_coding_lines(
                self.session, lines, chart.service_date, chart.setting
            )
            jev_output = self.jev_provider.validate(
                {
                    "service_date": chart.service_date.isoformat(),
                    "setting": chart.setting,
                    "deidentified": chart.deidentified,
                    "clinical_facts": [
                        {
                            "fact_type": fact.fact_type,
                            "value": fact.value,
                            "normalized_value": fact.normalized_value,
                            "assertion": fact.assertion,
                            "confidence": fact.confidence,
                            "evidence_span_ids": fact.evidence_span_ids,
                        }
                        for fact in facts
                    ],
                    "lines": [
                        {
                            "system": line.code_system,
                            "code": line.code,
                            "units": line.units,
                            "modifiers": line.modifiers,
                        }
                        for line in lines
                    ],
                }
            )
            findings.extend(_jev_findings(lines, jev_output))
            self._persist_findings(result, findings)
            result.jev_provider = self.jev_provider.name
            result.jev_output = jev_output
            self._calibrate(result, lines, findings, pipeline_warnings, jev_output)
            chart.status = result.status
            chart.stage = "complete"
            chart.processing_completed_at = utcnow()
            encounter.status = "coded"
            self.session.add(
                AuditEvent(
                    actor_type="system",
                    action="chart.processing.completed",
                    entity_type="chart",
                    entity_id=chart.id,
                    details={
                        "result_id": result.id,
                        "confidence_state": result.confidence_state,
                        "line_count": len(lines),
                        "release_id": release.id,
                    },
                )
            )
            self.session.commit()
            return {
                "chart_id": chart.id,
                "status": chart.status,
                "result_id": result.id,
                "confidence_state": result.confidence_state,
                "confidence_score": result.confidence_score,
                "line_count": len(lines),
            }
        except Exception as exc:
            self.session.rollback()
            failed = self.session.get(Chart, chart_id)
            if failed is not None:
                failed.status = "failed"
                failed.stage = "failed"
                failed.error_code = _error_code(exc)
                failed.error_message = _safe_error_message(exc)
                failed.processing_completed_at = utcnow()
                self.session.add(
                    AuditEvent(
                        actor_type="system",
                        action="chart.processing.failed",
                        entity_type="chart",
                        entity_id=chart_id,
                        details={"error_code": failed.error_code},
                    )
                )
                self.session.commit()
            raise

    def _coding_release(self, chart: Chart) -> CodebookRelease:
        release = CodebookRepository(self.session).active_release(chart.service_date)
        cpt_count = self.session.scalar(
            select(func.count())
            .select_from(CodeEntry)
            .where(CodeEntry.codebook_release_id == release.id, CodeEntry.code_system == "CPT")
        ) or 0
        if cpt_count == 0:
            raise RuntimeError("Coding gate is blocked because the active release has no licensed CPT codes")
        return release

    def _clear_derived(self, chart_id: str) -> None:
        result_ids = select(CodingResult.id).where(CodingResult.chart_id == chart_id)
        review_ids = select(Review.id).where(Review.coding_result_id.in_(result_ids))
        for model, condition in (
            (ReviewChange, ReviewChange.review_id.in_(review_ids)),
            (Review, Review.coding_result_id.in_(result_ids)),
            (RuleDecision, RuleDecision.coding_result_id.in_(result_ids)),
            (CodingLine, CodingLine.coding_result_id.in_(result_ids)),
            (CodingResult, CodingResult.chart_id == chart_id),
            (CandidateCode, CandidateCode.encounter_id.in_(select(Encounter.id).where(Encounter.chart_id == chart_id))),
            (ClinicalFact, ClinicalFact.encounter_id.in_(select(Encounter.id).where(Encounter.chart_id == chart_id))),
            (EvidenceSpan, EvidenceSpan.chart_id == chart_id),
            (Encounter, Encounter.chart_id == chart_id),
            (ChartPage, ChartPage.chart_id == chart_id),
            (ModelRun, ModelRun.chart_id == chart_id),
        ):
            self.session.execute(delete(model).where(condition))
        self.session.commit()

    def _stage(self, chart: Chart, stage: str) -> None:
        chart.status = "processing"
        chart.stage = stage
        chart.error_code = None
        chart.error_message = None
        chart.processing_started_at = chart.processing_started_at or utcnow()
        self.session.commit()

    def _persist_pages(self, chart: Chart, pages: list[Any]) -> list[ChartPage]:
        rows: list[ChartPage] = []
        for page in pages:
            row = ChartPage(
                id=new_id(),
                chart_id=chart.id,
                page_number=page.page_number,
                text=page.text,
                text_sha256=page.text_sha256,
                extraction_method=page.extraction_method,
                width=page.width,
                height=page.height,
            )
            self.session.add(row)
            rows.append(row)
        chart.page_count = len(rows)
        self.session.flush()
        return rows

    def _persist_evidence(
        self, chart: Chart, encounter: Encounter, pages: list[ChartPage]
    ) -> list[EvidenceSpan]:
        spans: list[EvidenceSpan] = []
        for page in pages:
            for start, end, text in evidence_blocks(page.text):
                span = EvidenceSpan(
                    id=new_id(),
                    chart_id=chart.id,
                    encounter_id=encounter.id,
                    chart_page_id=page.id,
                    kind="document_text",
                    text=text,
                    start_offset=start,
                    end_offset=end,
                    bbox=None,
                    source="document",
                    confidence=1.0,
                )
                self.session.add(span)
                spans.append(span)
        self.session.flush()
        return spans

    def _extract_facts(
        self,
        chart: Chart,
        encounter: Encounter,
        spans: list[EvidenceSpan],
        provider: ClinicalReasoningProvider,
    ) -> tuple[list[ClinicalFact], list[str], str]:
        valid_ids = {span.id for span in spans}
        aggregated_facts: dict[tuple[str, str, str], dict[str, Any]] = {}
        queries: list[str] = []
        summaries: list[str] = []
        for chunk_number, chunk in enumerate(_evidence_chunks(spans), start=1):
            output = self._run_provider(
                chart,
                "fact_extraction",
                provider,
                lambda: provider.extract_facts(chunk),
                {"chunk": chunk_number, "evidence_spans": len(chunk)},
            ).data
            if output.get("summary"):
                summaries.append(str(output["summary"]))
            queries.extend(str(item).strip() for item in output.get("search_queries", []) if str(item).strip())
            for item in output.get("facts", []):
                evidence_ids = [value for value in item.get("evidence_span_ids", []) if value in valid_ids]
                if not evidence_ids:
                    continue
                key = (
                    str(item.get("fact_type", "clinical_context")),
                    str(item.get("normalized_value") or item.get("value") or "").strip().lower(),
                    str(item.get("assertion", "present")),
                )
                existing = aggregated_facts.get(key)
                if existing:
                    existing["evidence_span_ids"] = sorted(
                        set(existing["evidence_span_ids"]) | set(evidence_ids)
                    )
                    existing["confidence"] = max(
                        float(existing["confidence"]), float(item.get("confidence", 0))
                    )
                else:
                    aggregated_facts[key] = {**item, "evidence_span_ids": evidence_ids}

        rows: list[ClinicalFact] = []
        for item in aggregated_facts.values():
            row = ClinicalFact(
                id=new_id(),
                encounter_id=encounter.id,
                fact_type=str(item["fact_type"]),
                value=str(item["value"]),
                normalized_value=str(item.get("normalized_value") or "") or None,
                assertion=str(item.get("assertion", "present")),
                confidence=max(0.0, min(1.0, float(item.get("confidence", 0)))),
                evidence_span_ids=item["evidence_span_ids"],
                provenance={"provider": "openai", "stage": "fact_extraction"},
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return rows, list(dict.fromkeys(queries))[:20], " ".join(summaries)[:2000]

    def _retrieve_candidates(
        self,
        encounter: Encounter,
        facts: list[ClinicalFact],
        queries: list[str],
        service_date: Any,
    ) -> list[CandidateCode]:
        repository = CodebookRepository(self.session)
        search_terms = list(queries)
        search_terms.extend(
            fact.normalized_value or fact.value
            for fact in facts
            if fact.assertion == "present" and fact.fact_type in {"diagnosis", "procedure", "device"}
        )
        direct_codes = {
            match.upper()
            for value in search_terms
            for match in re.findall(r"\b(?:[A-TV-Z][0-9][0-9A-Z.]{2,6}|\d{4}[FMTU]?|\d{5})\b", value, re.I)
        }
        found: dict[tuple[str, str], tuple[CodeEntry, str, int]] = {}
        rank = 0
        for code in direct_codes:
            for system in ("CPT", "HCPCS", "ICD10CM"):
                entry = repository.get_code(system, code, service_date)
                if entry:
                    rank += 1
                    found.setdefault((entry.code_system, entry.code_key), (entry, code, rank))
        for term in list(dict.fromkeys(search_terms))[:20]:
            cleaned = " ".join(str(term).split())[:160]
            if len(cleaned) < 3:
                continue
            for system in ("CPT", "ICD10CM", "HCPCS"):
                for entry in repository.search_codes(
                    cleaned, system=system, service_date=service_date, limit=4
                ):
                    rank += 1
                    found.setdefault((entry.code_system, entry.code_key), (entry, cleaned, rank))
                    if len(found) >= 60:
                        break
                if len(found) >= 60:
                    break
            if len(found) >= 60:
                break

        rows: list[CandidateCode] = []
        for entry, query, retrieval_rank in found.values():
            row = CandidateCode(
                id=new_id(),
                encounter_id=encounter.id,
                code_entry_id=entry.id,
                code_system=entry.code_system,
                code=entry.code,
                description=entry.long_description or entry.short_description,
                retrieval_query=query,
                retrieval_rank=retrieval_rank,
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return rows

    def _select_codes(
        self,
        chart: Chart,
        facts: list[ClinicalFact],
        candidates: list[CandidateCode],
        provider: ClinicalReasoningProvider,
        extraction_summary: str,
    ) -> dict[str, Any]:
        if not candidates:
            return {
                "summary": extraction_summary or "No supported code candidates were retrieved.",
                "lines": [],
                "pipeline_warnings": [
                    {"code": "NO_CANDIDATES", "message": "No active code candidates matched the extracted facts"}
                ],
            }
        fact_payload = [
            {
                "fact_type": fact.fact_type,
                "value": fact.value,
                "normalized_value": fact.normalized_value,
                "assertion": fact.assertion,
                "confidence": fact.confidence,
                "evidence_span_ids": fact.evidence_span_ids,
            }
            for fact in facts
        ]
        candidate_payload = [
            {
                "candidate_id": candidate.id,
                "code_system": candidate.code_system,
                "code": candidate.code,
                "description": candidate.description,
                "retrieval_rank": candidate.retrieval_rank,
            }
            for candidate in candidates
        ]
        result = self._run_provider(
            chart,
            "coding_reasoning",
            provider,
            lambda: provider.select_codes(
                fact_payload, candidate_payload, chart.service_date.isoformat()
            ),
            {"facts": len(facts), "candidates": len(candidates)},
        )
        return {**result.data, "pipeline_warnings": []}

    def _run_provider(
        self,
        chart: Chart,
        stage: str,
        provider: ClinicalReasoningProvider,
        call: Any,
        input_summary: dict[str, Any],
    ) -> ProviderResult:
        run = ModelRun(
            id=new_id(),
            chart_id=chart.id,
            stage=stage,
            provider=getattr(provider, "provider_name", "configured"),
            model=getattr(provider, "model", "configured"),
            status="running",
            request_fingerprint=hashlib.sha256(
                f"{chart.id}:{stage}:{input_summary}".encode()
            ).hexdigest(),
            input_summary=input_summary,
            output_json=None,
            token_usage={},
            store_enabled=False,
            started_at=utcnow(),
        )
        self.session.add(run)
        self.session.commit()
        try:
            result = call()
            run.status = "complete"
            run.model = result.model
            run.request_fingerprint = result.request_fingerprint
            run.output_json = result.data
            run.token_usage = result.usage
            run.completed_at = utcnow()
            self.session.commit()
            return result
        except Exception as exc:
            self.session.rollback()
            failed = self.session.get(ModelRun, run.id)
            if failed:
                failed.status = "failed"
                failed.error = f"{type(exc).__name__}: provider request failed"
                failed.completed_at = utcnow()
                self.session.commit()
            raise

    def _persist_result(
        self,
        chart: Chart,
        encounter: Encounter,
        release: CodebookRelease,
        candidates: list[CandidateCode],
        output: dict[str, Any],
    ) -> tuple[CodingResult, list[CodingLine], list[dict[str, Any]]]:
        result = CodingResult(
            id=new_id(),
            chart_id=chart.id,
            encounter_id=encounter.id,
            codebook_release_id=release.id,
            status="needs_review",
            confidence_state="RED",
            confidence_score=0,
            summary=str(output.get("summary") or "") or None,
            warnings=[],
            autonomous_eligible=False,
        )
        self.session.add(result)
        self.session.flush()
        allowed = {(candidate.code_system, canonical_code(candidate.code)): candidate for candidate in candidates}
        valid_evidence_ids = set(
            self.session.scalars(select(EvidenceSpan.id).where(EvidenceSpan.chart_id == chart.id))
        )
        warnings = list(output.get("pipeline_warnings", []))
        lines: list[CodingLine] = []
        for item in output.get("lines", []):
            key = (str(item.get("code_system", "")).upper(), canonical_code(item.get("code")))
            candidate = allowed.get(key)
            if candidate is None:
                warnings.append(
                    {"code": "OUT_OF_SET_CODE", "message": "A model-selected code was not in the retrieved candidate set"}
                )
                continue
            evidence_ids = [
                value for value in item.get("evidence_span_ids", []) if value in valid_evidence_ids
            ]
            candidate.selected = True
            candidate.model_confidence = float(item.get("confidence", 0))
            candidate.rationale = str(item.get("rationale", ""))
            candidate.evidence_span_ids = evidence_ids
            line = CodingLine(
                id=new_id(),
                coding_result_id=result.id,
                position=len(lines) + 1,
                code_system=candidate.code_system,
                code=candidate.code,
                description=candidate.description,
                units=max(1, int(item.get("units", 1))),
                modifiers=[canonical_code(value) for value in item.get("modifiers", []) if canonical_code(value)],
                diagnosis_pointers=[str(value) for value in item.get("diagnosis_pointers", [])],
                confidence=max(0.0, min(1.0, float(item.get("confidence", 0)))),
                rationale=str(item.get("rationale", "")),
                evidence_span_ids=evidence_ids,
                source="reasoning_model",
            )
            self.session.add(line)
            lines.append(line)
        self.session.flush()
        return result, lines, warnings

    def _persist_findings(self, result: CodingResult, findings: list[RuleFinding]) -> None:
        for finding in findings:
            self.session.add(
                RuleDecision(
                    id=new_id(),
                    coding_result_id=result.id,
                    coding_line_id=finding.line_id,
                    rule_type=finding.rule_type,
                    outcome=finding.outcome,
                    message=finding.message,
                    details=finding.details,
                )
            )
        self.session.flush()

    def _calibrate(
        self,
        result: CodingResult,
        lines: list[CodingLine],
        findings: list[RuleFinding],
        pipeline_warnings: list[dict[str, Any]],
        jev_output: dict[str, Any],
    ) -> None:
        outcomes = Counter(finding.outcome for finding in findings)
        base = sum(line.confidence for line in lines) / len(lines) if lines else 0.0
        score = max(0.0, min(1.0, base - outcomes["fail"] * 0.25 - outcomes["warning"] * 0.06))
        if lines and score >= 0.9 and outcomes["fail"] == 0:
            state = "GREEN"
        elif lines and score >= 0.7 and outcomes["fail"] == 0:
            state = "YELLOW"
        else:
            state = "RED"
        result.confidence_score = round(score, 4)
        result.confidence_state = state
        result.warnings = pipeline_warnings + [
            {"code": finding.rule_type.upper(), "message": finding.message}
            for finding in findings
            if finding.outcome in {"warning", "fail"}
        ]
        jev_confirmed = jev_output.get("status") == "confirmed"
        result.autonomous_eligible = bool(
            self.settings.autonomous_coding_enabled
            and state == "GREEN"
            and outcomes["fail"] == 0
            and jev_confirmed
        )
        result.status = "ready_for_submission" if result.autonomous_eligible else "needs_review"


def _evidence_chunks(
    spans: list[EvidenceSpan], maximum_chars: int = 12_000
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for span in spans:
        item = {"evidence_span_id": span.id, "text": span.text}
        item_size = len(span.text) + 80
        if current and size + item_size > maximum_chars:
            chunks.append(current)
            current = []
            size = 0
        current.append(item)
        size += item_size
    if current:
        chunks.append(current)
    return chunks


def _error_code(exc: Exception) -> str:
    if isinstance(exc, DocumentExtractionError):
        return "DOCUMENT_EXTRACTION_FAILED"
    if isinstance(exc, NoPublishedReleaseError):
        return "REFERENCE_RELEASE_UNAVAILABLE"
    if "OPENAI_API_KEY" in str(exc):
        return "MODEL_CONFIGURATION_MISSING"
    return f"{type(exc).__name__.upper()}"


def _safe_error_message(exc: Exception) -> str:
    if isinstance(exc, (DocumentExtractionError, NoPublishedReleaseError)):
        return str(exc)
    if isinstance(exc, RuntimeError) and (
        "Coding gate" in str(exc) or "de-identified" in str(exc) or "configured" in str(exc)
    ):
        return str(exc)
    return "Processing failed without exposing chart content; retry or inspect protected server logs"


def _jev_findings(lines: list[CodingLine], output: dict[str, Any]) -> list[RuleFinding]:
    status = output.get("status")
    if status not in {"confirmed", "requires_review"}:
        return [
            RuleFinding(
                "jev_decision",
                "warning",
                str(output.get("label") or "Jev was not executed; human review is required"),
                details={"provider": output.get("provider"), "status": status},
            )
        ]
    findings: list[RuleFinding] = []
    for decision in output.get("decisions", []):
        line_index = decision.get("line_index")
        if not isinstance(line_index, int) or line_index < 0 or line_index >= len(lines):
            continue
        line = lines[line_index]
        probability = decision.get("probability")
        if not isinstance(probability, (float, int)):
            outcome = "warning"
            message = "Jev did not return a usable probability for this coding decision"
        elif probability >= 0.8:
            outcome = "pass"
            message = f"Jev support probability is {probability:.1%}"
        elif probability >= 0.5:
            outcome = "warning"
            message = f"Jev support probability is only {probability:.1%}"
        else:
            outcome = "fail"
            message = f"Jev does not support this decision ({probability:.1%})"
        if decision.get("kind") == "modifier":
            message = f"Modifier {decision.get('modifier')}: {message}"
        findings.append(
            RuleFinding(
                "jev_decision",
                outcome,
                message,
                line.id,
                {
                    "probability": probability,
                    "kind": decision.get("kind"),
                    "question": decision.get("question"),
                    "model": output.get("model"),
                },
            )
        )
    return findings


def process_chart(chart_id: str) -> dict[str, Any]:
    settings = get_settings()
    with SessionLocal() as session:
        try:
            return ChartProcessor(session, settings).process(chart_id)
        except Exception as exc:
            session.rollback()
            chart = session.get(Chart, chart_id)
            if chart is not None and chart.status != "failed":
                chart.status = "failed"
                chart.stage = "failed"
                chart.error_code = _error_code(exc)
                chart.error_message = _safe_error_message(exc)
                chart.processing_completed_at = utcnow()
                session.add(
                    AuditEvent(
                        actor_type="system",
                        action="chart.processing.failed",
                        entity_type="chart",
                        entity_id=chart_id,
                        details={"error_code": chart.error_code},
                    )
                )
                session.commit()
            raise
