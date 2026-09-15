"""Task 18 step 3 needs per-stage and LLM metrics that survive in SQLite."""

from __future__ import annotations

import json

import pytest

from _pipeline_fakes import NOW, CountingLLM, FakeGitHub, payload, run_context

HistoryStore = pytest.importorskip(
    "hidden_gems.history.database", reason="Task 2 (SQLite history) not available yet"
).HistoryStore

from hidden_gems.orchestrator import run_pipeline  # noqa: E402


def test_run_row_persists_stage_counts_and_llm_usage(app_config, tmp_path):
    github = FakeGitHub([payload(9501, "metrics-labs", "flowkit")])
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    try:
        summary = run_pipeline(
            app_config,
            store,
            github,
            CountingLLM(),
            run_context("RUN-METRICS"),
            as_of=NOW,
            llm_enabled=True,
        )
        row = store.run_row("RUN-METRICS")
        assert row is not None
        usage = json.loads(row["usage"]) if isinstance(row["usage"], str) else row["usage"]
        counts = usage["counts"]
        for key in ("discovered", "light_analyzed", "deep_analyzed", "scored", "reported"):
            assert key in counts
        assert counts["discovered"] == summary.counts["discovered"]
        assert usage["calls_made"] >= 0
        assert "cache_hits" in usage
    finally:
        store.close()
