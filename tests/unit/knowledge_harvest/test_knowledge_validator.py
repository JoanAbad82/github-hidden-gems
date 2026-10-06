from __future__ import annotations

import pytest

from hidden_gems.knowledge_harvest.validator import (
    KnowledgeValidationError,
    validate_analysis,
)


def payload():
    return {
        "capabilities": ["durable state recovery"],
        "patterns": [
            {
                "id": "P01",
                "title": "Journal replay",
                "description": "Rebuild runtime state from an append-only journal.",
                "transferability": "HIGH",
                "confidence": "HIGH",
                "evidence_refs": ["E01"],
            }
        ],
        "lessons": [
            {
                "title": "One state owner",
                "lesson": "Assign each durable state surface a single source of truth.",
                "confidence": "HIGH",
                "evidence_refs": ["E01"],
            }
        ],
        "opportunities": [
            {
                "target_project_id": "github-hidden-gems",
                "action": "EXPERIMENT",
                "title": "Replayable harvest state",
                "rationale": "The evidence shows a recovery-oriented state model.",
                "expected_benefit": "More resilient interrupted runs.",
                "integration_cost": "MEDIUM",
                "risk": "LOW",
                "evidence_refs": ["E01"],
            }
        ],
        "limitations": ["Runtime behavior was not executed."],
    }


def test_validator_accepts_grounded_analysis():
    result = validate_analysis(
        payload(),
        evidence_ids=["E01"],
        target_ids=["github-hidden-gems"],
    )
    assert result["patterns"][0]["id"] == "P01"


def test_validator_rejects_unknown_evidence_ref():
    candidate = payload()
    candidate["patterns"][0]["evidence_refs"] = ["E99"]
    with pytest.raises(KnowledgeValidationError, match="unknown evidence"):
        validate_analysis(candidate, evidence_ids=["E01"], target_ids=["github-hidden-gems"])


def test_validator_rejects_unknown_target():
    candidate = payload()
    candidate["opportunities"][0]["target_project_id"] = "invented"
    with pytest.raises(KnowledgeValidationError, match="unknown target"):
        validate_analysis(candidate, evidence_ids=["E01"], target_ids=["github-hidden-gems"])


def test_apply_must_be_low_risk():
    candidate = payload()
    candidate["opportunities"][0]["action"] = "APPLY"
    candidate["opportunities"][0]["risk"] = "MEDIUM"
    with pytest.raises(KnowledgeValidationError, match="APPLY"):
        validate_analysis(candidate, evidence_ids=["E01"], target_ids=["github-hidden-gems"])
