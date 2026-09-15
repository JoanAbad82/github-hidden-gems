"""History-aware notification decisions and report selection (SPEC_V1 §6/§10)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Sequence

from ..config import AppConfig
from ..models import (
    NOTIFICATION_STATUS_NEW,
    NOTIFICATION_STATUS_UPDATE,
    HiddenGemScore,
    NotificationDecision,
    SelectedFinding,
)
from ..scoring.hidden_gem_v1 import (
    EXCEPTIONAL_THRESHOLD,
    NOTIFICATION_THRESHOLD,
    RENOTIFICATION_SCORE_DELTA,
    required_notification_threshold,
)
from .fingerprints import first_discovery_fingerprint, score_increase_fingerprint

#: Ordering rank for confidence: HIGH first, then MEDIUM, then LOW.
CONFIDENCE_RANK: dict[str, int] = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}


@dataclass(frozen=True)
class RepoNotificationState:
    """What history remembers about a repository's notification status."""

    github_repo_id: int
    ever_seen: bool = False
    last_notified_score: int | None = None
    last_notification_id: int | None = None
    last_notified_at: datetime | None = None
    notified_fingerprints: frozenset[str] = frozenset()


def _config_defaults(config: AppConfig | None) -> tuple[int, int]:
    if config is None:
        return NOTIFICATION_THRESHOLD, RENOTIFICATION_SCORE_DELTA
    return (config.scoring.notification_threshold, config.scoring.renotification_score_delta)


def make_notification_decision(
    *,
    score: HiddenGemScore,
    stars: int,
    state: RepoNotificationState,
    release_fingerprint: str | None = None,
    content_fingerprint: str | None = None,
    config: AppConfig | None = None,
) -> NotificationDecision:
    """Decide whether (and why) a scored repository becomes a notification."""

    normal_threshold, delta_required = _config_defaults(config)
    threshold = required_notification_threshold(stars, config=config)
    previous = state.last_notified_score
    base = dict(
        notification_type=None,
        trigger_fingerprint=None,
        previous_score=previous,
        current_score=score.total,
    )

    if threshold is None:
        return NotificationDecision(notify=False, **base)
    if score.confidence == "LOW":
        return NotificationDecision(notify=False, **base)
    if score.total < max(threshold, normal_threshold):
        return NotificationDecision(notify=False, **base)

    already_notified = frozenset(state.notified_fingerprints or ())

    if previous is None:
        return NotificationDecision(
            notify=True,
            notification_type=NOTIFICATION_STATUS_NEW,
            trigger_fingerprint=first_discovery_fingerprint(
                state.github_repo_id, score.score_version
            ),
            previous_score=None,
            current_score=score.total,
        )

    if score.total - previous >= delta_required:
        return NotificationDecision(
            notify=True,
            notification_type=NOTIFICATION_STATUS_UPDATE,
            trigger_fingerprint=score_increase_fingerprint(
                state.github_repo_id, state.last_notification_id or 0, score.total
            ),
            previous_score=previous,
            current_score=score.total,
        )

    for candidate in (release_fingerprint, content_fingerprint):
        if candidate and candidate not in already_notified:
            return NotificationDecision(
                notify=True,
                notification_type=NOTIFICATION_STATUS_UPDATE,
                trigger_fingerprint=candidate,
                previous_score=previous,
                current_score=score.total,
            )

    return NotificationDecision(notify=False, **base)


def ordering_key(finding: SelectedFinding) -> tuple:
    return (
        -finding.score.total,
        CONFIDENCE_RANK.get(finding.score.confidence, len(CONFIDENCE_RANK)),
        -finding.score.novelty,
        -finding.score.visibility,
        -finding.score.activity,
        finding.repo.github_repo_id,
    )


def select_report_candidates(
    findings: Sequence[SelectedFinding], *, config: AppConfig | None = None
) -> list[SelectedFinding]:
    """Apply the 5/10 rule; never pad, never exceed the absolute maximum."""

    if not findings:
        return []
    normal_max = config.reporting.normal_max if config else 5
    absolute_max = config.reporting.absolute_max if config else 10
    extra_min_score = config.reporting.extra_positions_min_score if config else EXCEPTIONAL_THRESHOLD

    eligible = sorted((item for item in findings if item.decision.notify), key=ordering_key)
    exceptionals = [item for item in eligible if item.score.total >= extra_min_score]
    normals = [item for item in eligible if item.score.total < extra_min_score]
    chosen = sorted([*normals[:normal_max], *exceptionals], key=ordering_key)[:absolute_max]
    return [replace(item, rank=index) for index, item in enumerate(chosen, start=1)]
