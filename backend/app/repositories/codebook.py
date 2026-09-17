from __future__ import annotations

from datetime import date

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from app.models.reference import CodeEntry, CodeSearchDocument, CodebookRelease, ModifierEntry
from app.reference_data.utils import canonical_code


class NoPublishedReleaseError(RuntimeError):
    pass


class CodebookRepository:
    """Runtime access to normalized, published codebook tables only."""

    def __init__(self, session: Session):
        self.session = session

    def active_release(self, service_date: date | None = None) -> CodebookRelease:
        service_date = service_date or date.today()
        release = self.session.scalar(
            select(CodebookRelease)
            .where(
                CodebookRelease.status == "published",
                CodebookRelease.effective_from <= service_date,
                or_(CodebookRelease.effective_to.is_(None), CodebookRelease.effective_to >= service_date),
            )
            .order_by(CodebookRelease.effective_from.desc())
            .limit(1)
        )
        if release is None:
            raise NoPublishedReleaseError(
                f"No published normalized release is active for {service_date.isoformat()}"
            )
        return release

    def get_code(self, system: str, code: str, service_date: date | None = None) -> CodeEntry | None:
        service_date = service_date or date.today()
        release = self.active_release(service_date)
        return self.session.scalar(
            select(CodeEntry).where(
                CodeEntry.codebook_release_id == release.id,
                CodeEntry.code_system == system.upper(),
                CodeEntry.code_key == canonical_code(code),
                or_(CodeEntry.effective_from.is_(None), CodeEntry.effective_from <= service_date),
                or_(CodeEntry.effective_to.is_(None), CodeEntry.effective_to >= service_date),
            )
        )

    def code_active_on(self, system: str, code: str, service_date: date) -> bool:
        return self.get_code(system, code, service_date) is not None

    def get_modifier(self, modifier: str, service_date: date | None = None) -> ModifierEntry | None:
        service_date = service_date or date.today()
        release = self.active_release(service_date)
        return self.session.scalar(
            select(ModifierEntry).where(
                ModifierEntry.codebook_release_id == release.id,
                ModifierEntry.modifier_key == canonical_code(modifier),
                or_(ModifierEntry.effective_from.is_(None), ModifierEntry.effective_from <= service_date),
                or_(ModifierEntry.effective_to.is_(None), ModifierEntry.effective_to >= service_date),
            )
        )

    def search_modifiers(
        self,
        query: str,
        *,
        service_date: date | None = None,
        limit: int = 20,
    ) -> list[ModifierEntry]:
        service_date = service_date or date.today()
        release = self.active_release(service_date)
        normalized = canonical_code(query)
        text_query = query.strip().lower()
        return list(
            self.session.scalars(
                select(ModifierEntry)
                .where(
                    ModifierEntry.codebook_release_id == release.id,
                    or_(
                        ModifierEntry.modifier_key.like(f"{normalized}%"),
                        func.lower(ModifierEntry.description).like(f"%{text_query}%"),
                    ),
                    or_(ModifierEntry.effective_from.is_(None), ModifierEntry.effective_from <= service_date),
                    or_(ModifierEntry.effective_to.is_(None), ModifierEntry.effective_to >= service_date),
                )
                .order_by(
                    case(
                        (ModifierEntry.modifier_key == normalized, 0),
                        (ModifierEntry.modifier_key.like(f"{normalized}%"), 1),
                        else_=2,
                    ),
                    ModifierEntry.modifier,
                )
                .limit(min(max(limit, 1), 100))
            )
        )

    def search_codes(
        self,
        query: str,
        *,
        system: str | None = None,
        service_date: date | None = None,
        limit: int = 20,
    ) -> list[CodeEntry]:
        service_date = service_date or date.today()
        release = self.active_release(service_date)
        normalized = canonical_code(query)
        text_query = query.strip().lower()
        statement = (
            select(CodeEntry)
            .join(CodeSearchDocument, CodeSearchDocument.code_entry_id == CodeEntry.id)
            .where(
                CodeEntry.codebook_release_id == release.id,
                or_(
                    CodeEntry.code_key.like(f"{normalized}%"),
                    func.lower(CodeSearchDocument.search_text).like(f"%{text_query}%"),
                ),
                or_(CodeEntry.effective_from.is_(None), CodeEntry.effective_from <= service_date),
                or_(CodeEntry.effective_to.is_(None), CodeEntry.effective_to >= service_date),
            )
            .order_by(
                case((CodeEntry.code_key == normalized, 0), (CodeEntry.code_key.like(f"{normalized}%"), 1), else_=2),
                CodeEntry.code,
            )
            .limit(min(max(limit, 1), 100))
        )
        if system:
            statement = statement.where(CodeEntry.code_system == system.upper())
        return list(self.session.scalars(statement))
