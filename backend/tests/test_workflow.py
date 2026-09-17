from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from app.coding.document import ExtractedPage
from app.coding.processing import ChartProcessor
from app.coding.providers import MockJevProvider, ProviderResult
from app.config import Settings
from app.models.reference import (
    CodeEntry,
    CodeSearchDocument,
    CodebookRelease,
    RawReferenceFile,
    ReferenceImportRun,
    new_id,
)
from app.models.workflow import Chart, CodingResult, EvidenceSpan, ModelRun, RuleDecision
from app.storage import chart_storage


class FakeDocumentExtractor:
    def extract(self, _path: Path) -> list[ExtractedPage]:
        text = "Arthroscopic rotator cuff repair was performed on the right shoulder."
        return [
            ExtractedPage(
                page_number=1,
                text=text,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                extraction_method="embedded_text",
                width=612,
                height=792,
            )
        ]


class FakeProvider:
    provider_name = "test"
    model = "deterministic-test-model"

    def extract_facts(self, evidence):  # type: ignore[no-untyped-def]
        evidence_id = evidence[0]["evidence_span_id"]
        data = {
            "summary": "Documented arthroscopic rotator cuff repair.",
            "search_queries": ["rotator cuff repair"],
            "facts": [
                {
                    "fact_type": "procedure",
                    "value": "arthroscopic rotator cuff repair",
                    "normalized_value": "rotator cuff repair",
                    "assertion": "present",
                    "confidence": 0.98,
                    "evidence_span_ids": [evidence_id],
                }
            ],
        }
        return ProviderResult(data, {"input_tokens": 10}, self.model, "facts-fingerprint")

    def select_codes(self, facts, candidates, service_date):  # type: ignore[no-untyped-def]
        candidate = next(item for item in candidates if item["code"] == "29827")
        data = {
            "summary": "CPT 29827 is directly supported by the operative statement.",
            "lines": [
                {
                    "code_system": candidate["code_system"],
                    "code": candidate["code"],
                    "units": 1,
                    "modifiers": [],
                    "diagnosis_pointers": [],
                    "confidence": 0.95,
                    "rationale": "Documented arthroscopic rotator cuff repair.",
                    "evidence_span_ids": facts[0]["evidence_span_ids"],
                }
            ],
        }
        return ProviderResult(data, {"input_tokens": 20}, self.model, "coding-fingerprint")


def test_chart_processing_preserves_evidence_and_applies_gate(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url=None,
        storage_provider="local",
        local_storage_path=tmp_path,
        openai_api_key="test",
        llm_model="test",
        autonomous_coding_enabled=False,
    )
    run = ReferenceImportRun(
        id=new_id(),
        status="published",
        source_root="test",
        release_name="2026-test",
        parser_version="test",
        source_manifest_sha256="a" * 64,
        published=True,
        summary={},
    )
    session.add(run)
    session.flush()
    source = RawReferenceFile(
        id=new_id(),
        import_run_id=run.id,
        original_filename="licensed.txt",
        relative_path="licensed.txt",
        source_family="cpt_licensed",
        file_size=1,
        sha256="b" * 64,
        parser_version="test",
        metadata_json={"licensed_boundary": True},
    )
    session.add(source)
    release = CodebookRelease(
        id=new_id(),
        import_run_id=run.id,
        name="2026-test",
        status="published",
        effective_from=date(2026, 1, 1),
        source_manifest_sha256="a" * 64,
        parser_version="test",
        validation_summary={},
    )
    session.add(release)
    session.flush()
    entry = CodeEntry(
        id=new_id(),
        codebook_release_id=release.id,
        code_system="CPT",
        code="29827",
        code_key="29827",
        short_description="Arthroscopic rotator cuff repair",
        long_description="Arthroscopy shoulder surgical rotator cuff repair",
        effective_from=date(2026, 1, 1),
        billable=True,
        category="Category I",
        chapter="Surgery",
        metadata_json={"licensed_boundary": True},
        source_version="2026",
        source_file_id=source.id,
    )
    session.add(entry)
    session.flush()
    session.add(
        CodeSearchDocument(
            id=new_id(),
            codebook_release_id=release.id,
            code_entry_id=entry.id,
            code=entry.code,
            description=entry.long_description,
            synonyms=[],
            search_text="29827 arthroscopy shoulder surgical rotator cuff repair",
            embedding=None,
        )
    )
    chart_id = new_id()
    storage_key = chart_storage(settings).put_pdf(chart_id, b"%PDF-test")
    chart = Chart(
        id=chart_id,
        original_filename="deidentified.pdf",
        storage_key=storage_key,
        sha256="c" * 64,
        file_size=9,
        service_date=date(2026, 9, 1),
        setting="practitioner",
        deidentified=True,
    )
    session.add(chart)
    session.commit()

    report = ChartProcessor(
        session,
        settings,
        provider=FakeProvider(),
        jev_provider=MockJevProvider(),
        document_extractor=FakeDocumentExtractor(),
    ).process(chart.id)

    assert report["status"] == "needs_review"
    assert report["confidence_state"] == "YELLOW"
    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert result.autonomous_eligible is False
    assert result.lines[0].code == "29827"
    assert result.lines[0].evidence_span_ids
    assert session.query(EvidenceSpan).count() == 1
    assert session.query(ModelRun).count() == 2
    assert {item.outcome for item in session.query(RuleDecision)} == {"pass", "warning"}
