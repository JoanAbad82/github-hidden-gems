"""The run must leave a `state_manifest.json` next to the database (Task 14)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import jsonschema
import pytest

from hidden_gems.history.state_branch import (
    MANIFEST_SCHEMA_VERSION,
    write_state_manifest,
)

HistoryStore = pytest.importorskip(
    "hidden_gems.history.database", reason="Task 2 (SQLite history) not available yet"
).HistoryStore


def _db(tmp_path):
    db_path = tmp_path / "state" / "history.sqlite3"
    store = HistoryStore.open(db_path)
    try:
        store.migrate()
    finally:
        store.close()
    return db_path


def test_manifest_matches_the_frozen_schema(repo_root, tmp_path):
    db_path = _db(tmp_path)
    moment = datetime(2026, 9, 15, 6, 17, tzinfo=timezone.utc)

    manifest_path = write_state_manifest(
        db_path,
        run_id="RUN-20260915T061700Z",
        run_result="SUCCESS",
        report_state="REPORT_PUBLISHED",
        report_fingerprint="REPORT:deadbeef",
        moment=moment,
    )

    assert manifest_path.name == "state_manifest.json"
    assert manifest_path.parent == db_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads((repo_root / "state_manifest.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(manifest)
    assert manifest["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert manifest["last_run_id"] == "RUN-20260915T061700Z"
    assert manifest["db_sha256"] == hashlib.sha256(db_path.read_bytes()).hexdigest()
    assert manifest["db_bytes"] == db_path.stat().st_size
    assert manifest["report_state"] == "REPORT_PUBLISHED"
    assert manifest["state_timestamp"].startswith("2026-09-15T06:17")


def test_manifest_never_contains_secret_like_values(repo_root, tmp_path, monkeypatch):
    db_path = _db(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "a" * 36)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-" + "b" * 32)

    manifest_path = write_state_manifest(db_path, run_id="RUN-SECRETS", run_result="SUCCESS")
    text = manifest_path.read_text(encoding="utf-8")

    assert "ghp_" not in text and "sk-" not in text
    assert set(json.loads(text)) <= set(
        json.loads((repo_root / "state_manifest.schema.json").read_text(encoding="utf-8"))[
            "properties"
        ]
    )


def test_manifest_keeps_idle_state_without_publication(tmp_path):
    db_path = _db(tmp_path)
    manifest_path = write_state_manifest(db_path, run_id="RUN-DRY", run_result="SUCCESS_NO_FINDINGS")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["report_state"] == "IDLE"
    assert manifest["last_run_result"] == "SUCCESS_NO_FINDINGS"
    assert manifest["pending_report_fingerprint"] is None


def test_cli_helper_writes_a_published_manifest_only_for_live_runs(tmp_path):
    from hidden_gems.cli import write_run_manifest
    from hidden_gems.models import IssueRef, RunSummary

    db_path = _db(tmp_path)
    summary = RunSummary(
        run_id="RUN-LIVE",
        result="SUCCESS",
        started_at=datetime(2026, 9, 15, 6, 17, tzinfo=timezone.utc),
        dry_run=False,
        counts={"reported": 1},
        report_fingerprint="REPORT:abc123",
        issue=IssueRef(number=7, url="https://github.com/o/r/issues/7", fingerprint="REPORT:abc123"),
    )
    manifest_path = write_run_manifest(db_path, summary)
    assert manifest_path is not None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["report_state"] == "REPORT_PUBLISHED"
    assert manifest["last_run_id"] == "RUN-LIVE"

    dry_summary = RunSummary(
        run_id="RUN-DRY",
        result="SUCCESS",
        started_at=datetime(2026, 9, 15, 6, 17, tzinfo=timezone.utc),
        dry_run=True,
    )
    assert write_run_manifest(db_path, dry_summary) is None
