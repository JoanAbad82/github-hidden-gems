"""Offline call trace for GitHub rate-limit halts at pipeline phase boundaries."""

from __future__ import annotations

import json

import pytest

from _pipeline_fakes import NOW, FakeGitHub, payload, run_context
from hidden_gems import orchestrator
from hidden_gems.github.client import GitHubAuthError, GitHubRateLimited
from hidden_gems.history.database import HistoryStore

_API_METHODS = (
    "search_repositories", "get_readme", "get_tree", "get_releases",
    "get_recent_commits", "get_json", "get_repo_metadata", "post_json",
)


def _recorded_github(*, failed_method: str, occurrence: int, error: Exception):
    github = FakeGitHub([
        payload(8301, "acme-labs", "flowkit"),
        payload(8302, "acme-labs", "pipeforge", stars=24),
    ])
    calls: list[tuple[str, str]] = []
    hits = 0

    for name in _API_METHODS:
        original = getattr(github, name)

        def traced(*args, _name=name, _original=original, **kwargs):
            nonlocal hits
            calls.append((_name, str(args[0]) if args else ""))
            if _name == failed_method:
                hits += 1
                if hits == occurrence:
                    if isinstance(error, GitHubRateLimited):
                        github.rate_limited = True
                    raise error
            return _original(*args, **kwargs)

        setattr(github, name, traced)
    return github, calls


def _force_publication_path(monkeypatch):
    from types import SimpleNamespace

    attempted: list[str] = []
    selected = SimpleNamespace(repo=SimpleNamespace(github_repo_id=8301), rank=1)
    monkeypatch.setattr(
        orchestrator, "select_report_candidates", lambda findings, config: [selected]
    )
    monkeypatch.setattr(orchestrator, "build_report", lambda *args, **kwargs: "offline report")
    monkeypatch.setattr(orchestrator, "report_fingerprint", lambda *args: "offline-fingerprint")
    monkeypatch.setattr(
        orchestrator, "_publish", lambda **kwargs: attempted.append("publish")
    )
    return attempted


@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.parametrize(
    "stage,failed_method,occurrence",
    [
        ("discovery", "search_repositories", 2),
        ("light", "get_readme", 1),
        ("light_manifest", "get_json", 1),
        ("relationships", "get_json", 3),
        ("deep", "get_tree", 3),
        ("deep_contents", "get_json", 4),
    ],
)
def test_rate_limit_halts_all_future_github_calls_and_publication(
    app_config, tmp_path, monkeypatch, status, stage, failed_method, occurrence
):
    github, calls = _recorded_github(
        failed_method=failed_method,
        occurrence=occurrence,
        error=GitHubRateLimited("synthetic quota limit", status_code=status),
    )
    publication_attempts = _force_publication_path(monkeypatch)
    store = HistoryStore.open(tmp_path / f"{stage}-{status}.sqlite3")
    try:
        summary = orchestrator.run_pipeline(
            app_config, store, github, None,
            run_context(f"RATE-HALT-{stage.upper()}-{status}", dry_run=False),
            as_of=NOW, llm_enabled=False,
        )
        method_names = [name for name, _endpoint in calls]
        assert method_names.count(failed_method) == occurrence, "the intended limit must occur"
        assert method_names[-1] == failed_method, f"external GitHub call leaked after limit: {calls}"
        assert publication_attempts == [], "GitHub publication must be stopped"
        assert summary.issue is None
        assert summary.result == "PARTIAL_SUCCESS_RATE_LIMIT"
        assert store.get_repository(8301) is not None
        assert store.integrity_check() is True
        artifact_path = app_config.root / "artifacts" / summary.run_id / "candidates.json"
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert artifact["run"]["result"] == "PARTIAL_SUCCESS_RATE_LIMIT"
        assert artifact["run"]["counts"]["discovered"] >= 1
    finally:
        store.close()


def test_permission_denial_during_light_analysis_is_not_a_rate_limit(
    app_config, tmp_path, monkeypatch
):
    github, calls = _recorded_github(
        failed_method="get_readme",
        occurrence=1,
        error=GitHubAuthError("synthetic permission denial", status_code=403),
    )
    publication_attempts = _force_publication_path(monkeypatch)
    store = HistoryStore.open(tmp_path / "permission.sqlite3")
    try:
        summary = orchestrator.run_pipeline(
            app_config, store, github, None,
            run_context("RATE-HALT-NEGATIVE", dry_run=False),
            as_of=NOW, llm_enabled=False,
        )
        method_names = [name for name, _endpoint in calls]
        assert method_names.index("get_tree") > method_names.index("get_readme")
        assert publication_attempts == ["publish"]
        assert summary.result != "PARTIAL_SUCCESS_RATE_LIMIT"
        assert store.integrity_check() is True
    finally:
        store.close()
