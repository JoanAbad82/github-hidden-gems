"""Task 5 contract checks against the frozen SPEC_V1 rules.

These complement `test_hard_filter.py` (owned by the filtering implementer) and
pin the behaviours the spec states explicitly: trivial-fork/archive/empty
rejection, thematic false-positive protection (ssh agent != AI agent), the
"never reject for low stars / one contributor / no releases" rule, the
two-weak-signal rule for semantic categories, and determinism.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hidden_gems.filtering import FilterEvidence
from hidden_gems.filtering.hard_filter import evaluate_candidate, is_irrelevant
from hidden_gems.github.repositories import payload_to_candidate

CASES_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "repos" / "hard_filter_cases.json"
FIXTURES = json.loads(CASES_PATH.read_text(encoding="utf-8"))


def build(case_name: str):
    case = FIXTURES[case_name]
    candidate = payload_to_candidate(case["payload"])
    assert candidate is not None, case_name
    evidence_payload = case.get("evidence")
    evidence = FilterEvidence(**evidence_payload) if evidence_payload else None
    return candidate, evidence


@pytest.mark.parametrize(
    "case_name,expected",
    [
        ("archived_real_project", "REJECT_ARCHIVED"),
        ("trivial_fork", "REJECT_FORK"),
        ("empty_shell", "REJECT_EMPTY"),
        ("tutorial_notebook", "REJECT_TUTORIAL"),
        ("demo_showcase", "REJECT_DEMO"),
        ("ssh_agent_false_positive", "REJECT_IRRELEVANT"),
        ("zero_star_real_project", None),
        ("one_contributor_real_project", None),
        ("new_real_project", None),
    ],
)
def test_frozen_rejection_codes(app_config, case_name, expected):
    candidate, evidence = build(case_name)

    decision = evaluate_candidate(candidate, evidence, config=app_config)

    assert decision.reason_code == expected


def test_rejection_decisions_are_explainable(app_config):
    candidate, evidence = build("tutorial_notebook")

    decision = evaluate_candidate(candidate, evidence, config=app_config)

    assert decision.reason_code == "REJECT_TUTORIAL"
    assert decision.evidence


def test_zero_stars_is_never_a_rejection_reason(app_config):
    candidate, _ = build("zero_star_real_project")

    assert candidate.stars == 0
    assert evaluate_candidate(candidate, config=app_config).passed is True


def test_single_contributor_and_missing_releases_are_not_rejection_reasons(app_config):
    candidate, _ = build("one_contributor_real_project")

    assert evaluate_candidate(candidate, config=app_config).passed is True


def test_low_priority_language_and_youth_are_not_rejection_reasons(app_config):
    candidate, _ = build("new_real_project")
    candidate.primary_language = "Haskell"

    assert evaluate_candidate(candidate, config=app_config).passed is True


def test_ssh_agent_is_not_treated_as_an_ai_agent(app_config):
    candidate, evidence = build("ssh_agent_false_positive")

    assert is_irrelevant(candidate, evidence, config=app_config) is True


def test_agent_with_llm_companion_terms_is_relevant(app_config):
    candidate, evidence = build("ssh_agent_false_positive")
    candidate.description = "LLM agent framework with tool calling and RAG"
    candidate.topics = ("ai-agents", "llm")

    assert is_irrelevant(candidate, evidence, config=app_config) is False


def test_semantic_categories_need_two_independent_signals(app_config):
    candidate, _ = build("new_real_project")
    candidate.description = "A tutorial for workflow automation"
    assert evaluate_candidate(candidate, config=app_config).passed is True

    evidence = FilterEvidence(
        tree_paths=("README.md", "lesson-01.ipynb", "lesson-02.ipynb"),
        readme_text="This tutorial explains every lesson step by step.",
    )
    assert evaluate_candidate(candidate, evidence, config=app_config).reason_code == "REJECT_TUTORIAL"


def test_empty_size_without_content_is_rejected_but_readable_project_is_not(app_config):
    empty, _ = build("empty_shell")
    tiny, _ = build("zero_star_real_project")
    tiny.size_kb = 3

    assert evaluate_candidate(empty, config=app_config).reason_code == "REJECT_EMPTY"
    assert (
        evaluate_candidate(
            tiny, FilterEvidence(tree_paths=("README.md", "src/forge.py")), config=app_config
        ).reason_code
        is None
    )


def test_filter_is_deterministic(app_config):
    candidate, evidence = build("new_real_project")

    assert evaluate_candidate(candidate, evidence, config=app_config) == evaluate_candidate(
        candidate, evidence, config=app_config
    )
