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
                  dry_run: int = 0, previous_db: Path | None = None):
    import shutil
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "history.sqlite3"
    if previous_db is not None:
        shutil.copyfile(previous_db, db_path)
    connection = sqlite3.connect(db_path)
    try:
        if previous_db is None:
            connection.execute(
                "CREATE TABLE runs (run_id TEXT PRIMARY KEY, started_at TEXT, "
                "result TEXT, dry_run INTEGER, report_state TEXT, "
                "issue_number INTEGER, issue_url TEXT)"
            )
            connection.execute(
                "CREATE TABLE notifications (notification_id INTEGER PRIMARY KEY, "
                "github_repo_id INTEGER, run_id TEXT, fingerprint TEXT, score INTEGER)"
            )
        connection.execute(
            "INSERT INTO runs (run_id,started_at,result,dry_run,report_state) VALUES (?,?,?,?,?)",
            (run_id, when, "SUCCESS", dry_run, "NONE"),
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
                           when="2026-10-13T06:17:00Z", previous_db=old)
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
                          when="2026-10-13T06:17:00Z", previous_db=old)
    stage_live(newer, old.parent)
    archive = next((old.parent / "backups").glob("*.sqlite3.gz"))
    archive.write_bytes(b"not gzip")
    with pytest.raises((OSError, EOFError, LiveStateError)):
        verify_state(old.parent)


def test_stage_live_rejects_dry_run(tmp_path):
    old = fake_snapshot(tmp_path / "state", "RUN-20260916T114014Z")
    new = fake_snapshot(tmp_path / "app", "RUN-20261013T061700Z", dry_run=1,
                        previous_db=old)
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


def _b1_evidence():
    return {
        "repo": "acme-labs/flowkit",
        "github_repo_id": 501,
        "repository": {
            "full_name": "acme-labs/flowkit",
            "github_repo_id": 501,
            "html_url": "https://github.com/acme-labs/flowkit",
        },
        "observed": {"source_file_count": 3},
    }


def test_b1_retry_reserves_feedback_prompt_cost(app_config):
    """A retry with a larger prompt must be gated at its actual upper estimate."""
    import httpx
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "not json"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        probe = DeepSeekProvider(app_config, api_key="OFFLINE", client=client)
        try:
            first_ceiling = probe._maximum_request_cost(_b1_evidence())
            retry_ceiling = probe._maximum_request_cost(
                _b1_evidence(),
                validation_feedback="schema violation at evidence/observed/0; " + "x" * 220,
            )
            assert retry_ceiling > first_ceiling
        finally:
            probe.close()
        budget = LLMBudget(max_calls=5, max_budget=first_ceiling + 0.00005)
        provider = DeepSeekProvider(
            app_config, api_key="OFFLINE", client=client, budget=budget,
        )
        answer = provider.analyze_repository(_b1_evidence())
        assert answer.status == "LLM_FAILED"
        assert len(calls) == 1
        assert budget.calls_made == 1


def test_b1_network_errors_consume_call_cap_and_projected_spend(app_config):
    """A failed HTTP request may be billable; do not allow unlimited retries."""
    import httpx
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError("offline injected failure", request=request)

    budget = LLMBudget(max_calls=1, max_budget=1.0)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = DeepSeekProvider(
            app_config, api_key="OFFLINE", client=client, budget=budget,
        )
        result = provider.analyze_repository(_b1_evidence())
        assert result.status == "LLM_FAILED"
        assert len(calls) == 1
        assert budget.calls_made == 1
        assert budget.cost > 0
        with pytest.raises(LLMProviderError, match="budget"):
            provider.analyze_repository(_b1_evidence())
        assert len(calls) == 1


def test_b1_valid_response_without_usage_reserves_nonzero_cost(app_config):
    """Missing usage telemetry cannot be interpreted as zero-dollar billing."""
    import httpx
    import json
    calls = []

    content = {
        "summary": "A small workflow runtime.",
        "why_interesting": "Compact and tested.",
        "relevance_suggestion": 11,
        "originality_suggestion": 2,
        "confidence": "MEDIUM",
        "risks": [],
        "evidence": {"observed": ["example"], "inferred": [], "unknown": []},
    }

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    budget = LLMBudget(max_calls=2, max_budget=1.0)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = DeepSeekProvider(
            app_config, api_key="OFFLINE", client=client, budget=budget,
        )
        expected = provider._maximum_request_cost(_b1_evidence())
        answer = provider.analyze_repository(_b1_evidence())
        assert answer.status == "OK"
        assert budget.calls_made == 1
        assert budget.cost >= expected > 0
        assert budget.snapshot()["reasons"]["USAGE_UNKNOWN"] == 1


def test_b1_http_error_and_nonjson_response_are_not_free(app_config):
    import httpx
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, text="not json")

    budget = LLMBudget(max_calls=2, max_budget=1.0)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = DeepSeekProvider(
            app_config, api_key="OFFLINE", client=client, budget=budget,
        )
        result = provider.analyze_repository(_b1_evidence())
        assert result.status == "LLM_FAILED"
        assert len(calls) == 2
        assert budget.calls_made == 2
        assert budget.cost > 0



@pytest.mark.parametrize("usage", [
    {"prompt_tokens": 0, "completion_tokens": 0},
    {"prompt_tokens": -1, "completion_tokens": 5},
    {"prompt_tokens": "invalid", "completion_tokens": 10},
])
def test_b1_malformed_or_zero_usage_reserves_projection(app_config, usage):
    import httpx
    import json
    content = {
        "summary": "Offline example",
        "why_interesting": "Useful pattern",
        "relevance_suggestion": 5,
        "originality_suggestion": 2,
        "confidence": "MEDIUM",
        "risks": [],
        "evidence": {"observed": ["some file"], "inferred": [], "unknown": []},
    }

    def handler(request):
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}],
                  "usage": usage},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        budget = LLMBudget(max_calls=1, max_budget=1.0)
        provider = DeepSeekProvider(
            app_config, api_key="OFFLINE", client=client, budget=budget,
        )
        bound = provider._maximum_request_cost(_b1_evidence())
        result = provider.analyze_repository(_b1_evidence())
        assert result.status == "OK"
        assert budget.calls_made == 1
        assert budget.cost >= bound > 0
        assert budget.snapshot()["reasons"]["USAGE_UNKNOWN"] == 1


def _continuity_fixture(tmp_path):
    old = fake_snapshot(tmp_path / "state", "RUN-20260916T114014Z")
    with sqlite3.connect(old) as db:
        db.execute(
            "INSERT INTO notifications (notification_id,github_repo_id,run_id,fingerprint,score) "
            "VALUES (1,42,'RUN-20260916T114014Z','FIRST_DISCOVERY:42',73)"
        )
    write_state_manifest(old, run_id="RUN-20260916T114014Z", run_result="SUCCESS")
    new = fake_snapshot(
        tmp_path / "app", "RUN-20261014T061700Z",
        when="2026-10-14T06:17:00Z", previous_db=old,
    )
    return old, new


def _assert_stage_rejected_without_state_damage(old, new, phrase):
    before_hash = hashlib.sha256(old.read_bytes()).hexdigest()
    before_manifest = (old.parent / "state_manifest.json").read_bytes()
    with pytest.raises(LiveStateError, match=phrase):
        stage_live(new, old.parent)
    assert hashlib.sha256(old.read_bytes()).hexdigest() == before_hash
    assert (old.parent / "state_manifest.json").read_bytes() == before_manifest
    assert not list((old.parent / "backups").glob("*.gz")) if (old.parent / "backups").exists() else True


def test_b4_rejects_missing_prior_runs_even_with_valid_new_manifest(tmp_path):
    old, new = _continuity_fixture(tmp_path)
    with sqlite3.connect(new) as db:
        db.execute("DELETE FROM runs WHERE run_id='RUN-20260916T114014Z'")
    write_state_manifest(new, run_id="RUN-20261014T061700Z", run_result="SUCCESS")
    assert verify_state(new.parent, require_live=True)
    _assert_stage_rejected_without_state_damage(old, new, "lost 1 runs")


def test_b4_rejects_missing_prior_notifications(tmp_path):
    old, new = _continuity_fixture(tmp_path)
    with sqlite3.connect(new) as db:
        db.execute("DELETE FROM notifications WHERE notification_id=1")
    write_state_manifest(new, run_id="RUN-20261014T061700Z", run_result="SUCCESS")
    _assert_stage_rejected_without_state_damage(old, new, "lost 0 runs and 1 notifications")


def test_b4_rejects_rewritten_prior_runs(tmp_path):
    old, new = _continuity_fixture(tmp_path)
    with sqlite3.connect(new) as db:
        db.execute("UPDATE runs SET result='FAILED' WHERE run_id='RUN-20260916T114014Z'")
    write_state_manifest(new, run_id="RUN-20261014T061700Z", run_result="SUCCESS")
    _assert_stage_rejected_without_state_damage(old, new, "previous run modified")


def test_b4_rejects_modified_prior_notification(tmp_path):
    old, new = _continuity_fixture(tmp_path)
    with sqlite3.connect(new) as db:
        db.execute("UPDATE notifications SET score=1 WHERE notification_id=1")
    write_state_manifest(new, run_id="RUN-20261014T061700Z", run_result="SUCCESS")
    _assert_stage_rejected_without_state_damage(old, new, "prior notification modified")


def test_b4_rejects_extra_unexpected_run(tmp_path):
    old, new = _continuity_fixture(tmp_path)
    with sqlite3.connect(new) as db:
        db.execute(
            "INSERT INTO runs (run_id,started_at,result,dry_run) VALUES "
            "('RUN-20261014T061701Z','2026-10-14T06:17:01Z','SUCCESS',0)"
        )
    write_state_manifest(new, run_id="RUN-20261014T061701Z", run_result="SUCCESS")
    _assert_stage_rejected_without_state_damage(old, new, "expected exactly one new run")


def test_b4_allows_append_only_runs_and_new_notifications(tmp_path):
    old, new = _continuity_fixture(tmp_path)
    with sqlite3.connect(new) as db:
        db.execute(
            "INSERT INTO notifications (notification_id,github_repo_id,run_id,fingerprint,score) "
            "VALUES (2,43,'RUN-20261014T061700Z','FIRST_DISCOVERY:43',76)"
        )
    write_state_manifest(new, run_id="RUN-20261014T061700Z", run_result="SUCCESS")
    outcome = stage_live(new, old.parent)
    assert outcome["run_id"] == "RUN-20261014T061700Z"
    with sqlite3.connect(old) as db:
        assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 2


def test_b4_allows_pending_report_becoming_published(tmp_path):
    old, new = _continuity_fixture(tmp_path)
    with sqlite3.connect(old) as db:
        db.execute(
            "UPDATE runs SET report_state='PENDING_REPORT' "
            "WHERE run_id='RUN-20260916T114014Z'"
        )
    write_state_manifest(old, run_id="RUN-20260916T114014Z", run_result="SUCCESS")
    with sqlite3.connect(new) as db:
        db.execute(
            "UPDATE runs SET report_state='PENDING_REPORT' "
            "WHERE run_id='RUN-20260916T114014Z'"
        )
        db.execute(
            "UPDATE runs SET report_state='REPORT_PUBLISHED', issue_number=36, "
            "issue_url='https://github.com/example/repo/issues/36' "
            "WHERE run_id='RUN-20260916T114014Z'"
        )
    write_state_manifest(new, run_id="RUN-20261014T061700Z", run_result="SUCCESS")
    outcome = stage_live(new, old.parent)
    assert outcome["run_id"] == "RUN-20261014T061700Z"
