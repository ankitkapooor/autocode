from __future__ import annotations

import re
from datetime import date

from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.orm import Session

from app.models.reference import CodeEntry, CodeSearchDocument, CodebookRelease, ModifierEntry
from app.reference_data.utils import canonical_code


_SEARCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "during",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "with",
}

_TOKEN_ALIASES = {
    "arthroscopic": "arthroscopy",
    "osteoarthritic": "osteoarthritis",
}


def _search_tokens(value: str) -> list[str]:
    return list(
        dict.fromkeys(
            _TOKEN_ALIASES.get(token, token)
            for token in re.findall(r"[a-z0-9]+", value.lower())
            if len(token) > 1 and token not in _SEARCH_STOPWORDS
        )
    )


def _normalized_phrase(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


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
        text_query = " ".join(query.strip().lower().split())
        tokens = _search_tokens(text_query)
        if not text_query or (not normalized and not tokens):
            return []
        search_text = func.lower(CodeSearchDocument.search_text)
        text_conditions = [search_text.like(f"%{token}%") for token in tokens]
        phrase_condition = search_text.like(f"%{text_query}%")
        match_conditions = [
            CodeEntry.code_key.like(f"{normalized}%"),
            phrase_condition,
        ]
        match_conditions.extend(text_conditions)
        token_score = sum(
            (case((condition, 1), else_=0) for condition in text_conditions),
            literal(0),
        )
        capped_limit = min(max(limit, 1), 100)
        pool_limit = min(1000, max(200, capped_limit * 50))
        statement = (
            select(CodeEntry, CodeSearchDocument.search_text)
            .join(CodeSearchDocument, CodeSearchDocument.code_entry_id == CodeEntry.id)
            .where(
                CodeEntry.codebook_release_id == release.id,
                or_(*match_conditions),
                or_(CodeEntry.effective_from.is_(None), CodeEntry.effective_from <= service_date),
                or_(CodeEntry.effective_to.is_(None), CodeEntry.effective_to >= service_date),
            )
            .order_by(
                case(
                    (CodeEntry.code_key == normalized, 0),
                    (phrase_condition, 1),
                    else_=2,
                ),
                token_score.desc(),
                CodeEntry.code,
            )
            .limit(pool_limit)
        )
        if system:
            statement = statement.where(CodeEntry.code_system == system.upper())
        rows = self.session.execute(statement).all()
        query_tokens = set(tokens)
        normalized_query_phrase = _normalized_phrase(text_query)

        def rank(row: tuple[CodeEntry, str]) -> tuple[int, int, float, str]:
            entry, document = row
            document_phrase = _normalized_phrase(document or "")
            document_tokens = set(_search_tokens(document or ""))
            overlap = len(query_tokens & document_tokens)
            overlap_ratio = overlap / len(query_tokens) if query_tokens else 0.0
            if entry.code_key == normalized:
                tier = 0
            elif normalized_query_phrase and normalized_query_phrase in document_phrase:
                tier = 1
            elif overlap_ratio >= 0.6:
                tier = 2
            else:
                tier = 3
            return (tier, -overlap, -overlap_ratio, entry.code)

        ranked = sorted(rows, key=rank)
        return [entry for entry, _ in ranked[:capped_limit]]
