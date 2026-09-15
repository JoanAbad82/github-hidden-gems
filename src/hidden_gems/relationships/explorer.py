"""One-hop relationship expansion.

Expansion depth is exactly one in V1: a related repository re-enters the normal
dedupe/filter/light-analysis flow and is never expanded again. Only GitHub
repositories become candidates; ordinary external documentation URLs are
ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Collection, Iterable, Mapping, Sequence

from ..config import AppConfig
from ..github.repositories import payload_to_candidate
from ..models import DiscoveryCandidate, LightAnalysis

CHANNEL = "RELATIONSHIP_EXPLORATION"

#: How many related repositories one seed may contribute per source.
MAX_PER_SOURCE_PER_SEED = 3
#: Hard ceiling for one exploration pass.
MAX_TOTAL_CANDIDATES = 60

_GITHUB_URL = re.compile(
    r"https?://(?:www\.)?github\.com/([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*)",
    re.IGNORECASE,
)
_RESERVED_OWNERS = frozenset(
    {
        "features", "topics", "about", "pricing", "marketplace", "sponsors", "orgs", "users",
        "collections", "trending", "settings", "login", "join", "explore", "search", "apps",
        "site", "blog", "docs", "security", "enterprise", "readme", "github",
    }
)


@dataclass(frozen=True)
class RelationshipSource:
    source_type: str  # same_owner | readme_link | dependency | related_project_link
    source_repo_id: int


def _evidence_value(light: LightAnalysis, *keys: str) -> Any:
    evidence = light.evidence or {}
    for key in keys:
        if key in evidence and evidence[key]:
            return evidence[key]
    return None


def _github_full_names(values: Iterable[Any]) -> list[str]:
    """Extract canonical owner/name pairs from URLs; ignore non-GitHub URLs."""

    found: list[str] = []
    for value in values or ():
        text = str(value or "").strip()
        if not text:
            continue
        match = _GITHUB_URL.match(text)
        if match:
            owner, name = match.group(1), match.group(2)
            if owner.lower() not in _RESERVED_OWNERS:
                name = name[:-4] if name.endswith(".git") else name
                found.append(f"{owner}/{name}")
        elif re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*", text):
            found.append(text)
    return found


def _links_from_readme(light: LightAnalysis) -> list[str]:
    explicit = _evidence_value(light, "readme_links", "readme_urls", "links")
    if explicit:
        return _github_full_names(explicit)
    readme_text = _evidence_value(light, "readme_text")
    if not readme_text:
        return []
    matches = _GITHUB_URL.findall(str(readme_text))
    return _github_full_names(f"https://github.com/{owner}/{name}" for owner, name in matches)


def _candidate_from_payload(payload: Mapping[str, Any]) -> DiscoveryCandidate | None:
    return payload_to_candidate(payload, channels={CHANNEL}, query_ids=set())


def _same_owner(client: Any, owner: str, exclude: set[int]) -> list[DiscoveryCandidate]:
    try:
        payload = client.get_json(
            f"/users/{owner}/repos", {"per_page": 50, "sort": "updated", "type": "owner"}
        )
    except Exception:
        return []
    results: list[DiscoveryCandidate] = []
    if not isinstance(payload, list):
        return results
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        if bool(item.get("fork")) or bool(item.get("archived")):
            continue
        candidate = _candidate_from_payload(item)
        if candidate is None or candidate.repo.github_repo_id in exclude:
            continue
        results.append(candidate)
        if len(results) >= MAX_PER_SOURCE_PER_SEED:
            break
    return results


def _from_links(
    client: Any, full_names: Sequence[str], exclude: set[int]
) -> list[DiscoveryCandidate]:
    results: list[DiscoveryCandidate] = []
    for full_name in full_names:
        if len(results) >= MAX_PER_SOURCE_PER_SEED:
            break
        try:
            payload = client.get_repo_metadata(full_name)
        except Exception:
            continue
        if not isinstance(payload, Mapping):
            continue
        candidate = _candidate_from_payload(payload)
        if candidate is None or candidate.repo.github_repo_id in exclude:
            continue
        results.append(candidate)
    return results


def explore_relationships(
    *,
    config: AppConfig,
    client: Any,
    seeds: Sequence[LightAnalysis],
    existing_repo_ids: Collection[int],
) -> list[DiscoveryCandidate]:
    """Expand at most one hop from the best seeds."""

    depth = config.discovery.relationship_depth
    if depth != 1:
        raise ValueError(f"RELATIONSHIP_DEPTH must be exactly 1 in V1, got {depth!r}")
    if not seeds:
        return []

    max_seeds = int(config.discovery.max_relationship_seeds)
    enabled_sources = tuple(config.discovery.relationship_sources)
    exclude = set(existing_repo_ids or ())
    exclude.update(seed.repo.github_repo_id for seed in seeds)

    collected: dict[int, DiscoveryCandidate] = {}
    for seed in list(seeds)[:max_seeds]:
        if len(collected) >= MAX_TOTAL_CANDIDATES:
            break
        owner = seed.repo.owner
        if "same_owner" in enabled_sources:
            for candidate in _same_owner(client, owner, exclude | set(collected)):
                collected.setdefault(candidate.repo.github_repo_id, candidate)
        if "readme_link" in enabled_sources:
            for candidate in _from_links(client, _links_from_readme(seed), exclude | set(collected)):
                collected.setdefault(candidate.repo.github_repo_id, candidate)
        if "dependency" in enabled_sources:
            dependencies = _github_full_names(
                _evidence_value(seed, "dependency_links", "dependency_repos") or ()
            )
            for candidate in _from_links(client, dependencies, exclude | set(collected)):
                collected.setdefault(candidate.repo.github_repo_id, candidate)
        if "related_project_link" in enabled_sources:
            related = _github_full_names(
                _evidence_value(seed, "related_project_links", "related_projects") or ()
            )
            for candidate in _from_links(client, related, exclude | set(collected)):
                collected.setdefault(candidate.repo.github_repo_id, candidate)

    return list(collected.values())
