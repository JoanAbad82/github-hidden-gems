from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hidden_gems.models import LightAnalysis, RepositoryRef


@pytest.fixture
def repo_ref() -> RepositoryRef:
    return RepositoryRef.from_full_name("acme/gem", 1001)


def make_light(
    repo_ref: RepositoryRef,
    *,
    areas=frozenset({"ai_agents", "automation"}),
    activity_level: str = "STRONG",
    quality_signals=("implementation:core", "tests:unit", "docs:readme", "structure:src"),
    negative_signals=(),
    latest_relevant_activity_at: datetime | None = None,
) -> LightAnalysis:
    return LightAnalysis(
        repo=repo_ref,
        detected_areas=frozenset(areas),
        activity_level=activity_level,
        quality_signals=tuple(quality_signals),
        negative_signals=tuple(negative_signals),
        latest_release_tag="v0.1.0",
        latest_release_at=latest_relevant_activity_at,
        latest_relevant_activity_at=latest_relevant_activity_at,
        readme_hash="r",
        tree_hash="t",
        dependency_hash="d",
        relevant_content_hash="c",
        evidence={"verified_areas": sorted(areas)},
    )


@pytest.fixture
def light_factory(repo_ref):
    def _make(**kwargs) -> LightAnalysis:
        return make_light(repo_ref, **kwargs)

    return _make


@pytest.fixture
def utcnow() -> datetime:
    return datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
