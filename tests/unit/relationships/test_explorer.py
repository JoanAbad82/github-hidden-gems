"""Task 8: bounded one-hop relationship exploration."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from hidden_gems.models import LightAnalysis, RepositoryRef
from hidden_gems.relationships.explorer import RelationshipSource, explore_relationships

NOW = datetime(2026, 9, 15, 6, 17, tzinfo=timezone.utc)


def payload(repo_id: int, owner: str, name: str, **overrides) -> dict:
    base = {
        "id": repo_id,
        "name": name,
        "full_name": f"{owner}/{name}",
        "owner": {"login": owner},
        "html_url": f"https://github.com/{owner}/{name}",
        "description": "related automation project",
        "stargazers_count": 9,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-10T00:00:00Z",
        "pushed_at": "2026-09-10T00:00:00Z",
        "language": "Python",
        "topics": ["automation"],
        "fork": False,
        "archived": False,
        "is_template": False,
        "size": 100,
        "default_branch": "main",
    }
    base.update(overrides)
    return base


def light(repo_id: int, owner: str, name: str, **evidence) -> LightAnalysis:
    repo = RepositoryRef.from_full_name(f"{owner}/{name}", repo_id)
    base = {"readme_present": True, "file_count": 5}
    base.update(evidence)
    return LightAnalysis(
        repo=repo,
        detected_areas=frozenset({"automation"}),
        activity_level="STRONG",
        quality_signals=("structure:src",),
        negative_signals=(),
        latest_release_tag=None,
        latest_release_at=None,
        latest_relevant_activity_at=NOW,
        readme_hash="r",
        tree_hash="t",
        dependency_hash="d",
        relevant_content_hash="c",
        evidence=base,
    )


class FakeClient:
    def __init__(self, *, owner_repos=None, metadata=None, failing=()) -> None:
        self.owner_repos = owner_repos or {}
        self.metadata = metadata or {}
        self.failing = set(failing)
        self.calls: list[tuple[str, str]] = []

    def get_json(self, path, params=None):
        owner = path.split("/")[2]
        self.calls.append(("owner_repos", owner))
        if owner in self.failing:
            raise RuntimeError("boom")
        return list(self.owner_repos.get(owner, []))

    def get_repo_metadata(self, full_name: str):
        self.calls.append(("metadata", full_name))
        if full_name in self.failing:
            raise RuntimeError("boom")
        if full_name not in self.metadata:
            raise KeyError(full_name)
        return dict(self.metadata[full_name])


def test_depth_is_exactly_one(app_config):
    broken = replace(app_config, discovery=replace(app_config.discovery, relationship_depth=2))

    with pytest.raises(ValueError, match="RELATIONSHIP_DEPTH"):
        explore_relationships(config=broken, client=FakeClient(), seeds=[], existing_repo_ids=[])


def test_only_one_hop_is_explored(app_config):
    """A -> B -> C must yield B only when A is the seed."""

    client = FakeClient(
        metadata={
            "acme/alpha": payload(1, "acme", "alpha"),
            "other/beta": payload(2, "other", "beta"),
            "third/gamma": payload(3, "third", "gamma"),
        }
    )
    seed_a = light(1, "acme", "alpha", readme_links=["https://github.com/other/beta"])
    seed_b = light(2, "other", "beta", readme_links=["https://github.com/third/gamma"])

    result = explore_relationships(
        config=app_config, client=client, seeds=[seed_a], existing_repo_ids=[]
    )

    assert [candidate.repo.full_name for candidate in result] == ["other/beta"]
    assert ("metadata", "third/gamma") not in client.calls
    assert ("owner_repos", "third") not in client.calls
    # B is reachable only when it is itself a seed (depth is still one hop)
    deeper = explore_relationships(
        config=app_config, client=client, seeds=[seed_b], existing_repo_ids=[1]
    )
    assert [candidate.repo.full_name for candidate in deeper] == ["third/gamma"]


def test_same_owner_repositories_are_discovered(app_config):
    client = FakeClient(
        owner_repos={
            "acme": [
                payload(2, "acme", "sibling"),
                payload(3, "acme", "forked", fork=True),
                payload(4, "acme", "dead", archived=True),
            ]
        }
    )
    seed = light(1, "acme", "alpha")

    result = explore_relationships(
        config=app_config, client=client, seeds=[seed], existing_repo_ids=[]
    )

    assert [candidate.repo.full_name for candidate in result] == ["acme/sibling"]


def test_readme_dependency_and_related_links_are_discovered(app_config):
    client = FakeClient(
        owner_repos={"acme": []},
        metadata={
            "beta/bee": payload(11, "beta", "bee"),
            "gamma/gee": payload(12, "gamma", "gee"),
            "delta/dee": payload(13, "delta", "dee"),
        },
    )
    seed = light(
        1,
        "acme",
        "alpha",
        readme_links=["https://github.com/beta/bee"],
        dependency_links=["https://github.com/gamma/gee"],
        related_project_links=["https://github.com/delta/dee"],
    )

    result = explore_relationships(
        config=app_config, client=client, seeds=[seed], existing_repo_ids=[]
    )

    assert sorted(candidate.repo.full_name for candidate in result) == [
        "beta/bee",
        "delta/dee",
        "gamma/gee",
    ]
    assert all(candidate.discovery_channels == {"RELATIONSHIP_EXPLORATION"} for candidate in result)


def test_readme_text_links_are_parsed(app_config):
    client = FakeClient(
        owner_repos={"acme": []}, metadata={"beta/bee": payload(11, "beta", "bee")}
    )
    readme = (
        "See https://github.com/beta/bee for the runtime, docs at "
        "https://docs.python.org/3/ and https://github.com/features/actions for CI."
    )
    seed = light(1, "acme", "alpha", readme_text=readme)

    result = explore_relationships(
        config=app_config, client=client, seeds=[seed], existing_repo_ids=[]
    )

    assert [candidate.repo.full_name for candidate in result] == ["beta/bee"]


def test_non_github_urls_never_become_candidates(app_config):
    client = FakeClient(owner_repos={"acme": []})
    seed = light(
        1,
        "acme",
        "alpha",
        readme_links=[
            "https://docs.python.org/3/library/asyncio.html",
            "https://gitlab.com/other/project",
            "https://example.com/blog",
        ],
        dependency_links=["https://pypi.org/project/httpx/"],
    )

    assert explore_relationships(
        config=app_config, client=client, seeds=[seed], existing_repo_ids=[]
    ) == []
    assert all(kind == "owner_repos" for kind, _ in client.calls)


def test_already_seen_repositories_are_excluded(app_config):
    client = FakeClient(
        owner_repos={"acme": [payload(2, "acme", "sibling")]},
        metadata={"beta/bee": payload(11, "beta", "bee")},
    )
    seed = light(1, "acme", "alpha", readme_links=["https://github.com/beta/bee"])

    result = explore_relationships(
        config=app_config, client=client, seeds=[seed], existing_repo_ids=[2, 11]
    )

    assert result == []


def test_only_the_configured_number_of_seeds_is_expanded(app_config):
    client = FakeClient(owner_repos={f"org{index}": [] for index in range(30)})
    seeds = [light(index + 1, f"org{index}", "repo") for index in range(30)]

    explore_relationships(config=app_config, client=client, seeds=seeds, existing_repo_ids=[])

    expanded = {owner for kind, owner in client.calls if kind == "owner_repos"}
    assert len(expanded) == app_config.discovery.max_relationship_seeds


def test_source_failures_are_fail_soft(app_config):
    client = FakeClient(owner_repos={"acme": []}, failing={"acme", "beta/bee"})
    seed = light(1, "acme", "alpha", readme_links=["https://github.com/beta/bee"])

    assert explore_relationships(
        config=app_config, client=client, seeds=[seed], existing_repo_ids=[]
    ) == []


def test_relationship_source_record_is_frozen():
    source = RelationshipSource(source_type="same_owner", source_repo_id=1)

    with pytest.raises(Exception):
        source.source_type = "readme_link"
