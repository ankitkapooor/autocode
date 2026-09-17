from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class DiscoveredFile:
    id: str
    path: Path
    relative_path: str
    source_family: str
    size: int
    sha256: str
    source_url: str | None = None
    effective_from: date | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ValidationIssue:
    severity: str
    code: str
    message: str
    source_family: str | None = None
    source_file_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedBundle:
    code_entries: list[dict[str, Any]] = field(default_factory=list)
    modifiers: list[dict[str, Any]] = field(default_factory=list)
    pfs_attributes: list[dict[str, Any]] = field(default_factory=list)
    ncci_edits: list[dict[str, Any]] = field(default_factory=list)
    mue_edits: list[dict[str, Any]] = field(default_factory=list)
    addon_relations: list[dict[str, Any]] = field(default_factory=list)
    rule_documents: list[dict[str, Any]] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    def extend(self, other: ParsedBundle) -> None:
        self.code_entries.extend(other.code_entries)
        self.modifiers.extend(other.modifiers)
        self.pfs_attributes.extend(other.pfs_attributes)
        self.ncci_edits.extend(other.ncci_edits)
        self.mue_edits.extend(other.mue_edits)
        self.addon_relations.extend(other.addon_relations)
        self.rule_documents.extend(other.rule_documents)
        self.issues.extend(other.issues)
