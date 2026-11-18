"""Offline adversarial checks for the fixed UTC window and its write boundaries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import yaml

from hidden_gems.github.client import GitHubClient
from hidden_gems.utc_live_guard import (
    BASELINE_MAIN_SHA as MAIN_SHA, PRODUCER_CUTOFF, REPOSITORY, UTCWindowDenied,
    WINDOW_START, require_live_window,
)

ISSUE_PATH = f"/repos/{REPOSITORY}/issues"


@pytest.fixture
def pilot_env():
    return {
        "HIDDEN_GEMS_V1_UTC_GUARD": "1",
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "schedule",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_SHA": MAIN_SHA,
        "LLM_ENABLED": "false",
    }


@pytest.mark.parametrize("instant", [
    WINDOW_START,
    WINDOW_START + timedelta(seconds=1),
    WINDOW_START + timedelta(days=3),
    PRODUCER_CUTOFF - timedelta(microseconds=1),
    datetime(2026, 11, 26, 23, 0, tzinfo=timezone(timedelta(hours=1)))
    - timedelta(microseconds=1),
])
def test_inclusive_start_and_strict_cutoff(pilot_env, instant):
    assert require_live_window("test", now=instant, environ=pilot_env)


@pytest.mark.parametrize("instant", [
    WINDOW_START - timedelta(microseconds=1),
    PRODUCER_CUTOFF,
    PRODUCER_CUTOFF + timedelta(microseconds=1),
    datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc),
    datetime(2026, 11, 28, 9, 0, tzinfo=timezone.utc),
])
def test_reject_outside_authorized_window(pilot_env, instant):
    with pytest.raises(UTCWindowDenied, match="OUTSIDE_PRODUCER_WINDOW"):
        require_live_window("test", now=instant, environ=pilot_env)


@pytest.mark.parametrize(("key", "bad"), [
    ("HIDDEN_GEMS_V1_UTC_GUARD", ""),
    ("GITHUB_ACTIONS", "false"),
    ("GITHUB_EVENT_NAME", "workflow_dispatch"),
    ("GITHUB_REPOSITORY", "other/repo"),
    ("GITHUB_REF", "refs/heads/feature"),
    ("GITHUB_RUN_ATTEMPT", "2"),
    ("GITHUB_SHA", "0" * 39),
    ("LLM_ENABLED", "true"),
])
def test_identity_fail_closed(pilot_env, key, bad):
    pilot_env[key] = bad
    with pytest.raises(UTCWindowDenied):
        require_live_window("test", now=WINDOW_START, environ=pilot_env)


def test_ambiguous_local_clock_rejected(pilot_env):
    with pytest.raises(UTCWindowDenied, match="NAIVE"):
        require_live_window("test", now=datetime(2026, 11, 20), environ=pilot_env)


def test_timezone_normalization(pilot_env):
    at = WINDOW_START.astimezone(timezone(timedelta(hours=2)))
    assert require_live_window("test", now=at, environ=pilot_env) == WINDOW_START


def _install(monkeypatch, env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_issue_http_post_inside_window_with_frozen_identity(monkeypatch, app_config, pilot_env):
    _install(monkeypatch, pilot_env)
    posts = []
    def respond(request):
        if request.method == "POST":
            posts.append(request)
        return httpx.Response(201, json={"number": 1})
    c = GitHubClient(app_config, transport=httpx.MockTransport(respond), clock=lambda: WINDOW_START)
    try:
        c.post_json(ISSUE_PATH, {"title": "x", "body": "fake"})
    finally:
        c.close()
    assert len(posts) == 1


@pytest.mark.parametrize("at", [WINDOW_START - timedelta(seconds=1), PRODUCER_CUTOFF])
def test_issue_post_blocked_without_transport_call(monkeypatch, app_config, pilot_env, at):
    _install(monkeypatch, pilot_env)
    calls = []
    def fake(request):
        calls.append(request)
        return httpx.Response(201, json={"number": 7})
    client = GitHubClient(app_config, transport=httpx.MockTransport(fake), clock=lambda: at)
    try:
        with pytest.raises(UTCWindowDenied):
            client.post_json(ISSUE_PATH, {"title": "fake"})
    finally:
        client.close()
    assert calls == []


def test_post_retry_rechecks_clock_after_500(monkeypatch, app_config, pilot_env):
    _install(monkeypatch, pilot_env)
    time_points = iter([PRODUCER_CUTOFF - timedelta(seconds=1), PRODUCER_CUTOFF])
    attempts = []
    def fake(request):
        attempts.append(request)
        return httpx.Response(500, json={"error": "transient"})
    client = GitHubClient(
        app_config,
        transport=httpx.MockTransport(fake),
        clock=lambda: next(time_points),
        sleep=lambda seconds: None,
    )
    try:
        with pytest.raises(UTCWindowDenied, match="OUTSIDE_PRODUCER_WINDOW"):
            client.post_json(ISSUE_PATH, {"title": "fake"})
    finally:
        client.close()
    assert len(attempts) == 1


def test_manual_dispatch_rejected_even_when_live_flag_true(monkeypatch, app_config, pilot_env):
    pilot_env["GITHUB_EVENT_NAME"] = "workflow_dispatch"
    _install(monkeypatch, pilot_env)
    calls = []
    client = GitHubClient(
        app_config,
        transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(201))[1]),
        clock=lambda: WINDOW_START,
    )
    try:
        with pytest.raises(UTCWindowDenied, match="EVENT_NOT_SCHEDULE"):
            client.post_json(ISSUE_PATH, {"title": "fake"})
    finally:
        client.close()
    assert calls == []


def test_loss_of_both_external_executors_does_not_bypass_inprocess_gate(
    monkeypatch, app_config, pilot_env,
):
    _install(monkeypatch, pilot_env)
    monkeypatch.setenv("CLOUD_WATCHDOG_AVAILABLE", "false")
    monkeypatch.setenv("LINUX_EXECUTOR_AVAILABLE", "false")
    client = GitHubClient(
        app_config,
        transport=httpx.MockTransport(lambda req: pytest.fail("HTTP transport reached")),
        clock=lambda: PRODUCER_CUTOFF,
    )
    try:
        with pytest.raises(UTCWindowDenied):
            client.post_json(ISSUE_PATH, {"title": "fake"})
    finally:
        client.close()


def test_http_read_only_is_allowed_after_end(monkeypatch, app_config, pilot_env):
    _install(monkeypatch, pilot_env)
    called = []
    client = GitHubClient(
        app_config,
        transport=httpx.MockTransport(
            lambda req: (called.append(req), httpx.Response(200, json=[]))[1]
        ),
        clock=lambda: PRODUCER_CUTOFF,
    )
    try:
        assert client.get_json(f"/repos/{REPOSITORY}/issues") == []
    finally:
        client.close()
    assert len(called) == 1


def test_workflow_guards_before_live_issues_and_state_push(repo_root):
    wf = (repo_root / ".github/workflows/daily_discovery.yml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(wf)
    job = parsed["jobs"]["discover"]
    assert job["timeout-minutes"] <= 45
    assert job["env"]["HIDDEN_GEMS_V1_UTC_GUARD"] == "1"
    steps = {step["name"]: step for step in job["steps"]}
    assert steps["Checkout main"]["with"]["ref"] == "main"
    mode = steps["Resolve run mode"]["run"]
    assert 'if [ "$dry" = "false" ]; then' in mode
    assert "utc_live_guard --phase mode" in mode
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in mode
    assert "utc_live_guard --phase pre-run" in steps["Run discovery"]["run"]
    stage = steps["Stage verified live snapshot and restorable backup"]["run"]
    assert stage.index("utc_live_guard --phase pre-stage") < stage.index("stage-live")
    persist = steps["Persist state branch"]["run"]
    assert persist.index("utc_live_guard --phase pre-state") < persist.index("git add")
    assert persist.index("utc_live_guard --phase pre-push") < persist.index("timeout 60s git push origin HEAD:state")
    assert wf.count("git push origin HEAD:state") == 1


def test_no_live_publishing_after_backup_is_down_at_deadline(pilot_env):
    # Backup availability is deliberately not a premise of the producer gate.
    for phase in ["mode", "pre-run", "issue-post", "pre-stage", "pre-state", "pre-push"]:
        with pytest.raises(UTCWindowDenied):
            require_live_window(phase, now=PRODUCER_CUTOFF, environ=pilot_env)


def test_guard_does_not_contain_activation_logic(repo_root):
    source = (repo_root / "src/hidden_gems/utc_live_guard.py").read_text(encoding="utf-8")
    assert "PATCH" not in source and "post_json" not in source
    assert "LIVE_ENABLED=true" not in source


def test_new_deployment_main_sha_is_allowed_with_unchanged_scoring(pilot_env):
    # Adding the UTC guard necessarily produces a new main commit.
    pilot_env["GITHUB_SHA"] = "e" * 40
    assert require_live_window("mode", now=WINDOW_START, environ=pilot_env)


def test_score_hash_drift_denied_without_writing_files(monkeypatch, pilot_env):
    from pathlib import Path
    real = Path.read_bytes
    def tamper(self):
        if str(self).replace("\\", "/").endswith("/config/scoring.yml"):
            return b"ATTACK_CONFIG_MOCK"
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", tamper)
    with pytest.raises(UTCWindowDenied, match="SCORING_SHA_DRIFT"):
        require_live_window("mode", now=WINDOW_START, environ=pilot_env)
