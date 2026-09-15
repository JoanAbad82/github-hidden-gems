"""Task 4: deterministic discovery query planning."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from hidden_gems.discovery.queries import build_query_plan


def test_core_plan_covers_all_four_area_families(app_config):
    plan = build_query_plan(app_config, date(2026, 9, 15))

    area_ids = {area.id for area in app_config.topics.areas}
    assert area_ids == {"ai_agents", "automation", "data", "trading"}
    for area_id in area_ids:
        assert any(area_id in query.areas for query in plan.core), area_id


def test_core_plan_includes_every_core_template_and_channel(app_config):
    plan = build_query_plan(app_config, date(2026, 9, 15))

    assert {query.template for query in plan.core} == set(app_config.discovery.core_templates)
    assert {query.channel for query in plan.core} == {
        "NEW_REPOSITORY",
        "RECENT_ACTIVITY",
        "TOPIC_SEARCH",
    }


def test_core_plan_covers_every_configured_star_band(app_config):
    plan = build_query_plan(app_config, date(2026, 9, 15))
    bands = {f"{low}..{high}" for low, high in app_config.discovery.query_star_bands}

    rendered = {query.query for query in plan.core}
    for band in bands:
        assert any(band in query for query in rendered), band


def test_new_repository_queries_use_the_configured_creation_window(app_config):
    as_of = date(2026, 9, 15)
    plan = build_query_plan(app_config, as_of)
    cutoff = (as_of - timedelta(days=app_config.discovery.query_created_within_days)).isoformat()

    new_queries = [query for query in plan.core if query.channel == "NEW_REPOSITORY"]
    assert new_queries
    for query in new_queries:
        assert f"created:>={cutoff}" in query.query


def test_activity_queries_use_the_configured_push_window(app_config):
    as_of = date(2026, 9, 15)
    plan = build_query_plan(app_config, as_of)
    cutoff = (as_of - timedelta(days=app_config.discovery.query_pushed_within_days)).isoformat()

    activity_queries = [query for query in plan.core if query.channel == "RECENT_ACTIVITY"]
    assert activity_queries
    for query in activity_queries:
        assert f"pushed:>={cutoff}" in query.query


def test_plan_never_contains_a_forbidden_solo_crypto_query(app_config):
    plan = build_query_plan(app_config, date(2026, 9, 15))

    for forbidden in app_config.discovery.forbidden_solo_query_terms:
        for query in (*plan.core, *plan.rotating):
            assert forbidden not in query.query.lower(), query.query


def test_query_identifiers_are_unique(app_config):
    plan = build_query_plan(app_config, date(2026, 9, 15))
    ids = [query.id for query in (*plan.core, *plan.rotating)]

    assert len(ids) == len(set(ids))


def test_rotating_group_selection_is_deterministic_and_date_driven(app_config):
    first = build_query_plan(app_config, date(2026, 9, 15))
    second = build_query_plan(app_config, date(2026, 9, 15))
    assert first == second
    assert first.as_of_date == date(2026, 9, 15)

    group_ids = {group.id for group in app_config.discovery.rotating_groups}
    assert first.rotating_group_id in group_ids

    seen_groups = {
        build_query_plan(app_config, date(2026, 9, 15) + timedelta(days=offset)).rotating_group_id
        for offset in range(len(app_config.discovery.rotating_groups))
    }
    assert seen_groups == group_ids


def test_rotating_queries_use_the_selected_group_area_pairs(app_config):
    as_of = date(2026, 9, 15)
    plan = build_query_plan(app_config, as_of)
    group = next(g for g in app_config.discovery.rotating_groups if g.id == plan.rotating_group_id)

    assert plan.rotating
    assert {query.channel for query in plan.rotating} == {"INTERSECTION_SEARCH"}
    assert {frozenset(query.areas) for query in plan.rotating} == {
        frozenset(pair) for pair in group.area_pairs
    }
    for query in plan.rotating:
        assert len(query.areas) == 2
        assert query.template == "intersection"


def test_intersection_queries_render_both_terms(app_config):
    plan = build_query_plan(app_config, date(2026, 9, 15))
    group = next(g for g in app_config.discovery.rotating_groups if g.id == plan.rotating_group_id)
    by_pair = {frozenset(query.areas): query for query in plan.rotating}

    terms = {area.id: area.search_terms for area in app_config.topics.areas}
    for pair in group.area_pairs:
        query = by_pair[frozenset(pair)]
        assert any(term in query.query for term in terms[pair[0]])
        assert any(term in query.query for term in terms[pair[1]])


def test_invalid_relationship_depth_is_rejected(app_config, monkeypatch):
    from dataclasses import replace

    broken = replace(app_config, discovery=replace(app_config.discovery, relationship_depth=2))
    with pytest.raises(ValueError):
        build_query_plan(broken, date(2026, 9, 15))
