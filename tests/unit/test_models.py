from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hidden_gems.models import (
    AREA_IDS,
    DeepAnalysis,
    FilterDecision,
    HiddenGemScore,
    LightAnalysis,
    ModelError,
    RepositoryRef,
    RunSummary,
)


def make_ref(**overrides) -> RepositoryRef:
    payload = dict(
        github_repo_id=4242,
        owner="acme",
        name="gem",
        full_name="acme/gem",
        html_url="https://github.com/acme/gem",
    )
    payload.update(overrides)
    return RepositoryRef(**payload)


def test_repository_ref_requires_canonical_url():
    ref = make_ref()
    assert ref.full_name == "acme/gem"
    with pytest.raises(ModelError):
        make_ref(html_url="https://evil.example/acme/gem")


def test_repository_ref_from_full_name():
    ref = RepositoryRef.from_full_name("acme/gem", 7)
    assert ref.owner == "acme" and ref.name == "gem" and ref.html_url == "https://github.com/acme/gem"


def test_repository_ref_rejects_invalid_names():
    with pytest.raises(ModelError):
        RepositoryRef.from_full_name("acme/../etc", 7)


def test_example_hidden_gem_totals_90():
    score = HiddenGemScore(18, 17, 19, 15, 9, 8, 4, 90, "HIGH")
    assert score.total == 90
    assert score.score_version == "HIDDEN_GEM_SCORE_V1"
    assert score.notified_kind == "EXCEPTIONAL"


def test_hidden_gem_score_is_range_checked():
    with pytest.raises(ModelError):
        HiddenGemScore(21, 17, 19, 15, 9, 8, 4, 93, "HIGH")
    with pytest.raises(ModelError):
        HiddenGemScore(18, 17, 19, 15, 9, 8, 4, 91, "HIGH")
    with pytest.raises(ModelError):
        HiddenGemScore(18, 17, 19, 15, 9, 8, 4, 90, "MAYBE")


def test_light_analysis_rejects_unknown_areas():
    with pytest.raises(ModelError):
        LightAnalysis(
            repo=make_ref(),
            detected_areas=frozenset({"ai_agents", "crypto"}),
            activity_level="MEDIUM",
            quality_signals=(),
            negative_signals=(),
            latest_release_tag=None,
            latest_release_at=None,
            latest_relevant_activity_at=None,
            readme_hash="a",
            tree_hash="b",
            dependency_hash="c",
            relevant_content_hash="d",
        )


def test_deep_analysis_status_and_confidence_are_constrained():
    analysis = DeepAnalysis(repo=make_ref(), confidence="LOW", status="LLM_FAILED")
    assert analysis.status == "LLM_FAILED"
    with pytest.raises(ModelError):
        DeepAnalysis(repo=make_ref(), confidence="CERTAIN")


def test_filter_decision_is_frozen_and_explainable():
    decision = FilterDecision(passed=False, reason_code="REJECT_FORK", evidence=("fork=true",))
    assert decision.reason_code == "REJECT_FORK"
    with pytest.raises(Exception):
        decision.passed = True  # type: ignore[misc]


def test_run_summary_rejects_unknown_result():
    now = datetime.now(timezone.utc)
    with pytest.raises(ModelError):
        RunSummary(run_id="r", result="MAYBE_OK", started_at=now)
    summary = RunSummary(run_id="r", result="SUCCESS_NO_FINDINGS", started_at=now)
    assert summary.result == "SUCCESS_NO_FINDINGS"


def test_area_ids_are_frozen():
    assert AREA_IDS == ("ai_agents", "automation", "data", "trading")
