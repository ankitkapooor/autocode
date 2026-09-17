from __future__ import annotations

from datetime import date

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.models.reference import AddonCodeRelation, MueEdit, NcciPtpEdit, PfsProcedureAttribute
from app.reference_data.ncci_index import IndexedNcciEdit, get_configured_ncci_source_index
from app.reference_data.utils import canonical_code
from app.repositories.codebook import CodebookRepository


class CodingRulesRepository:
    """Runtime access to normalized deterministic-rule tables only."""

    def __init__(self, session: Session):
        self.session = session
        self.codebooks = CodebookRepository(session)

    def get_ncci_edit(
        self, column_1_code: str, column_2_code: str, service_date: date, *, setting: str = "practitioner"
    ) -> NcciPtpEdit | IndexedNcciEdit | None:
        release = self.codebooks.active_release(service_date)
        materialized = self.session.scalar(
            select(NcciPtpEdit)
            .where(
                NcciPtpEdit.codebook_release_id == release.id,
                NcciPtpEdit.setting == setting,
                NcciPtpEdit.column_1_code_key == canonical_code(column_1_code),
                NcciPtpEdit.column_2_code_key == canonical_code(column_2_code),
                or_(NcciPtpEdit.effective_from.is_(None), NcciPtpEdit.effective_from <= service_date),
                or_(NcciPtpEdit.effective_to.is_(None), NcciPtpEdit.effective_to >= service_date),
            )
            .order_by(
                NcciPtpEdit.effective_from.desc(),
                case((NcciPtpEdit.modifier_indicator == "9", 1), else_=0),
                NcciPtpEdit.effective_to.desc().nulls_first(),
            )
            .limit(1)
        )
        if materialized is not None:
            return materialized
        source_index = self._compatible_ncci_index(release.source_manifest_sha256)
        if source_index is None:
            return None
        return source_index.lookup(setting, column_1_code, column_2_code, service_date)

    def ncci_runtime_count(self, service_date: date) -> int:
        release = self.codebooks.active_release(service_date)
        materialized = self.session.scalar(
            select(func.count())
            .select_from(NcciPtpEdit)
            .where(NcciPtpEdit.codebook_release_id == release.id)
        ) or 0
        if materialized:
            return int(materialized)
        source_index = self._compatible_ncci_index(release.source_manifest_sha256)
        return source_index.record_count if source_index is not None else 0

    @staticmethod
    def _compatible_ncci_index(source_manifest_sha256: str):  # type: ignore[no-untyped-def]
        source_index = get_configured_ncci_source_index()
        if source_index is None or not source_index.is_compatible(source_manifest_sha256):
            return None
        return source_index

    def get_mue(self, code: str, service_date: date, *, setting: str = "practitioner") -> MueEdit | None:
        release = self.codebooks.active_release(service_date)
        return self.session.scalar(
            select(MueEdit).where(
                MueEdit.codebook_release_id == release.id,
                MueEdit.setting == setting,
                MueEdit.code_key == canonical_code(code),
                or_(MueEdit.effective_from.is_(None), MueEdit.effective_from <= service_date),
                or_(MueEdit.effective_to.is_(None), MueEdit.effective_to >= service_date),
            )
        )

    def get_addon_relationships(self, code: str, service_date: date) -> list[AddonCodeRelation]:
        release = self.codebooks.active_release(service_date)
        return list(
            self.session.scalars(
                select(AddonCodeRelation).where(
                    AddonCodeRelation.codebook_release_id == release.id,
                    AddonCodeRelation.addon_code_key == canonical_code(code),
                    or_(AddonCodeRelation.effective_from.is_(None), AddonCodeRelation.effective_from <= service_date),
                    or_(AddonCodeRelation.effective_to.is_(None), AddonCodeRelation.effective_to >= service_date),
                )
            )
        )

    def get_pfs_attributes(self, code: str, service_date: date, modifier: str = "") -> PfsProcedureAttribute | None:
        release = self.codebooks.active_release(service_date)
        return self.session.scalar(
            select(PfsProcedureAttribute).where(
                PfsProcedureAttribute.codebook_release_id == release.id,
                PfsProcedureAttribute.code_key == canonical_code(code),
                PfsProcedureAttribute.modifier == modifier.upper(),
                or_(PfsProcedureAttribute.effective_from.is_(None), PfsProcedureAttribute.effective_from <= service_date),
                or_(PfsProcedureAttribute.effective_to.is_(None), PfsProcedureAttribute.effective_to >= service_date),
            )
        )
