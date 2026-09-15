"""Task 4: discovery execution, deduplication, budgets, and rate zones."""

from __future__ import annotations

import sys
import types
from datetime import date, datetime, timezone

from hidden_gems.discovery import engine
from hidden_gems.models import DiscoveryCandidate, RepositoryRef


class _Budget:
    def __init__(self, zone: str = "GREEN", remaining: int = 5000) -> None:
        self.zone = zone
        self.remaining = remaining

    def snapshot(self) -> dict[str, object]:
        return {"zone": self.zone, "remaining": self.remaining}


class FakeClient:
    """Minimal stand-in for GitHubClient that records executed queries."""

    def __init__(self, response_map, *, zone: str = "GREEN") -> None:
        self.responses = response_map
        self.executed: list[str] = []
        self.rate_budget = _Budget(zone)

    def search_repositories(self, query: str, page: int = 1) -> dict:
        self.executed.append(query)
        return self.responses.get(query, {"total_count": 0, "items": []})


def payload(repo_id: int, owner: str, name: str) -> dict:
    return {
        "id": repo_id,
        "name": name,
        "full_name": f"{owner}/{name}",
        "owner": {"login": owner},
        "html_url": f"https://github.com/{owner}/{name}",
        "description": "an automation workflow toolkit",
        "stargazers_count": 12,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-10T00:00:00Z",
        "pushed_at": "2026-09-10T00:00:00Z",
        "language": "Python",
        "topics": ["automation"],
        "fork": False,
        "archived": False,
        "is_template": False,
        "size": 120,
        "default_branch": "main",
        "license": {"spdx_id": "MIT"},
        "open_issues_count": 2,
    }


def empty_responses(app_config, as_of=date(2026, 9, 15)) -> tuple[dict, object]:
    plan = engine.build_query_plan(app_config, as_of)
    return {query.query: {"total_count": 0, "items": []} for query in (*plan.core, *plan.rotating)}, plan


def test_repository_found_by_three_routes_is_one_candidate_with_three_channels(app_config, payload_parser):
    shared = payload(106, "acme", "flowkit")
    responses, plan = empty_responses(app_config)
    for wanted in ("NEW_REPOSITORY", "RECENT_ACTIVITY", "TOPIC_SEARCH"):
        match = next(query for query in plan.core if query.channel == wanted)
        responses[match.query] = {"total_count": 1, "items": [shared]}
    client = FakeClient(responses)

    result = engine.run_discovery(app_config, client, as_of=date(2026, 9, 15), parser=payload_parser)

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.repo.github_repo_id == 106
    assert len(candidate.matched_query_ids) == 3
    assert candidate.discovery_channels == {"NEW_REPOSITORY", "RECENT_ACTIVITY", "TOPIC_SEARCH"}
    assert result.stopped_reason is None
    assert result.skipped_payloads == 0


def test_duplicate_payloads_keep_one_candidate_per_repository(app_config, payload_parser):
    shared = payload(107, "acme", "duplicate")
    responses, _ = empty_responses(app_config)
    responses = {query: {"total_count": 1, "items": [shared]} for query in responses}
    client = FakeClient(responses)

    result = engine.run_discovery(app_config, client, as_of=date(2026, 9, 15), parser=payload_parser)

    assert [c.repo.github_repo_id for c in result.candidates] == [107]
    assert result.results_seen == len(client.executed)


def test_candidate_budget_is_enforced_and_recorded(app_config, payload_parser):
    items = [payload(1000 + index, "acme", f"repo{index}") for index in range(1200)]
    responses, _ = empty_responses(app_config)
    responses = {query: {"total_count": len(items), "items": items} for query in responses}
    client = FakeClient(responses)

    result = engine.run_discovery(app_config, client, as_of=date(2026, 9, 15), parser=payload_parser)

    assert len(result.candidates) == 1000
    assert result.budget_exhausted is True
    assert result.stopped_reason == "BUDGET_EXHAUSTED"


def test_explicit_max_candidates_overrides_configuration(app_config, payload_parser):
    items = [payload(2000 + index, "acme", f"repo{index}") for index in range(40)]
    responses, _ = empty_responses(app_config)
    responses = {query: {"total_count": len(items), "items": items} for query in responses}
    client = FakeClient(responses)

    result = engine.run_discovery(
        app_config, client, as_of=date(2026, 9, 15), max_candidates=5, parser=payload_parser
    )

    assert len(result.candidates) == 5
    assert result.budget_exhausted is True


def test_red_zone_stops_new_searches_immediately(app_config, payload_parser):
    client = FakeClient({}, zone="RED")

    result = engine.run_discovery(app_config, client, as_of=date(2026, 9, 15), parser=payload_parser)

    assert client.executed == []
    assert result.candidates == []
    assert result.queries_executed == 0
    assert result.stopped_reason == "RATE_LIMIT_RED"
    assert result.rate_zone == "RED"


def test_yellow_zone_skips_rotating_searches(app_config, payload_parser):
    client = FakeClient({}, zone="YELLOW")

    result = engine.run_discovery(app_config, client, as_of=date(2026, 9, 15), parser=payload_parser)

    plan = engine.build_query_plan(app_config, date(2026, 9, 15))
    assert len(client.executed) == len(plan.core)
    assert result.stopped_reason == "RATE_LIMIT_YELLOW"
    assert result.rate_zone == "YELLOW"


def test_zone_change_to_red_mid_run_stops_new_searches(app_config, payload_parser):
    responses, plan = empty_responses(app_config)
    client = FakeClient(responses)

    class Flaky(FakeClient):
        def search_repositories(self, query: str, page: int = 1) -> dict:
            if len(self.executed) >= 2:
                self.rate_budget.zone = "RED"
            return super().search_repositories(query, page)

    flaky = Flaky(responses)
    result = engine.run_discovery(app_config, flaky, as_of=date(2026, 9, 15), parser=payload_parser)

    assert len(flaky.executed) == 3
    assert result.stopped_reason == "RATE_LIMIT_RED"
    assert result.rate_zone == "RED"


def test_green_zone_executes_core_and_rotating_queries(app_config, payload_parser):
    client = FakeClient({})

    result = engine.run_discovery(app_config, client, as_of=date(2026, 9, 15), parser=payload_parser)

    plan = engine.build_query_plan(app_config, date(2026, 9, 15))
    assert len(client.executed) == len(plan.core) + len(plan.rotating)
    assert result.queries_executed == len(client.executed)
    assert result.stopped_reason is None


def test_seed_candidates_flow_through_the_same_dedupe_path(app_config, payload_parser):
    seed = DiscoveryCandidate(
        repo=RepositoryRef.from_full_name("acme/seed", 4242),
        description="seed",
        stars=3,
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        primary_language="Python",
        discovery_channels={"RELATIONSHIP_EXPLORATION"},
        matched_query_ids={"REL:4242"},
    )
    client = FakeClient({})

    result = engine.run_discovery(
        app_config, client, as_of=date(2026, 9, 15), seed_candidates=[seed], parser=payload_parser
    )

    assert 4242 in [c.repo.github_repo_id for c in result.candidates]
    assert result.candidates[0].discovery_channels == {"RELATIONSHIP_EXPLORATION"}


def test_unusable_payloads_are_counted_and_skipped(app_config, payload_parser):
    good = payload(31, "acme", "good")
    responses, plan = empty_responses(app_config)
    first = plan.core[0].query
    responses[first] = {"total_count": 2, "items": [{"not": "a repo"}, good]}
    client = FakeClient(responses)

    result = engine.run_discovery(app_config, client, as_of=date(2026, 9, 15), parser=payload_parser)

    assert [c.repo.github_repo_id for c in result.candidates] == [31]
    assert result.skipped_payloads == 1


def test_search_errors_are_fail_soft(app_config, payload_parser):
    class Exploding(FakeClient):
        def search_repositories(self, query: str, page: int = 1) -> dict:
            self.executed.append(query)
            if len(self.executed) == 1:
                raise RuntimeError("network down")
            return {"total_count": 1, "items": [payload(77, "acme", "survivor")]}

    client = Exploding({})
    result = engine.run_discovery(app_config, client, as_of=date(2026, 9, 15), parser=payload_parser)

    assert result.errors == 1
    assert [c.repo.github_repo_id for c in result.candidates] == [77]


def test_default_parser_is_the_github_package_normalizer(app_config, monkeypatch):
    calls: list[tuple] = []
    module = types.ModuleType("hidden_gems.github.repositories")

    def payload_to_candidate(item, *, channels, query_ids):
        calls.append((item.get("id"), tuple(channels), tuple(query_ids)))
        return None

    module.payload_to_candidate = payload_to_candidate
    package = types.ModuleType("hidden_gems.github")
    package.repositories = module
    monkeypatch.setitem(sys.modules, "hidden_gems.github", package)
    monkeypatch.setitem(sys.modules, "hidden_gems.github.repositories", module)

    responses, plan = empty_responses(app_config)
    responses[plan.core[0].query] = {"total_count": 1, "items": [payload(9, "acme", "wired")]}
    client = FakeClient(responses)

    engine.run_discovery(app_config, client, as_of=date(2026, 9, 15))

    assert calls
    assert calls[0][0] == 9
    assert calls[0][1] == (plan.core[0].channel,)
    assert calls[0][2] == (plan.core[0].id,)
