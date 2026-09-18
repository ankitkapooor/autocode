from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ParsedDecision:
    value: str | float | None
    probability: float | None
    probabilities: dict[str, float] = field(default_factory=dict)
    valid: bool = False
    error: str | None = None


def parse_choice(answer: Any, allowed: set[str]) -> ParsedDecision:
    if not isinstance(answer, dict):
        return ParsedDecision(None, None, error="missing_answer")
    raw_probabilities = answer.get("probabilities") or answer.get("distribution") or {}
    probabilities = {
        str(key): float(value)
        for key, value in raw_probabilities.items()
        if isinstance(value, (float, int)) and not isinstance(value, bool) and 0 <= float(value) <= 1
    } if isinstance(raw_probabilities, dict) else {}
    value = answer.get("choice")
    if value is None:
        value = answer.get("value")
    if value is None:
        value = answer.get("answer")
    if value is None and probabilities:
        value = max(probabilities, key=probabilities.get)  # type: ignore[arg-type]
    if not isinstance(value, str):
        return ParsedDecision(None, None, probabilities, error="missing_choice")
    probability = _probability(answer.get("probability"))
    if probability is None:
        probability = probabilities.get(value)
    if probability is None:
        probability = _probability(answer.get("confidence"))
    if value not in allowed:
        return ParsedDecision(value, probability, probabilities, error="out_of_set_choice")
    if probability is None:
        return ParsedDecision(value, None, probabilities, error="missing_probability")
    return ParsedDecision(value, probability, probabilities, valid=True)


def parse_noul(answer: Any) -> ParsedDecision:
    if not isinstance(answer, dict):
        return ParsedDecision(None, None, error="missing_answer")
    value = answer.get("noul")
    if value is None:
        value = answer.get("probability")
    if isinstance(value, bool):
        value = float(value)
    probability = _probability(value)
    if probability is None:
        return ParsedDecision(None, None, error="missing_probability")
    return ParsedDecision(probability, probability, valid=True)


def decision_bucket(probability: float | None, accept: float, review: float) -> str:
    if probability is None:
        return "rejected"
    if probability >= accept:
        return "accepted"
    if probability >= review:
        return "review"
    return "rejected"


def decision_key(*parts: str) -> str:
    value = "_".join(parts).lower()
    return re.sub(r"[^a-z0-9_]+", "_", value).strip("_")[:120]


def _probability(value: Any) -> float | None:
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        result = float(value)
        if 0 <= result <= 1:
            return result
    return None
