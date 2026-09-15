"""Task 10/13: `MAX_LLM_CANDIDATES_PER_RUN` must bound semantic enrichment.

SPEC_V1 section 8 lists `MAX_LLM_CANDIDATES_PER_RUN` as a mandatory limit. The
call budget (`MAX_LLM_CALLS_PER_RUN`) alone is not enough: a run may deep-analyze
many more repositories than the number of repositories allowed to reach the LLM.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from _pipeline_fakes import NOW, CountingLLM, FakeGitHub, payload, run_context

HistoryStore = pytest.importorskip(
    "hidden_gems.history.database", reason="Task 2 (SQLite history) not available yet"
).HistoryStore

from hidden_gems.orchestrator import run_pipeline  # noqa: E402


def _config_with_candidate_cap(app_config, *, cap: int, calls: int = 8):
    llm = replace(
        app_config.llm,
        max_llm_candidates_per_run=cap,
        max_llm_calls_per_run=calls,
    )
    return replace(app_config, llm=llm, limits=replace(app_config.limits, llm=llm))


def test_llm_candidate_cap_limits_semantic_enrichment(app_config, tmp_path):
    repos = [
        payload(8101, "cap-labs", "flowkit"),
        payload(8102, "cap-labs", "pipeforge"),
        payload(8103, "cap-labs", "taskgraph"),
    ]
    config = _config_with_candidate_cap(app_config, cap=1)
    github = FakeGitHub(repos)
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    llm = CountingLLM()
    try:
        summary = run_pipeline(
            config, store, github, llm, run_context("RUN-CAP-1"), as_of=NOW, llm_enabled=True
        )
        # Precondition: the run really did deep-analyze more than the LLM cap.
        assert summary.counts["deep_analyzed"] >= 3
        # The mandatory per-run candidate cap must bound provider calls.
        assert llm.calls <= 1, summary.errors
        assert summary.usage.get("candidate_cap_skipped", 0) >= 2
    finally:
        store.close()


def test_llm_candidate_cap_zero_disables_enrichment_without_failing(app_config, tmp_path):
    config = _config_with_candidate_cap(app_config, cap=0, calls=4)
    github = FakeGitHub([payload(8104, "cap-labs", "flowkit")])
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    llm = CountingLLM()
    try:
        summary = run_pipeline(
            config, store, github, llm, run_context("RUN-CAP-0"), as_of=NOW, llm_enabled=True
        )
        assert llm.calls == 0
        assert summary.result in {"SUCCESS", "SUCCESS_NO_FINDINGS", "PARTIAL_SUCCESS"}
    finally:
        store.close()
