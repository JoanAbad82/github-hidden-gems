"""Deterministic HIDDEN_GEM_SCORE_V1 primitives (no network, no SQLite)."""

from .hidden_gem_v1 import (
    EXCEPTION_STAR_MAX,
    EXCEPTION_STAR_MIN,
    EXCEPTION_STAR_THRESHOLD,
    EXCEPTIONAL_THRESHOLD,
    NOTIFICATION_THRESHOLD,
    PRIMARY_STAR_LIMIT,
    RENOTIFICATION_SCORE_DELTA,
    compute_final_score,
    required_notification_threshold,
    score_activity,
    score_intersection,
    score_novelty,
    score_quality,
    score_visibility,
)
from .preliminary import compute_preliminary_score, maximum_possible_score

__all__ = [
    "EXCEPTION_STAR_MAX",
    "EXCEPTION_STAR_MIN",
    "EXCEPTION_STAR_THRESHOLD",
    "EXCEPTIONAL_THRESHOLD",
    "NOTIFICATION_THRESHOLD",
    "PRIMARY_STAR_LIMIT",
    "RENOTIFICATION_SCORE_DELTA",
    "compute_final_score",
    "compute_preliminary_score",
    "maximum_possible_score",
    "required_notification_threshold",
    "score_activity",
    "score_intersection",
    "score_novelty",
    "score_quality",
    "score_visibility",
]
