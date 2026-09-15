"""Preliminary pruning: cheap maximum-possible score before expensive analysis."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from ..common.time import age_days, ensure_utc, utcnow
from ..config import AppConfig, ScoringConfig
from ..models import MaximumPossibleScore, PreliminaryScore
from .hidden_gem_v1 import (
    NOTIFICATION_THRESHOLD,
    RELEVANCE_BASE_BY_AREA_COUNT,
    RELEVANCE_CAP_BY_AREA_COUNT,
    compute_final_score,
    score_activity,
    score_intersection,
    score_novelty,
    score_quality,
    score_visibility,
)

#: Maximum originality points a validated DeepAnalysis may add.
MAX_ORIGINALITY_POINTS = 10


def compute_preliminary_score(
    light,
    metadata: Mapping[str, Any],
    *,
    config: AppConfig | ScoringConfig | None = None,
    as_of: datetime | None = None,
) -> PreliminaryScore:
    """Deterministic partial score plus the still-reachable points."""

    scoring = config.scoring if isinstance(config, AppConfig) else config
    moment = ensure_utc(as_of) if as_of is not None else utcnow()
    stars = int(metadata.get("stars", 0) or 0)
    created_at = metadata.get("created_at")
    if created_at is None:
        raise ValueError("metadata must include created_at")
    repository_age = age_days(created_at, as_of=moment)

    areas = frozenset(area for area in light.detected_areas)
    area_count = len(areas)
    relevance_base = RELEVANCE_BASE_BY_AREA_COUNT.get(area_count, 14)
    relevance_cap = RELEVANCE_CAP_BY_AREA_COUNT.get(area_count, 20)
    if scoring is not None:
        relevance_base = min(relevance_base, scoring.preliminary_relevance_max)

    activity_age = metadata.get("relevant_activity_age_days")
    if activity_age is None and light.latest_relevant_activity_at is not None:
        activity_age = age_days(light.latest_relevant_activity_at, as_of=moment)

    achieved = (
        relevance_base
        + score_quality(light.quality_signals, light.negative_signals, config=config)
        + score_activity(light.activity_level, activity_age, config=config)
        + score_visibility(stars, config=config)
        + score_novelty(repository_age, config=config)
        + score_intersection(areas, config=config)
    )
    originality_cap = MAX_ORIGINALITY_POINTS
    pending_max = max(0, relevance_cap - relevance_base) + originality_cap
    return PreliminaryScore(
        achieved=min(100, achieved),
        pending_max=pending_max,
        relevance_cap=relevance_cap,
        originality_cap=originality_cap,
    )


def maximum_possible_score(
    partial: PreliminaryScore, *, notification_threshold: int = NOTIFICATION_THRESHOLD
) -> MaximumPossibleScore:
    """Highest score still reachable; used for `REJECT_LOW_MAX_SCORE` pruning."""

    total = min(100, max(0, partial.achieved) + max(0, partial.pending_max))
    return MaximumPossibleScore(total=total, can_reach_notification=total >= notification_threshold)


__all__ = [
    "MAX_ORIGINALITY_POINTS",
    "compute_final_score",
    "compute_preliminary_score",
    "maximum_possible_score",
]
