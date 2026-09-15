"""Discovery Engine execution: bounded, deduplicated, rate-zone aware."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Mapping, Sequence

from ..config import AppConfig
from ..models import DiscoveryCandidate
from .queries import DiscoveryQuery, QueryPlan, build_query_plan

PayloadParser = Callable[..., "DiscoveryCandidate | None"]

STOP_BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
STOP_RATE_LIMIT_RED = "RATE_LIMIT_RED"
STOP_RATE_LIMIT_YELLOW = "RATE_LIMIT_YELLOW"


@dataclass
class DiscoveryResult:
    candidates: list[DiscoveryCandidate] = field(default_factory=list)
    queries_executed: int = 0
    results_seen: int = 0
    budget_exhausted: bool = False
    stopped_reason: str | None = None
    rate_zone: str = "GREEN"
    skipped_payloads: int = 0
    errors: int = 0


def _default_parser() -> PayloadParser:
    """Resolve the canonical GitHub payload normalizer (owned by `github`)."""

    from ..github.repositories import payload_to_candidate

    return payload_to_candidate


def _zone(client: Any) -> str:
    budget = getattr(client, "rate_budget", None)
    zone = getattr(budget, "zone", None) or "GREEN"
    return str(zone).upper()


def _merge(target: dict[int, DiscoveryCandidate], candidate: DiscoveryCandidate) -> None:
    existing = target.get(candidate.repo.github_repo_id)
    if existing is None:
        target[candidate.repo.github_repo_id] = candidate
        return
    existing.discovery_channels.update(candidate.discovery_channels)
    existing.matched_query_ids.update(candidate.matched_query_ids)


def _record(
    ordered: dict[int, DiscoveryCandidate],
    payload: Mapping[str, Any],
    *,
    parser: PayloadParser,
    query: DiscoveryQuery,
) -> bool:
    """Normalize and merge one search payload. Returns False when unusable."""

    candidate = parser(
        payload,
        channels={query.channel},
        query_ids={query.id},
    )
    if candidate is None:
        return False
    _merge(ordered, candidate)
    return True


def run_discovery(
    config: AppConfig,
    client: Any,
    *,
    as_of: date,
    max_candidates: int | None = None,
    seed_candidates: Sequence[DiscoveryCandidate] = (),
    parser: PayloadParser | None = None,
) -> DiscoveryResult:
    """Execute the daily query plan with hard budgets and rate-zone gating."""

    plan: QueryPlan = build_query_plan(config, as_of)
    parse = parser if parser is not None else _default_parser()
    budget = int(
        max_candidates
        if max_candidates is not None
        else config.limits.run_budgets.get("max_raw_candidates", 1000)
    )

    ordered: dict[int, DiscoveryCandidate] = {}
    result = DiscoveryResult(rate_zone=_zone(client))

    for seed in seed_candidates:
        _merge(ordered, seed)

    if len(ordered) >= budget:
        result.budget_exhausted = True
        result.stopped_reason = STOP_BUDGET_EXHAUSTED
        result.candidates = list(ordered.values())
        return result

    zone = result.rate_zone
    if zone == "RED":
        result.stopped_reason = STOP_RATE_LIMIT_RED
        result.candidates = list(ordered.values())
        return result

    queries = list(plan.core)
    if zone == "YELLOW":
        result.stopped_reason = STOP_RATE_LIMIT_YELLOW
    else:
        queries.extend(plan.rotating)

    for query in queries:
        zone = _zone(client)
        result.rate_zone = zone
        if zone == "RED":
            result.stopped_reason = STOP_RATE_LIMIT_RED
            break
        if zone == "YELLOW" and query.channel == "INTERSECTION_SEARCH":
            result.stopped_reason = STOP_RATE_LIMIT_YELLOW
            break
        try:
            payload = client.search_repositories(query.query, page=1)
        except Exception:  # fail-soft: a single query never aborts discovery
            result.errors += 1
            continue
        result.queries_executed += 1
        for item in (payload or {}).get("items") or ():
            result.results_seen += 1
            if not isinstance(item, Mapping):
                result.skipped_payloads += 1
                continue
            try:
                recorded = _record(ordered, item, parser=parse, query=query)
            except Exception:
                recorded = False
            if not recorded:
                result.skipped_payloads += 1
                continue
            if len(ordered) >= budget:
                result.budget_exhausted = True
                result.stopped_reason = STOP_BUDGET_EXHAUSTED
                break
        if result.budget_exhausted:
            break

    result.candidates = list(ordered.values())
    return result
