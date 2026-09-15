"""Canonical domain models for SPEC_V1.

These types are the frozen interfaces shared by every module of the pipeline.
They are pure data containers: no network, no SQLite, no clock access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Mapping, Sequence

#: The four equally weighted areas of SPEC_V1.
AREA_IDS: tuple[str, ...] = ("ai_agents", "automation", "data", "trading")

CONFIDENCE_LEVELS: tuple[str, ...] = ("HIGH", "MEDIUM", "LOW")
ACTIVITY_LEVELS: tuple[str, ...] = ("STRONG", "MEDIUM", "WEAK", "STALE", "UNKNOWN")

NOTIFICATION_STATUS_NEW = "NEW_DISCOVERY"
NOTIFICATION_STATUS_UPDATE = "UPDATE"
NOTIFICATION_STATUSES: tuple[str, ...] = (NOTIFICATION_STATUS_NEW, NOTIFICATION_STATUS_UPDATE)

RUN_RESULTS: tuple[str, ...] = (
    "SUCCESS",
    "SUCCESS_NO_FINDINGS",
    "PARTIAL_SUCCESS",
    "PARTIAL_SUCCESS_RATE_LIMIT",
    "FAILED_INTEGRITY",
    "FAILED_CONFIGURATION",
)

_GITHUB_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ModelError(ValueError):
    """Raised when a domain model receives invalid data."""


def canonical_html_url(owner: str, name: str) -> str:
    return f"https://github.com/{owner}/{name}"


@dataclass(frozen=True)
class RepositoryRef:
    """Canonical GitHub repository identity (primary key: github_repo_id)."""

    github_repo_id: int
    owner: str
    name: str
    full_name: str
    html_url: str

    def __post_init__(self) -> None:
        if not isinstance(self.github_repo_id, int) or self.github_repo_id <= 0:
            raise ModelError(f"invalid github_repo_id: {self.github_repo_id!r}")
        if not _GITHUB_NAME_RE.match(self.owner or "") or not _GITHUB_NAME_RE.match(self.name or ""):
            raise ModelError(f"invalid owner/name: {self.owner!r}/{self.name!r}")
        expected_full = f"{self.owner}/{self.name}"
        if self.full_name != expected_full:
            raise ModelError(f"full_name {self.full_name!r} does not match {expected_full!r}")
        expected_url = canonical_html_url(self.owner, self.name)
        if self.html_url != expected_url:
            raise ModelError(f"html_url {self.html_url!r} is not canonical ({expected_url!r})")

    @classmethod
    def from_full_name(cls, full_name: str, github_repo_id: int, html_url: str | None = None) -> "RepositoryRef":
        owner, _, name = full_name.partition("/")
        return cls(
            github_repo_id=github_repo_id,
            owner=owner,
            name=name,
            full_name=full_name,
            html_url=html_url or canonical_html_url(owner, name),
        )


@dataclass
class DiscoveryCandidate:
    repo: RepositoryRef
    description: str | None
    stars: int
    created_at: datetime
    updated_at: datetime
    primary_language: str | None
    topics: tuple[str, ...] = ()
    discovery_channels: set[str] = field(default_factory=set)
    matched_query_ids: set[str] = field(default_factory=set)
    pushed_at: datetime | None = None
    is_fork: bool = False
    is_archived: bool = False
    is_template: bool = False
    size_kb: int | None = None
    default_branch: str | None = None
    license_spdx_id: str | None = None
    open_issues: int | None = None


@dataclass(frozen=True)
class FilterDecision:
    passed: bool
    reason_code: str | None
    evidence: tuple[str, ...] = ()


@dataclass
class LightAnalysis:
    repo: RepositoryRef
    detected_areas: frozenset[str]
    activity_level: str
    quality_signals: tuple[str, ...]
    negative_signals: tuple[str, ...]
    latest_release_tag: str | None
    latest_release_at: datetime | None
    latest_relevant_activity_at: datetime | None
    readme_hash: str
    tree_hash: str
    dependency_hash: str
    relevant_content_hash: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.activity_level not in ACTIVITY_LEVELS:
            raise ModelError(f"invalid activity_level: {self.activity_level!r}")
        unknown = set(self.detected_areas) - set(AREA_IDS)
        if unknown:
            raise ModelError(f"unknown areas: {sorted(unknown)}")


@dataclass
class DeepAnalysis:
    repo: RepositoryRef
    evidence: dict[str, Any] = field(default_factory=dict)
    relevance_suggestion: int | None = None
    originality_suggestion: int | None = None
    why_interesting: str | None = None
    summary: str | None = None
    risks: tuple[str, ...] = ()
    confidence: str = "LOW"
    status: str = "OK"
    source: str = "PROVIDER"

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ModelError(f"invalid confidence: {self.confidence!r}")
        if self.status not in ("OK", "LLM_FAILED"):
            raise ModelError(f"invalid status: {self.status!r}")
        if self.source not in ("PROVIDER", "CACHE", "DISABLED"):
            raise ModelError(f"invalid source: {self.source!r}")


@dataclass(frozen=True)
class HiddenGemScore:
    """HIDDEN_GEM_SCORE_V1 (0..100)."""

    relevance: int
    quality: int
    activity: int
    visibility: int
    novelty: int
    originality: int
    intersection: int
    total: int
    confidence: str
    score_version: str = "HIDDEN_GEM_SCORE_V1"

    DIMENSIONS: ClassVar[tuple[str, ...]] = (
        "relevance",
        "quality",
        "activity",
        "visibility",
        "novelty",
        "originality",
        "intersection",
    )

    MAXIMA: ClassVar[Mapping[str, int]] = {
        "relevance": 20,
        "quality": 20,
        "activity": 20,
        "visibility": 15,
        "novelty": 10,
        "originality": 10,
        "intersection": 5,
    }

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ModelError(f"invalid confidence: {self.confidence!r}")
        for dim in self.DIMENSIONS:
            value = getattr(self, dim)
            if not isinstance(value, int) or value < 0 or value > self.MAXIMA[dim]:
                raise ModelError(f"{dim}={value!r} outside 0..{self.MAXIMA[dim]}")
        if not isinstance(self.total, int) or not 0 <= self.total <= 100:
            raise ModelError(f"total={self.total!r} outside 0..100")
        expected_total = sum(getattr(self, dim) for dim in self.DIMENSIONS)
        if self.total != expected_total:
            raise ModelError(f"total {self.total} != sum of dimensions {expected_total}")

    @property
    def notified_kind(self) -> str:
        return "EXCEPTIONAL" if self.total >= 85 else "INTERESTING"


@dataclass(frozen=True)
class MaximumPossibleScore:
    total: int
    can_reach_notification: bool


@dataclass(frozen=True)
class PreliminaryScore:
    achieved: int
    pending_max: int
    relevance_cap: int
    originality_cap: int


@dataclass(frozen=True)
class NotificationDecision:
    notify: bool
    notification_type: str | None
    trigger_fingerprint: str | None
    previous_score: int | None
    current_score: int


@dataclass(frozen=True)
class IssueRef:
    number: int
    url: str
    fingerprint: str
    created: bool = False


@dataclass
class SelectedFinding:
    """One report entry, ordered by the reporting selector."""

    repo: RepositoryRef
    score: HiddenGemScore
    decision: NotificationDecision
    status: str
    rank: int
    light: LightAnalysis | None = None
    deep: DeepAnalysis | None = None
    areas: tuple[str, ...] = ()
    previous_score: int | None = None
    first_seen_at: datetime | None = None
    latest_release_tag: str | None = None
    latest_relevant_activity_at: datetime | None = None
    primary_language: str | None = None
    stars: int = 0
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.status not in NOTIFICATION_STATUSES:
            raise ModelError(f"invalid report status: {self.status!r}")
        if self.rank < 1:
            raise ModelError(f"invalid rank: {self.rank!r}")


@dataclass
class RunContext:
    run_id: str
    started_at: datetime
    dry_run: bool
    config_version: str
    score_version: str
    prompt_version: str
    budgets: dict[str, int | float] = field(default_factory=dict)
    usage: dict[str, int | float] = field(default_factory=dict)


@dataclass
class RunSummary:
    run_id: str
    result: str
    started_at: datetime
    finished_at: datetime | None = None
    dry_run: bool = True
    counts: dict[str, int] = field(default_factory=dict)
    usage: dict[str, int | float] = field(default_factory=dict)
    report_fingerprint: str | None = None
    issue: IssueRef | None = None
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.result not in RUN_RESULTS:
            raise ModelError(f"invalid run result: {self.result!r}")


def ensure_unique_repo_ids(refs: Sequence[RepositoryRef]) -> list[int]:
    seen: list[int] = []
    for ref in refs:
        if ref.github_repo_id not in seen:
            seen.append(ref.github_repo_id)
    return seen
