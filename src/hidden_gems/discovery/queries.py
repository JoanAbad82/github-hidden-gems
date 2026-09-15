"""Deterministic discovery query planning.

The plan is a pure function of the frozen configuration and the UTC date: the
same date always produces the same queries (no randomness, no clock access).

Budget shape (per run): every area family is searched through every core
template, with the star band rotating across consecutive query slots so that a
single run still covers every configured band. The rotating pair group is
selected by UTC date so that all groups are visited cyclically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..config import AppConfig

#: template name -> canonical discovery channel
CHANNEL_BY_TEMPLATE: dict[str, str] = {
    "new_repository": "NEW_REPOSITORY",
    "recently_active": "RECENT_ACTIVITY",
    "topic_search": "TOPIC_SEARCH",
    "intersection": "INTERSECTION_SEARCH",
}


@dataclass(frozen=True)
class DiscoveryQuery:
    id: str
    channel: str
    query: str
    template: str
    areas: tuple[str, ...]


@dataclass(frozen=True)
class QueryPlan:
    core: tuple[DiscoveryQuery, ...]
    rotating: tuple[DiscoveryQuery, ...]
    rotating_group_id: str
    as_of_date: date


def star_range_label(band: tuple[int, int]) -> str:
    low, high = band
    return f"{low}..{high}"


def _render(template: str, *, term: str = "", term_a: str = "", term_b: str = "",
            since_date: str = "", star_range: str = "") -> str:
    return " ".join(
        template.format(
            term=term,
            term_a=term_a,
            term_b=term_b,
            since_date=since_date,
            star_range=star_range,
        ).split()
    )


def _validate(config: AppConfig) -> None:
    depth = config.discovery.relationship_depth
    if depth != 1:
        raise ValueError(f"RELATIONSHIP_DEPTH must be 1 in V1, got {depth!r}")
    if not config.topics.areas:
        raise ValueError("topics configuration defines no areas")
    if not config.discovery.query_star_bands:
        raise ValueError("discovery configuration defines no query star bands")
    if not config.discovery.rotating_groups:
        raise ValueError("discovery configuration defines no rotating groups")


def build_query_plan(config: AppConfig, as_of: date) -> QueryPlan:
    """Build the canonical daily query plan for ``as_of``."""

    _validate(config)
    discovery = config.discovery
    areas = tuple(config.topics.areas)
    bands = tuple(discovery.query_star_bands)
    templates = tuple(discovery.core_templates)
    ordinal = as_of.toordinal()
    since_date = (as_of.fromordinal(ordinal - discovery.query_created_within_days)).isoformat()
    pushed_since = (as_of.fromordinal(ordinal - discovery.query_pushed_within_days)).isoformat()

    core: list[DiscoveryQuery] = []
    slot = 0
    for template_name in templates:
        template = discovery.query_templates[template_name]
        channel = CHANNEL_BY_TEMPLATE[template_name]
        for area_index, area in enumerate(areas):
            band = bands[(ordinal + slot) % len(bands)]
            term = area.search_terms[(ordinal + area_index + slot) % len(area.search_terms)]
            cutoff = pushed_since if channel == "RECENT_ACTIVITY" else since_date
            rendered = _render(
                template,
                term=term,
                since_date=cutoff,
                star_range=star_range_label(band),
            )
            core.append(
                DiscoveryQuery(
                    id=f"CORE:{template_name}:{area.id}:{star_range_label(band)}",
                    channel=channel,
                    query=rendered,
                    template=template_name,
                    areas=(area.id,),
                )
            )
            slot += 1

    groups = tuple(discovery.rotating_groups)
    group = groups[ordinal % len(groups)]
    area_by_id = {area.id: area for area in areas}
    rotating: list[DiscoveryQuery] = []
    for pair_index, pair in enumerate(group.area_pairs):
        area_a = area_by_id.get(pair[0])
        area_b = area_by_id.get(pair[1])
        if area_a is None or area_b is None:
            raise ValueError(f"rotating group {group.id} references unknown areas: {pair!r}")
        band = bands[(ordinal + pair_index) % len(bands)]
        term_a = area_a.search_terms[(ordinal + pair_index) % len(area_a.search_terms)]
        term_b = area_b.search_terms[(ordinal + pair_index + 1) % len(area_b.search_terms)]
        rendered = _render(
            discovery.query_templates[group.template],
            term_a=term_a,
            term_b=term_b,
            star_range=star_range_label(band),
        )
        rotating.append(
            DiscoveryQuery(
                id=f"ROT:{group.id}:{area_a.id}:{area_b.id}",
                channel=CHANNEL_BY_TEMPLATE[group.template],
                query=rendered,
                template=group.template,
                areas=(area_a.id, area_b.id),
            )
        )

    return QueryPlan(
        core=tuple(core),
        rotating=tuple(rotating),
        rotating_group_id=group.id,
        as_of_date=as_of,
    )
