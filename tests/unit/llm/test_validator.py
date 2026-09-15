"""Task 10: strict LLM_ANALYSIS_V1 schema validation."""

from __future__ import annotations

import json

import pytest

from hidden_gems.llm.validator import (
    LLMValidationError,
    SCHEMA_VERSION,
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
