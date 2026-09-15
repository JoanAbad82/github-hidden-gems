"""Hotfix R1 regression: the report header describes selection, not threshold count."""

from __future__ import annotations

from datetime import datetime, timezone

from hidden_gems.models import (
    HiddenGemScore,
    NotificationDecision,
    RepositoryRef,
    RunSummary,
    SelectedFinding,
)
from hidden_gems.reporting.markdown import build_report


def test_report_header_says_how_many_repositories_were_selected(app_config):
    repo = RepositoryRef.from_full_name("acme-labs/selected", 9801)
    score = HiddenGemScore(
        relevance=20,
        quality=20,
        activity=15,
        visibility=10,
        novelty=3,
        originality=2,
        intersection=0,
        total=70,
        confidence="MEDIUM",
    )
    finding = SelectedFinding(
        repo=repo,
        score=score,
        decision=NotificationDecision(
            notify=True,
            notification_type="NEW_DISCOVERY",
            trigger_fingerprint="FIRST_DISCOVERY:9801:HIDDEN_GEM_SCORE_V1",
            previous_score=None,
            current_score=70,
        ),
        status="NEW_DISCOVERY",
        rank=1,
    )
    started = datetime(2026, 9, 15, 20, 26, tzinfo=timezone.utc)
    summary = RunSummary(
        run_id="RUN-HOTFIX-R1-REPORT",
        result="SUCCESS",
        started_at=started,
        finished_at=started,
        dry_run=True,
    )

    report = build_report([finding], summary, config=app_config)

    assert "1 repository selected for this report." in report
    assert "reached the notification threshold" not in report
