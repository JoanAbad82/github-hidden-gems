"""Task 11: confidence gating and 5/10 report selection."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hidden_gems.models import HiddenGemScore, NotificationDecision, RepositoryRef, SelectedFinding
from hidden_gems.reporting.selector import (
    RepoNotificationState,
    make_notification_decision,
    select_report_candidates,
)

SCORE_VERSION = "HIDDEN_GEM_SCORE_V1"


def score(total: int, *, confidence: str = "HIGH") -> HiddenGemScore:
    """Build a valid score whose dimensions add up to ``total``."""

    order = ("relevance", "quality", "activity", "visibility", "novelty", "originality", "intersection")
    maxima = {"relevance": 20, "quality": 20, "activity": 20, "visibility": 15, "novelty": 10,
              "originality": 10, "intersection": 5}
    values = {name: 0 for name in order}
    remaining = total
    for name in order:
        take = min(maxima[name], remaining)
        values[name] = take
        remaining -= take
    assert remaining == 0
    return HiddenGemScore(
        values["relevance"], values["quality"], values["activity"], values["visibility"],
        values["novelty"], values["originality"], values["intersection"], total, confidence,
    )


def state(**kwargs) -> RepoNotificationState:
    return RepoNotificationState(github_repo_id=kwargs.pop("github_repo_id", 1), **kwargs)


@pytest.mark.parametrize(
    "stars,total,expected",
    [
        (499, 70, True),
        (0, 69, False),
        (1200, 79, False),
        (1200, 80, True),
        (2000, 80, True),
        (2001, 100, False),
    ],
)
def test_thresholds_follow_the_frozen_star_bands(app_config, stars, total, expected):
    decision = make_notification_decision(
        score=score(total), stars=stars, state=state(ever_seen=False), config=app_config
    )

    assert decision.notify is expected
    if expected:
        assert decision.notification_type == "NEW_DISCOVERY"
        assert decision.trigger_fingerprint == f"FIRST_DISCOVERY:1:{SCORE_VERSION}"


def test_low_confidence_is_never_notified_immediately(app_config):
    decision = make_notification_decision(
        score=score(95, confidence="LOW"), stars=10, state=state(), config=app_config
    )

    assert decision.notify is False
    assert decision.trigger_fingerprint is None
    assert decision.current_score == 95


@pytest.mark.parametrize("previous,current,expected", [(72, 79, False), (72, 81, False), (72, 82, True)])
def test_renotification_requires_ten_points_over_the_last_notified_score(
    app_config, previous, current, expected
):
    decision = make_notification_decision(
        score=score(current),
        stars=10,
        state=state(ever_seen=True, last_notified_score=previous, last_notification_id=5),
        config=app_config,
    )

    assert decision.notify is expected
    if expected:
        assert decision.notification_type == "UPDATE"
        assert decision.trigger_fingerprint == f"SCORE_INCREASE:1:5:{current}"
        assert decision.previous_score == previous


def test_daily_fluctuation_does_not_renotify(app_config):
    decision = make_notification_decision(
        score=score(86),
        stars=10,
        state=state(ever_seen=True, last_notified_score=80, last_notification_id=3),
        config=app_config,
    )

    assert decision.notify is False


def test_new_major_release_updates_when_score_still_qualifies(app_config):
    release = "NEW_RELEASE:1:777"
    decision = make_notification_decision(
        score=score(74),
        stars=10,
        state=state(ever_seen=True, last_notified_score=74, last_notification_id=3),
        release_fingerprint=release,
        config=app_config,
    )

    assert decision.notify is True
    assert decision.notification_type == "UPDATE"
    assert decision.trigger_fingerprint == release


def test_identical_release_fingerprint_never_notifies_twice(app_config):
    release = "NEW_RELEASE:1:777"
    decision = make_notification_decision(
        score=score(74),
        stars=10,
        state=state(
            ever_seen=True,
            last_notified_score=74,
            last_notification_id=3,
            notified_fingerprints=frozenset({release}),
        ),
        release_fingerprint=release,
        config=app_config,
    )

    assert decision.notify is False


def test_release_below_threshold_is_not_notified(app_config):
    decision = make_notification_decision(
        score=score(60),
        stars=10,
        state=state(ever_seen=True, last_notified_score=60, last_notification_id=3),
        release_fingerprint="NEW_RELEASE:1:9",
        config=app_config,
    )

    assert decision.notify is False


def test_major_content_change_updates_a_previously_notified_repo(app_config):
    decision = make_notification_decision(
        score=score(76),
        stars=10,
        state=state(ever_seen=True, last_notified_score=77, last_notification_id=8),
        content_fingerprint="MAJOR_CHANGE:1:deadbeef",
        config=app_config,
    )

    assert decision.notify is True
    assert decision.trigger_fingerprint == "MAJOR_CHANGE:1:deadbeef"


def finding(repo_id: int, total: int, *, confidence: str = "HIGH", notify: bool = True) -> SelectedFinding:
    return SelectedFinding(
        repo=RepositoryRef.from_full_name(f"acme/repo{repo_id}", repo_id),
        score=score(total, confidence=confidence),
        decision=NotificationDecision(
            notify=notify,
            notification_type="NEW_DISCOVERY" if notify else None,
            trigger_fingerprint=f"FIRST_DISCOVERY:{repo_id}:{SCORE_VERSION}" if notify else None,
            previous_score=None,
            current_score=total,
        ),
        status="NEW_DISCOVERY",
        rank=1,
        first_seen_at=datetime(2026, 9, 15, tzinfo=timezone.utc),
    )


def test_eight_normal_candidates_yield_only_the_top_five(app_config):
    findings = [finding(100 + index, 70 + index) for index in range(8)]

    selected = select_report_candidates(findings, config=app_config)

    assert len(selected) == 5
    assert [item.rank for item in selected] == [1, 2, 3, 4, 5]
    assert [item.score.total for item in selected] == [77, 76, 75, 74, 73]


def test_five_normal_plus_three_exceptional_yield_eight(app_config):
    findings = [finding(200 + index, 70 + index) for index in range(5)]
    findings += [finding(300 + index, 85 + index) for index in range(3)]

    selected = select_report_candidates(findings, config=app_config)

    assert len(selected) == 8
    assert [item.score.total for item in selected[:3]] == [87, 86, 85]


def test_positions_six_to_ten_require_eighty_five(app_config):
    # Five strong-but-normal findings, four more normal findings that would
    # otherwise extend the list, and two exceptional ones.
    findings = [finding(400 + index, 82) for index in range(5)]
    findings += [finding(500 + index, 84) for index in range(4)]
    findings += [finding(600 + index, 86) for index in range(2)]

    selected = select_report_candidates(findings, config=app_config)

    assert len(selected) == 7
    totals = [item.score.total for item in selected]
    normal_totals = [total for total in totals if total < 85]
    assert len(normal_totals) == 5, "at most five normal findings"
    assert totals.count(86) == 2, "exceptional findings fill positions 6-10"
    assert 84 in totals


def test_absolute_maximum_is_ten(app_config):
    findings = [finding(700 + index, 85 + (index % 10)) for index in range(14)]

    selected = select_report_candidates(findings, config=app_config)

    assert len(selected) == 10


def test_no_candidates_yields_no_report(app_config):
    assert select_report_candidates([], config=app_config) == []


def test_non_notified_findings_are_excluded(app_config):
    findings = [finding(800, 90, notify=False), finding(801, 90)]

    selected = select_report_candidates(findings, config=app_config)

    assert [item.repo.github_repo_id for item in selected] == [801]


def test_ordering_is_fully_deterministic(app_config):
    same_score = [finding(900 + index, 80) for index in range(3)]
    same_score[1].score = score(80, confidence="LOW")
    same_score[2].score = score(80, confidence="MEDIUM")
    shuffled = [same_score[2], same_score[0], same_score[1]]

    selected = select_report_candidates(shuffled, config=app_config)

    assert [item.repo.github_repo_id for item in selected] == [900, 902, 901]
