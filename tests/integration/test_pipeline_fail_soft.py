"""Task 13: fail-soft per-candidate behaviour and rate-limit stops."""

from __future__ import annotations

import pytest

from _pipeline_fakes import NOW, FakeGitHub, payload, run_context

pytest.importorskip(
    "hidden_gems.history.database", reason="Task 2 (SQLite history) not available yet"
)

from hidden_gems import orchestrator  # noqa: E402
from hidden_gems.history.database import HistoryStore  # noqa: E402


def test_one_failing_candidate_does_not_abort_the_run(app_config, tmp_path, monkeypatch):
    repos = [
        payload(8001, "acme-labs", "alpha"),
        payload(8002, "acme-labs", "broken"),
        payload(8003, "acme-labs", "timeout"),
        payload(8004, "acme-labs", "delta"),
    ]
    github = FakeGitHub(repos)
    store = HistoryStore.open(tmp_path / "history.sqlite3")

    real_analyzer = orchestrator.LightAnalyzer

    class FlakyAnalyzer:
        def __init__(self, config, client) -> None:
            self._inner = real_analyzer(config, client)

        def analyze(self, candidate, *, as_of):
            if candidate.repo.github_repo_id == 8002:
                raise RuntimeError("GitHubNotFound")
            if candidate.repo.github_repo_id == 8003:
                raise TimeoutError("read timed out")
            return self._inner.analyze(candidate, as_of=as_of)

    monkeypatch.setattr(orchestrator, "LightAnalyzer", FlakyAnalyzer)

    try:
        summary = orchestrator.run_pipeline(
            app_config, store, github, None, run_context("RUN-FAILSOFT-1"), as_of=NOW, llm_enabled=False
        )
        assert summary.result == "PARTIAL_SUCCESS"
        assert any("light:8002" in error for error in summary.errors)
        assert any("light:8003" in error for error in summary.errors)
        assert store.get_repository(8001) is not None
        assert store.get_repository(8004) is not None
        assert store.integrity_check() is True
    finally:
        store.close()


def test_rate_limit_stop_persists_state_and_reports_partial_success(app_config, tmp_path):
    repos = [payload(8100 + index, "acme-labs", f"repo{index}") for index in range(6)]
    github = FakeGitHub(repos)
    store = HistoryStore.open(tmp_path / "history.sqlite3")

    original = github.search_repositories
    calls = {"count": 0}

    def flaky_search(query: str, page: int = 1) -> dict:
        calls["count"] += 1
        if calls["count"] >= 2:
            github.rate_budget.zone = "RED"
        return original(query, page)

    github.search_repositories = flaky_search

    try:
        summary = orchestrator.run_pipeline(
            app_config, store, github, None, run_context("RUN-RATE-1"), as_of=NOW, llm_enabled=False
        )
        assert summary.result == "PARTIAL_SUCCESS_RATE_LIMIT"
        assert github.owner_scans == [], "relationship expansion must not start under RED"
        assert store.integrity_check() is True
    finally:
        store.close()
