from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError

from app.coding.jev import parse_choice
from app.coding.providers import MockJevProvider, TypeSafeJevProvider, get_jev_provider
from app.config import Settings


def test_typesafe_jev_adapter_builds_typed_decomposed_questions() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "jev-test",
                "answers": {
                    "line_0_code_supported": {"type": "noul", "noul": 0.96},
                    "line_0_modifier_lt_supported": {"type": "noul", "noul": 0.91},
                },
                "usage": {"input_tokens": 25, "output_tokens": 2},
            },
        )

    settings = Settings(
        _env_file=None,
        jev_enabled=True,
        jev_api_key="test-key",
        jev_base_url="https://api.typesafe.ai/v1/systemone",
        jev_model="jev-test",
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = TypeSafeJevProvider(settings, client=client)

    output = provider.validate(
        {
            "deidentified": True,
            "service_date": "2026-09-17",
            "setting": "practitioner",
            "clinical_facts": [{"fact_type": "laterality", "value": "left"}],
            "lines": [{"system": "CPT", "code": "29827", "modifiers": ["LT"]}],
        }
    )

    assert output["status"] == "confirmed"
    assert output["provider"] == "typesafe_jev"
    assert set(captured["questions"]) == {
        "line_0_code_supported",
        "line_0_modifier_lt_supported",
    }
    assert captured["state"]["clinical_facts"][0]["value"] == "left"


def test_typesafe_jev_adapter_blocks_unapproved_phi() -> None:
    settings = Settings(
        _env_file=None,
        jev_enabled=True,
        jev_api_key="test-key",
        jev_base_url="https://api.typesafe.ai/v1/systemone",
        jev_model="jev-test",
        jev_phi_allowed=False,
    )
    provider = TypeSafeJevProvider(settings, client=httpx.Client())

    output = provider.validate(
        {"deidentified": False, "lines": [{"system": "CPT", "code": "29827"}]}
    )

    assert output["status"] == "blocked_phi"


def test_typesafe_jev_adapter_supports_choice_and_score_batches() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "jev-test",
                "answers": {
                    "code": {
                        "type": "choice",
                        "choice": "cpt_29827",
                        "probabilities": {"cpt_29827": 0.94, "NONE": 0.06},
                    },
                    "ambiguity": {"type": "score", "score": 1.2, "confidence": 0.91},
                },
            },
        )

    settings = Settings(
        _env_file=None,
        jev_enabled=True,
        jev_api_key="test-key",
        jev_base_url="https://api.typesafe.ai",
        jev_model="jev-test",
    )
    provider = TypeSafeJevProvider(
        settings, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    questions = {
        "code": {
            "type": "choice",
            "instructions": "Choose a code",
            "criteria": {"cpt_29827": "CPT 29827", "NONE": "Abstain"},
        },
        "ambiguity": {
            "type": "score",
            "instructions": "Score ambiguity",
            "criteria": ["none", "moderate", "high"],
        },
    }

    output = provider.decide({"deidentified": True}, questions)

    assert output["status"] == "complete"
    assert captured["questions"] == questions


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, json={"error": "failure"}),
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"answers": []}),
        httpx.Response(200, json={"answers": {}}),
        httpx.Response(
            200,
            json={"answers": {"decision": {"type": "noul"}}},
        ),
    ],
)
def test_typesafe_jev_failures_return_safe_noncomplete_status(response: httpx.Response) -> None:
    settings = Settings(
        _env_file=None,
        jev_enabled=True,
        jev_api_key="test-key",
        jev_base_url="https://api.typesafe.ai",
        jev_model="jev-test",
    )
    provider = TypeSafeJevProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(lambda _request: response)),
    )

    output = provider.decide(
        {"deidentified": True},
        {"decision": {"type": "noul", "instructions": "Is it supported?"}},
    )

    assert output["status"] in {"unavailable", "malformed"}


def test_typesafe_jev_reports_safe_http_diagnostics() -> None:
    settings = Settings(
        _env_file=None,
        jev_enabled=True,
        jev_api_key="test-key",
        jev_base_url="https://api.typesafe.ai",
        jev_model="jev-test",
    )
    provider = TypeSafeJevProvider(
        settings,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    400,
                    json={
                        "error": {
                            "code": "invalid_question",
                            "message": "Question contract was rejected",
                        }
                    },
                )
            )
        ),
    )

    output = provider.decide(
        {"deidentified": True},
        {"decision": {"type": "noul", "instructions": "Is it supported?"}},
    )

    assert output["status"] == "unavailable"
    assert output["error_code"] == "JEV_HTTP_400"
    assert output["http_status"] == 400
    assert output["provider_error"] == "invalid_question"
    assert output["question_count"] == 1


def test_typesafe_jev_retries_transient_provider_overload() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(
            200,
            json={"answers": {"decision": {"type": "noul", "noul": 0.97}}},
        )

    settings = Settings(
        _env_file=None,
        jev_enabled=True,
        jev_api_key="test-key",
        jev_base_url="https://api.typesafe.ai",
        jev_model="jev-test",
    )
    provider = TypeSafeJevProvider(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    output = provider.decide(
        {"deidentified": True},
        {"decision": {"type": "noul", "instructions": "Is it supported?"}},
    )

    assert output["status"] == "complete"
    assert calls == 2


def test_mock_jev_is_explicitly_unavailable_for_primary_decisions() -> None:
    output = MockJevProvider().decide(
        {"deidentified": True},
        {"decision": {"type": "noul", "instructions": "Is it supported?"}},
    )
    assert output["status"] == "unavailable"


def test_incomplete_enabled_provider_configuration_is_safely_unavailable() -> None:
    provider = get_jev_provider(Settings(_env_file=None, jev_enabled=True))
    output = provider.decide(
        {"deidentified": True},
        {"decision": {"type": "noul", "instructions": "Is it supported?"}},
    )
    assert output["status"] == "unavailable"
    assert output["provider"] == "typesafe_jev"


def test_choice_parser_rejects_unknown_candidate_and_missing_probability() -> None:
    unknown = parse_choice(
        {"choice": "hallucinated", "probability": 0.99}, {"candidate_0", "NONE"}
    )
    missing = parse_choice({"choice": "candidate_0"}, {"candidate_0", "NONE"})
    assert unknown.valid is False
    assert unknown.error == "out_of_set_choice"
    assert missing.valid is False
    assert missing.error == "missing_probability"


def test_jev_thresholds_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, jev_accept_threshold=0.4, jev_review_threshold=0.6)
