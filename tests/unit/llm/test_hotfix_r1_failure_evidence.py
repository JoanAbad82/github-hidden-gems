"""Hotfix R1 regression: failed provider output must keep a safe concrete cause."""

from __future__ import annotations

import httpx

from hidden_gems.llm.deepseek import DeepSeekProvider


def test_failed_validation_exposes_safe_failure_type_and_reason(app_config, monkeypatch):
    monkeypatch.setenv(app_config.llm.api_key_env_var, "test-key")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "not json"}}]},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = DeepSeekProvider(app_config, client=client)
    evidence = {
        "repo": "acme-labs/invalid-output",
        "github_repo_id": 9701,
        "repository": {
            "full_name": "acme-labs/invalid-output",
            "github_repo_id": 9701,
            "html_url": "https://github.com/acme-labs/invalid-output",
        },
    }

    result = provider.analyze_repository(evidence)

    assert result.status == "LLM_FAILED"
    assert result.evidence["failure"] == "LLMValidationError"
    assert "provider output is not valid JSON" in result.evidence["failure_reason"]
    assert "test-key" not in result.evidence["failure_reason"]
