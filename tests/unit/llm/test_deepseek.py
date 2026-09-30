"""Task 10: DeepSeek provider budgets, retries, and secret hygiene."""

from __future__ import annotations

import json

import httpx
import pytest

from hidden_gems.llm.base import LLMBudget, LLMProviderError
from hidden_gems.llm.deepseek import DeepSeekProvider

API_KEY = "sk-super-secret-value"


def evidence(repo_id: int = 501, content_hash: str = "hash-1") -> dict:
    return {
        "repo": "acme-labs/flowkit",
        "github_repo_id": repo_id,
        "relevant_content_hash": content_hash,
        "repository": {
            "full_name": "acme-labs/flowkit",
            "github_repo_id": repo_id,
            "html_url": "https://github.com/acme-labs/flowkit",
        },
        "observed": {"source_file_count": 3},
    }


def valid_body() -> dict:
    content = {
        "summary": "A small workflow runtime.",
        "why_interesting": "Compact and tested.",
        "relevance_suggestion": 11,
        "originality_suggestion": 2,
        "confidence": "MEDIUM",
        "risks": [],
        "evidence": {
            "observed": ["src/main.py", "tests/test_main.py"],
            "inferred": [],
            "unknown": [],
        },
    }
    return {
        "choices": [{"message": {"content": json.dumps(content)}}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 200},
    }


def make_provider(app_config, handler, *, budget=None, api_key=API_KEY, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setenv(app_config.llm.api_key_env_var, api_key)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return DeepSeekProvider(app_config, client=client, budget=budget)


def test_valid_response_becomes_a_deep_analysis(app_config, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=valid_body())

    api = make_provider(app_config, handler, monkeypatch=monkeypatch)
    deep = api.analyze_repository(evidence())

    assert deep.status == "OK"
    assert deep.relevance_suggestion == 11
    assert deep.confidence == "MEDIUM"
    assert len(calls) == 1
    body = json.loads(calls[0].content.decode("utf-8"))
    assert body["model"] == app_config.llm.model
    assert body["response_format"] == {"type": "json_object"}
    assert "UNTRUSTED" in body["messages"][0]["content"].upper()
    assert body["temperature"] == 0
    assert body["max_tokens"] == 2200


def test_authorization_header_is_never_leaked_in_errors(app_config, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    api = make_provider(app_config, handler, monkeypatch=monkeypatch)
    deep = api.analyze_repository(evidence())

    assert deep.status == "LLM_FAILED"
    rendered = json.dumps(
        {"risks": list(deep.risks), "evidence": deep.evidence, "budget": api.budget.snapshot()}
    )
    assert API_KEY not in rendered
    assert "Bearer" not in rendered


def test_schema_failure_is_retried_then_fails_without_fabricating_a_score(app_config, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    api = make_provider(app_config, handler, monkeypatch=monkeypatch)
    deep = api.analyze_repository(evidence())

    assert deep.status == "LLM_FAILED"
    assert deep.relevance_suggestion is None
    assert deep.originality_suggestion is None
    assert len(calls) == app_config.llm.max_retries_per_candidate + 1


def test_retry_after_invalid_output_can_succeed(app_config, monkeypatch):
    responses = iter(["not json", json.dumps(valid_body())])

    def handler(request: httpx.Request) -> httpx.Response:
        value = next(responses)
        if value == "not json":
            return httpx.Response(200, json={"choices": [{"message": {"content": value}}]})
        return httpx.Response(200, json=json.loads(value))

    api = make_provider(app_config, handler, monkeypatch=monkeypatch)
    deep = api.analyze_repository(evidence())

    assert deep.status == "OK"
    assert api.budget.calls_made == 2


def test_call_budget_caps_calls_including_retries(app_config, monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    budget = LLMBudget(max_calls=5, max_budget=10.0)
    api = make_provider(app_config, handler, budget=budget, monkeypatch=monkeypatch)

    results = []
    with pytest.raises(LLMProviderError, match="budget"):
        for _ in range(20):
            results.append(api.analyze_repository(evidence()))

    assert results, "at least one candidate was attempted"
    assert len(calls) <= 5
    assert budget.calls_made <= 5
    assert all(result.status == "LLM_FAILED" for result in results)


def test_missing_api_key_raises_without_network(app_config, monkeypatch):
    monkeypatch.delenv(app_config.llm.api_key_env_var, raising=False)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=valid_body())

    api = make_provider(app_config, handler, api_key="", monkeypatch=monkeypatch)

    try:
        api.analyze_repository(evidence())
    except LLMProviderError as exc:
        assert app_config.llm.api_key_env_var in str(exc)
    else:
        raise AssertionError("missing key must raise")
    assert calls == []


def test_usage_and_cost_are_accounted(app_config, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=valid_body())

    budget = LLMBudget(max_calls=10, max_budget=1.0)
    api = make_provider(app_config, handler, budget=budget, monkeypatch=monkeypatch)
    api.analyze_repository(evidence())

    snapshot = budget.snapshot()
    assert snapshot["calls_made"] == 1
    assert snapshot["input_tokens"] == 1000
    assert snapshot["output_tokens"] == 200


def test_network_failure_is_reported_not_raised(app_config, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    api = make_provider(app_config, handler, monkeypatch=monkeypatch)
    deep = api.analyze_repository(evidence())

    assert deep.status == "LLM_FAILED"
    assert api.budget.failures == 1


def test_schema_retry_feedback_is_structured_and_does_not_echo_overlong_value(
    app_config, monkeypatch
):
    calls = []
    overlong = (
        "Parent pom.xml declares packaging 'pom' with modules common, "
        "s02-minimal-chat, s11-agent-loop, s12-tool-use, s13-permission, "
        "s14-hooks, s21-planning, s22-subagent, s23-memory, "
        "s24-context-compact, s25-error-recovery, s31-supervisor, "
        "s32-orchestrator, s33-protocol, s34-checkpoint, s35-taskboard, "
        "s36-bus, s41-tasksystem, s42-scheduler, s43-mcp, s44-capstone."
    )
    invalid = {
        "summary": "A multi-module agent learning project.",
        "why_interesting": "It covers a broad sequence of agent patterns.",
        "relevance_suggestion": 12,
        "originality_suggestion": 3,
        "confidence": "MEDIUM",
        "risks": [],
        "evidence": {
            "observed": [overlong],
            "inferred": [],
            "unknown": [],
        },
        "claims_supported": [],
    }
    bodies = iter(
        [
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps(invalid)},
                    }
                ],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 900},
            },
            valid_body(),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=next(bodies))

    api = make_provider(app_config, handler, monkeypatch=monkeypatch)
    deep = api.analyze_repository(evidence(repo_id=1379423359))

    assert deep.status == "OK"
    assert len(calls) == 2
    retry_payload = json.loads(calls[1].content.decode("utf-8"))
    retry_message = retry_payload["messages"][-1]["content"]
    assert "path=evidence/observed/0" in retry_message
    assert "rule=maxLength" in retry_message
    assert "limit=300" in retry_message
    assert overlong not in retry_message
