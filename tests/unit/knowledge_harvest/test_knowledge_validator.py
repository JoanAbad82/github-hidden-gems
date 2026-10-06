from __future__ import annotations

import pytest

from hidden_gems.knowledge_harvest.validator import (
    KnowledgeValidationError,
    evidence_status,
    validate_analysis,
)


MANIFEST = [
    {"id": "E01", "kind": "SOURCE"},
    {"id": "E02", "kind": "TEST"},
    {"id": "E03", "kind": "DOCUMENTATION"},
]


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
                "evidence_status": "IMPLEMENTED",
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
                "confidence": "HIGH",
                "evidence_status": "IMPLEMENTED",
                "evidence_refs": ["E01"],
            }
        ],
        "limitations": ["Runtime behavior was not executed."],
    }


def validate(candidate):
    return validate_analysis(
        candidate,
        evidence_manifest=MANIFEST,
        target_ids=["github-hidden-gems"],
    )


def test_evidence_status_is_deterministic():
    kinds = {item["id"]: item["kind"] for item in MANIFEST}
    assert evidence_status(["E03"], kinds) == "DOCUMENTED_ONLY"
    assert evidence_status(["E02"], kinds) == "PARTIAL_IMPLEMENTATION"
    assert evidence_status(["E01"], kinds) == "IMPLEMENTED"
    assert evidence_status(["E01", "E02"], kinds) == "IMPLEMENTED_TESTED"


def test_validator_accepts_grounded_analysis():
    result = validate(payload())
    assert result["patterns"][0]["id"] == "P01"


def test_validator_rejects_unknown_evidence_ref():
    candidate = payload()
    candidate["patterns"][0]["evidence_refs"] = ["E99"]
    with pytest.raises(KnowledgeValidationError, match="unknown evidence"):
        validate(candidate)


def test_validator_rejects_false_evidence_status():
    candidate = payload()
    candidate["patterns"][0]["evidence_status"] = "IMPLEMENTED_TESTED"
    with pytest.raises(KnowledgeValidationError, match="deterministic support"):
        validate(candidate)


def test_validator_rejects_unknown_target():
    candidate = payload()
    candidate["opportunities"][0]["target_project_id"] = "invented"
    with pytest.raises(KnowledgeValidationError, match="unknown target"):
        validate(candidate)


def test_apply_must_be_low_risk():
    candidate = payload()
    candidate["opportunities"][0]["action"] = "APPLY"
    candidate["opportunities"][0]["risk"] = "MEDIUM"
    with pytest.raises(KnowledgeValidationError, match="APPLY"):
        validate(candidate)


def test_apply_requires_source_and_test_evidence():
    candidate = payload()
    candidate["opportunities"][0]["action"] = "APPLY"
    with pytest.raises(KnowledgeValidationError, match="IMPLEMENTED_TESTED"):
        validate(candidate)


def test_apply_accepts_high_confidence_source_plus_test():
    candidate = payload()
    opportunity = candidate["opportunities"][0]
    opportunity["action"] = "APPLY"
    opportunity["evidence_refs"] = ["E01", "E02"]
    opportunity["evidence_status"] = "IMPLEMENTED_TESTED"
    result = validate(candidate)
    assert result["opportunities"][0]["action"] == "APPLY"
