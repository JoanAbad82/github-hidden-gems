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


def test_markdown_renderer_never_prints_python_none():
    report = evaluate_acceptance([])
    markdown = render_acceptance_markdown(report)
    assert "None" not in markdown
    assert "n/a" in markdown


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


def test_history_sept15_sept16_daily_selection_is_order_independent():
    """Exact historical run IDs and six human grades; prior gate returned 1/1=100%."""
    from itertools import permutations
    dry = CycleEvidence(
        run_id="RUN-20260915T152056Z", run_date=date(2026, 9, 15),
        result="SUCCESS_NO_FINDINGS", dry_run=True,
    )
    live_15 = CycleEvidence(
        run_id="RUN-20260915T202610Z", run_date=date(2026, 9, 15),
        result="PARTIAL_SUCCESS", dry_run=False,
        issues_created=1,
        notifications=tuple(
            NotificationGrade(github_repo_id=i, grade=g, score=s)
            for i, g, s in [
                (1355559081, "GOOD", 79), (1353380091, "BAD", 78),
                (1353488448, "MAYBE", 77), (1353725004, "MAYBE", 77),
                (1354832590, "BAD", 77),
            ]
        ),
    )
    live_16 = CycleEvidence(
        run_id="RUN-20260916T114014Z", run_date=date(2026, 9, 16),
        result="PARTIAL_SUCCESS", dry_run=False,
        issues_created=1,
        notifications=(NotificationGrade(github_repo_id=1340901539, grade="GOOD", score=73),),
    )
    for order in permutations((dry, live_15, live_16)):
        report = evaluate_acceptance(order)
        assert report.metrics["consecutive_cycles"] == 2
        assert report.metrics["window_cycles"] == 2
        assert report.metrics["window_run_records"] == 2
        assert report.metrics["notified_repositories"] == 6
        assert report.metrics["useful_notifications"] == 4
        assert report.metrics["useful_discovery_rate"] == pytest.approx(4 / 6)
        assert report.metrics["dry_run_cycles"] == 0
        assert report.status == STATUS_PENDING
        assert report.criterion("unique_live_cycle_per_day").status == "PASS"


def test_duplicated_live_runs_fail_closed_without_dropping_evidence():
    from itertools import permutations

    regular = [_cycle(i, grades=("GOOD",)) for i in range(7)]
    duplicate = CycleEvidence(
        run_id="RUN-SAME-DAY-SECOND",
        run_date=regular[-1].run_date,
        result="PARTIAL_SUCCESS",
        dry_run=False,
        issues_created=1,
        notifications=(NotificationGrade(github_repo_id=10991, grade="BAD", score=81),),
    )
    for ordered in (
        tuple(regular) + (duplicate,),
        (duplicate,) + tuple(reversed(regular)),
    ):
        result = evaluate_acceptance(ordered)
        assert result.metrics["consecutive_cycles"] == 7
        assert result.metrics["window_cycles"] == 7
        assert result.metrics["window_run_records"] == 8
        assert result.metrics["notified_repositories"] == 8
        assert result.metrics["useful_discovery_rate"] == pytest.approx(7 / 8)
        assert result.criterion("unique_live_cycle_per_day").status == "FAIL"
        assert result.status == STATUS_NOT_ACCEPTED


def test_multiple_dry_runs_do_not_shadow_same_day_live_result():
    days = [_cycle(i, grades=("GOOD",)) for i in range(7)]
    dry_a = _cycle(4, grades=(), dry_run=True)
    dry_b = CycleEvidence(
        run_id="RUN-DRY-AFTER", run_date=days[4].run_date,
        result="SUCCESS_NO_FINDINGS", dry_run=True,
    )
    result = evaluate_acceptance((dry_b, *reversed(days), dry_a))
    assert result.status == STATUS_ACCEPTED
    assert result.metrics["window_run_records"] == 7
    assert result.metrics["window_cycles"] == 7
    assert result.metrics["dry_run_cycles"] == 0


def test_dry_only_duplicate_day_does_not_invent_extra_real_day():
    days = [_cycle(i, grades=("GOOD",), dry_run=True) for i in range(7)]
    additional = CycleEvidence(
        run_id="RUN-ADDITIONAL-DRY", run_date=days[-1].run_date,
        result="SUCCESS_NO_FINDINGS", dry_run=True,
    )
    result = evaluate_acceptance((additional, *days))
    assert result.status == STATUS_PENDING
    assert result.metrics["consecutive_cycles"] == 7
    assert result.metrics["window_run_records"] == 7
    assert result.criterion("production_publication_cycles").status == "PENDING"


def test_duplicate_live_day_does_not_push_prior_day_from_seven_day_window():
    days = [_cycle(i, grades=("BAD", "GOOD")) for i in range(7)]
    second = CycleEvidence(
        run_id="RUN-DOUBLE-LIVE",
        run_date=days[-1].run_date,
        result="PARTIAL_SUCCESS",
        dry_run=False,
        issues_created=1,
        notifications=(NotificationGrade(github_repo_id=19991, grade="BAD", score=71),),
    )
    result = evaluate_acceptance((*days, second))
    assert result.metrics["window_cycles"] == 7
    assert result.metrics["window_run_records"] == 8
    assert result.metrics["notified_repositories"] == 15
    assert result.criterion("unique_live_cycle_per_day").status == "FAIL"
    assert result.status == STATUS_NOT_ACCEPTED
