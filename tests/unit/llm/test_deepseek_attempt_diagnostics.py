"""RED tests for bounded, secret-safe DeepSeek attempt diagnostics."""

from __future__ import annotations

from pathlib import Path

import httpx

from hidden_gems.llm.deepseek import DeepSeekProvider

API_KEY = "sk-test-only"


def _evidence(repo_id: int = 501) -> dict:
    return {
        "repo": "acme-labs/flowkit",
        "github_repo_id": repo_id,
        "relevant_content_hash": "hash-1",
        "repository": {
            "full_name": "acme-labs/flowkit",
            "github_repo_id": repo_id,
            "html_url": "https://github.com/acme-labs/flowkit",
        },
        "observed": {"source_file_count": 3},
    }


def _provider(app_config, monkeypatch, *, finish_reason: str, completion_tokens: int):
    monkeypatch.setenv(app_config.llm.api_key_env_var, API_KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": finish_reason,
                        "message": {"content": '{"summary":"unterminated'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 321,
                    "completion_tokens": completion_tokens,
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return DeepSeekProvider(app_config, api_key=API_KEY, client=client)


def test_authoritative_output_token_budget_is_2200(app_config):
    assert app_config.llm.max_output_tokens_per_repo == 2200


def test_invalid_json_records_length_finish_reason_as_truncation_for_each_attempt(
    app_config, monkeypatch
):
    output_budget = app_config.llm.max_output_tokens_per_repo
    api = _provider(
        app_config,
        monkeypatch,
        finish_reason="length",
        completion_tokens=output_budget,
    )

    deep = api.analyze_repository(_evidence())

    assert deep.status == "LLM_FAILED"
    assert deep.relevance_suggestion is None
    assert deep.originality_suggestion is None
    assert "truncat" in deep.evidence["failure_reason"].lower()
    assert "finish_reason=length" in deep.evidence["failure_reason"]
    assert str(output_budget) in deep.evidence["failure_reason"]
    attempts = api.budget.snapshot()["attempts"]
    assert len(attempts) == app_config.llm.max_retries_per_candidate + 1
    assert attempts[0] == {
        "repo_id": 501,
        "attempt": "PRIMARY",
        "http_status": 200,
        "finish_reason": "length",
        "prompt_tokens": 321,
        "completion_tokens": output_budget,
        "content_length": len('{"summary":"unterminated'),
        "validation_result": "TRUNCATION",
    }
    assert attempts[1]["attempt"] == "RETRY"
    assert attempts[1]["finish_reason"] == "length"
    assert attempts[1]["completion_tokens"] == output_budget
    assert attempts[1]["validation_result"] == "TRUNCATION"


def test_invalid_json_with_stop_is_distinguished_from_length(app_config, monkeypatch):
    api = _provider(app_config, monkeypatch, finish_reason="stop", completion_tokens=187)

    deep = api.analyze_repository(_evidence(repo_id=777))

    assert deep.status == "LLM_FAILED"
    assert "truncat" not in deep.evidence["failure_reason"].lower()
    attempts = api.budget.snapshot()["attempts"]
    assert attempts[0]["repo_id"] == 777
    assert attempts[0]["finish_reason"] == "stop"
    assert attempts[0]["completion_tokens"] == 187
    assert attempts[0]["validation_result"] == "VALIDATION_ERROR"


def test_dry_run_workflow_emits_attempt_diagnostics():
    workflow = Path(".github/workflows/daily_discovery.yml").read_text(encoding="utf-8")

    assert "LLM_ATTEMPTS=" in workflow
