"""Hard filter orchestration (SPEC_V1 section 4).

The filter is evaluated twice by the orchestrator: once with cheap metadata
only (right after discovery) and once with light-analysis evidence (README,
tree, manifests). Missing evidence never triggers a rejection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import AppConfig
from ..models import DiscoveryCandidate, FilterDecision
from . import rules

FILTER_PASS = rules.FILTER_PASS


@dataclass(frozen=True)
class FilterEvidence:
    readme_text: str | None = None
    tree_paths: tuple[str, ...] = ()
    manifest_names: tuple[str, ...] = ()
    commit_messages: tuple[str, ...] = ()
    total_size_kb: int | None = None


def is_irrelevant(
    candidate: DiscoveryCandidate,
    evidence: FilterEvidence | None = None,
    *,
    config: AppConfig | None = None,
) -> bool:
    return rules.is_irrelevant(candidate, evidence, config)


def evaluate_candidate(
    candidate: DiscoveryCandidate,
    evidence: FilterEvidence | None = None,
    *,
    config: AppConfig | None = None,
) -> FilterDecision:
    """Return the first matching canonical rejection, or a passing decision."""

    for reason, signals in (
        (rules.REASON_FORK, rules.fork_reason(candidate)),
        (rules.REASON_ARCHIVED, rules.archived_reason(candidate)),
        (rules.REASON_EMPTY, rules.empty_reason(candidate, evidence)),
    ):
        if signals:
            return FilterDecision(passed=False, reason_code=reason, evidence=tuple(signals))

    if getattr(candidate, "is_template", False):
        # GitHub metadata explicitly marks a template: no second signal needed.
        return FilterDecision(
            passed=False,
            reason_code=rules.REASON_TEMPLATE,
            evidence=("github:is_template=true",),
        )

    if rules.is_irrelevant(candidate, evidence, config):
        scores = rules.area_scores(candidate, evidence, config)
        return FilterDecision(
            passed=False,
            reason_code=rules.REASON_IRRELEVANT,
            evidence=tuple(f"area_score:{area}={score}" for area, score in sorted(scores.items())),
        )

    reason, signals = rules.semantic_rejection(candidate, evidence)
    if reason is not None:
        return FilterDecision(passed=False, reason_code=reason, evidence=signals)

    return FilterDecision(passed=True, reason_code=None, evidence=("passed:no_rejection_rule_matched",))
