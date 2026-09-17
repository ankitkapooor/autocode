from __future__ import annotations

import httpx

from app.coding.providers import TypeSafeJevProvider
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
