from __future__ import annotations

from datetime import timedelta

import pytest

from hidden_gems.config import AppConfig
from hidden_gems.models import DeepAnalysis, HiddenGemScore
from hidden_gems.scoring.hidden_gem_v1 import (
    EXCEPTION_STAR_MAX,
    EXCEPTION_STAR_MIN,
    EXCEPTION_STAR_THRESHOLD,
    EXCEPTIONAL_THRESHOLD,
    NOTIFICATION_THRESHOLD,
    PRIMARY_STAR_LIMIT,
    RENOTIFICATION_SCORE_DELTA,
    required_notification_threshold,
    score_activity,
    score_intersection,
    score_novelty,
    score_quality,
    score_visibility,
)
from hidden_gems.scoring.preliminary import compute_final_score


@pytest.mark.parametrize(
    ("stars", "expected"),
    [
        (0, 15),
        (24, 15),
        (25, 13),
        (99, 13),
        (100, 10),
        (249, 10),
        (250, 7),
        (499, 7),
        (500, 4),
        (999, 4),
        (1000, 3),
        (1499, 3),
        (1500, 1),
        (2000, 1),
        (2001, 0),
        (25000, 0),
    ],
)
def test_visibility_bands(stars: int, expected: int, app_config: AppConfig):
    assert score_visibility(stars, config=app_config) == expected
    assert score_visibility(stars, config=app_config.scoring) == expected


@pytest.mark.parametrize(
    ("age_days", "expected"),
    [
        (0, 10),
        (15, 10),
        (16, 9),
        (30, 9),
        (31, 7),
        (60, 7),
        (61, 5),
        (90, 5),
        (91, 2),
        (180, 2),
        (181, 0),
        (400, 0),
    ],
)
def test_novelty_bands(age_days: int, expected: int, app_config: AppConfig):
    assert score_novelty(age_days, config=app_config) == expected


@pytest.mark.parametrize(
    ("activity_level", "age_days", "expected"),
    [
        ("STRONG", 0, 20),
        ("STRONG", 15, 20),
        ("MEDIUM", 15, 16),
        ("STRONG", 16, 12),
        ("MEDIUM", 30, 12),
        ("WEAK", 3, 7),
        ("STALE", 90, 2),
        ("UNKNOWN", None, 0),
        ("STALE", None, 2),
    ],
)
def test_activity_rules(activity_level, age_days, expected, app_config: AppConfig):
    assert score_activity(activity_level, age_days, config=app_config) == expected


def test_activity_strong_with_stale_age_is_penalised(app_config: AppConfig):
    assert score_activity("STRONG", 45, config=app_config) == 2


@pytest.mark.parametrize(
    ("areas", "expected"),
    [
        ({"ai_agents"}, 0),
        ({"ai_agents", "automation"}, 2),
        ({"ai_agents", "automation", "data"}, 4),
        ({"ai_agents", "automation", "data", "trading"}, 5),
        (set(), 0),
    ],
)
def test_intersection_points(areas, expected, app_config: AppConfig):
    assert score_intersection(areas, config=app_config) == expected


def test_quality_is_capped_by_evidence_and_config(app_config: AppConfig):
    empty = score_quality((), config=app_config)
    assert empty == 0
    rich = score_quality(
        (
            "implementation:core",
            "implementation:modules",
            "structure:src",
            "structure:packaging",
            "docs:readme",
            "docs:install",
            "docs:examples",
            "docs:api",
            "tests:unit",
            "tests:integration",
            "tests:ci",
            "usability:install",
            "usability:quickstart",
            "hygiene:license",
        ),
        config=app_config,
    )
    assert rich == 20


def test_quality_penalties_reduce_score(app_config: AppConfig):
    base = score_quality(("implementation:core", "tests:unit", "docs:readme"), config=app_config)
    penalised = score_quality(
        ("implementation:core", "tests:unit", "docs:readme"),
        ("claim_implementation_mismatch", "minimal_implementation"),
        config=app_config,
    )
    assert penalised < base
    assert penalised >= 0


@pytest.mark.parametrize(
    ("stars", "expected"),
    [
        (0, 70),
        (499, 70),
        (500, 80),
        (2000, 80),
        (2001, None),
    ],
)
def test_required_notification_threshold(stars, expected, app_config: AppConfig):
    assert required_notification_threshold(stars, config=app_config) == expected


def test_frozen_constants_match_spec():
    assert PRIMARY_STAR_LIMIT == 499
    assert (EXCEPTION_STAR_MIN, EXCEPTION_STAR_MAX) == (500, 2000)
    assert NOTIFICATION_THRESHOLD == 70
    assert EXCEPTION_STAR_THRESHOLD == 80
    assert EXCEPTIONAL_THRESHOLD == 85
    assert RENOTIFICATION_SCORE_DELTA == 10


def test_compute_final_score_is_deterministic_and_valid(light_factory, utcnow, app_config: AppConfig):
    light = light_factory(latest_relevant_activity_at=utcnow - timedelta(days=5))
    metadata = {
        "stars": 120,
        "created_at": utcnow - timedelta(days=40),
        "relevance_evidence": ["topic:ai_agents", "readme:automation"],
        "originality_evidence": ["differentiated:capability"],
    }
    first = compute_final_score(light, None, metadata, config=app_config, as_of=utcnow)
    second = compute_final_score(light, None, metadata, config=app_config, as_of=utcnow)
    assert first == second
    assert isinstance(first, HiddenGemScore)
    assert first.visibility == 10
    assert first.novelty == 7
    assert first.intersection == 2
    assert first.activity == 20
    assert 0 <= first.originality <= app_config.scoring.no_llm_originality_max
    assert first.total == sum(
        (
            first.relevance,
            first.quality,
            first.activity,
            first.visibility,
            first.novelty,
            first.originality,
            first.intersection,
        )
    )


def test_no_llm_originality_requires_evidence(light_factory, utcnow, app_config: AppConfig):
    light = light_factory(latest_relevant_activity_at=utcnow - timedelta(days=1))
    metadata = {"stars": 10, "created_at": utcnow - timedelta(days=3)}
    score = compute_final_score(light, None, metadata, config=app_config, as_of=utcnow)
    assert score.originality == 0
    assert score.confidence in ("LOW", "MEDIUM", "HIGH")


def test_deep_suggestion_raises_relevance_within_evidence_cap(light_factory, utcnow, app_config: AppConfig):
    light = light_factory(areas={"ai_agents"}, latest_relevant_activity_at=utcnow - timedelta(days=2))
    metadata = {
        "stars": 5,
        "created_at": utcnow - timedelta(days=10),
        "relevance_evidence": ["topic:ai_agents"],
        "originality_evidence": ["differentiated:capability"],
    }
    deep = DeepAnalysis(
        repo=light.repo,
        relevance_suggestion=20,
        originality_suggestion=10,
        confidence="HIGH",
        why_interesting="unique design",
        summary="summary",
        evidence={"verified_areas": ["ai_agents"]},
    )
    score = compute_final_score(light, deep, metadata, config=app_config, as_of=utcnow)
    assert score.relevance <= 12  # single verified area caps relevance
    assert score.relevance >= 8
    assert score.originality <= 10
    assert score.confidence == "HIGH"


def test_llm_failed_deep_analysis_does_not_inject_points(light_factory, utcnow, app_config: AppConfig):
    light = light_factory(latest_relevant_activity_at=utcnow - timedelta(days=2))
    metadata = {"stars": 5, "created_at": utcnow - timedelta(days=10), "relevance_evidence": ["topic:ai_agents"]}
    failed = DeepAnalysis(repo=light.repo, confidence="LOW", status="LLM_FAILED", relevance_suggestion=20)
    score = compute_final_score(light, failed, metadata, config=app_config, as_of=utcnow)
    assert score.relevance <= 12


def test_scoring_is_pure_and_does_not_touch_network(monkeypatch, light_factory, utcnow, app_config: AppConfig):
    import socket

    def _boom(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("scoring must not perform network access")

    monkeypatch.setattr(socket, "socket", _boom)
    light = light_factory(latest_relevant_activity_at=utcnow - timedelta(days=1))
    compute_final_score(light, None, {"stars": 3, "created_at": utcnow - timedelta(days=2)}, config=app_config, as_of=utcnow)
