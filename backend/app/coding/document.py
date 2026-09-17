from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class DocumentExtractionError(RuntimeError):
    pass


@dataclass(slots=True)
class ExtractedPage:
    page_number: int
    text: str
    text_sha256: str
    extraction_method: str
    width: float | None
    height: float | None


class DocumentExtractor(Protocol):
    def extract(self, path: Path) -> list[ExtractedPage]: ...


class PypdfDocumentExtractor:
    def extract(self, path: Path) -> list[ExtractedPage]:
        from pypdf import PdfReader

        try:
            reader = PdfReader(path)
        except Exception as exc:
            raise DocumentExtractionError("PDF could not be opened") from exc
        if reader.is_encrypted:
            raise DocumentExtractionError("Encrypted PDFs are not accepted")
        if not reader.pages:
            raise DocumentExtractionError("PDF has no pages")
        if len(reader.pages) > 200:
            raise DocumentExtractionError("PDF exceeds the 200-page processing limit")
        pages: list[ExtractedPage] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except TypeError:
                text = page.extract_text() or ""
            text = _normalize_text(text)
            box = page.mediabox
            pages.append(
                ExtractedPage(
                    page_number=page_number,
                    text=text,
                    text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    extraction_method="embedded_text" if text else "ocr_required",
                    width=float(box.width) if box else None,
                    height=float(box.height) if box else None,
                )
            )
        return pages


def evidence_blocks(text: str, *, maximum_chars: int = 1200) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, str]] = []
    for match in re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, flags=re.DOTALL):
        start, end = match.span()
        value = re.sub(r"[ \t]+", " ", match.group(0)).strip()
        if not value:
            continue
        offset = 0
        while offset < len(value):
            chunk = value[offset : offset + maximum_chars]
            if len(chunk) == maximum_chars and " " in chunk:
                chunk = chunk[: chunk.rfind(" ")]
            chunk = chunk.strip()
            if chunk:
                blocks.append((start + offset, start + offset + len(chunk), chunk))
            offset += max(len(chunk), 1)
    if not blocks and text.strip():
        value = text.strip()
        blocks.append((0, len(value), value[:maximum_chars]))
    return blocks


def _normalize_text(value: str) -> str:
    value = value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    value = "\n".join(line.rstrip() for line in value.splitlines())
    return re.sub(r"\n{4,}", "\n\n\n", value).strip()
