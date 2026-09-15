"""Task 17/18 CLI surface: reduced-budget controlled-live gate + acceptance gate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hidden_gems.cli import (
    CONTROLLED_LIVE_LIMITS,
    _build_parser,
    _want_dry_run,
    apply_run_overrides,
    main,
)
from hidden_gems.config import ConfigError
from hidden_gems.models import RepositoryRef
from hidden_gems.validation.acceptance import STATUS_PENDING

START = datetime(2026, 9, 1, 6, 17, tzinfo=timezone.utc)


def _args(argv):
    return _build_parser().parse_args(argv)


def test_controlled_live_preset_only_lowers_budgets(app_config):
    args = _args(["run", "--controlled-live"])
    lowered = apply_run_overrides(app_config, args)
    assert lowered.limits.run_budgets["max_raw_candidates"] == CONTROLLED_LIVE_LIMITS["max_raw_candidates"]
    assert lowered.limits.run_budgets["max_light_analysis"] == CONTROLLED_LIVE_LIMITS["max_light_analysis"]
    assert lowered.limits.run_budgets["max_deep_analysis"] == CONTROLLED_LIVE_LIMITS["max_deep_analysis"]
    assert lowered.llm.max_llm_calls_per_run == CONTROLLED_LIVE_LIMITS["max_llm_calls_per_run"]
    for key, value in CONTROLLED_LIVE_LIMITS.items():
        if key in app_config.limits.run_budgets:
            assert value <= app_config.limits.run_budgets[key]


def test_controlled_live_forces_dry_run_even_with_live_flag():
    args = _args(["run", "--controlled-live", "--live"])
    assert _want_dry_run(args) is True


def test_plain_run_still_defaults_to_dry_run():
    assert _want_dry_run(_args(["run"])) is True
    assert _want_dry_run(_args(["run", "--live"])) is False


def test_budget_override_may_only_lower_the_configured_limit(app_config):
    args = _args(["run", "--max-light", "5000"])
    with pytest.raises(ConfigError, match="lower"):
        apply_run_overrides(app_config, args)


def test_budget_override_lowers_one_budget(app_config):
    args = _args(["run", "--max-deep", "2"])
    lowered = apply_run_overrides(app_config, args)
    assert lowered.limits.run_budgets["max_deep_analysis"] == 2
    assert lowered.limits.run_budgets["max_light_analysis"] == app_config.limits.run_budgets["max_light_analysis"]


def _seed_history(db_path, *, cycles: int = 3) -> None:
    from hidden_gems.history.database import HistoryStore

    store = HistoryStore.open(db_path)
    try:
        for index in range(cycles):
            moment = START + timedelta(days=index)
            run_id = f"RUN-{index:02d}"
            repo = RepositoryRef.from_full_name(f"cli-labs/tool-{index}", 6000 + index)
            store.start_run(
                run_id=run_id,
                started_at=moment,
                dry_run=False,
                config_version="1.0.0",
                score_version="HIDDEN_GEM_SCORE_V1",
                prompt_version="DEEP_ANALYZER_PROMPT_V1",
                budgets={"max_raw_candidates": 1000},
            )
            store.upsert_repository(repo, stars=12, seen_at=moment)
            store.save_notification(
                repo.github_repo_id,
                fingerprint=f"FIRST_DISCOVERY:{repo.github_repo_id}:HIDDEN_GEM_SCORE_V1",
                notification_type="NEW_DISCOVERY",
                score=78,
                notified_at=moment,
                run_id=run_id,
                issue_number=100 + index,
            )
            store.finish_run(
                run_id,
                result="SUCCESS",
                finished_at=moment + timedelta(minutes=3),
                usage={"calls_made": 1, "max_calls": 30},
                issue_number=100 + index,
            )
    finally:
        store.close()


def test_validation_status_is_read_only_and_pending_without_seven_cycles(
    repo_root, tmp_path, capsys
):
    db_path = tmp_path / "history.sqlite3"
    _seed_history(db_path, cycles=3)
    before = db_path.read_bytes()

    exit_code = main(["validation-status", "--root", str(repo_root), "--db", str(db_path)])
    output = capsys.readouterr().out

    assert f"STATUS={STATUS_PENDING}" in output
    assert "RESULT=VALIDATION_PENDING" in output
    assert exit_code == 2
    assert db_path.read_bytes() == before, "the acceptance gate must not write to history"


def test_validation_status_rejects_a_missing_database(repo_root, tmp_path, capsys):
    missing = tmp_path / "nope.sqlite3"
    exit_code = main(["validation-status", "--root", str(repo_root), "--db", str(missing)])
    output = capsys.readouterr().out
    assert "RESULT=FAILED_INTEGRITY" in output
    assert exit_code == 3
