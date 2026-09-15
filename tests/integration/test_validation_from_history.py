"""Task 18: cycle evidence must be reconstructed from the canonical history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hidden_gems.models import RepositoryRef
from hidden_gems.validation.acceptance import (
    STATUS_ACCEPTED,
    STATUS_NOT_ACCEPTED,
    STATUS_PENDING,
    NotificationGrade,
    cycles_from_history,
    evaluate_acceptance,
    render_acceptance_markdown,
)

HistoryStore = pytest.importorskip(
    "hidden_gems.history.database", reason="Task 2 (SQLite history) not available yet"
).HistoryStore

START = datetime(2026, 9, 1, 6, 17, tzinfo=timezone.utc)


def _repo(index: int) -> RepositoryRef:
    owner = "history-labs"
    name = f"tool-{index}"
    return RepositoryRef(
        github_repo_id=5000 + index,
        owner=owner,
        name=name,
        full_name=f"{owner}/{name}",
        html_url=f"https://github.com/{owner}/{name}",
    )


def _seed_cycle(
    store,
    index: int,
    *,
    result: str = "SUCCESS",
    issue_number: int | None,
    dry_run: bool = False,
    score: int = 78,
    usage: dict | None = None,
) -> None:
    moment = START + timedelta(days=index)
    run_id = f"RUN-{index:02d}"
    repo = _repo(index)
    store.start_run(
        run_id=run_id,
        started_at=moment,
        dry_run=dry_run,
        config_version="1.0.0",
        score_version="HIDDEN_GEM_SCORE_V1",
        prompt_version="DEEP_ANALYZER_PROMPT_V1",
        budgets={"max_raw_candidates": 1000, "max_light_analysis": 200},
    )
    store.upsert_repository(repo, stars=12, seen_at=moment)
    if issue_number is not None:
        store.save_notification(
            repo.github_repo_id,
            fingerprint=f"FIRST_DISCOVERY:{repo.github_repo_id}:HIDDEN_GEM_SCORE_V1",
            notification_type="NEW_DISCOVERY",
            score=score,
            notified_at=moment,
            run_id=run_id,
            issue_number=issue_number,
        )
    store.finish_run(
        run_id,
        result=result,
        finished_at=moment + timedelta(minutes=5),
        usage=usage or {"calls_made": 2, "max_calls": 30},
        issue_number=issue_number,
    )


def _store_with_seven_cycles(tmp_path, **kwargs):
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    for index in range(7):
        _seed_cycle(store, index, issue_number=100 + index, **kwargs)
    return store


def test_cycles_from_history_is_pending_without_human_gradings(tmp_path):
    store = _store_with_seven_cycles(tmp_path)
    try:
        cycles = cycles_from_history(store)
        assert [cycle.run_id for cycle in cycles] == [f"RUN-{i:02d}" for i in range(6, -1, -1)]
        report = evaluate_acceptance(cycles)
        assert report.status == STATUS_PENDING
        assert report.metrics["ungraded_notifications"] == 7
    finally:
        store.close()


def test_cycles_from_history_accepts_when_every_notification_is_graded(tmp_path):
    store = _store_with_seven_cycles(tmp_path)
    gradings = {
        5000 + index: NotificationGrade(
            github_repo_id=5000 + index, grade="GOOD", score=78, note="useful"
        )
        for index in range(7)
    }
    try:
        report = evaluate_acceptance(cycles_from_history(store, gradings=gradings))
        assert report.status == STATUS_ACCEPTED
        assert report.metrics["useful_discovery_rate"] == 1.0
        markdown = render_acceptance_markdown(report)
        assert markdown.count("STATUS=") == 1
    finally:
        store.close()


def test_cycles_from_history_notices_a_duplicated_issue_number(tmp_path):
    store = HistoryStore.open(tmp_path / "history.sqlite3")
    try:
        for index in range(7):
            # Two different runs published notifications pointing at Issue 555.
            _seed_cycle(store, index, issue_number=555 if index in (0, 1) else 100 + index)
        gradings = {
            5000 + index: NotificationGrade(github_repo_id=5000 + index, grade="GOOD", score=78)
            for index in range(7)
        }
        report = evaluate_acceptance(cycles_from_history(store, gradings=gradings))
        assert report.status == STATUS_NOT_ACCEPTED
        assert report.metrics["issues_created"] == 7
        assert any("duplicate" in reason.lower() for reason in report.blocking)
    finally:
        store.close()


def test_cycles_from_history_flags_budget_overrun_from_usage(tmp_path):
    store = _store_with_seven_cycles(tmp_path, usage={"calls_made": 31, "max_calls": 30})
    gradings = {
        5000 + index: NotificationGrade(github_repo_id=5000 + index, grade="GOOD", score=78)
        for index in range(7)
    }
    try:
        report = evaluate_acceptance(cycles_from_history(store, gradings=gradings))
        assert report.status == STATUS_NOT_ACCEPTED
        assert any("budget" in reason.lower() for reason in report.blocking)
    finally:
        store.close()
