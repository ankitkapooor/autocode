from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from app.coding.document import ExtractedPage
from app.coding.processing import ChartProcessor
from app.coding.providers import MockJevProvider, ProviderResult
from app.config import Settings
from app.models.reference import (
    AddonCodeRelation,
    CodeEntry,
    CodeSearchDocument,
    CodebookRelease,
    ModifierEntry,
    NcciPtpEdit,
    RawReferenceFile,
    ReferenceImportRun,
    new_id,
)
from app.models.workflow import (
    CandidateCode,
    Chart,
    CodingResult,
    EvidenceSpan,
    ModelRun,
    RuleDecision,
)
from app.storage import chart_storage


class FakeDocumentExtractor:
    def __init__(self, text: str | None = None):
        self.text = text or "Arthroscopic rotator cuff repair was performed on the right shoulder."

    def extract(self, _path: Path) -> list[ExtractedPage]:
        text = self.text
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

    def __init__(
        self,
        *,
        facts: list[dict] | None = None,
        search_queries: list[str] | None = None,
        selected_codes: list[str] | None = None,
        fail_on_select: bool = False,
    ):
        self.facts = facts
        self.search_queries = search_queries
        self.selected_codes = selected_codes or ["29827"]
        self.fail_on_select = fail_on_select
        self.extract_calls = 0
        self.select_calls = 0

    def extract_facts(self, evidence):  # type: ignore[no-untyped-def]
        self.extract_calls += 1
        evidence_id = evidence[0]["evidence_span_id"]
        facts = self.facts or [
            {
                "fact_type": "procedure",
                "value": "arthroscopic rotator cuff repair",
                "normalized_value": "rotator cuff repair",
                "assertion": "present",
                "confidence": 0.98,
            }
        ]
        data = {
            "summary": "Documented arthroscopic rotator cuff repair.",
            "search_queries": self.search_queries or [
                str(item.get("normalized_value") or item.get("value")) for item in facts
            ],
            "facts": [
                {**item, "evidence_span_ids": item.get("evidence_span_ids") or [evidence_id]}
                for item in facts
            ],
        }
        return ProviderResult(data, {"input_tokens": 10}, self.model, "facts-fingerprint")

    def select_codes(self, facts, candidates, service_date):  # type: ignore[no-untyped-def]
        self.select_calls += 1
        if self.fail_on_select:
            raise AssertionError("select_codes must not be called")
        selected = [item for item in candidates if item["code"] in self.selected_codes]
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
                for candidate in selected
            ],
        }
        return ProviderResult(data, {"input_tokens": 20}, self.model, "coding-fingerprint")


class ScriptedJevProvider:
    name = "typesafe_jev"
    model = "jev-test"

    def __init__(
        self,
        *,
        fact_classes: dict[str, str] | None = None,
        code_by_fact: dict[str, str] | None = None,
        abstain_for: set[str] | None = None,
        unavailable: bool = False,
    ):
        self.fact_classes = fact_classes or {}
        self.code_by_fact = code_by_fact or {}
        self.abstain_for = abstain_for or set()
        self.unavailable = unavailable
        self.calls: list[set[str]] = []
        self.question_batches: list[dict[str, dict]] = []
        self.states: list[dict] = []

    def decide(self, state, questions):  # type: ignore[no-untyped-def]
        self.calls.append(set(questions))
        self.question_batches.append(questions)
        self.states.append(state)
        if self.unavailable:
            return {
                "provider": self.name,
                "model": self.model,
                "status": "unavailable",
                "label": "simulated JEV outage",
                "answers": {},
            }
        evidence = " ".join(item.get("text", "") for item in state.get("evidence", [])).lower()
        answers = {}
        for key, question in questions.items():
            if question["type"] == "choice":
                instructions = question["instructions"].lower()
                criteria = question["criteria"]
                if key.startswith("fact_"):
                    choice = next(
                        (
                            classification
                            for phrase, classification in self.fact_classes.items()
                            if phrase.lower() in instructions
                        ),
                        "performed" if "procedure fact" in instructions else (
                            "active" if "diagnosis fact" in instructions else "supported"
                        ),
                    )
                else:
                    if any(phrase.lower() in instructions for phrase in self.abstain_for):
                        choice = "NONE"
                    else:
                        target = next(
                            (
                                code
                                for phrase, code in self.code_by_fact.items()
                                if phrase.lower() in instructions
                            ),
                            None,
                        )
                        choice = next(
                            (
                                option
                                for option, description in criteria.items()
                                if target and f" {target}:" in description
                            ),
                            next(option for option in criteria if option.startswith("candidate_")),
                        )
                answers[key] = {
                    "type": "choice",
                    "choice": choice,
                    "probabilities": {choice: 0.96},
                }
            else:
                instructions = question["instructions"].lower()
                probability = 0.95
                if "_candidate_" in key:
                    target = next(
                        (
                            code
                            for phrase, code in self.code_by_fact.items()
                            if phrase.lower() in instructions
                        ),
                        None,
                    )
                    if any(phrase.lower() in instructions for phrase in self.abstain_for):
                        probability = 0.5
                    elif target and f" {target.lower()} (" in instructions:
                        probability = 0.96
                    else:
                        probability = 0.05
                elif "modifier rt" in instructions and "right" not in evidence:
                    probability = 0.05
                elif "modifier lt" in instructions and "left" not in evidence:
                    probability = 0.05
                elif "modifier 50" in instructions and not (
                    "bilateral" in evidence or ("left" in evidence and "right" in evidence)
                ):
                    probability = 0.05
                elif "modifier 51" in instructions or "modifier 80" in instructions:
                    probability = 0.05
                elif "ncci pair" in instructions and "separate incision" not in evidence:
                    probability = 0.05
                answers[key] = {"type": "noul", "noul": probability}
        return {
            "provider": self.name,
            "model": self.model,
            "status": "complete",
            "answers": answers,
            "usage": {},
        }

    def validate(self, payload):  # type: ignore[no-untyped-def]
        return {
            "provider": self.name,
            "model": self.model,
            "status": "confirmed",
            "decisions": [],
            "answers": {},
        }


def _settings(tmp_path: Path, mode: str) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+pysqlite:///:memory:",
        redis_url=None,
        storage_provider="local",
        local_storage_path=tmp_path,
        openai_api_key="test",
        llm_model="test",
        coding_decision_engine=mode,
        autonomous_coding_enabled=False,
    )


def _seed_chart(
    session,  # type: ignore[no-untyped-def]
    settings: Settings,
    *,
    text: str,
    codes: list[dict],
    modifiers: list[str] | None = None,
) -> tuple[Chart, CodebookRelease, RawReferenceFile]:
    run = ReferenceImportRun(
        id=new_id(),
        status="published",
        source_root="test",
        release_name="2026-test",
        parser_version="test",
        source_manifest_sha256="d" * 64,
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
        sha256="e" * 64,
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
        source_manifest_sha256="d" * 64,
        parser_version="test",
        validation_summary={},
    )
    session.add(release)
    session.flush()
    for row in codes:
        entry = CodeEntry(
            id=new_id(),
            codebook_release_id=release.id,
            code_system=row.get("code_system", "CPT"),
            code=row["code"],
            code_key=row["code"].replace(".", "").upper(),
            short_description=row["description"],
            long_description=row["description"],
            effective_from=date(2026, 1, 1),
            billable=row.get("billable", True),
            category="Category I",
            chapter="Test",
            metadata_json=row.get("metadata", {"licensed_boundary": True}),
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
                search_text=f"{entry.code} {entry.long_description}".lower(),
                embedding=None,
            )
        )
    for modifier in modifiers or []:
        session.add(
            ModifierEntry(
                id=new_id(),
                codebook_release_id=release.id,
                modifier=modifier,
                modifier_key=modifier,
                description=f"Test modifier {modifier}",
                type="HCPCS_LEVEL_II",
                compatible_code_families=[],
                effective_from=date(2026, 1, 1),
                metadata_json={},
                source_version="2026",
                source_file_id=source.id,
            )
        )
    chart_id = new_id()
    storage_key = chart_storage(settings).put_pdf(chart_id, b"%PDF-test")
    chart = Chart(
        id=chart_id,
        original_filename="deidentified.pdf",
        storage_key=storage_key,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        file_size=9,
        service_date=date(2026, 9, 1),
        setting="practitioner",
        deidentified=True,
    )
    session.add(chart)
    session.commit()
    return chart, release, source


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
        coding_decision_engine="legacy_llm",
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


def test_jev_primary_calls_extraction_but_never_openai_code_selection(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "Arthroscopic rotator cuff repair was performed on the right shoulder."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[{"code": "29827", "description": "arthroscopic rotator cuff repair"}],
    )
    provider = FakeProvider(fail_on_select=True)
    jev = ScriptedJevProvider(code_by_fact={"rotator cuff": "29827"})

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert provider.extract_calls == 1
    assert provider.select_calls == 0
    assert jev.calls
    assert result.lines[0].code == "29827"
    assert result.lines[0].source == "jev_decision_engine"
    assert result.lines[0].confidence == 0.96
    candidate = session.query(CandidateCode).filter_by(code="29827").one()
    assert candidate.selected is True
    assert candidate.model_confidence == 0.96
    assert result.jev_output["mode"] == "primary"


def test_jev_primary_can_select_multiple_supported_codes_for_one_fact(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "Two separately reportable shoulder services were performed in the same encounter."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {"code": "29827", "description": "primary tendon repair service"},
            {"code": "29826", "description": "separate decompression service"},
        ],
    )
    provider = FakeProvider(
        facts=[
            {
                "fact_type": "procedure",
                "value": "combined separately reportable shoulder services",
                "normalized_value": "combined shoulder services",
                "assertion": "present",
                "confidence": 0.99,
            }
        ],
        search_queries=["primary tendon repair service", "separate decompression service"],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(
        code_by_fact={
            "primary tendon repair service": "29827",
            "separate decompression service": "29826",
        }
    )

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert {line.code for line in result.lines} == {"29827", "29826"}
    assert result.jev_output["summary"]["codes_selected"] == 2


def test_jev_primary_bridges_open_carpal_tunnel_to_cpt_descriptor(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "An open left carpal tunnel release was performed."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {
                "code": "64721",
                "description": "Neuroplasty and/or transposition; median nerve at carpal tunnel",
            },
            {
                "code": "29848",
                "description": (
                    "Endoscopy, wrist, surgical, with release of transverse carpal ligament"
                ),
            },
        ],
    )
    provider = FakeProvider(
        facts=[
            {
                "fact_type": "procedure",
                "value": "Open release of left carpal tunnel",
                "normalized_value": "open left carpal tunnel release",
                "assertion": "present",
                "confidence": 0.99,
            }
        ],
        search_queries=["open left carpal tunnel release"],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(code_by_fact={"carpal tunnel": "64721"})

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert [line.code for line in result.lines] == ["64721"]
    candidate = session.query(CandidateCode).filter_by(code="64721").one()
    assert "median nerve" in candidate.description.lower()
    question = next(
        question
        for batch in jev.question_batches
        for key, question in batch.items()
        if "_candidate_" in key and "CPT 64721" in question["instructions"]
    )
    assert "open carpal tunnel release" in question["instructions"]
    assert "`coding_facts.fact_" in question["instructions"]
    assert "`candidate_decisions.decision_" in question["instructions"]


def test_jev_primary_excludes_diagnostic_arthroscopy_included_in_surgical_scope(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = (
        "Diagnostic arthroscopy of the left knee was followed by arthroscopically aided "
        "left ACL reconstruction during the same operative session."
    )
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {
                "code": "29870",
                "description": "Arthroscopy, knee, diagnostic, with or without synovial biopsy",
            },
            {
                "code": "29888",
                "description": (
                    "Arthroscopically aided anterior cruciate ligament repair/augmentation "
                    "or reconstruction"
                ),
            },
        ],
    )
    provider = FakeProvider(
        facts=[
            {
                "fact_type": "procedure",
                "value": "diagnostic arthroscopy of left knee",
                "normalized_value": "diagnostic arthroscopy left knee",
                "assertion": "present",
                "confidence": 0.99,
            },
            {
                "fact_type": "procedure",
                "value": "arthroscopic left ACL reconstruction",
                "normalized_value": "arthroscopic ACL reconstruction left knee",
                "assertion": "present",
                "confidence": 0.99,
            },
        ],
        search_queries=["diagnostic knee arthroscopy", "arthroscopic ACL reconstruction"],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(
        code_by_fact={
            "diagnostic arthroscopy": "29870",
            "acl reconstruction": "29888",
        }
    )

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert [line.code for line in result.lines] == ["29888"]
    assert result.jev_output["deterministic_exclusions"] == [
        {
            "rule": "included_diagnostic_arthroscopy",
            "code_system": "CPT",
            "code": "29870",
            "included_in": "29888",
            "joint": "knee",
            "source": "CMS NCCI Policy Manual Chapter IV, Section E.1",
        }
    ]


def test_jev_primary_receives_icd_injury_and_initial_encounter_guidance(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "An acute complete left ACL rupture received operative treatment today."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {"code": "00000", "description": "Licensed CPT gate placeholder"},
            {
                "code_system": "ICD10CM",
                "code": "S83.512",
                "description": "Sprain of anterior cruciate ligament of left knee",
                "billable": False,
            },
            {
                "code_system": "ICD10CM",
                "code": "S83.512A",
                "description": (
                    "Sprain of anterior cruciate ligament of left knee, initial encounter"
                ),
            },
            {
                "code_system": "ICD10CM",
                "code": "S83.512D",
                "description": (
                    "Sprain of anterior cruciate ligament of left knee, subsequent encounter"
                ),
            },
        ],
    )
    provider = FakeProvider(
        facts=[
            {
                "fact_type": "diagnosis",
                "value": "Acute complete rupture of anterior cruciate ligament of left knee",
                "normalized_value": "acute complete left ACL rupture",
                "assertion": "present",
                "confidence": 0.99,
            }
        ],
        search_queries=["anterior cruciate ligament rupture left knee"],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(code_by_fact={"acute complete left acl rupture": "S83.512A"})

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert [line.code for line in result.lines] == ["S83.512A"]
    question = next(
        question
        for batch in jev.question_batches
        for key, question in batch.items()
        if "_candidate_" in key and "S83.512A" in question["instructions"]
    )
    assert "active treatment" in question["instructions"]
    assert "tear or rupture" in question["instructions"]
    assert session.query(CandidateCode).filter_by(code="S83.512").count() == 0


def test_jev_candidate_decisions_are_sent_in_bounded_batches(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    chart, _, _ = _seed_chart(
        session,
        settings,
        text="Synthetic batching fixture with enough embedded text for processing.",
        codes=[{"code": "29827", "description": "rotator cuff repair"}],
    )
    jev = ScriptedJevProvider()
    processor = ChartProcessor(session, settings, jev_provider=jev)
    questions = {
        f"candidate_{index}": {
            "type": "noul",
            "instructions": f"Is synthetic candidate {index} supported?",
            "criteria": {"true": "Supported", "false": "Unsupported"},
        }
        for index in range(81)
    }

    output = processor._run_jev_decision_batches(
        chart,
        "jev_code_selection",
        {"deidentified": True},
        questions,
        {"questions": len(questions)},
    )

    assert output["status"] == "complete"
    assert len(output["answers"]) == 81
    assert [len(batch) for batch in jev.question_batches] == [40, 40, 1]


def test_jev_candidate_batches_only_receive_referenced_fact_state(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    chart, _, _ = _seed_chart(
        session,
        settings,
        text="Synthetic scoped-state fixture with enough embedded text for processing.",
        codes=[{"code": "29827", "description": "rotator cuff repair"}],
    )
    jev = ScriptedJevProvider()
    processor = ChartProcessor(session, settings, jev_provider=jev)
    questions = {
        f"candidate_{index}": {
            "type": "noul",
            "instructions": f"Is synthetic candidate {index} supported?",
            "criteria": {"true": "Supported", "false": "Unsupported"},
        }
        for index in range(3)
    }
    state = {
        "deidentified": True,
        "coding_facts": {"fact_a": {"evidence": ["A"]}, "fact_b": {"evidence": ["B"]}},
        "candidate_decisions": {
            "decision_0": {"code": "0"},
            "decision_1": {"code": "1"},
            "decision_2": {"code": "2"},
        },
    }
    refs = {
        "candidate_0": {"fact": "fact_a", "candidate": "decision_0"},
        "candidate_1": {"fact": "fact_a", "candidate": "decision_1"},
        "candidate_2": {"fact": "fact_b", "candidate": "decision_2"},
    }

    output = processor._run_jev_decision_batches(
        chart,
        "jev_code_selection",
        state,
        questions,
        {"questions": len(questions)},
        batch_size=2,
        question_state_refs=refs,
    )

    assert output["status"] == "complete"
    assert list(jev.states[0]["coding_facts"]) == ["fact_a"]
    assert list(jev.states[0]["candidate_decisions"]) == ["decision_0", "decision_1"]
    assert list(jev.states[1]["coding_facts"]) == ["fact_b"]
    assert list(jev.states[1]["candidate_decisions"]) == ["decision_2"]


def test_jev_primary_retrieves_total_hip_and_diagnosis_from_independent_fact_pools(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "Left total hip arthroplasty was performed for primary osteoarthritis of the left hip."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {
                "code": "27130",
                "description": "Arthroplasty acetabular and proximal femoral prosthetic replacement total hip",
            },
            {"code": "27125", "description": "Hip hemiarthroplasty prosthetic replacement"},
            {"code": "27447", "description": "Total knee arthroplasty"},
            {"code": "27236", "description": "Open treatment femoral fracture proximal end"},
            {
                "code_system": "ICD10CM",
                "code": "M16.12",
                "description": "Unilateral primary osteoarthritis left hip",
            },
            {
                "code_system": "ICD10CM",
                "code": "M17.12",
                "description": "Unilateral primary osteoarthritis left knee",
            },
            {
                "code_system": "ICD10CM",
                "code": "M25.552",
                "description": "Pain in left hip",
            },
        ],
    )
    provider = FakeProvider(
        facts=[
            {
                "fact_type": "procedure",
                "value": "left total hip arthroplasty",
                "normalized_value": "total hip arthroplasty",
                "assertion": "present",
                "confidence": 0.99,
            },
            {
                "fact_type": "diagnosis",
                "value": "primary osteoarthritis of the left hip",
                "normalized_value": "primary osteoarthritis left hip",
                "assertion": "present",
                "confidence": 0.99,
            },
        ],
        search_queries=["total hip replacement", "primary osteoarthritis left hip"],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(
        code_by_fact={"total hip arthroplasty": "27130", "osteoarthritis": "M16.12"}
    )

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert provider.select_calls == 0
    assert {line.code for line in result.lines} == {"27130", "M16.12"}
    code_questions = [
        question["instructions"]
        for batch in jev.question_batches
        for key, question in batch.items()
        if "_candidate_" in key
    ]
    procedure_questions = [
        instructions
        for instructions in code_questions
        if "total hip arthroplasty" in instructions
    ]
    diagnosis_questions = [
        instructions for instructions in code_questions if "osteoarthritis" in instructions
    ]
    assert any("CPT 27130 (" in instructions for instructions in procedure_questions)
    assert all("ICD10CM" not in instructions for instructions in procedure_questions)
    assert any("ICD10CM M16.12 (" in instructions for instructions in diagnosis_questions)
    assert all("CPT " not in instructions for instructions in diagnosis_questions)


def test_jev_primary_uses_evidence_linked_diagnosis_to_retrieve_trigger_release_cpt(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = (
        "Open right middle finger A1 pulley release was performed for stenosing "
        "tenosynovitis, also called trigger finger."
    )
    distractors = [
        ("26210", "Excision of benign tumor of middle phalanx of finger"),
        ("26215", "Excision of benign tumor of middle phalanx of finger with autograft"),
        ("26235", "Partial excision of proximal or middle phalanx of finger"),
        ("26260", "Radical resection of tumor of middle phalanx of finger"),
        ("26720", "Closed treatment of middle phalanx finger fracture without manipulation"),
        ("26725", "Closed treatment of middle phalanx finger fracture with manipulation"),
        ("26727", "Percutaneous fixation of middle phalanx finger fracture"),
        ("26735", "Open treatment of middle phalanx finger fracture"),
        ("00120", "Anesthesia for procedures on external middle and inner ear"),
        ("00124", "Anesthesia for procedures on middle ear with otoscopy"),
        ("00126", "Anesthesia for procedures on middle ear with tympanotomy"),
        ("26455", "Tenotomy flexor finger open each tendon"),
        ("26460", "Tenotomy extensor hand or finger open each tendon"),
        ("15002", "Surgical preparation of open wounds trunk arms or legs"),
        ("15003", "Surgical preparation additional open wound surface area"),
        ("15004", "Surgical preparation of open wounds hands or feet"),
        ("15005", "Surgical preparation additional hand or foot wound area"),
        ("81404", "Molecular pathology procedure level 5"),
        ("81406", "Molecular pathology procedure level 7"),
        ("26160", "Excision of lesion of tendon sheath hand or finger"),
        ("26715", "Closed treatment of finger articular fracture"),
    ]
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {"code": code, "description": description} for code, description in distractors
        ]
        + [
            {"code": "26055", "description": "Tendon sheath incision for trigger finger"},
            {
                "code_system": "ICD10CM",
                "code": "M65.331",
                "description": "Trigger finger right middle finger",
            },
        ],
    )
    provider = FakeProvider(
        facts=[
            {
                "fact_type": "procedure",
                "value": "Open right middle finger A1 pulley release",
                "normalized_value": "A1 pulley release of middle finger",
                "assertion": "present",
                "confidence": 1.0,
            },
            {
                "fact_type": "diagnosis",
                "value": "Stenosing tenosynovitis trigger finger right middle finger",
                "normalized_value": "Trigger finger of right middle finger",
                "assertion": "present",
                "confidence": 1.0,
            },
        ],
        search_queries=["A1 pulley release right middle finger"],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(
        code_by_fact={"a1 pulley release": "26055", "trigger finger": "M65.331"}
    )

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert provider.select_calls == 0
    assert "26055" in {line.code for line in result.lines}
    procedure_question = next(
        question
        for batch in jev.question_batches
        for key, question in batch.items()
        if "procedure_candidate_" in key and "CPT 26055 (" in question["instructions"]
    )
    assert "A1 pulley release" in procedure_question["instructions"]
    procedure_decision = next(
        item
        for item in result.jev_output["code_selections"]
        if item["fact_type"] == "procedure" and item["selected"]
    )
    assert procedure_decision["code"] == "26055"
    assert procedure_decision["abstained"] is False


def test_jev_primary_code_choices_use_only_the_generating_facts_candidate_pool(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = (
        "Arthroscopic rotator cuff repair and acromioplasty were performed. "
        "The active diagnoses were right rotator cuff tear and shoulder impingement."
    )
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {"code": "29827", "description": "Rotator cuff repair"},
            {"code": "29826", "description": "Acromioplasty decompression"},
            {"code": "29824", "description": "Distal claviculectomy"},
            {"code": "23412", "description": "Open chronic rotator cuff repair"},
            {
                "code_system": "ICD10CM",
                "code": "M75.121",
                "description": "Complete right rotator cuff tear",
            },
            {
                "code_system": "ICD10CM",
                "code": "M75.41",
                "description": "Impingement syndrome right shoulder",
            },
            {
                "code_system": "ICD10CM",
                "code": "M19.011",
                "description": "Primary osteoarthritis right shoulder",
            },
        ],
    )
    provider = FakeProvider(
        facts=[
            {"fact_type": "procedure", "value": "arthroscopic rotator cuff repair", "normalized_value": "rotator cuff repair", "assertion": "present", "confidence": 0.99},
            {"fact_type": "procedure", "value": "arthroscopic acromioplasty", "normalized_value": "acromioplasty", "assertion": "present", "confidence": 0.99},
            {"fact_type": "diagnosis", "value": "right rotator cuff tear", "normalized_value": "right rotator cuff tear", "assertion": "present", "confidence": 0.99},
            {"fact_type": "diagnosis", "value": "right shoulder impingement", "normalized_value": "right shoulder impingement", "assertion": "present", "confidence": 0.99},
        ],
        search_queries=[
            "rotator cuff repair",
            "acromioplasty decompression",
            "right rotator cuff tear",
            "right shoulder impingement",
        ],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(
        code_by_fact={
            "procedure fact 'rotator cuff repair'": "29827",
            "procedure fact 'acromioplasty'": "29826",
            "diagnosis fact 'right rotator cuff tear'": "M75.121",
            "diagnosis fact 'right shoulder impingement'": "M75.41",
        }
    )

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert {line.code for line in result.lines} == {"29827", "29826", "M75.121", "M75.41"}
    code_questions = [
        question
        for batch in jev.question_batches
        for key, question in batch.items()
        if "_candidate_" in key
    ]
    expected = {
        "rotator cuff repair": "29827",
        "acromioplasty": "29826",
        "right rotator cuff tear": "M75.121",
        "right shoulder impingement": "M75.41",
    }
    for phrase, code in expected.items():
        fact_questions = [
            item for item in code_questions if phrase in item["instructions"]
        ]
        assert fact_questions
        assert any(f" {code} (" in item["instructions"] for item in fact_questions)
        if code.startswith("M"):
            assert all("ICD10CM " in item["instructions"] for item in fact_questions)
        else:
            assert all(
                "CPT " in item["instructions"] or "HCPCS " in item["instructions"]
                for item in fact_questions
            )


def test_jev_primary_records_zero_candidate_fact_without_empty_choice(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "A rare unsupported reconstruction was performed."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[{"code": "00000", "description": "Licensed coding gate placeholder"}],
    )
    provider = FakeProvider(
        facts=[
            {"fact_type": "procedure", "value": "rare unsupported reconstruction", "normalized_value": "rare unsupported reconstruction", "assertion": "present", "confidence": 0.99}
        ],
        search_queries=["rare unsupported reconstruction"],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider()

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    warning = next(item for item in result.warnings if item["code"] == "NO_CANDIDATES_FOR_FACT")
    assert warning["fact_id"]
    assert warning["fact"] == "rare unsupported reconstruction"
    assert warning["fact_type"] == "procedure"
    assert warning["searched_terms"] == ["rare unsupported reconstruction"]
    assert result.lines == []
    assert result.confidence_state == "RED"
    assert all("_candidate_" not in key for batch in jev.question_batches for key in batch)


def test_ambiguous_candidate_decisions_require_review_without_selecting_code(
    session, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "Arthroscopic rotator cuff repair was documented, but coding support is ambiguous."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {"code": "29827", "description": "Arthroscopic rotator cuff repair"},
            {"code": "23412", "description": "Open chronic rotator cuff repair"},
        ],
    )
    provider = FakeProvider(fail_on_select=True)
    jev = ScriptedJevProvider(abstain_for={"rotator cuff repair"})

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    summary = result.jev_output["summary"]
    assert summary["abstained"] == 0
    assert summary["codes_selected"] == 0
    assert summary["accepted"] == 1  # Fact validation only.
    assert summary["review"] == 2
    assert result.lines == []
    assert any(item["code"] == "JEV_REVIEW_REQUIRED" for item in result.warnings)


def test_jev_primary_planned_not_performed_procedure_is_not_coded(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = (
        "Carpal tunnel release was considered preoperatively. "
        "Carpal tunnel release was not performed."
    )
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[{"code": "64721", "description": "open carpal tunnel release"}],
    )
    provider = FakeProvider(
        facts=[
            {
                "fact_type": "procedure",
                "value": "carpal tunnel release",
                "normalized_value": "carpal tunnel release",
                "assertion": "uncertain",
                "confidence": 0.99,
            }
        ],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(
        fact_classes={"carpal tunnel release": "planned_only"},
        code_by_fact={"carpal tunnel": "64721"},
    )

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert provider.select_calls == 0
    assert result.lines == []
    assert result.confidence_state == "RED"
    assert result.jev_output["facts"][0]["classification"] == "planned_only"


def test_jev_primary_left_laterality_is_evidence_backed_without_rt(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "Left knee arthroscopy with meniscectomy was performed during this operative session."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[{"code": "29881", "description": "knee arthroscopy with meniscectomy"}],
        modifiers=["LT", "RT"],
    )
    provider = FakeProvider(
        facts=[
            {"fact_type": "procedure", "value": "knee arthroscopy with meniscectomy", "normalized_value": "knee arthroscopy with meniscectomy", "assertion": "present", "confidence": 0.98},
            {"fact_type": "laterality", "value": "left", "normalized_value": "left", "assertion": "present", "confidence": 0.99},
        ],
        selected_codes=["29881"],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(code_by_fact={"meniscectomy": "29881"})

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert result.lines[0].modifiers == ["LT"]
    assert "RT" not in result.lines[0].modifiers
    lt_decision = next(
        item for item in result.jev_output["modifier_decisions"] if item["modifier"] == "LT"
    )
    assert lt_decision["applied"] is True
    assert result.lines[0].evidence_span_ids


def test_jev_primary_bilateral_context_uses_active_modifier_50(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = (
        "Open carpal tunnel release was performed on the right wrist and left wrist "
        "during the same operative session."
    )
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[{"code": "64721", "description": "open carpal tunnel release"}],
        modifiers=["50", "LT", "RT"],
    )
    provider = FakeProvider(
        facts=[
            {"fact_type": "procedure", "value": "bilateral open carpal tunnel release", "normalized_value": "open carpal tunnel release", "assertion": "present", "confidence": 0.98},
            {"fact_type": "laterality", "value": "right", "normalized_value": "right", "assertion": "present", "confidence": 0.99},
            {"fact_type": "laterality", "value": "left", "normalized_value": "left", "assertion": "present", "confidence": 0.99},
        ],
        selected_codes=["64721"],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(code_by_fact={"carpal tunnel": "64721"})

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert result.lines[0].modifiers == ["50"]


def test_jev_primary_failure_preserves_facts_and_candidates_without_fallback(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "Arthroscopic rotator cuff repair was performed on the right shoulder."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[{"code": "29827", "description": "arthroscopic rotator cuff repair"}],
    )
    provider = FakeProvider(fail_on_select=True)
    jev = ScriptedJevProvider(unavailable=True)

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert provider.select_calls == 0
    assert session.query(CandidateCode).count() == 1
    assert result.lines == []
    assert result.status == "needs_review"
    assert result.confidence_state == "RED"
    assert result.autonomous_eligible is False
    assert result.jev_output["error_code"] == "JEV_UNAVAILABLE"
    assert any(item["code"] == "JEV_UNAVAILABLE" for item in result.warnings)


def test_jev_shadow_keeps_legacy_lines_and_persists_comparison(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_shadow")
    text = "Arthroscopic rotator cuff repair was performed on the right shoulder."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[{"code": "29827", "description": "arthroscopic rotator cuff repair"}],
    )
    provider = FakeProvider()
    jev = ScriptedJevProvider(code_by_fact={"rotator cuff": "29827"})

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert provider.select_calls == 1
    assert result.lines[0].source == "reasoning_model"
    assert result.jev_output["mode"] == "shadow"
    assert result.jev_output["shadow"]["code_selections"]
    assert result.jev_output["comparison"]["exact_code_set_agreement"] is True


def test_jev_primary_addon_selection_still_requires_deterministic_primary(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "Primary lumbar procedure and documented add-on decompression were both performed."
    chart, release, source = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {"code": "63047", "description": "primary lumbar decompression"},
            {"code": "63048", "description": "add-on lumbar decompression segment"},
        ],
    )
    session.add(
        AddonCodeRelation(
            id=new_id(),
            codebook_release_id=release.id,
            addon_code="63048",
            addon_code_key="63048",
            primary_code="63047",
            primary_code_key="63047",
            relationship_type="explicit_primary",
            effective_from=date(2026, 1, 1),
            source_file_id=source.id,
            metadata_json={},
        )
    )
    session.commit()
    provider = FakeProvider(
        facts=[
            {"fact_type": "procedure", "value": "primary lumbar decompression", "normalized_value": "primary lumbar decompression", "assertion": "present", "confidence": 0.98},
            {"fact_type": "procedure", "value": "add-on lumbar decompression segment", "normalized_value": "add-on lumbar decompression segment", "assertion": "present", "confidence": 0.98},
        ],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(
        code_by_fact={"primary lumbar": "63047", "add-on lumbar": "63048"}
    )

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert {line.code for line in result.lines} == {"63047", "63048"}
    addon = session.query(RuleDecision).filter_by(rule_type="addon_primary").one()
    assert addon.outcome == "pass"


def test_addon_without_required_primary_fails_regardless_of_jev_confidence(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "Only the add-on lumbar decompression segment was documented as performed today."
    chart, release, source = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {"code": "63047", "description": "primary lumbar decompression"},
            {"code": "63048", "description": "add-on lumbar decompression segment"},
        ],
    )
    session.add(
        AddonCodeRelation(
            id=new_id(),
            codebook_release_id=release.id,
            addon_code="63048",
            addon_code_key="63048",
            primary_code="63047",
            primary_code_key="63047",
            relationship_type="explicit_primary",
            effective_from=date(2026, 1, 1),
            source_file_id=source.id,
            metadata_json={},
        )
    )
    session.commit()
    provider = FakeProvider(
        facts=[
            {"fact_type": "procedure", "value": "add-on lumbar decompression segment", "normalized_value": "add-on lumbar decompression segment", "assertion": "present", "confidence": 0.99}
        ],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(code_by_fact={"add-on lumbar": "63048"})

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    addon = session.query(RuleDecision).filter_by(rule_type="addon_primary").one()
    assert addon.outcome == "fail"
    assert result.confidence_state == "RED"


def test_hcpcs_units_are_calculated_in_python_from_administered_quantity(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "Triamcinolone 40 mg was administered into the knee joint during this encounter."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {"code": "00000", "description": "licensed CPT gate placeholder"},
            {
                "code_system": "HCPCS",
                "code": "J3301",
                "description": "triamcinolone acetonide per 10 mg",
                "metadata": {"billing_unit_mg": 10},
            },
        ],
    )
    provider = FakeProvider(
        facts=[
            {"fact_type": "medication", "value": "triamcinolone administered", "normalized_value": "triamcinolone", "assertion": "present", "confidence": 0.99},
            {"fact_type": "quantity", "value": "40 mg administered", "normalized_value": "40 mg", "assertion": "present", "confidence": 0.99},
        ],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(code_by_fact={"triamcinolone": "J3301"})

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    assert result.lines[0].code == "J3301"
    assert result.lines[0].units == 4


def test_diagnosis_pointers_come_from_jev_relationship_decisions(session, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    text = "Right rotator cuff tear was treated with arthroscopic rotator cuff repair."
    chart, _, _ = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {"code": "29827", "description": "arthroscopic rotator cuff repair"},
            {"code_system": "ICD10CM", "code": "M75.121", "description": "complete right rotator cuff tear"},
        ],
    )
    provider = FakeProvider(
        facts=[
            {"fact_type": "procedure", "value": "arthroscopic rotator cuff repair", "normalized_value": "rotator cuff repair", "assertion": "present", "confidence": 0.99},
            {"fact_type": "diagnosis", "value": "complete right rotator cuff tear", "normalized_value": "right rotator cuff tear", "assertion": "present", "confidence": 0.99},
        ],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(
        code_by_fact={"repair": "29827", "tear": "M75.121"}
    )

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    procedure = next(line for line in result.lines if line.code == "29827")
    assert procedure.diagnosis_pointers == ["M75.121"]
    assert result.jev_output["diagnosis_links"][0]["linked"] is True
    link_batch_index = next(
        index
        for index, batch in enumerate(jev.question_batches)
        if any(key.startswith("diagnosis_link_") for key in batch)
    )
    link_question = next(iter(jev.question_batches[link_batch_index].values()))
    assert "complete right rotator cuff tear" in link_question["instructions"]
    assert "arthroscopic rotator cuff repair" in link_question["instructions"]
    assert "`diagnosis_link_decisions.link_0_0`" in link_question["instructions"]
    assert list(jev.states[link_batch_index]["diagnosis_link_decisions"]) == ["link_0_0"]


@pytest.mark.parametrize(
    ("text", "expected_outcome", "expected_modifier"),
    [
        (
            "Rotator cuff repair and decompression were performed through the same operative field.",
            "fail",
            False,
        ),
        (
            "Rotator cuff repair and decompression were performed through a documented separate incision.",
            "pass",
            True,
        ),
    ],
)
def test_ncci_modifier_indicator_one_uses_jev_for_documentation_only(
    session,
    tmp_path: Path,
    text: str,
    expected_outcome: str,
    expected_modifier: bool,
) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path, "jev_primary")
    chart, release, source = _seed_chart(
        session,
        settings,
        text=text,
        codes=[
            {"code": "29827", "description": "arthroscopic rotator cuff repair"},
            {"code": "29826", "description": "arthroscopic decompression"},
        ],
        modifiers=["59"],
    )
    session.add(
        NcciPtpEdit(
            id=new_id(),
            codebook_release_id=release.id,
            setting="practitioner",
            revision_key=new_id(),
            column_1_code="29827",
            column_1_code_key="29827",
            column_2_code="29826",
            column_2_code_key="29826",
            effective_from=date(2026, 1, 1),
            modifier_indicator="1",
            source_file_id=source.id,
            source_record={},
        )
    )
    session.commit()
    provider = FakeProvider(
        facts=[
            {"fact_type": "procedure", "value": "arthroscopic rotator cuff repair", "normalized_value": "rotator cuff repair", "assertion": "present", "confidence": 0.99},
            {"fact_type": "procedure", "value": "arthroscopic decompression", "normalized_value": "arthroscopic decompression", "assertion": "present", "confidence": 0.99},
        ],
        fail_on_select=True,
    )
    jev = ScriptedJevProvider(
        code_by_fact={"rotator cuff": "29827", "decompression": "29826"}
    )

    report = ChartProcessor(
        session,
        settings,
        provider=provider,
        jev_provider=jev,
        document_extractor=FakeDocumentExtractor(text),
    ).process(chart.id)

    result = session.get(CodingResult, report["result_id"])
    assert result is not None
    ncci = session.query(RuleDecision).filter_by(rule_type="ncci_ptp").one()
    assert ncci.outcome == expected_outcome
    assert any("59" in line.modifiers for line in result.lines) is expected_modifier
