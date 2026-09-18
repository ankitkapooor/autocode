from __future__ import annotations

import hashlib
import math
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
from app.coding.jev import decision_bucket, decision_key, parse_choice, parse_noul
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

            mode = self.settings.coding_decision_engine
            fact_trace: dict[str, Any] | None = None
            retrieval_facts = facts
            retrieval_queries = queries
            if mode == "jev_primary":
                self._stage(chart, "jev_fact_validation")
                fact_trace = self._jev_validate_facts(chart, facts, spans)
                accepted_ids = set(fact_trace.get("accepted_fact_ids", []))
                if fact_trace.get("status") == "complete":
                    retrieval_facts = [fact for fact in facts if fact.id in accepted_ids]
                    retrieval_queries = []

            self._stage(chart, "candidate_retrieval")
            candidates = self._retrieve_candidates(
                encounter,
                retrieval_facts,
                retrieval_queries,
                chart.service_date,
                facts_validated=bool(
                    mode == "jev_primary" and fact_trace and fact_trace.get("status") == "complete"
                ),
            )
            self.session.commit()

            if mode == "jev_primary":
                self._stage(chart, "jev_code_selection")
                jev_output, coding_output = self._jev_primary_output(
                    chart,
                    facts,
                    candidates,
                    spans,
                    fact_trace or {},
                    extraction_summary,
                )
                self._stage(chart, "coding_assembly")
                result, lines, pipeline_warnings = self._persist_result(
                    chart,
                    encounter,
                    release,
                    candidates,
                    coding_output,
                    source="jev_decision_engine",
                )
                result.jev_provider = self.jev_provider.name
                result.jev_output = jev_output
            else:
                self._stage(chart, "coding_reasoning")
                coding_output = self._select_codes(
                    chart, facts, candidates, provider, extraction_summary
                )
                result, lines, pipeline_warnings = self._persist_result(
                    chart, encounter, release, candidates, coding_output
                )
                legacy_jev_output = self.jev_provider.validate(
                    self._legacy_jev_payload(chart, facts, lines)
                )
                if mode == "jev_shadow":
                    self._stage(chart, "jev_fact_validation")
                    shadow_fact_trace = self._jev_validate_facts(chart, facts, spans)
                    self._stage(chart, "jev_code_selection")
                    shadow_output, shadow_coding = self._jev_primary_output(
                        chart,
                        facts,
                        candidates,
                        spans,
                        shadow_fact_trace,
                        extraction_summary,
                    )
                    jev_output = {
                        "provider": self.jev_provider.name,
                        "mode": "shadow",
                        "status": shadow_output.get("status"),
                        "model": shadow_output.get("model"),
                        "legacy_verification": legacy_jev_output,
                        "shadow": shadow_output,
                        "comparison": _shadow_comparison(coding_output, shadow_coding),
                        "summary": shadow_output.get("summary", {}),
                    }
                else:
                    jev_output = {**legacy_jev_output, "mode": "legacy"}
                result.jev_provider = self.jev_provider.name
                result.jev_output = jev_output
            self.session.commit()

            self._stage(chart, "deterministic_rules")
            findings = evaluate_coding_lines(self.session, lines, chart.service_date, chart.setting)
            if mode == "jev_primary":
                self._stage(chart, "jev_rule_adjudication")
                findings.extend(
                    self._jev_adjudicate_rule_exceptions(
                        chart, facts, spans, lines, findings, result.jev_output
                    )
                )
                result.jev_output = {**result.jev_output}
                findings.extend(self._primary_jev_findings(lines, result.jev_output))
            else:
                calibration_output = (
                    result.jev_output.get("legacy_verification", {})
                    if mode == "jev_shadow"
                    else result.jev_output
                )
                findings.extend(
                    _jev_findings(
                        lines,
                        calibration_output,
                        self.settings.jev_accept_threshold,
                        self.settings.jev_review_threshold,
                    )
                )
            self._persist_findings(result, findings)
            if mode == "jev_primary":
                self._calibrate_primary(
                    result, lines, findings, pipeline_warnings, result.jev_output
                )
            else:
                self._calibrate_legacy(
                    result, lines, findings, pipeline_warnings, calibration_output
                )
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
        *,
        facts_validated: bool = False,
    ) -> list[CandidateCode]:
        repository = CodebookRepository(self.session)
        search_terms = list(queries)
        search_terms.extend(
            fact.normalized_value or fact.value
            for fact in facts
            if (facts_validated or fact.assertion == "present")
            and fact.fact_type in {"diagnosis", "procedure", "device", "medication"}
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

    def _legacy_jev_payload(
        self,
        chart: Chart,
        facts: list[ClinicalFact],
        lines: list[CodingLine],
    ) -> dict[str, Any]:
        return {
            "service_date": chart.service_date.isoformat(),
            "setting": chart.setting,
            "deidentified": chart.deidentified,
            "clinical_facts": [_fact_payload(fact) for fact in facts],
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

    def _jev_validate_facts(
        self,
        chart: Chart,
        facts: list[ClinicalFact],
        spans: list[EvidenceSpan],
    ) -> dict[str, Any]:
        questions: dict[str, dict[str, Any]] = {}
        metadata: dict[str, ClinicalFact] = {}
        for fact in facts:
            key = decision_key("fact", fact.id)
            if fact.fact_type == "procedure":
                criteria = {
                    "performed": "The procedure was actually performed during this encounter.",
                    "planned_only": "The procedure was discussed, ordered, or planned but not performed.",
                    "historical": "The procedure occurred before this encounter.",
                    "uncertain": "The evidence is conflicting or does not establish timing.",
                    "unsupported": "The evidence does not support this procedure fact.",
                }
            elif fact.fact_type == "diagnosis":
                criteria = {
                    "active": "The diagnosis is active and documented for this encounter.",
                    "historical": "The diagnosis is only historical or resolved.",
                    "ruled_out": "The diagnosis is negated or ruled out.",
                    "uncertain": "The diagnosis is suspected or documentation is conflicting.",
                    "unsupported": "The evidence does not support this diagnosis fact.",
                }
            else:
                criteria = {
                    "supported": (
                        "The fact is directly documented for this encounter. For a quantity or "
                        "medication, it was actually administered or used, not merely planned or ordered."
                    ),
                    "historical": "The fact applies only to a prior encounter.",
                    "planned_only": "The fact was planned or ordered but did not occur.",
                    "uncertain": "The evidence is conflicting or ambiguous.",
                    "unsupported": "The evidence does not support this fact.",
                }
            questions[key] = {
                "type": "choice",
                "instructions": (
                    f"Classify the {fact.fact_type} fact '{fact.normalized_value or fact.value}' "
                    "using only its cited source evidence."
                ),
                "criteria": criteria,
            }
            metadata[key] = fact
        state = self._jev_state(chart, facts, spans)
        output = self._run_jev_decisions(
            chart,
            "jev_fact_validation",
            state,
            questions,
            {"facts": len(facts), "questions": len(questions)},
        )
        decisions: list[dict[str, Any]] = []
        accepted_fact_ids: list[str] = []
        if output.get("status") != "complete":
            return {
                "status": output.get("status", "unavailable"),
                "provider": output.get("provider", self.jev_provider.name),
                "model": output.get("model"),
                "label": output.get("label"),
                "decisions": decisions,
                "accepted_fact_ids": accepted_fact_ids,
            }
        answers = output.get("answers", {})
        for key, fact in metadata.items():
            allowed = set(questions[key]["criteria"])
            parsed = parse_choice(answers.get(key), allowed)
            bucket = decision_bucket(
                parsed.probability,
                self.settings.jev_accept_threshold,
                self.settings.jev_review_threshold,
            )
            supported_values = {
                "procedure": {"performed"},
                "diagnosis": {"active"},
            }.get(fact.fact_type, {"supported"})
            supports_coding = bool(
                parsed.valid
                and parsed.value in supported_values
                and parsed.probability is not None
                and parsed.probability >= self.settings.jev_review_threshold
            )
            if supports_coding:
                accepted_fact_ids.append(fact.id)
            decisions.append(
                {
                    "question": key,
                    "fact_id": fact.id,
                    "fact_type": fact.fact_type,
                    "fact": fact.normalized_value or fact.value,
                    "classification": parsed.value,
                    "probability": parsed.probability,
                    "probabilities": parsed.probabilities,
                    "status": bucket,
                    "supports_coding": supports_coding,
                    "error": parsed.error,
                    "evidence_span_ids": fact.evidence_span_ids,
                }
            )
        return {
            "status": "complete",
            "provider": output.get("provider", self.jev_provider.name),
            "model": output.get("model"),
            "decisions": decisions,
            "accepted_fact_ids": accepted_fact_ids,
        }

    def _jev_primary_output(
        self,
        chart: Chart,
        facts: list[ClinicalFact],
        candidates: list[CandidateCode],
        spans: list[EvidenceSpan],
        fact_trace: dict[str, Any],
        extraction_summary: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if fact_trace.get("status") != "complete":
            jev_output = _unavailable_jev_graph(
                self.jev_provider.name,
                fact_trace.get("model"),
                "JEV_UNAVAILABLE",
                fact_trace.get("label") or "JEV fact validation was unavailable",
                fact_trace.get("decisions", []),
            )
            return jev_output, {
                "summary": extraction_summary or "Clinical facts were preserved for review.",
                "lines": [],
                "pipeline_warnings": [
                    {"code": "JEV_UNAVAILABLE", "message": jev_output["label"]}
                ],
            }

        accepted_ids = set(fact_trace.get("accepted_fact_ids", []))
        validated_facts = [fact for fact in facts if fact.id in accepted_ids]
        codable_facts = [
            fact
            for fact in validated_facts
            if fact.fact_type in {"procedure", "diagnosis", "device", "medication"}
        ]
        questions: dict[str, dict[str, Any]] = {}
        metadata: dict[str, dict[str, Any]] = {}
        for fact in codable_facts:
            systems = (
                {"ICD10CM"}
                if fact.fact_type == "diagnosis"
                else {"CPT", "HCPCS"}
            )
            scoped = [item for item in candidates if item.code_system in systems][:20]
            criteria: dict[str, str] = {
                f"candidate_{index}": f"{item.code_system} {item.code}: {item.description or ''}"
                for index, item in enumerate(scoped)
            }
            criteria["NONE"] = "No supplied candidate is supported by the evidence."
            criteria["INSUFFICIENT_DOCUMENTATION"] = (
                "The evidence is insufficient to choose among the supplied candidates."
            )
            key = decision_key(fact.fact_type, "code", fact.id)
            questions[key] = {
                "type": "choice",
                "instructions": (
                    f"Choose the single active billing-code candidate best supported for the atomic "
                    f"{fact.fact_type} fact '{fact.normalized_value or fact.value}'. Abstain when needed."
                ),
                "criteria": criteria,
            }
            metadata[key] = {
                "fact": fact,
                "options": {
                    f"candidate_{index}": item for index, item in enumerate(scoped)
                },
            }
        selection_state = self._jev_state(chart, validated_facts, spans)
        selection_state["candidates"] = [
            self._candidate_state_payload(item) for item in candidates
        ]
        selection_output = self._run_jev_decisions(
            chart,
            "jev_code_selection",
            selection_state,
            questions,
            {"facts": len(codable_facts), "candidates": len(candidates), "questions": len(questions)},
        )
        if selection_output.get("status") != "complete":
            jev_output = _unavailable_jev_graph(
                self.jev_provider.name,
                selection_output.get("model"),
                "JEV_UNAVAILABLE",
                selection_output.get("label") or "JEV code selection was unavailable",
                fact_trace.get("decisions", []),
            )
            return jev_output, {
                "summary": extraction_summary or "Clinical facts and candidates were preserved for review.",
                "lines": [],
                "pipeline_warnings": [
                    {"code": "JEV_UNAVAILABLE", "message": jev_output["label"]}
                ],
            }

        selections: list[dict[str, Any]] = []
        proposed: dict[tuple[str, str], dict[str, Any]] = {}
        warnings: list[dict[str, Any]] = []
        answers = selection_output.get("answers", {})
        for key, details in metadata.items():
            fact = details["fact"]
            options = details["options"]
            allowed = set(options) | {"NONE", "INSUFFICIENT_DOCUMENTATION"}
            parsed = parse_choice(answers.get(key), allowed)
            bucket = decision_bucket(
                parsed.probability,
                self.settings.jev_accept_threshold,
                self.settings.jev_review_threshold,
            )
            candidate = options.get(parsed.value)
            abstained = parsed.value in {"NONE", "INSUFFICIENT_DOCUMENTATION"}
            selected = bool(
                parsed.valid
                and candidate is not None
                and parsed.probability is not None
                and parsed.probability >= self.settings.jev_review_threshold
            )
            if parsed.error == "out_of_set_choice":
                warnings.append(
                    {
                        "code": "OUT_OF_SET_JEV_CHOICE",
                        "message": "JEV returned a code choice outside the supplied candidate set",
                    }
                )
            alternatives = _choice_alternatives(parsed.probabilities, options)
            decision = {
                "question": key,
                "fact_id": fact.id,
                "fact_type": fact.fact_type,
                "fact": fact.normalized_value or fact.value,
                "candidate_id": candidate.id if candidate is not None else None,
                "code_system": candidate.code_system if candidate is not None else None,
                "code": candidate.code if candidate is not None else None,
                "choice": parsed.value,
                "probability": parsed.probability,
                "status": bucket,
                "selected": selected,
                "abstained": abstained,
                "error": parsed.error,
                "alternatives": alternatives,
                "evidence_span_ids": fact.evidence_span_ids,
            }
            selections.append(decision)
            if not selected or candidate is None:
                continue
            code_key = (candidate.code_system, canonical_code(candidate.code))
            existing = proposed.get(code_key)
            if existing is None:
                proposed[code_key] = {
                    "candidate": candidate,
                    "facts": [fact],
                    "probability": parsed.probability,
                    "evidence_span_ids": list(fact.evidence_span_ids),
                    "alternatives": alternatives,
                    "candidate_count": len(options),
                }
            else:
                existing["facts"].append(fact)
                existing["probability"] = min(existing["probability"], parsed.probability)
                existing["evidence_span_ids"] = sorted(
                    set(existing["evidence_span_ids"]) | set(fact.evidence_span_ids)
                )
                existing["candidate_count"] = max(existing["candidate_count"], len(options))

        proposed_lines = list(proposed.values())
        modifier_output, modifier_decisions = self._jev_modifier_decisions(
            chart, validated_facts, spans, proposed_lines
        )
        if modifier_output.get("status") != "complete":
            jev_output = _unavailable_jev_graph(
                self.jev_provider.name,
                modifier_output.get("model"),
                "JEV_UNAVAILABLE",
                modifier_output.get("label") or "JEV modifier decisions were unavailable",
                fact_trace.get("decisions", []),
            )
            jev_output["code_selections"] = selections
            return jev_output, {
                "summary": extraction_summary or "JEV modifier decisions require review.",
                "lines": [],
                "pipeline_warnings": [
                    {"code": "JEV_UNAVAILABLE", "message": jev_output["label"]}
                ],
            }

        diagnosis_output, diagnosis_links = self._jev_diagnosis_links(
            chart, validated_facts, spans, proposed_lines
        )
        if diagnosis_output.get("status") != "complete":
            jev_output = _unavailable_jev_graph(
                self.jev_provider.name,
                diagnosis_output.get("model"),
                "JEV_UNAVAILABLE",
                diagnosis_output.get("label") or "JEV diagnosis linkage was unavailable",
                fact_trace.get("decisions", []),
            )
            jev_output["code_selections"] = selections
            jev_output["modifier_decisions"] = modifier_decisions
            return jev_output, {
                "summary": extraction_summary or "JEV diagnosis linkage requires review.",
                "lines": [],
                "pipeline_warnings": [
                    {"code": "JEV_UNAVAILABLE", "message": jev_output["label"]}
                ],
            }

        line_output: list[dict[str, Any]] = []
        for proposed_line in proposed_lines:
            candidate = proposed_line["candidate"]
            code_key = (candidate.code_system, canonical_code(candidate.code))
            modifier_rows = [
                row
                for row in modifier_decisions
                if (row.get("code_system"), canonical_code(row.get("code"))) == code_key
            ]
            link_rows = [
                row
                for row in diagnosis_links
                if (row.get("procedure_system"), canonical_code(row.get("procedure_code")))
                == code_key
            ]
            modifiers = [row["modifier"] for row in modifier_rows if row.get("applied")]
            pointers = [row["diagnosis_code"] for row in link_rows if row.get("linked")]
            relevant_probabilities = [float(proposed_line["probability"])]
            relevant_probabilities.extend(
                float(row["probability"])
                for row in modifier_rows
                if row.get("applied") and row.get("probability") is not None
            )
            relevant_probabilities.extend(
                float(row["probability"])
                for row in link_rows
                if row.get("linked") and row.get("probability") is not None
            )
            fact = proposed_line["facts"][0]
            units = self._deterministic_units(candidate, fact, validated_facts)
            rationale = (
                f"{candidate.code_system} {candidate.code} selected by JEV from "
                f"{proposed_line['candidate_count']} active candidate options. "
                f"Selection probability: {float(proposed_line['probability']):.1%}. "
                f"Supporting clinical fact: '{fact.normalized_value or fact.value}'. "
                f"Evidence spans: {', '.join(proposed_line['evidence_span_ids'])}."
            )
            line_output.append(
                {
                    "code_system": candidate.code_system,
                    "code": candidate.code,
                    "units": units,
                    "modifiers": modifiers,
                    "diagnosis_pointers": pointers,
                    "confidence": min(relevant_probabilities),
                    "rationale": rationale,
                    "evidence_span_ids": proposed_line["evidence_span_ids"],
                }
            )

        all_decisions = (
            list(fact_trace.get("decisions", []))
            + selections
            + modifier_decisions
            + diagnosis_links
        )
        summary = _decision_summary(all_decisions)
        model = selection_output.get("model") or fact_trace.get("model")
        jev_output = {
            "provider": self.jev_provider.name,
            "mode": "primary",
            "status": "complete",
            "model": model,
            "facts": fact_trace.get("decisions", []),
            "code_selections": selections,
            "modifier_decisions": modifier_decisions,
            "diagnosis_links": diagnosis_links,
            "rule_exception_decisions": [],
            "summary": summary,
        }
        if any(item.get("abstained") for item in selections):
            warnings.append(
                {
                    "code": "JEV_ABSTAINED",
                    "message": "JEV abstained from one or more coding choices; human review is required",
                }
            )
        return jev_output, {
            "summary": (
                f"TypeSafe JEV assembled {len(line_output)} evidence-backed coding line(s) "
                f"from {len(selections)} bounded code decisions."
            ),
            "lines": line_output,
            "pipeline_warnings": warnings,
        }

    def _jev_modifier_decisions(
        self,
        chart: Chart,
        facts: list[ClinicalFact],
        spans: list[EvidenceSpan],
        proposed_lines: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        supported_text = " ".join(
            (fact.normalized_value or fact.value).lower() for fact in facts
        )
        left = bool(re.search(r"\b(left|lt)\b", supported_text))
        right = bool(re.search(r"\b(right|rt)\b", supported_text))
        bilateral = "bilateral" in supported_text or (left and right)
        modifier_codes: list[str] = []
        if bilateral:
            modifier_codes.append("50")
        elif left:
            modifier_codes.append("LT")
        elif right:
            modifier_codes.append("RT")
        if len([row for row in proposed_lines if row["candidate"].code_system in {"CPT", "HCPCS"}]) > 1:
            modifier_codes.append("51")
        if "assistant surgeon" in supported_text or "assistant at surgery" in supported_text:
            modifier_codes.append("80")
        codebooks = CodebookRepository(self.session)
        active_modifiers = {
            code: codebooks.get_modifier(code, chart.service_date)
            for code in dict.fromkeys(modifier_codes)
        }
        active_modifiers = {code: entry for code, entry in active_modifiers.items() if entry}
        questions: dict[str, dict[str, Any]] = {}
        metadata: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(proposed_lines):
            candidate = row["candidate"]
            if candidate.code_system not in {"CPT", "HCPCS"}:
                continue
            for modifier, entry in active_modifiers.items():
                key = decision_key("line", str(index), "modifier", modifier)
                questions[key] = {
                    "type": "noul",
                    "instructions": (
                        f"Does the source evidence support active modifier {modifier} "
                        f"({entry.description or 'modifier'}) on {candidate.code_system} "
                        f"{candidate.code} for this encounter?"
                    ),
                    "criteria": {
                        "true": "The modifier circumstance is directly supported.",
                        "false": "It is absent, contradictory, planned-only, or uncertain.",
                    },
                }
                metadata[key] = {
                    "code_system": candidate.code_system,
                    "code": candidate.code,
                    "modifier": modifier,
                }
        output = self._run_jev_decisions(
            chart,
            "jev_modifier_resolution",
            self._jev_state(chart, facts, spans),
            questions,
            {"lines": len(proposed_lines), "questions": len(questions)},
        )
        if output.get("status") != "complete":
            return output, []
        decisions: list[dict[str, Any]] = []
        for key, details in metadata.items():
            parsed = parse_noul(output.get("answers", {}).get(key))
            bucket, supported = _noul_status(
                parsed.probability, self.settings.jev_accept_threshold
            )
            decisions.append(
                {
                    **details,
                    "question": key,
                    "probability": parsed.probability,
                    "status": bucket,
                    "supported": supported,
                    "applied": parsed.valid and bucket == "accepted" and supported,
                    "error": parsed.error,
                }
            )
        return output, decisions

    def _jev_diagnosis_links(
        self,
        chart: Chart,
        facts: list[ClinicalFact],
        spans: list[EvidenceSpan],
        proposed_lines: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        procedures = [
            row for row in proposed_lines if row["candidate"].code_system in {"CPT", "HCPCS"}
        ]
        diagnoses = [
            row for row in proposed_lines if row["candidate"].code_system == "ICD10CM"
        ]
        questions: dict[str, dict[str, Any]] = {}
        metadata: dict[str, dict[str, Any]] = {}
        for procedure_index, procedure in enumerate(procedures):
            for diagnosis_index, diagnosis in enumerate(diagnoses):
                procedure_candidate = procedure["candidate"]
                diagnosis_candidate = diagnosis["candidate"]
                key = decision_key("diagnosis_link", str(procedure_index), str(diagnosis_index))
                questions[key] = {
                    "type": "noul",
                    "instructions": (
                        f"Does diagnosis {diagnosis_candidate.code} support procedure "
                        f"{procedure_candidate.code} for this encounter based on the source evidence?"
                    ),
                    "criteria": {
                        "true": "The diagnosis is clinically related to and supports this procedure.",
                        "false": "The diagnosis is unrelated, historical, ruled out, or unsupported.",
                    },
                }
                metadata[key] = {
                    "procedure_system": procedure_candidate.code_system,
                    "procedure_code": procedure_candidate.code,
                    "diagnosis_code": diagnosis_candidate.code,
                }
        output = self._run_jev_decisions(
            chart,
            "jev_diagnosis_linkage",
            self._jev_state(chart, facts, spans),
            questions,
            {"procedures": len(procedures), "diagnoses": len(diagnoses), "questions": len(questions)},
        )
        if output.get("status") != "complete":
            return output, []
        decisions: list[dict[str, Any]] = []
        for key, details in metadata.items():
            parsed = parse_noul(output.get("answers", {}).get(key))
            bucket, supported = _noul_status(
                parsed.probability, self.settings.jev_accept_threshold
            )
            decisions.append(
                {
                    **details,
                    "question": key,
                    "probability": parsed.probability,
                    "status": bucket,
                    "supported": supported,
                    "linked": parsed.valid and bucket == "accepted" and supported,
                    "error": parsed.error,
                }
            )
        return output, decisions

    def _deterministic_units(
        self,
        candidate: CandidateCode,
        fact: ClinicalFact,
        facts: list[ClinicalFact],
    ) -> int:
        if candidate.code_system != "HCPCS":
            return 1
        entry = self.session.get(CodeEntry, candidate.code_entry_id)
        metadata = entry.metadata_json if entry is not None else {}
        unit_size = _numeric_metadata(
            metadata,
            "billing_unit_mg",
            "unit_size_mg",
            "billing_unit",
            "units_per_billing_unit",
        )
        if unit_size is None or unit_size <= 0:
            return 1
        evidence_ids = set(fact.evidence_span_ids)
        quantities = [
            item
            for item in facts
            if item.fact_type == "quantity"
            and (evidence_ids & set(item.evidence_span_ids) or len(facts) == 1)
        ]
        if not quantities:
            quantities = [item for item in facts if item.fact_type == "quantity"]
        for quantity in quantities:
            match = re.search(
                r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>mg|mcg|g|ml)\b",
                quantity.normalized_value or quantity.value,
                re.I,
            )
            if not match or match.group("unit").lower() != "mg":
                continue
            administered = float(match.group("value"))
            return max(1, math.ceil(administered / unit_size))
        return 1

    def _jev_state(
        self,
        chart: Chart,
        facts: list[ClinicalFact],
        spans: list[EvidenceSpan],
    ) -> dict[str, Any]:
        referenced_ids = {
            evidence_id for fact in facts for evidence_id in fact.evidence_span_ids
        }
        evidence = [
            {"evidence_span_id": span.id, "text": span.text[:4000]}
            for span in spans
            if span.id in referenced_ids
        ]
        return {
            "service_date": chart.service_date.isoformat(),
            "setting": chart.setting,
            "deidentified": chart.deidentified,
            "facts": [_fact_payload(fact) for fact in facts],
            "evidence": evidence,
        }

    def _candidate_state_payload(self, candidate: CandidateCode) -> dict[str, Any]:
        entry = self.session.get(CodeEntry, candidate.code_entry_id)
        metadata = entry.metadata_json if entry is not None else {}
        return {
            **_candidate_payload(candidate),
            "codebook_metadata": {
                "billable": entry.billable if entry is not None else None,
                "category": entry.category if entry is not None else None,
                "chapter": entry.chapter if entry is not None else None,
                "anatomic_region": entry.anatomic_region if entry is not None else None,
                "laterality_supported": (
                    entry.laterality_supported if entry is not None else None
                ),
                "billing_unit_mg": (
                    metadata.get("billing_unit_mg") if isinstance(metadata, dict) else None
                ),
                "unit_size_mg": (
                    metadata.get("unit_size_mg") if isinstance(metadata, dict) else None
                ),
            },
        }

    def _run_jev_decisions(
        self,
        chart: Chart,
        stage: str,
        state: dict[str, Any],
        questions: dict[str, dict[str, Any]],
        input_summary: dict[str, Any],
    ) -> dict[str, Any]:
        if not questions:
            return {
                "provider": self.jev_provider.name,
                "status": "complete",
                "model": getattr(self.jev_provider, "model", "configured"),
                "answers": {},
                "usage": {},
            }
        run = ModelRun(
            id=new_id(),
            chart_id=chart.id,
            stage=stage,
            provider=self.jev_provider.name,
            model=getattr(self.jev_provider, "model", "configured"),
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
            output = self.jev_provider.decide(state, questions)
        except Exception as exc:
            output = {
                "provider": self.jev_provider.name,
                "status": "unavailable",
                "model": getattr(self.jev_provider, "model", "configured"),
                "label": "JEV decision service was unavailable; human review is required",
                "error_type": type(exc).__name__,
                "answers": {},
            }
        run.status = "complete" if output.get("status") == "complete" else "failed"
        run.model = str(output.get("model") or run.model)
        run.output_json = output
        run.token_usage = output.get("usage", {})
        run.error = None if run.status == "complete" else str(output.get("label") or "JEV unavailable")
        run.completed_at = utcnow()
        self.session.commit()
        return output

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
        *,
        source: str = "reasoning_model",
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
            if not evidence_ids:
                warnings.append(
                    {
                        "code": "EVIDENCE_REQUIRED",
                        "message": f"{candidate.code_system} {candidate.code} was omitted because it had no valid evidence",
                    }
                )
                continue
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
                source=source,
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

    def _jev_adjudicate_rule_exceptions(
        self,
        chart: Chart,
        facts: list[ClinicalFact],
        spans: list[EvidenceSpan],
        lines: list[CodingLine],
        findings: list[RuleFinding],
        jev_output: dict[str, Any],
    ) -> list[RuleFinding]:
        questions: dict[str, dict[str, Any]] = {}
        metadata: dict[str, RuleFinding] = {}
        for index, finding in enumerate(findings):
            if (
                finding.rule_type != "ncci_ptp"
                or finding.details.get("modifier_indicator") != "1"
            ):
                continue
            key = decision_key("ncci_exception", str(index))
            questions[key] = {
                "type": "noul",
                "instructions": (
                    "Does the source evidence document a genuinely distinct procedural service "
                    f"for NCCI pair {finding.details.get('column_1')}/"
                    f"{finding.details.get('column_2')} that supports a permitted modifier exception?"
                ),
                "criteria": {
                    "true": "The distinct-service circumstance is explicit in the evidence.",
                    "false": "The evidence is insufficient, contradictory, or describes bundled work.",
                },
            }
            metadata[key] = finding
        state = self._jev_state(chart, facts, spans)
        state["proposed_coding_lines"] = [
            {
                "system": line.code_system,
                "code": line.code,
                "modifiers": line.modifiers,
                "evidence_span_ids": line.evidence_span_ids,
            }
            for line in lines
        ]
        output = self._run_jev_decisions(
            chart,
            "jev_rule_adjudication",
            state,
            questions,
            {"ncci_exceptions": len(questions)},
        )
        if output.get("status") != "complete":
            if questions:
                jev_output["status"] = "unavailable"
                jev_output["label"] = output.get("label") or "JEV rule adjudication unavailable"
                return [
                    RuleFinding(
                        "jev_availability",
                        "warning",
                        "JEV_UNAVAILABLE: NCCI documentation exception could not be adjudicated",
                        details={"status": output.get("status")},
                    )
                ]
            return []
        extra_findings: list[RuleFinding] = []
        line_by_id = {line.id: line for line in lines}
        decisions = jev_output.setdefault("rule_exception_decisions", [])
        for key, finding in metadata.items():
            parsed = parse_noul(output.get("answers", {}).get(key))
            status, supported = _noul_status(
                parsed.probability, self.settings.jev_accept_threshold
            )
            line = line_by_id.get(finding.line_id or "")
            applied = False
            if status == "accepted" and supported and line is not None:
                modifier = CodebookRepository(self.session).get_modifier("59", chart.service_date)
                if modifier is not None and "59" not in line.modifiers:
                    line.modifiers = [*line.modifiers, "59"]
                    line.confidence = min(line.confidence, float(parsed.probability))
                    applied = True
                    finding.outcome = "pass"
                    finding.message = (
                        f"JEV supports a documented NCCI modifier exception "
                        f"({float(parsed.probability):.1%})"
                    )
                    extra_findings.append(
                        RuleFinding(
                            "modifier_active",
                            "pass",
                            "Modifier 59 is active",
                            line.id,
                            {"modifier": "59", "source": "jev_ncci_exception"},
                        )
                    )
            elif status == "accepted" and not supported:
                finding.outcome = "fail"
                finding.message = "NCCI modifier exception is not supported by the documentation"
            else:
                finding.outcome = "warning"
                finding.message = "NCCI modifier exception remains ambiguous and requires review"
            decisions.append(
                {
                    "question": key,
                    "kind": "ncci_exception",
                    "column_1": finding.details.get("column_1"),
                    "column_2": finding.details.get("column_2"),
                    "probability": parsed.probability,
                    "status": status,
                    "supported": supported,
                    "modifier": "59" if applied else None,
                    "error": parsed.error,
                }
            )
        jev_output["summary"] = _decision_summary(_all_jev_decisions(jev_output))
        return extra_findings

    def _primary_jev_findings(
        self,
        lines: list[CodingLine],
        output: dict[str, Any],
    ) -> list[RuleFinding]:
        if output.get("status") != "complete":
            return [
                RuleFinding(
                    "jev_availability",
                    "warning",
                    str(output.get("label") or "JEV_UNAVAILABLE: human review is required"),
                    details={"status": output.get("status")},
                )
            ]
        line_by_code = {
            (line.code_system, canonical_code(line.code)): line for line in lines
        }
        findings: list[RuleFinding] = []
        for decision in _all_jev_decisions(output):
            status = decision.get("status")
            abstained = bool(decision.get("abstained"))
            if abstained:
                outcome = "warning"
                message = "JEV abstained from a bounded coding choice"
            elif status == "accepted":
                outcome = "pass"
                message = "JEV decision met the configured acceptance threshold"
            elif status == "review":
                outcome = "warning"
                message = "JEV decision is within the configured review band"
            else:
                outcome = "warning"
                message = "JEV decision was missing, malformed, or unsupported"
            code_system = decision.get("code_system") or decision.get("procedure_system")
            code = decision.get("code") or decision.get("procedure_code")
            line = line_by_code.get((code_system, canonical_code(code)))
            findings.append(
                RuleFinding(
                    "jev_decision",
                    outcome,
                    message,
                    line.id if line is not None else None,
                    {
                        "question": decision.get("question"),
                        "probability": decision.get("probability"),
                        "status": status,
                        "model": output.get("model"),
                    },
                )
            )
        return findings

    def _calibrate_primary(
        self,
        result: CodingResult,
        lines: list[CodingLine],
        findings: list[RuleFinding],
        pipeline_warnings: list[dict[str, Any]],
        jev_output: dict[str, Any],
    ) -> None:
        outcomes = Counter(finding.outcome for finding in findings)
        probabilities = [line.confidence for line in lines]
        score = min(probabilities) if probabilities else 0.0
        summary = jev_output.get("summary", {})
        unavailable = jev_output.get("status") != "complete"
        unresolved = bool(summary.get("review", 0) or summary.get("rejected", 0))
        if unavailable or not lines or outcomes["fail"]:
            state = "RED"
        elif (
            score >= self.settings.jev_accept_threshold
            and not unresolved
            and not pipeline_warnings
            and outcomes["warning"] == 0
        ):
            state = "GREEN"
        else:
            state = "YELLOW"
        result.confidence_score = round(max(0.0, min(1.0, score)), 4)
        result.confidence_state = state
        result.warnings = pipeline_warnings + [
            {"code": finding.rule_type.upper(), "message": finding.message}
            for finding in findings
            if finding.outcome in {"warning", "fail"}
        ]
        result.autonomous_eligible = bool(
            self.settings.autonomous_coding_enabled
            and self.settings.coding_decision_engine == "jev_primary"
            and not unavailable
            and state == "GREEN"
            and outcomes["fail"] == 0
            and all(line.confidence >= self.settings.jev_accept_threshold for line in lines)
        )
        result.status = "ready_for_submission" if result.autonomous_eligible else "needs_review"

    def _calibrate_legacy(
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
            and self.settings.coding_decision_engine == "jev_primary"
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


def _fact_payload(fact: ClinicalFact) -> dict[str, Any]:
    return {
        "fact_id": fact.id,
        "fact_type": fact.fact_type,
        "value": fact.value,
        "normalized_value": fact.normalized_value,
        "assertion": fact.assertion,
        "confidence": fact.confidence,
        "evidence_span_ids": fact.evidence_span_ids,
    }


def _candidate_payload(candidate: CandidateCode) -> dict[str, Any]:
    return {
        "candidate_id": candidate.id,
        "code_system": candidate.code_system,
        "code": candidate.code,
        "description": candidate.description,
        "retrieval_rank": candidate.retrieval_rank,
    }


def _choice_alternatives(
    probabilities: dict[str, float],
    options: dict[str, CandidateCode],
) -> list[dict[str, Any]]:
    alternatives = [
        {
            "candidate_id": candidate.id,
            "code_system": candidate.code_system,
            "code": candidate.code,
            "description": candidate.description,
            "probability": probability,
        }
        for option, probability in probabilities.items()
        if (candidate := options.get(option)) is not None
    ]
    return sorted(alternatives, key=lambda item: item["probability"], reverse=True)


def _noul_status(probability: float | None, accept_threshold: float) -> tuple[str, bool]:
    if probability is None:
        return "rejected", False
    if probability >= accept_threshold:
        return "accepted", True
    if probability <= 1 - accept_threshold:
        return "accepted", False
    return "review", probability >= 0.5


def _decision_summary(decisions: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"decision_count": len(decisions), "accepted": 0, "review": 0, "rejected": 0}
    for decision in decisions:
        status = str(decision.get("status", "rejected"))
        if status not in {"accepted", "review", "rejected"}:
            status = "rejected"
        summary[status] += 1
    return summary


def _all_jev_decisions(output: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for key in (
            "facts",
            "code_selections",
            "modifier_decisions",
            "diagnosis_links",
            "rule_exception_decisions",
        )
        for item in output.get(key, [])
        if isinstance(item, dict)
    ]


def _unavailable_jev_graph(
    provider: str,
    model: Any,
    code: str,
    label: str,
    fact_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "provider": provider,
        "mode": "primary",
        "status": "unavailable",
        "model": model,
        "error_code": code,
        "label": label,
        "facts": fact_decisions,
        "code_selections": [],
        "modifier_decisions": [],
        "diagnosis_links": [],
        "rule_exception_decisions": [],
        "summary": _decision_summary(fact_decisions),
    }


def _numeric_metadata(metadata: Any, *keys: str) -> float | None:
    if not isinstance(metadata, dict):
        return None
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, (float, int)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"\d+(?:\.\d+)?", value)
            if match:
                return float(match.group())
    return None


def _shadow_comparison(
    legacy_output: dict[str, Any],
    shadow_output: dict[str, Any],
) -> dict[str, Any]:
    legacy_lines = list(legacy_output.get("lines", []))
    shadow_lines = list(shadow_output.get("lines", []))

    def code_set(lines: list[dict[str, Any]], system: str | None = None) -> set[str]:
        return {
            canonical_code(line.get("code"))
            for line in lines
            if line.get("code") and (system is None or line.get("code_system") == system)
        }

    def modifiers(lines: list[dict[str, Any]]) -> set[tuple[str, str]]:
        return {
            (canonical_code(line.get("code")), canonical_code(modifier))
            for line in lines
            for modifier in line.get("modifiers", [])
        }

    def units(lines: list[dict[str, Any]]) -> dict[str, int]:
        return {
            canonical_code(line.get("code")): int(line.get("units", 1))
            for line in lines
            if line.get("code")
        }

    confidences = [
        float(line.get("confidence"))
        for line in shadow_lines
        if isinstance(line.get("confidence"), (float, int))
    ]
    return {
        "exact_code_set_agreement": code_set(legacy_lines) == code_set(shadow_lines),
        "cpt_agreement": code_set(legacy_lines, "CPT") == code_set(shadow_lines, "CPT"),
        "icd_agreement": code_set(legacy_lines, "ICD10CM") == code_set(shadow_lines, "ICD10CM"),
        "hcpcs_agreement": code_set(legacy_lines, "HCPCS") == code_set(shadow_lines, "HCPCS"),
        "modifier_agreement": modifiers(legacy_lines) == modifiers(shadow_lines),
        "unit_agreement": units(legacy_lines) == units(shadow_lines),
        "line_count_difference": len(shadow_lines) - len(legacy_lines),
        "jev_confidence": min(confidences) if confidences else None,
    }


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


def _jev_findings(
    lines: list[CodingLine],
    output: dict[str, Any],
    accept_threshold: float,
    review_threshold: float,
) -> list[RuleFinding]:
    status = output.get("status")
    if status not in {"confirmed", "requires_review"}:
        return [
            RuleFinding(
                "jev_decision",
                "warning",
                str(output.get("label") or "JEV was not executed; human review is required"),
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
            message = "JEV did not return a usable probability for this coding decision"
        elif probability >= accept_threshold:
            outcome = "pass"
            message = f"JEV support probability is {probability:.1%}"
        elif probability >= review_threshold:
            outcome = "warning"
            message = f"JEV support probability is only {probability:.1%}"
        else:
            outcome = "fail"
            message = f"JEV does not support this decision ({probability:.1%})"
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
