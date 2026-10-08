"""CLI contract tests (Task 13): one terminal RESULT line per command."""

from __future__ import annotations

from pathlib import Path

import pytest

from hidden_gems import cli
from hidden_gems.models import RunSummary


class FakeClient:
    def __init__(self, *args, **kwargs) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def tree(tmp_path: Path, canonical_config_tree):
    return canonical_config_tree(tmp_path)


def test_migrate_then_db_check_succeed(tree: Path, capsys):
    db = tree / "state" / "history.sqlite3"
    assert cli.main(["migrate", "--root", str(tree), "--db", str(db)]) == 0
    assert "RESULT=DB_MIGRATED" in capsys.readouterr().out
    assert cli.main(["db-check", "--root", str(tree), "--db", str(db)]) == 0
    assert "RESULT=DB_VALID" in capsys.readouterr().out


def test_db_check_reports_missing_database(tree: Path, capsys):
    missing = tree / "state" / "absent.sqlite3"
    assert cli.main(["db-check", "--root", str(tree), "--db", str(missing)]) == 3
    assert "RESULT=FAILED_INTEGRITY" in capsys.readouterr().out


def test_global_and_subcommand_root_are_both_accepted(tree: Path, capsys):
    assert cli.main(["--root", str(tree), "validate-config"]) == 0
    assert "RESULT=CONFIG_VALID" in capsys.readouterr().out


def _patch_pipeline(monkeypatch, captured: dict) -> None:
    def fake_run_pipeline(config, history, github, llm, context, *, publisher=None, **kwargs):
        captured["dry_run"] = context.dry_run
        captured["publisher"] = publisher
        return RunSummary(
            run_id=context.run_id,
            result="SUCCESS_NO_FINDINGS",
            started_at=context.started_at,
            dry_run=context.dry_run,
        )

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("hidden_gems.github.client.GitHubClient", FakeClient)


def test_run_defaults_to_dry_run_without_publisher(monkeypatch, tree: Path, capsys):
    captured: dict = {}
    _patch_pipeline(monkeypatch, captured)
    db = tree / "state" / "history.sqlite3"
    assert cli.main(["run", "--root", str(tree), "--db", str(db)]) == 0
    assert captured["dry_run"] is True
    assert captured["publisher"] is None
    assert "RESULT=SUCCESS_NO_FINDINGS" in capsys.readouterr().out


def test_dry_run_env_flag_forces_dry_run(monkeypatch, tree: Path):
    captured: dict = {}
    _patch_pipeline(monkeypatch, captured)
    monkeypatch.setenv("DRY_RUN", "true")
    db = tree / "state" / "history.sqlite3"
    assert cli.main(["run", "--root", str(tree), "--db", str(db), "--live"]) == 0
    assert captured["dry_run"] is True
    assert captured["publisher"] is None


def test_live_run_requires_a_repository(monkeypatch, tree: Path, capsys):
    captured: dict = {}
    _patch_pipeline(monkeypatch, captured)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    db = tree / "state" / "history.sqlite3"
    assert cli.main(["run", "--root", str(tree), "--db", str(db), "--live"]) == 2
    assert "RESULT=FAILED_CONFIGURATION" in capsys.readouterr().out


def test_live_run_creates_a_publisher(monkeypatch, tree: Path):
    captured: dict = {}
    _patch_pipeline(monkeypatch, captured)
    monkeypatch.delenv("DRY_RUN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/hidden-gems")
    db = tree / "state" / "history.sqlite3"
    assert cli.main(["run", "--root", str(tree), "--db", str(db), "--live"]) == 0
    assert captured["dry_run"] is False
    assert captured["publisher"] is not None


def test_validate_config_failure_exit_code(tmp_path: Path, canonical_config_tree, capsys):
    tree = canonical_config_tree(tmp_path, extra_limits={"max_lmm_calls": 3})
    assert cli.main(["validate-config", "--root", str(tree)]) == 2
    assert "RESULT=FAILED_CONFIGURATION" in capsys.readouterr().out


def test_default_database_path_lives_under_the_state_directory(monkeypatch, tree: Path):
    monkeypatch.delenv("HIDDEN_GEMS_DB", raising=False)
    assert cli.main(["migrate", "--root", str(tree)]) == 0
    assert (tree / "state" / "history.sqlite3").is_file()


def test_llm_enabled_env_var_switches_enrichment_on(monkeypatch, tree: Path):
    captured: dict = {}
    _patch_pipeline(monkeypatch, captured)

    def fake_build_llm(config, store, context, enabled):
        captured["llm_enabled"] = enabled
        return None

    monkeypatch.setattr(cli, "_build_llm", fake_build_llm)
    monkeypatch.setenv("LLM_ENABLED", "true")
    db = tree / "state" / "history.sqlite3"
    assert cli.main(["run", "--root", str(tree), "--db", str(db)]) == 0
    assert captured["llm_enabled"] is True

    monkeypatch.setenv("LLM_ENABLED", "false")
    assert cli.main(["run", "--root", str(tree), "--db", str(db)]) == 0
    assert captured["llm_enabled"] is False



def test_opt_in_local_trace_records_run_and_summary(monkeypatch, tree: Path, tmp_path: Path):
    from hidden_gems.local_trace import summarize_trace

    captured: dict = {}
    _patch_pipeline(monkeypatch, captured)
    trace = tmp_path / "run-trace.jsonl"
    monkeypatch.setenv("HIDDEN_GEMS_TRACE_JSONL", str(trace))
    monkeypatch.setenv("LLM_ENABLED", "false")
    db = tree / "state" / "history.sqlite3"

    assert cli.main(["run", "--root", str(tree), "--db", str(db), "--controlled-live"]) == 0

    summary = summarize_trace(trace)
    assert summary["event_counts"] == {"RUN_FINISHED": 1, "RUN_STARTED": 1}
    assert summary["result_counts"] == {"SUCCESS_NO_FINDINGS": 1}
    assert summary["safety_summary"]["dry_run_starts"] == 1
    assert summary["safety_summary"]["controlled_live_starts"] == 1
    assert summary["safety_summary"]["llm_enabled_starts"] == 0
    assert summary["started_without_finish"] == []


def test_trace_summary_cli_writes_deterministic_summary(tmp_path: Path, capsys):
    from hidden_gems.local_trace import append_trace_event

    trace = tmp_path / "trace.jsonl"
    output = tmp_path / "summary.json"
    append_trace_event(
        trace,
        event_type="RUN_STARTED",
        run_id="RUN-CLI",
        recorded_at="2026-10-08T16:00:00+00:00",
        payload={
            "dry_run": True,
            "llm_enabled": False,
            "controlled_live": False,
            "live_requested": False,
        },
    )

    assert cli.main(
        [
            "trace-summary",
            "--trace",
            str(trace),
            "--output",
            str(output),
        ]
    ) == 0
    rendered = capsys.readouterr().out
    assert "RESULT=TRACE_SUMMARY_SUCCESS" in rendered
    assert output.exists()
    payload = __import__("json").loads(output.read_text(encoding="utf-8"))
    assert payload["run_ids"] == ["RUN-CLI"]
    assert payload["started_without_finish"] == ["RUN-CLI"]
