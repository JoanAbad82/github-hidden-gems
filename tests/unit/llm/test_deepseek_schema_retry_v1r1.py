"""Regression tests for the 2026-09-16 DeepSeek schema failures."""

from __future__ import annotations

import json

import httpx

from hidden_gems.llm.deepseek import DeepSeekProvider
from hidden_gems.llm.validator import PROMPT_VERSION

API_KEY = "sk-test-only"


def _evidence() -> dict:
    return {
        "repo": "acme/example",
        "github_repo_id": 4242,
        "relevant_content_hash": "hash-v1r1",
        "repository": {
            "full_name": "acme/example",
            "github_repo_id": 4242,
            "html_url": "https://github.com/acme/example",
        },
        "observed": {"source_file_count": 3},
    }


def _valid_content() -> dict:
    return {
        "summary": "A tested example repository.",
        "why_interesting": "It demonstrates a concrete engineering pattern.",
        "relevance_suggestion": 11,
        "originality_suggestion": 2,
        "confidence": "MEDIUM",
        "risks": [],
        "evidence": {
            "observed": ["src/main.py"],
            "inferred": [],
            "unknown": [],
        },
        "claims_supported": [
            {"claim": "Has implementation", "supported": True, "note": "src/main.py"}
        ],
    }


def _response(content: dict, *, prompt_tokens: int = 100, completion_tokens: int = 50) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": json.dumps(content)}}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            },
        },
    )


def _provider(app_config, handler, monkeypatch) -> DeepSeekProvider:
    monkeypatch.setenv(app_config.llm.api_key_env_var, API_KEY)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return DeepSeekProvider(app_config, client=client)


def _messages_text(request: httpx.Request) -> str:
    payload = json.loads(request.content.decode("utf-8"))
    return "\n".join(str(message.get("content", "")) for message in payload["messages"])


def test_prompt_version_is_v1r1():
    assert PROMPT_VERSION == "DEEP_ANALYZER_PROMPT_V1R1"


def test_primary_request_contains_canonical_json_schema(app_config, monkeypatch):
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _response(_valid_content())

    provider = _provider(app_config, handler, monkeypatch)
    result = provider.analyze_repository(_evidence())

    assert result.status == "OK"
    assert len(calls) == 1
    messages = _messages_text(calls[0])
    assert "LLM_ANALYSIS_V1_CANONICAL_SCHEMA" in messages
    assert '"additionalProperties": false' in messages
    assert '"claims_supported"' in messages
    assert '"maxLength": 300' in messages


def test_retry_after_unexpected_claim_property_receives_validation_feedback(app_config, monkeypatch):
    calls: list[httpx.Request] = []
    invalid = _valid_content()
    invalid["claims_supported"] = [
        {
            "claim": "Has implementation",
            "supported": True,
            "reason": "This field is forbidden by LLM_ANALYSIS_V1",
        }
    ]
    responses = iter([_response(invalid), _response(_valid_content())])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return next(responses)

    provider = _provider(app_config, handler, monkeypatch)
    result = provider.analyze_repository(_evidence())

    assert result.status == "OK"
    assert len(calls) == 2
    retry_messages = _messages_text(calls[1])
    assert "schema violation at claims_supported/0" in retry_messages
    assert "reason" in retry_messages
    assert "Generate a new JSON object from scratch" in retry_messages


def test_retry_after_oversized_risk_receives_validation_feedback(app_config, monkeypatch):
    calls: list[httpx.Request] = []
    invalid = _valid_content()
    invalid["risks"] = ["x" * 301]
    responses = iter([_response(invalid), _response(_valid_content())])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return next(responses)

    provider = _provider(app_config, handler, monkeypatch)
    result = provider.analyze_repository(_evidence())

    assert result.status == "OK"
    assert len(calls) == 2
    retry_messages = _messages_text(calls[1])
    assert "schema violation at risks/0" in retry_messages
    assert "Generate a new JSON object from scratch" in retry_messages
