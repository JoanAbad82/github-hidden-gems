"""Hotfix R1 regression tests for LLM accounting and fail-soft diagnostics."""

from __future__ import annotations

import json

from _pipeline_fakes import NOW, CountingLLM, FakeGitHub, payload, run_context

from hidden_gems.history.database import HistoryStore
from hidden_gems.llm.base import LLMBudget
from hidden_gems.models import DeepAnalysis, RepositoryRef
from hidden_gems.orchestrator import run_pipeline


class BudgetedCountingLLM(CountingLLM):
    def __init__(self) -> None:
        super().__init__()
        self.budget = LLMBudget(max_calls=30, max_budget=1.0)

    def analyze_repository(self, evidence):
        self.budget.record_call(
            reason="PRIMARY",
            input_tokens=123,
            output_tokens=45,
            cost=0.001,
        )
        return super().analyze_repository(evidence)


class FailedValidationLLM:
    def __init__(self) -> None:
        self.budget = LLMBudget(max_calls=30, max_budget=1.0)

    def analyze_repository(self, evidence):
        self.budget.record_call(reason="PRIMARY", input_tokens=50, output_tokens=10)
        full_name = str(evidence["repo"])
        repo = RepositoryRef.from_full_name(full_name, int(evidence["github_repo_id"]))
        return DeepAnalysis(
            repo=repo,
            evidence={
                "failure": "LLMValidationError",
                "failure_reason": "provider output is not valid JSON: Expecting value",
            },
            relevance_suggestion=None,
            originality_suggestion=None,
            why_interesting=None,
            summary=None,
            risks=("LLM analysis unavailable",),
            confidence="LOW",
            status="LLM_FAILED",
            source="PROVIDER",
        )


def test_pipeline_persists_the_provider_budget_that_made_real_llm_calls(app_config, tmp_path):
    github = FakeGitHub([payload(9601, "metrics-labs", "budgeted")])
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    llm = BudgetedCountingLLM()
    try:
        summary = run_pipeline(
            app_config,
            store,
            github,
            llm,
            run_context("RUN-HOTFIX-R1-BUDGET"),
            as_of=NOW,
            llm_enabled=True,
        )
        row = store.run_row("RUN-HOTFIX-R1-BUDGET")
        assert row is not None
        persisted = json.loads(row["usage"]) if isinstance(row["usage"], str) else row["usage"]

        assert llm.calls == 1
        assert llm.budget.calls_made == 1
        assert summary.usage["calls_made"] == 1
        assert summary.usage["input_tokens"] == 123
        assert summary.usage["output_tokens"] == 45
        assert summary.usage["cost"] == 0.001
        assert persisted["calls_made"] == 1
        assert persisted["input_tokens"] == 123
        assert persisted["output_tokens"] == 45
        assert persisted["cost"] == 0.001
    finally:
        store.close()


def test_failed_llm_analysis_records_repository_and_concrete_reason(app_config, tmp_path):
    github = FakeGitHub([payload(9602, "metrics-labs", "invalid-llm")])
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    llm = FailedValidationLLM()
    try:
        summary = run_pipeline(
            app_config,
            store,
            github,
            llm,
            run_context("RUN-HOTFIX-R1-ERROR"),
            as_of=NOW,
            llm_enabled=True,
        )

        assert summary.result == "PARTIAL_SUCCESS"
        assert len(summary.errors) == 1
        error = summary.errors[0]
        assert error.startswith("llm:9602:LLMValidationError:")
        assert "provider output is not valid JSON" in error
    finally:
        store.close()
