"""Activity classification for the light analyzer (SPEC_V1 §3).

Activity reflects real engineering work, not housekeeping: badge edits, typos,
README wording and bot dependency bumps are weak signals and can never make a
repository look strongly active.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from ..common.time import age_days, ensure_utc, parse_github_datetime

STRONG = "STRONG"
MEDIUM = "MEDIUM"
WEAK = "WEAK"
STALE = "STALE"
UNKNOWN = "UNKNOWN"

RANK: Mapping[str, int] = {UNKNOWN: 0, STALE: 1, WEAK: 2, MEDIUM: 3, STRONG: 4}

RECENT_DAYS = 15
MODERATE_DAYS = 30

WEAK_MESSAGE_TERMS = (
    "typo", "readme", "badge", "bump", "dependabot", "renovate", "chore",
    "merge branch", "merge pull request", "merge remote-tracking", "version bump",
    "update lock", "lint fixes", "formatting",
)

SUBSTANTIVE_MESSAGE_TERMS = (
    "feat", "feature", "fix", "add", "implement", "support", "refactor", "perf",
    "optimize", "rewrite", "introduce", "release", "breaking",
)


def _message(commit: Mapping[str, Any] | Any) -> str:
    if isinstance(commit, Mapping):
        body = commit.get("commit")
        if isinstance(body, Mapping):
            return str(body.get("message") or "")
        return str(commit.get("message") or "")
    return ""


def _commit_datetime(commit: Mapping[str, Any] | Any) -> datetime | None:
    if not isinstance(commit, Mapping):
        return None
    body = commit.get("commit")
    candidates: list[Any] = []
    if isinstance(body, Mapping):
        author = body.get("author")
        if isinstance(author, Mapping):
            candidates.append(author.get("date"))
        committer = body.get("committer")
        if isinstance(committer, Mapping):
            candidates.append(committer.get("date"))
    for value in candidates:
        if not value:
            continue
        try:
            return parse_github_datetime(str(value))
        except ValueError:
            continue
    return None


def _release_datetime(release: Mapping[str, Any] | Any) -> datetime | None:
    if not isinstance(release, Mapping):
        return None
    for key in ("published_at", "created_at"):
        value = release.get(key)
        if value:
            try:
                return parse_github_datetime(str(value))
            except ValueError:
                continue
    return None


def is_substantive(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    if any(term in text for term in WEAK_MESSAGE_TERMS):
        has_substantive = any(term in text for term in SUBSTANTIVE_MESSAGE_TERMS)
        return has_substantive and not text.startswith(("chore", "docs:", "style"))
    return True


def classify_activity(
    *,
    commits: Sequence[Mapping[str, Any]] = (),
    releases: Sequence[Mapping[str, Any]] = (),
    relevant_activity_at: datetime | None = None,
    as_of: datetime,
    recent_days: int = RECENT_DAYS,
    moderate_days: int = MODERATE_DAYS,
) -> tuple[str, dict[str, Any]]:
    """Return the activity level plus the evidence that produced it."""

    moment = ensure_utc(as_of)
    evidence: dict[str, Any] = {
        "commits_seen": len(commits or ()),
        "releases_seen": len(releases or ()),
        "substantive_commits_recent": 0,
        "substantive_commits_moderate": 0,
        "weak_commits_recent": 0,
        "latest_commit_age_days": None,
        "latest_release_age_days": None,
        "relevant_activity_age_days": None,
        "reasons": [],
    }

    level = UNKNOWN

    release_ages = [
        age_days(published, as_of=moment)
        for published in (_release_datetime(release) for release in releases or ())
        if published is not None
    ]
    if release_ages:
        newest_release_age = min(release_ages)
        evidence["latest_release_age_days"] = newest_release_age
        if newest_release_age <= recent_days:
            level = STRONG
            evidence["reasons"].append("release_within_recent_window")

    commit_ages: list[int] = []
    for commit in commits or ():
        moment_of_commit = _commit_datetime(commit)
        if moment_of_commit is None:
            continue
        commit_age = age_days(moment_of_commit, as_of=moment)
        commit_ages.append(commit_age)
        if is_substantive(_message(commit)):
            if commit_age <= recent_days:
                evidence["substantive_commits_recent"] += 1
            elif commit_age <= moderate_days:
                evidence["substantive_commits_moderate"] += 1
        elif commit_age <= recent_days:
            evidence["weak_commits_recent"] += 1

    if commit_ages:
        evidence["latest_commit_age_days"] = min(commit_ages)

    substantive_recent = evidence["substantive_commits_recent"]
    substantive_moderate = evidence["substantive_commits_moderate"]
    if substantive_recent >= 2:
        level = STRONG
        evidence["reasons"].append("multiple_substantive_commits_recent")
    elif substantive_recent == 1:
        level = max(level, MEDIUM, key=lambda item: RANK[item])
        evidence["reasons"].append("one_substantive_commit_recent")
    elif substantive_moderate >= 1:
        level = max(level, MEDIUM, key=lambda item: RANK[item])
        evidence["reasons"].append("substantive_commit_within_moderate_window")
    elif evidence["weak_commits_recent"]:
        level = max(level, WEAK, key=lambda item: RANK[item])
        evidence["reasons"].append("only_weak_commits_recent")

    if relevant_activity_at is not None:
        relevant_age = age_days(ensure_utc(relevant_activity_at), as_of=moment)
        evidence["relevant_activity_age_days"] = relevant_age
        if relevant_age <= moderate_days:
            level = max(level, MEDIUM, key=lambda item: RANK[item])
            evidence["reasons"].append("relevant_activity_within_moderate_window")
        elif level == UNKNOWN:
            level = STALE
            evidence["reasons"].append("relevant_activity_too_old")

    if level == UNKNOWN and (commit_ages or release_ages):
        level = STALE
        evidence["reasons"].append("no_recent_activity")

    return level, evidence
