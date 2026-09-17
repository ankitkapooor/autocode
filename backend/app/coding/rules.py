from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.reference_data.utils import canonical_code
from app.repositories import CodebookRepository
from app.repositories.rules import CodingRulesRepository


@dataclass(slots=True)
class RuleFinding:
    rule_type: str
    outcome: str
    message: str
    line_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def evaluate_coding_lines(
    session: Session,
    lines: list[Any],
    service_date: date,
    setting: str,
) -> list[RuleFinding]:
    codebooks = CodebookRepository(session)
    rules = CodingRulesRepository(session)
    findings: list[RuleFinding] = []
    selected = {canonical_code(line.code) for line in lines}
    release = codebooks.active_release(service_date)

    for line in lines:
        active = codebooks.get_code(line.code_system, line.code, service_date)
        findings.append(
            RuleFinding(
                "active_code",
                "pass" if active else "fail",
                "Code exists in the active release" if active else "Code is not active on the service date",
                line.id,
                {"code": line.code, "system": line.code_system},
            )
        )
        if not line.evidence_span_ids:
            findings.append(
                RuleFinding(
                    "evidence_required",
                    "fail",
                    "Coding line has no source evidence",
                    line.id,
                )
            )
        else:
            findings.append(
                RuleFinding(
                    "evidence_required",
                    "pass",
                    "Coding line is linked to source evidence",
                    line.id,
                    {"evidence_count": len(line.evidence_span_ids)},
                )
            )
        for modifier in line.modifiers:
            modifier_entry = codebooks.get_modifier(modifier, service_date)
            findings.append(
                RuleFinding(
                    "modifier_active",
                    "pass" if modifier_entry else "fail",
                    f"Modifier {modifier} is active"
                    if modifier_entry
                    else f"Modifier {modifier} is not active",
                    line.id,
                    {"modifier": modifier},
                )
            )
        if line.code_system in {"CPT", "HCPCS"}:
            mue = rules.get_mue(line.code, service_date, setting=setting)
            if mue and mue.mue_value is not None:
                allowed = float(mue.mue_value)
                findings.append(
                    RuleFinding(
                        "mue",
                        "pass" if line.units <= allowed else "fail",
                        f"Units {line.units} are within MUE {allowed:g}"
                        if line.units <= allowed
                        else f"Units {line.units} exceed MUE {allowed:g}",
                        line.id,
                        {"units": line.units, "mue": allowed, "mai": mue.mai},
                    )
                )
            addon_relations = rules.get_addon_relationships(line.code, service_date)
            if addon_relations:
                exact_primaries = {
                    relation.primary_code_key
                    for relation in addon_relations
                    if relation.relationship_type == "explicit_primary"
                }
                if exact_primaries:
                    supported = bool(selected & exact_primaries)
                    findings.append(
                        RuleFinding(
                            "addon_primary",
                            "pass" if supported else "fail",
                            "Required primary code is present"
                            if supported
                            else "Add-on code is missing an allowed primary code",
                            line.id,
                            {"allowed_primary_codes": sorted(exact_primaries)[:30]},
                        )
                    )
                else:
                    findings.append(
                        RuleFinding(
                            "addon_primary",
                            "warning",
                            "Add-on code requires contractor or range-based primary-code review",
                            line.id,
                        )
                    )
            pfs = rules.get_pfs_attributes(line.code, service_date)
            if pfs and pfs.status_code in {"B", "I", "N", "X"}:
                findings.append(
                    RuleFinding(
                        "pfs_status",
                        "warning",
                        f"PFS status indicator {pfs.status_code} requires reviewer attention",
                        line.id,
                        {"status_code": pfs.status_code},
                    )
                )

    procedure_lines = [line for line in lines if line.code_system in {"CPT", "HCPCS"}]
    ncci_count = rules.ncci_runtime_count(service_date)
    if procedure_lines and ncci_count == 0:
        findings.append(
            RuleFinding(
                "ncci_dataset",
                "warning",
                "NCCI source files were validated but are not materialized in this development preview; human review is required",
                details={"release_scope": release.scope},
            )
        )
    elif procedure_lines:
        findings.append(
            RuleFinding(
                "ncci_dataset",
                "pass",
                "NCCI PTP source index is available for directional pair checks",
                details={"runtime_records": ncci_count, "release_scope": release.scope},
            )
        )
    for index, first in enumerate(procedure_lines):
        for second in procedure_lines[index + 1 :]:
            for column_1, column_2 in ((first, second), (second, first)):
                edit = rules.get_ncci_edit(
                    column_1.code,
                    column_2.code,
                    service_date,
                    setting=setting,
                )
                if edit is None:
                    continue
                indicator = edit.modifier_indicator or ""
                if indicator == "0":
                    outcome = "fail"
                    message = f"NCCI edit prohibits reporting {column_2.code} with {column_1.code}"
                elif indicator == "1":
                    outcome = "warning"
                    message = (
                        f"NCCI edit for {column_1.code}/{column_2.code} permits a modifier only "
                        "when documentation supports a distinct service"
                    )
                else:
                    outcome = "warning"
                    message = f"NCCI edit for {column_1.code}/{column_2.code} requires review"
                findings.append(
                    RuleFinding(
                        "ncci_ptp",
                        outcome,
                        message,
                        column_2.id,
                        {
                            "column_1": column_1.code,
                            "column_2": column_2.code,
                            "modifier_indicator": indicator,
                        },
                    )
                )
                break
    return findings
