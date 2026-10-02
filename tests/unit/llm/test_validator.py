"""Task 10: strict LLM_ANALYSIS_V1 schema validation."""

from __future__ import annotations

import json

import pytest

from hidden_gems.llm.validator import (
    LLMValidationError,
    SCHEMA_VERSION,
    normalize_evidence_item_lengths,
    to_deep_analysis,
    validate_llm_output,
)
from hidden_gems.models import RepositoryRef


def payload(**overrides) -> dict:
    base = {
        "summary": "A bounded automation toolkit that runs workflow definitions.",
        "why_interesting": "Unusually small implementation with real tests.",
        "relevance_suggestion": 12,
        "originality_suggestion": 3,
        "confidence": "MEDIUM",
        "risks": ["single maintainer"],
        "evidence": {
            "observed": ["pyproject.toml declares the package", "src/main.py defines the runtime"],
            "inferred": ["the project is early stage"],
            "unknown": ["runtime performance"],
        },
        "claims_supported": [{"claim": "workflow automation", "supported": True}],
    }
    base.update(overrides)
    return base


def test_valid_payload_is_accepted():
    assert validate_llm_output(json.dumps(payload()))["confidence"] == "MEDIUM"


def test_broken_json_is_rejected():
    with pytest.raises(LLMValidationError, match="not valid JSON"):
        validate_llm_output('{"summary": "unterminated')


def test_free_text_instead_of_object_is_rejected():
    with pytest.raises(LLMValidationError, match="must be a JSON object"):
        validate_llm_output('"Sure! Here is my analysis of the repository."')


def test_prose_instead_of_json_is_rejected():
    with pytest.raises(LLMValidationError, match="not valid JSON"):
        validate_llm_output("Sure! Here is my analysis of the repository.")


def test_missing_confidence_is_rejected():
    broken = payload()
    del broken["confidence"]
    with pytest.raises(LLMValidationError):
        validate_llm_output(broken)


@pytest.mark.parametrize(
    "field,value",
    [
        ("relevance_suggestion", 21),
        ("relevance_suggestion", -1),
        ("originality_suggestion", 11),
        ("confidence", "VERY_HIGH"),
    ],
)
def test_out_of_range_or_unknown_values_are_rejected(field, value):
    with pytest.raises(LLMValidationError):
        validate_llm_output(payload(**{field: value}))


def test_evidence_less_maximum_scores_are_rejected():
    thin = payload()
    thin["evidence"]["observed"] = ["README.md exists"]
    thin["relevance_suggestion"] = 20

    with pytest.raises(LLMValidationError, match="observed evidence"):
        validate_llm_output(thin)

    thin["relevance_suggestion"] = 12
    thin["originality_suggestion"] = 10
    with pytest.raises(LLMValidationError, match="observed evidence"):
        validate_llm_output(thin)


def test_empty_observed_evidence_is_rejected():
    broken = payload()
    broken["evidence"]["observed"] = []
    with pytest.raises(LLMValidationError):
        validate_llm_output(broken)


def test_unknown_confidence_and_null_suggestions_are_accepted():
    uncertain = payload(confidence="UNKNOWN", relevance_suggestion=None, originality_suggestion=None)

    validated = validate_llm_output(uncertain)
    analysis = to_deep_analysis(RepositoryRef.from_full_name("acme/repo", 1), validated)

    assert analysis.confidence == "LOW"
    assert analysis.relevance_suggestion is None
    assert analysis.status == "OK"


def test_unexpected_additional_fields_are_rejected():
    with pytest.raises(LLMValidationError):
        validate_llm_output(payload(score=95))


def test_to_deep_analysis_maps_evidence_and_risks():
    analysis = to_deep_analysis(
        RepositoryRef.from_full_name("acme/repo", 2), validate_llm_output(payload())
    )

    assert analysis.summary.startswith("A bounded automation toolkit")
    assert analysis.why_interesting
    assert analysis.risks == ("single maintainer",)
    assert analysis.evidence["observed"]
    assert analysis.evidence["claims_supported"][0]["supported"] is True
    assert analysis.source == "PROVIDER"


def test_schema_version_constant_is_frozen():
    assert SCHEMA_VERSION == "LLM_ANALYSIS_V1"


def test_overlong_observed_item_exposes_structured_max_length_constraint():
    broken = payload()
    broken["evidence"]["observed"] = [
        (
            "Parent pom.xml declares packaging 'pom' with modules common, "
            "s02-minimal-chat, s11-agent-loop, s12-tool-use, s13-permission, "
            "s14-hooks, s21-planning, s22-subagent, s23-memory, "
            "s24-context-compact, s25-error-recovery, s31-supervisor, "
            "s32-orchestrator, s33-protocol, s34-checkpoint, s35-taskboard, "
            "s36-bus, s41-tasksystem, s42-scheduler, s43-mcp, s44-capstone."
        )
    ]

    with pytest.raises(LLMValidationError) as caught:
        validate_llm_output(broken)

    exc = caught.value
    assert exc.path == "evidence/observed/0"
    assert exc.validator == "maxLength"
    assert exc.validator_value == 300
    assert "schema violation at evidence/observed/0" in str(exc)


def test_overlong_evidence_normalization_is_lossless_and_schema_valid():
    source = "A" * 299 + "BC" + "D" * 320
    broken = payload()
    broken["evidence"]["observed"] = [source]

    normalized, changed = normalize_evidence_item_lengths(broken)

    assert changed is True
    parts = normalized["evidence"]["observed"]
    assert all(len(part) <= 300 for part in parts)
    assert "".join(parts) == source
    assert validate_llm_output(normalized)["evidence"]["observed"] == parts


def test_evidence_normalization_fails_closed_when_max_items_would_be_exceeded():
    broken = payload()
    broken["evidence"]["observed"] = ["ok"] * 24 + ["X" * 301]

    with pytest.raises(LLMValidationError) as caught:
        normalize_evidence_item_lengths(broken)

    assert caught.value.path == "evidence/observed"
    assert caught.value.validator == "maxItems"
    assert caught.value.validator_value == 25
