from __future__ import annotations

from datetime import timedelta

from hidden_gems.config import AppConfig
from hidden_gems.models import PreliminaryScore
from hidden_gems.scoring.preliminary import (
    compute_final_score,
    compute_preliminary_score,
    maximum_possible_score,
)


def test_preliminary_score_caps_relevance_at_14(light_factory, utcnow, app_config: AppConfig):
    light = light_factory(areas={"ai_agents", "automation", "data", "trading"})
    preliminary = compute_preliminary_score(
        light,
        {"stars": 10, "created_at": utcnow - timedelta(days=3)},
        config=app_config,
        as_of=utcnow,
    )
    assert preliminary.achieved <= 100
    assert preliminary.relevance_cap <= app_config.scoring.preliminary_relevance_max + 6
    assert preliminary.originality_cap == 10


def test_maximum_possible_pruning_example():
    partial = PreliminaryScore(achieved=41, pending_max=24, relevance_cap=12, originality_cap=10)
    result = maximum_possible_score(partial)
    assert result.total == 65
    assert result.can_reach_notification is False


def test_maximum_possible_score_can_reach_notification():
    partial = PreliminaryScore(achieved=60, pending_max=24, relevance_cap=16, originality_cap=10)
    result = maximum_possible_score(partial)
    assert result.total == 84
    assert result.can_reach_notification is True


def test_maximum_possible_score_is_capped_at_100():
    partial = PreliminaryScore(achieved=95, pending_max=30, relevance_cap=20, originality_cap=10)
    assert maximum_possible_score(partial).total == 100


def test_preliminary_never_exceeds_final_for_same_evidence(light_factory, utcnow, app_config: AppConfig):
    light = light_factory(latest_relevant_activity_at=utcnow - timedelta(days=1))
    metadata = {"stars": 30, "created_at": utcnow - timedelta(days=5)}
    preliminary = compute_preliminary_score(light, metadata, config=app_config, as_of=utcnow)
    final = compute_final_score(light, None, metadata, config=app_config, as_of=utcnow)
    assert preliminary.achieved <= final.total
    assert maximum_possible_score(preliminary).total >= final.total
