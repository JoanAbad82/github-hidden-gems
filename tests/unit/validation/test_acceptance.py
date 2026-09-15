"""Task 18: the seven-cycle V1 acceptance gate must be evidence-driven.

The gate may only return `V1_ACCEPTED` when seven consecutive real daily cycles
provide the required evidence. Missing days, ungraded notifications or dry-run
only cycles must never be papered over: they keep the gate pending or fail it.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from hidden_gems.validation.acceptance import (
    STATUS_ACCEPTED,
    STATUS_NOT_ACCEPTED,
    STATUS_PENDING,
    CycleEvidence,
    NotificationGrade,
    evaluate_acceptance,
    render_acceptance_markdown,
)

START = date(2026, 9, 1)


def _graded(cycle_index: int, grades: tuple[str, ...], *, score: int = 78) -> tuple[NotificationGrade, ...]:
    return tuple(
        NotificationGrade(
            github_repo_id=9000 + cycle_index * 10 + offset,
            grade=grade,
            score=score,
        )
        for offset, grade in enumerate(grades)
    )


def _cycle(index: int, *, grades=("GOOD",), result="SUCCESS", dry_run=False, **kwargs) -> CycleEvidence:
    if not grades and result == "SUCCESS":
        result = "SUCCESS_NO_FINDINGS"
    score = int(kwargs.pop("score", 78))
    return CycleEvidence(
        run_id=f"RUN-{index:02d}",
        run_date=START + timedelta(days=index),
        result=result,
        dry_run=dry_run,
        notifications=_graded(index, tuple(grades), score=score),
        **kwargs,
    )


def test_fewer_than_seven_cycles_stays_pending():
    report = evaluate_acceptance([_cycle(i) for i in range(6)])
    assert report.status == STATUS_PENDING
    assert report.metrics["consecutive_cycles"] == 6
    assert "seven" in render_acceptance_markdown(report).lower()


def test_no_cycles_yet_makes_every_criterion_pending_not_pass():
    report = evaluate_acceptance([])
    assert report.status == STATUS_PENDING
    assert report.criteria, "the gate must still explain itself"
    for item in report.criteria:
        assert item.status != "PASS", f"{item.name} cannot pass without evidence: {item.detail}"


def test_seven_healthy_cycles_with_udr_above_floor_is_accepted():
    cycles = [_cycle(i, grades=("GOOD", "MAYBE", "BAD", "GOOD")) for i in range(7)]
    report = evaluate_acceptance(cycles)
    assert report.status == STATUS_ACCEPTED
    assert report.metrics["useful_discovery_rate"] == pytest.approx(0.75)
    assert report.blocking == ()


def test_udr_below_floor_is_not_accepted():
    cycles = [_cycle(i, grades=("BAD", "BAD", "GOOD")) for i in range(7)]
    report = evaluate_acceptance(cycles)
    assert report.status == STATUS_NOT_ACCEPTED
    assert any("useful discovery rate" in reason.lower() for reason in report.blocking)


def test_missing_day_breaks_the_consecutive_run():
    cycles = [_cycle(i) for i in range(6)]
    cycles.append(
        CycleEvidence(
            run_id="RUN-GAP",
            run_date=START + timedelta(days=12),
            result="SUCCESS",
            dry_run=False,
            notifications=_graded(12, ("GOOD",)),
        )
    )
    report = evaluate_acceptance(cycles)
    assert report.status == STATUS_PENDING
    assert report.metrics["consecutive_cycles"] == 1


def test_ungraded_notification_keeps_the_gate_pending():
    cycles = [_cycle(i) for i in range(7)]
    cycles[-1] = CycleEvidence(
        run_id="RUN-UNGRADED",
        run_date=START + timedelta(days=6),
        result="SUCCESS",
        dry_run=False,
        notifications=(),
        issues_created=1,
        ungraded_notifications=1,
    )
    report = evaluate_acceptance(cycles)
    assert report.status == STATUS_PENDING
    assert any("ungraded" in reason.lower() for reason in report.blocking)


def test_duplicate_issue_fails_the_gate():
    cycles = [_cycle(i, duplicate_issues=1 if i == 3 else 0) for i in range(7)]
    report = evaluate_acceptance(cycles)
    assert report.status == STATUS_NOT_ACCEPTED
    assert any("duplicate" in reason.lower() for reason in report.blocking)


def test_corruption_budget_overrun_conflict_and_secret_exposure_fail_the_gate():
    cycles = [_cycle(i) for i in range(7)]
    cycles[0] = _cycle(0, integrity_ok=False)
    cycles[1] = _cycle(1, budget_overruns=1)
    cycles[2] = _cycle(2, state_conflicts=1)
    cycles[3] = _cycle(3, secret_exposures=1)
    report = evaluate_acceptance(cycles)
    assert report.status == STATUS_NOT_ACCEPTED
    joined = " ".join(report.blocking).lower()
    for keyword in ("integrity", "budget", "concurrent", "secret"):
        assert keyword in joined


def test_dry_run_only_cycles_are_pending_not_accepted():
    cycles = [_cycle(i, dry_run=True) for i in range(7)]
    report = evaluate_acceptance(cycles)
    assert report.status == STATUS_PENDING
    assert any("dry-run" in reason.lower() for reason in report.blocking)


def test_silent_day_must_report_success_no_findings():
    cycles = [_cycle(i) for i in range(7)]
    cycles[4] = CycleEvidence(
        run_id="RUN-SILENT",
        run_date=START + timedelta(days=4),
        result="SUCCESS",
        dry_run=False,
        notifications=(),
    )
    report = evaluate_acceptance(cycles)
    assert report.status == STATUS_NOT_ACCEPTED
    assert any("no findings" in reason.lower() for reason in report.blocking)


def test_exceptional_bad_notification_fails_calibration():
    cycles = [_cycle(i) for i in range(7)]
    cycles[2] = _cycle(2, grades=("GOOD", "GOOD", "GOOD"), score=90)
    cycles[2] = CycleEvidence(
        run_id="RUN-EXC",
        run_date=START + timedelta(days=2),
        result="SUCCESS",
        dry_run=False,
        notifications=(
            NotificationGrade(github_repo_id=1, grade="GOOD", score=78),
            NotificationGrade(github_repo_id=2, grade="BAD", score=91),
        ),
    )
    report = evaluate_acceptance(cycles)
    assert report.status == STATUS_NOT_ACCEPTED
    assert any("exceptional" in reason.lower() for reason in report.blocking)


def test_markdown_renderer_emits_exactly_one_status_line():
    report = evaluate_acceptance([_cycle(i) for i in range(7)])
    markdown = render_acceptance_markdown(report)
    assert markdown.count("STATUS=") == 1
    assert markdown.rstrip().endswith(f"STATUS={report.status}")
    assert report.status in {STATUS_ACCEPTED, STATUS_NOT_ACCEPTED, STATUS_PENDING}


def test_operational_metrics_aggregate_llm_cost_and_stage_counts():
    cycles = [
        _cycle(
            i,
            llm_calls=3,
            llm_cache_hits=1,
            llm_cost=0.02,
            stage_counts={"discovered": 100, "light_analyzed": 20, "deep_analyzed": 5},
        )
        for i in range(7)
    ]
    report = evaluate_acceptance(cycles)
    assert report.metrics["llm_calls"] == 21
    assert report.metrics["llm_cache_hits"] == 7
    assert report.metrics["llm_cost"] == pytest.approx(0.14)
    assert report.metrics["candidates_discovered"] == 700
    assert report.metrics["candidates_deep_analyzed"] == 35
    assert report.metrics["projected_monthly_llm_cost"] == pytest.approx(0.14 / 7 * 30)
