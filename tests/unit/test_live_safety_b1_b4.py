"""Regression coverage for fail-closed live state, backups and cost guard."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3

import pytest

from hidden_gems.history.live_state_guard import (
    LiveStateError, verify_state, restore_backup, stage_live,
)
from hidden_gems.history.state_branch import write_state_manifest
from hidden_gems.llm.base import LLMBudget, LLMProviderError
from hidden_gems.llm.deepseek import DeepSeekProvider


def fake_snapshot(root: Path, run_id: str, when: str = "2026-09-16T11:40:14Z", *,
                  dry_run: int = 0):
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "history.sqlite3"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "CREATE TABLE runs (run_id TEXT, started_at TEXT, result TEXT, dry_run INTEGER)"
        )
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?)",
            (run_id, when, "SUCCESS", dry_run),
        )
        connection.commit()
    finally:
        connection.close()
    write_state_manifest(db_path, run_id=run_id, run_result="SUCCESS")
    return db_path


def test_original_state_is_valid_and_backups_initially_empty(tmp_path):
    db = fake_snapshot(tmp_path / "state", "RUN-20260916T114014Z")
    result = verify_state(db.parent)
    assert result["backup_count"] == 0
    assert result["result"] == "SUCCESS"


def test_manifest_hash_mismatch_fails_closed(tmp_path):
    db = fake_snapshot(tmp_path / "state", "RUN-20260916T114014Z")
    (db.parent / "history.sqlite3").write_bytes(db.read_bytes() + b"corrupt")
    with pytest.raises(LiveStateError, match="SHA-256"):
        verify_state(db.parent)


def test_missing_source_or_manifest_fails_closed(tmp_path):
    with pytest.raises(LiveStateError, match="must include"):
        verify_state(tmp_path / "missing")


def test_live_staging_creates_verifiable_restorable_backup(tmp_path):
    base = tmp_path / "state"
    old = fake_snapshot(base, "RUN-20260916T114014Z")
    old_hash = hashlib.sha256(old.read_bytes()).hexdigest()
    app_db = fake_snapshot(tmp_path / "app", "RUN-20261013T061700Z",
                           when="2026-10-13T06:17:00Z")
    result = stage_live(app_db, base)
    assert result["run_id"] == "RUN-20261013T061700Z"
    assert result["backup_count"] == 1
    archive = next((base / "backups").glob("*.sqlite3.gz"))
    restored = tmp_path / "restored.sqlite3"
    assert restore_backup(archive, restored) == old_hash
    db = sqlite3.connect(restored)
    try:
        assert db.execute("SELECT run_id FROM runs").fetchone()[0] == "RUN-20260916T114014Z"
    finally:
        db.close()
    with pytest.raises(LiveStateError, match="exists"):
        restore_backup(archive, restored)


def test_tampered_backup_cannot_pass_verification(tmp_path):
    old = fake_snapshot(tmp_path / "state", "RUN-20260916T114014Z")
    newer = fake_snapshot(tmp_path / "new", "RUN-20261013T061700Z",
                          when="2026-10-13T06:17:00Z")
    stage_live(newer, old.parent)
    archive = next((old.parent / "backups").glob("*.sqlite3.gz"))
    archive.write_bytes(b"not gzip")
    with pytest.raises((OSError, EOFError, LiveStateError)):
        verify_state(old.parent)


def test_stage_live_rejects_dry_run(tmp_path):
    old = fake_snapshot(tmp_path / "state", "RUN-20260916T114014Z")
    new = fake_snapshot(tmp_path / "app", "RUN-20261013T061700Z", dry_run=1)
    with pytest.raises(LiveStateError, match="live"):
        stage_live(new, old.parent)


def test_cost_ceiling_conservative_and_nonzero(app_config, monkeypatch):
    monkeypatch.setenv(app_config.llm.api_key_env_var, "fake-not-used")
    provider = DeepSeekProvider(app_config)
    try:
        assert provider._cost({"prompt_tokens": 1000, "completion_tokens": 200}) > 0
        evidence = {"repo": "example/repo", "github_repo_id": 123}
        reserved = provider._maximum_request_cost(evidence)
        assert reserved > 0
        budget = LLMBudget(max_calls=30, max_budget=reserved - 0.00001)
        assert not budget.can_call(next_call_max_cost=reserved)
        assert budget.can_call(next_call_max_cost=0)
    finally:
        provider.close()


def test_invalid_zero_pricing_fails_closed(app_config):
    modified_llm = replace(app_config.llm, cost_per_1k_input_tokens=0.0)
    modified_config = replace(app_config, llm=modified_llm)
    with pytest.raises(LLMProviderError, match="positive"):
        DeepSeekProvider(modified_config)


def test_workflow_requires_state_and_guards_live(repo_root):
    text = (repo_root / ".github/workflows/daily_discovery.yml").read_text()
    assert "continue-on-error: true" not in text
    assert "live_state_guard verify --state-dir ../state" in text
    assert "live_state_guard stage-live --state-dir ../state" in text
    assert "state remote SHA mismatch" in text
    assert "HIDDEN_GEMS_SCHEDULED_LIVE" in text


def test_manifest_failure_returns_nonzero_instead_of_success(tmp_path, canonical_config_tree,
                                                               monkeypatch, capsys):
    from hidden_gems import cli
    from hidden_gems.models import RunSummary

    class FakeGithub:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    tree = canonical_config_tree(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/hidden-gems")
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setattr("hidden_gems.github.client.GitHubClient", FakeGithub)
    monkeypatch.setattr(
        cli, "run_pipeline",
        lambda config, store, github, llm, context, **kwargs: RunSummary(
            run_id=context.run_id, started_at=context.started_at, dry_run=False,
            result="SUCCESS_NO_FINDINGS",
        ),
    )

    def broken_manifest(*args, **kwargs):
        raise OSError("simulated manifest write failure")

    monkeypatch.setattr(cli, "write_run_manifest", broken_manifest)
    rc = cli.main(["run", "--root", str(tree), "--live"])
    assert rc == 3
    assert "RESULT=FAILED_INTEGRITY" in capsys.readouterr().out


def test_finish_run_failure_is_not_swallowed(app_config, monkeypatch):
    from hidden_gems.orchestrator import run_pipeline
    from hidden_gems.models import RunContext
    from hidden_gems.llm.base import DisabledLLMProvider
    from hidden_gems.history.state_branch import StateIntegrityError
    import hidden_gems.orchestrator as orchestrator

    class BrokenHistory:
        def start_run(self, **kwargs):
            pass

        def finish_run(self, *args, **kwargs):
            raise OSError("simulated storage outage")

    def broken_discovery(*args, **kwargs):
        raise RuntimeError("simulated discovery failure")

    monkeypatch.setattr(orchestrator, "run_discovery", broken_discovery)
    monkeypatch.setattr(orchestrator, "write_run_artifacts",
                        lambda *args, **kwargs: ("unused.json", "unused.csv"))
    context = RunContext(
        run_id="RUN-20261013T061700Z",
        started_at=datetime(2026, 10, 13, 6, 17, tzinfo=timezone.utc),
        dry_run=True,
        config_version=app_config.config_version,
        score_version=app_config.scoring.score_version,
        prompt_version="TEST",
    )
    with pytest.raises(StateIntegrityError, match="could not persist"):
        run_pipeline(app_config, BrokenHistory(), object(), DisabledLLMProvider(), context)
