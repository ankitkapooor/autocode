from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.reference import (
    CodeEntry,
    CodeSearchDocument,
    CodebookRelease,
    MueEdit,
    NcciPtpEdit,
    RawReferenceFile,
    ReferenceImportRun,
)
from app.reference_data.pipeline import publish_release
from app.repositories import CodebookRepository, CodingRulesRepository


def seed_release(session: Session, name: str, status: str, effective: date) -> CodebookRelease:
    run = ReferenceImportRun(
        id=f"run-{name}", status="validated", dry_run=False, source_root="/controlled/input",
        release_name=name, parser_version="test", source_manifest_sha256=f"sha-{name}", summary={}
    )
    session.add(run)
    session.flush()
    source = RawReferenceFile(
        id=f"file-{name}", import_run_id=run.id, original_filename="fixture.xml",
        relative_path="icd10cm/fixture.xml", source_family="icd10cm", release_name=name,
        release_effective_from=effective, file_size=1, sha256=f"file-sha-{name}", parser_version="test",
        metadata_json={}
    )
    session.add(source)
    session.flush()
    release = CodebookRelease(
        id=f"release-{name}", import_run_id=run.id, name=name, status=status,
        effective_from=effective, source_manifest_sha256=f"sha-{name}", parser_version="test",
        validation_summary={"blocking_errors": 0}
    )
    session.add(release)
    session.flush()
    return release


def test_atomic_publish_supersedes_previous_release(session: Session) -> None:
    first = seed_release(session, "2026-Q2", "published", date(2026, 4, 1))
    second = seed_release(session, "2026-Q3", "validated", date(2026, 7, 1))
    session.commit()
    publish_release(session, second.id)
    session.refresh(first)
    session.refresh(second)
    assert first.status == "superseded"
    assert second.status == "published"


def test_runtime_repositories_are_release_and_date_aware(session: Session) -> None:
    release = seed_release(session, "2026-Q3", "published", date(2026, 7, 1))
    source_id = "file-2026-Q3"
    code = CodeEntry(
        id="code-1", codebook_release_id=release.id, code_system="ICD10CM", code="M75.102",
        code_key="M75102", short_description="Left shoulder tear", long_description="Left shoulder tear",
        effective_from=date(2026, 8, 1), billable=True, category="M75", metadata_json={},
        source_version="2026", source_file_id=source_id
    )
    session.add(code)
    session.add(CodeSearchDocument(
        id="search-1", codebook_release_id=release.id, code_entry_id=code.id, code=code.code,
        description=code.long_description, synonyms=[], search_text="m75.102 left shoulder tear"
    ))
    session.add(NcciPtpEdit(
        id="ncci-1", codebook_release_id=release.id, setting="practitioner",
        column_1_code="29827", column_1_code_key="29827", column_2_code="29826",
        column_2_code_key="29826", effective_from=date(2026, 7, 1), modifier_indicator="1",
        source_file_id=source_id, source_record={}
    ))
    session.add(MueEdit(
        id="mue-1", codebook_release_id=release.id, setting="practitioner", code="29827",
        code_key="29827", mue_value=1, effective_from=date(2026, 7, 1), source_file_id=source_id,
        metadata_json={}
    ))
    session.commit()

    codebooks = CodebookRepository(session)
    rules = CodingRulesRepository(session)
    assert codebooks.get_code("ICD10CM", "M75.102", date(2026, 9, 1)) is not None
    assert codebooks.get_code("ICD10CM", "M75.102", date(2026, 7, 15)) is None
    assert rules.get_ncci_edit("29827", "29826", date(2026, 9, 1)) is not None
    assert rules.get_ncci_edit("29826", "29827", date(2026, 9, 1)) is None
    assert rules.get_mue("29827", date(2026, 9, 1), setting="practitioner") is not None
    assert rules.get_mue("29827", date(2026, 9, 1), setting="outpatient_hospital") is None


def test_code_search_uses_significant_token_overlap_for_non_exact_clinical_phrase(
    session: Session,
) -> None:
    release = seed_release(session, "2026-Q4", "published", date(2026, 7, 1))
    source_id = "file-2026-Q4"
    descriptions = {
        "29881": (
            "Arthroscopy knee surgical with meniscectomy medial OR lateral including "
            "any meniscal shaving"
        ),
        "29880": "Arthroscopy knee surgical with meniscectomy medial AND lateral",
        "29877": "Arthroscopy knee surgical debridement shaving articular cartilage",
        "29827": "Arthroscopy shoulder surgical rotator cuff repair",
        "27447": "Total knee arthroplasty",
    }
    for index, (code_value, description) in enumerate(descriptions.items(), start=1):
        entry = CodeEntry(
            id=f"lexical-code-{index}",
            codebook_release_id=release.id,
            code_system="CPT",
            code=code_value,
            code_key=code_value,
            short_description=description,
            long_description=description,
            effective_from=date(2026, 7, 1),
            billable=True,
            category="Category I",
            metadata_json={"licensed_boundary": True},
            source_version="2026",
            source_file_id=source_id,
        )
        session.add(entry)
        session.flush()
        session.add(
            CodeSearchDocument(
                id=f"lexical-search-{index}",
                codebook_release_id=release.id,
                code_entry_id=entry.id,
                code=entry.code,
                description=description,
                synonyms=[],
                search_text=f"{entry.code} {description}".lower(),
            )
        )
    session.commit()

    repository = CodebookRepository(session)
    matches = repository.search_codes(
        "arthroscopic partial medial meniscectomy",
        system="CPT",
        service_date=date(2026, 9, 1),
        limit=5,
    )

    assert "29881" in [entry.code for entry in matches]
    assert [entry.code for entry in matches[:2]] == ["29880", "29881"]
    assert repository.search_codes(
        "29881", system="CPT", service_date=date(2026, 9, 1), limit=1
    )[0].code == "29881"


def test_code_search_can_exclude_nonbillable_parent_categories(session: Session) -> None:
    release = seed_release(session, "2026-billable", "published", date(2026, 7, 1))
    source_id = "file-2026-billable"
    for index, (code, description, billable) in enumerate(
        [
            ("S83.512", "Sprain of anterior cruciate ligament of left knee", False),
            (
                "S83.512A",
                "Sprain of anterior cruciate ligament of left knee initial encounter",
                True,
            ),
        ],
        start=1,
    ):
        entry = CodeEntry(
            id=f"billable-code-{index}",
            codebook_release_id=release.id,
            code_system="ICD10CM",
            code=code,
            code_key=code.replace(".", ""),
            short_description=description,
            long_description=description,
            effective_from=date(2026, 7, 1),
            billable=billable,
            category="S83",
            metadata_json={},
            source_version="2026",
            source_file_id=source_id,
        )
        session.add(entry)
        session.flush()
        session.add(
            CodeSearchDocument(
                id=f"billable-search-{index}",
                codebook_release_id=release.id,
                code_entry_id=entry.id,
                code=entry.code,
                description=description,
                synonyms=[],
                search_text=f"{code} {description}".lower(),
            )
        )
    session.commit()

    matches = CodebookRepository(session).search_codes(
        "left anterior cruciate ligament sprain",
        system="ICD10CM",
        service_date=date(2026, 9, 1),
        limit=10,
        billable_only=True,
    )

    assert [entry.code for entry in matches] == ["S83.512A"]
