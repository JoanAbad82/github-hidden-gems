"""Task 6: activity classification must reflect real engineering work."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hidden_gems.light_analysis.activity import classify_activity
from hidden_gems.light_analysis.classification import (
    detect_areas,
    negative_signals,
    quality_signals,
)

AS_OF = datetime(2026, 9, 15, 6, 17, tzinfo=timezone.utc)


def commit(message: str, days_ago: int, sha: str = "abc") -> dict:
    moment = AS_OF - timedelta(days=days_ago)
    return {
        "sha": sha,
        "commit": {
            "message": message,
            "author": {"date": moment.strftime("%Y-%m-%dT%H:%M:%SZ")},
        },
    }


def release(days_ago: int, tag: str = "v1.0.0") -> dict:
    moment = AS_OF - timedelta(days=days_ago)
    return {
        "id": 1,
        "tag_name": tag,
        "published_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def test_release_within_fifteen_days_is_strong():
    level, evidence = classify_activity(releases=[release(3)], as_of=AS_OF)

    assert level == "STRONG"
    assert evidence["latest_release_age_days"] == 3


def test_two_substantive_commits_within_fifteen_days_are_strong():
    level, _ = classify_activity(
        commits=[commit("feat: add plugin runtime", 2, "a"), commit("fix: handle timeouts", 9, "b")],
        as_of=AS_OF,
    )

    assert level == "STRONG"


def test_one_substantive_commit_within_fifteen_days_is_medium():
    level, evidence = classify_activity(commits=[commit("fix: correct offset", 4)], as_of=AS_OF)

    assert level == "MEDIUM"
    assert evidence["substantive_commits_recent"] == 1


def test_substantive_activity_between_sixteen_and_thirty_days_is_medium():
    level, _ = classify_activity(commits=[commit("feat: new exporter", 22)], as_of=AS_OF)

    assert level == "MEDIUM"


def test_relevant_activity_between_sixteen_and_thirty_days_is_medium():
    level, evidence = classify_activity(
        relevant_activity_at=AS_OF - timedelta(days=20), as_of=AS_OF
    )

    assert level == "MEDIUM"
    assert evidence["relevant_activity_age_days"] == 20


def test_readme_typo_and_bot_bumps_are_only_weak():
    level, evidence = classify_activity(
        commits=[
            commit("docs: fix typo in README", 1, "a"),
            commit("chore(deps): bump requests from 2.31 to 2.32", 2, "b"),
            commit("Update badge", 3, "c"),
        ],
        as_of=AS_OF,
    )

    assert level == "WEAK"
    assert evidence["substantive_commits_recent"] == 0
    assert evidence["weak_commits_recent"] == 3


def test_no_real_activity_for_over_thirty_days_is_stale():
    level, evidence = classify_activity(
        commits=[commit("feat: old work", 95)], releases=[release(120)], as_of=AS_OF
    )

    assert level == "STALE"
    assert evidence["latest_commit_age_days"] == 95
    assert evidence["latest_release_age_days"] == 120


def test_no_evidence_at_all_is_unknown():
    level, evidence = classify_activity(as_of=AS_OF)

    assert level == "UNKNOWN"
    assert evidence["commits_seen"] == 0


def test_detect_areas_requires_central_evidence(app_config):
    areas = detect_areas(
        description="LLM agent framework with tool calling",
        topics=("ai-agents",),
        readme_text="# agent framework for llm orchestration",
        dependency_names=("langchain",),
        config=app_config,
    )

    assert areas == frozenset({"ai_agents"})


def test_detect_areas_ignores_isolated_readme_keyword(app_config):
    areas = detect_areas(
        description="ssh key helper",
        topics=("security",),
        readme_text="This tool talks to the ssh agent on your machine.",
        dependency_names=(),
        config=app_config,
    )

    assert "ai_agents" not in areas


def test_detect_areas_uses_dependencies(app_config):
    areas = detect_areas(
        description="pipeline runner",
        topics=(),
        readme_text=None,
        dependency_names=("airflow",),
        config=app_config,
    )

    assert areas == frozenset({"automation"})


def test_detect_areas_never_returns_unknown_areas(app_config):
    areas = detect_areas(
        description="crypto nft marketplace",
        topics=("crypto",),
        readme_text="bitcoin nft defi",
        dependency_names=(),
        config=app_config,
    )

    assert areas <= {"ai_agents", "automation", "data", "trading"}


def test_quality_signals_cover_structure_tests_docs_and_hygiene():
    signals = quality_signals(
        tree_paths=(
            "README.md", "LICENSE", "pyproject.toml", ".github/workflows/ci.yml",
            "src/main.py", "src/util.py", "tests/test_main.py", "examples/demo.py",
        ),
        readme_text="# project\n\n## Install\n\npip install project\n\n" + "x" * 900,
        has_license=True,
        has_ci=True,
        manifest_names=("pyproject.toml",),
    )

    prefixes = {signal.split(":", 1)[0] for signal in signals}
    assert {"structure", "implementation", "tests", "docs", "usability", "hygiene"} <= prefixes


def test_negative_signals_flag_missing_tests_docs_and_minimal_implementations():
    signals = negative_signals(
        tree_paths=("README.md", "main.py"),
        readme_text="# x",
        description="production-ready framework",
    )

    assert "no_tests" in signals
    assert "minimal_implementation" in signals
    assert "claim_implementation_mismatch" in signals


def test_negative_signals_empty_for_a_healthy_project():
    signals = negative_signals(
        tree_paths=(
            "README.md", "src/main.py", "src/core/engine.py", "tests/test_main.py", "LICENSE"
        ),
        readme_text="# project\n\n## Install\n\npip install project\n" + "y" * 400,
        description="workflow automation toolkit",
    )

    assert signals == ()
