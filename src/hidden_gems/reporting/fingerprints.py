"""Deterministic fingerprints for notifications and reports.

Identical evidence always produces identical fingerprints, which is what makes
issue publication idempotent across runs.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Sequence

from ..models import SelectedFinding

FIRST_DISCOVERY_PREFIX = "FIRST_DISCOVERY"
NEW_RELEASE_PREFIX = "NEW_RELEASE"
SCORE_INCREASE_PREFIX = "SCORE_INCREASE"
MAJOR_CHANGE_PREFIX = "MAJOR_CHANGE"
REPORT_PREFIX = "REPORT"


def first_discovery_fingerprint(github_repo_id: int, score_version: str) -> str:
    return f"{FIRST_DISCOVERY_PREFIX}:{int(github_repo_id)}:{score_version}"


def new_release_fingerprint(github_repo_id: int, release_id: int | str) -> str:
    return f"{NEW_RELEASE_PREFIX}:{int(github_repo_id)}:{release_id}"


def score_increase_fingerprint(
    github_repo_id: int, last_notification_id: int | str, current_score: int
) -> str:
    return f"{SCORE_INCREASE_PREFIX}:{int(github_repo_id)}:{last_notification_id}:{int(current_score)}"


def major_change_fingerprint(github_repo_id: int, relevant_content_hash: str) -> str:
    return f"{MAJOR_CHANGE_PREFIX}:{int(github_repo_id)}:{relevant_content_hash}"


def report_fingerprint(
    findings: Sequence[SelectedFinding], run_date: date, score_version: str
) -> str:
    """Stable identity of one report, independent of input ordering."""

    members = sorted(
        (
            f"{finding.repo.github_repo_id}:"
            f"{finding.decision.trigger_fingerprint or finding.status}:"
            f"{finding.score.total}"
        )
        for finding in findings
    )
    payload = "\n".join([run_date.isoformat(), score_version, *members])
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
    return f"{REPORT_PREFIX}:{digest}"
