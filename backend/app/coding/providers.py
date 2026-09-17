from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import Settings


@dataclass(slots=True)
class ProviderResult:
    data: dict[str, Any]
    usage: dict[str, Any]
    model: str
    request_fingerprint: str


class ClinicalReasoningProvider(Protocol):
    def extract_facts(self, evidence: list[dict[str, Any]]) -> ProviderResult: ...

    def select_codes(
        self,
        facts: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        service_date: str,
    ) -> ProviderResult: ...


class JevProvider(Protocol):
    name: str

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class OpenAIClinicalProvider:
    provider_name = "openai"

    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        if not settings.llm_model:
            raise RuntimeError("LLM_MODEL is not configured")
        from openai import OpenAI

        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.llm_model
        self.extraction_model = settings.extraction_model or settings.llm_model
        self.reasoning_effort = settings.llm_reasoning_effort

    def extract_facts(self, evidence: list[dict[str, Any]]) -> ProviderResult:
        payload = json.dumps({"evidence": evidence}, ensure_ascii=False, separators=(",", ":"))
        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "search_queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 12,
                },
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "fact_type": {
                                "type": "string",
                                "enum": [
                                    "diagnosis",
                                    "procedure",
                                    "anatomy",
                                    "laterality",
                                    "device",
                                    "approach",
                                    "encounter",
                                    "clinical_context",
                                ],
                            },
                            "value": {"type": "string"},
                            "normalized_value": {"type": "string"},
                            "assertion": {
                                "type": "string",
                                "enum": ["present", "absent", "historical", "uncertain"],
                            },
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "evidence_span_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                            },
                        },
                        "required": [
                            "fact_type",
                            "value",
                            "normalized_value",
                            "assertion",
                            "confidence",
                            "evidence_span_ids",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["summary", "search_queries", "facts"],
            "additionalProperties": False,
        }
        return self._response(
            model=self.extraction_model,
            name="orthocode_clinical_facts",
            schema=schema,
            instructions=(
                "You extract de-identified orthopedic coding facts. Use only the supplied evidence. "
                "Never infer an undocumented diagnosis, procedure, laterality, approach, device, or quantity. "
                "Every fact must cite one or more exact evidence_span_ids. Produce concise retrieval queries "
                "for CPT and ICD-10-CM candidate search; do not assign codes in this stage."
            ),
            payload=payload,
            max_output_tokens=5000,
        )

    def select_codes(
        self,
        facts: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        service_date: str,
    ) -> ProviderResult:
        request = {"service_date": service_date, "facts": facts, "allowed_candidates": candidates}
        payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code_system": {"type": "string", "enum": ["CPT", "HCPCS", "ICD10CM"]},
                            "code": {"type": "string"},
                            "units": {"type": "integer", "minimum": 1, "maximum": 99},
                            "modifiers": {"type": "array", "items": {"type": "string"}},
                            "diagnosis_pointers": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "rationale": {"type": "string"},
                            "evidence_span_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                            },
                        },
                        "required": [
                            "code_system",
                            "code",
                            "units",
                            "modifiers",
                            "diagnosis_pointers",
                            "confidence",
                            "rationale",
                            "evidence_span_ids",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["summary", "lines"],
            "additionalProperties": False,
        }
        return self._response(
            model=self.model,
            name="orthocode_coding_decision",
            schema=schema,
            instructions=(
                "You are a conservative orthopedic coding reasoning component. Select only from "
                "allowed_candidates and only when directly supported by cited facts and evidence. "
                "Do not invent codes, modifiers, quantities, diagnoses, or evidence IDs. Omit a line "
                "when documentation is insufficient. Deterministic NCCI, MUE, add-on, modifier, and "
                "fee-schedule checks run after this response."
            ),
            payload=payload,
            max_output_tokens=5000,
        )

    def _response(
        self,
        *,
        model: str,
        name: str,
        schema: dict[str, Any],
        instructions: str,
        payload: str,
        max_output_tokens: int,
    ) -> ProviderResult:
        fingerprint = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        response = self.client.responses.create(
            model=model,
            instructions=instructions,
            input=payload,
            reasoning={"effort": self.reasoning_effort},
            text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
            max_output_tokens=max_output_tokens,
            store=False,
        )
        data = json.loads(response.output_text)
        usage = response.usage.model_dump(mode="json") if response.usage else {}
        return ProviderResult(data=data, usage=usage, model=model, request_fingerprint=fingerprint)


class MockJevProvider:
    name = "mock"

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "provider": self.name,
            "status": "not_executed",
            "label": "Mock adapter — no external Jev decision was used",
            "line_count": len(payload.get("lines", [])),
            "agreements": [],
        }


class TypeSafeJevProvider:
    """Production adapter for TypeSafe's documented System One API."""

    name = "typesafe_jev"

    def __init__(self, settings: Settings, *, client: httpx.Client | None = None):
        if not settings.jev_api_key:
            raise RuntimeError("JEV_API_KEY is not configured")
        if not settings.jev_base_url:
            raise RuntimeError("JEV_BASE_URL is not configured")
        if not settings.jev_model:
            raise RuntimeError("JEV_MODEL is not configured")
        configured = settings.jev_base_url.rstrip("/")
        self.endpoint = (
            configured if configured.endswith("/v1/systemone") else f"{configured}/v1/systemone"
        )
        self.model = settings.jev_model
        self.phi_allowed = settings.jev_phi_allowed
        self.client = client or httpx.Client(
            headers={"Authorization": f"Bearer {settings.jev_api_key}"}, timeout=30.0
        )

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload.get("deidentified") and not self.phi_allowed:
            return {
                "provider": self.name,
                "status": "blocked_phi",
                "label": "Jev blocked because the chart is not approved for this provider",
                "answers": {},
            }
        questions, metadata = _jev_questions(payload.get("lines", []))
        if not questions:
            return {
                "provider": self.name,
                "status": "not_applicable",
                "label": "No proposed coding lines required a Jev decision",
                "answers": {},
            }
        state = {
            "service_date": payload.get("service_date"),
            "setting": payload.get("setting"),
            "clinical_facts": payload.get("clinical_facts", []),
            "proposed_coding_lines": payload.get("lines", []),
        }
        try:
            response = self.client.post(
                self.endpoint,
                json={"model": self.model, "state": state, "questions": questions},
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "provider": self.name,
                "status": "unavailable",
                "label": "Jev decision service was unavailable; human review is required",
                "error_type": type(exc).__name__,
                "answers": {},
            }

        answers = data.get("answers", {})
        decisions: list[dict[str, Any]] = []
        for key, details in metadata.items():
            answer = answers.get(key, {})
            probability = answer.get("noul") if answer.get("type") == "noul" else None
            decisions.append({**details, "question": key, "probability": probability})
        probabilities = [item["probability"] for item in decisions if item["probability"] is not None]
        confirmed = len(probabilities) == len(decisions) and all(value >= 0.8 for value in probabilities)
        return {
            "provider": self.name,
            "status": "confirmed" if confirmed else "requires_review",
            "label": (
                "Jev confirmed every proposed line and modifier"
                if confirmed
                else "One or more Jev decisions require human review"
            ),
            "model": data.get("model", self.model),
            "answers": answers,
            "decisions": decisions,
            "usage": data.get("usage", {}),
        }


def _jev_questions(
    lines: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    questions: dict[str, dict[str, Any]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(lines):
        code = str(line.get("code", ""))
        system = str(line.get("system", ""))
        code_key = f"line_{index}_code_supported"
        questions[code_key] = {
            "type": "noul",
            "instructions": (
                f"Do the supplied clinical facts directly support reporting {system} code {code} "
                "for this encounter?"
            ),
            "criteria": {
                "true": "The performed service or diagnosis is directly supported by the facts.",
                "false": "Support is absent, contradictory, planned-only, historical, or uncertain.",
            },
        }
        metadata[code_key] = {"line_index": index, "kind": "code", "code": code}
        for modifier in line.get("modifiers", []):
            modifier_key = f"line_{index}_modifier_{canonical_decision_key(str(modifier))}_supported"
            questions[modifier_key] = {
                "type": "noul",
                "instructions": (
                    f"Do the supplied clinical facts directly support modifier {modifier} on "
                    f"{system} code {code}?"
                ),
                "criteria": {
                    "true": "The modifier's required circumstance is directly documented.",
                    "false": "The required circumstance is absent, contradictory, or uncertain.",
                },
            }
            metadata[modifier_key] = {
                "line_index": index,
                "kind": "modifier",
                "code": code,
                "modifier": str(modifier),
            }
    return questions, metadata


def canonical_decision_key(value: str) -> str:
    return "".join(character.lower() if character.isalnum() else "_" for character in value)


def get_reasoning_provider(settings: Settings) -> ClinicalReasoningProvider:
    if settings.llm_provider.lower() != "openai":
        raise RuntimeError(f"Unsupported LLM provider: {settings.llm_provider}")
    return OpenAIClinicalProvider(settings)


def get_jev_provider(settings: Settings) -> JevProvider:
    if settings.jev_enabled:
        return TypeSafeJevProvider(settings)
    return MockJevProvider()
