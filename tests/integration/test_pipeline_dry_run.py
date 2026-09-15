"""Task 13: end-to-end dry run over fake GitHub + fake LLM + real SQLite."""

from __future__ import annotations

import pytest

from _pipeline_fakes import NOW, CountingLLM, FakeGitHub, payload, run_context

HistoryStore = pytest.importorskip(
    "hidden_gems.history.database", reason="Task 2 (SQLite history) not available yet"
).HistoryStore

from hidden_gems.orchestrator import run_pipeline  # noqa: E402


def test_dry_run_pipeline_completes_and_persists_without_publishing(app_config, tmp_path):
    repos = [
        payload(7001, "acme-labs", "flowkit"),
        payload(7002, "acme-labs", "pipeforge", stars=24),
    ]
    github = FakeGitHub(repos)
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    llm = CountingLLM()
    try:
        summary = run_pipeline(
            app_config, store, github, llm, run_context(), as_of=NOW, llm_enabled=True
        )
        assert summary.result in {"SUCCESS", "SUCCESS_NO_FINDINGS"}
        assert github.posts == []
        assert summary.dry_run is True
        assert summary.issue is None
        assert store.integrity_check() is True
        assert store.get_repository(7001) is not None
    finally:
        store.close()


def test_dry_run_never_calls_the_publisher(app_config, tmp_path):
    class ExplodingPublisher:
        def publish(self, *args, **kwargs):  # pragma: no cover - must not run
            raise AssertionError("publisher must not be used in dry-run")

    github = FakeGitHub([payload(7003, "acme-labs", "flowkit")])
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    try:
        summary = run_pipeline(
            app_config,
            store,
            github,
            CountingLLM(),
            run_context(),
            publisher=ExplodingPublisher(),
            as_of=NOW,
            llm_enabled=True,
        )
        assert summary.result in {"SUCCESS", "SUCCESS_NO_FINDINGS"}
    finally:
        store.close()


def test_llm_disabled_still_completes_the_pipeline(app_config, tmp_path):
    github = FakeGitHub([payload(7004, "acme-labs", "flowkit")])
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    llm = CountingLLM()
    try:
        summary = run_pipeline(
            app_config, store, github, llm, run_context(), as_of=NOW, llm_enabled=False
        )
        assert llm.calls == 0
        assert summary.result in {"SUCCESS", "SUCCESS_NO_FINDINGS", "PARTIAL_SUCCESS"}
    finally:
        store.close()


def test_pipeline_uses_the_state_and_history_layers_only(app_config, tmp_path):
    github = FakeGitHub([payload(7005, "acme-labs", "flowkit")])
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    try:
        summary = run_pipeline(app_config, store, github, None, run_context(), as_of=NOW)
        assert summary.run_id == "RUN-TEST-1"
        assert summary.counts["discovered"] >= 1
        assert summary.errors == ()
    finally:
        store.close()
