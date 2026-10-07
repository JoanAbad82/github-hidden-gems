from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hidden_gems.knowledge_harvest.target_fit import (
    TargetFitError,
    fit_transfer_plan,
    validate_target_fit,
    write_target_fit_artifacts,
)


def _opportunity(
    opportunity_id: str,
    *,
    stage: str = "REQUIRES_LOCAL_EXPERIMENT",
    action: str = "EXPERIMENT",
    target: str = "project-a",
):
    return {
        "opportunity_id": opportunity_id,
        "target_project_id": target,
        "stage": stage,
        "priority_score": 400,
        "action": action,
        "title": "Guard mutable actions",
        "rationale": "Useful target-fit candidate.",
        "expected_benefit": "Safer state transitions.",
        "integration_cost": "LOW",
        "risk": "LOW",
        "confidence": "HIGH",
        "evidence_status": "IMPLEMENTED_TESTED" if action == "APPLY" else "IMPLEMENTED",
        "source_repo": "acme/source",
        "head_sha": "a" * 40,
        "source_evidence_digest": "b" * 64,
        "evidence_refs": ["E01"],
        "evidence": [],
    }


def _target(repository: str | None = "acme/target"):
    value = {
        "project_id": "project-a",
        "label": "Project A",
        "needs": ["safe autonomous operation", "state recovery"],
    }
    if repository:
        value["repository"] = repository
    return value


def _manifest():
    return [
        {"id": "E01", "kind": "SOURCE", "path": "src/guard.py"},
        {"id": "E02", "kind": "TEST", "path": "tests/test_guard.py"},
        {"id": "E03", "kind": "DOCUMENTATION", "path": "README.md"},
    ]


def _fit_result(opportunity_id: str, classification: str, **overrides):
    payload = {
        "opportunity_id": opportunity_id,
        "classification": classification,
        "fit_confidence": "HIGH",
        "rationale": "Grounded fit decision.",
        "matched_needs": ["safe autonomous operation"],
        "target_evidence_refs": ["E01"],
        "integration_surface": "src/guard.py",
    }
    payload.update(overrides)
    return {"results": [payload]}


def test_ready_to_transfer_requires_source_ready_stage():
    opportunity = _opportunity("KOP-" + "1" * 16)
    with pytest.raises(TargetFitError, match="cannot promote source stage"):
        validate_target_fit(
            _fit_result(opportunity["opportunity_id"], "READY_TO_TRANSFER"),
            opportunities=[opportunity],
            target=_target(),
            evidence_manifest=_manifest(),
        )


def test_ready_to_transfer_accepts_tested_apply_with_target_surface():
    opportunity = _opportunity(
        "KOP-" + "2" * 16,
        stage="READY_TO_TRANSFER",
        action="APPLY",
    )
    result = validate_target_fit(
        _fit_result(opportunity["opportunity_id"], "READY_TO_TRANSFER"),
        opportunities=[opportunity],
        target=_target(),
        evidence_manifest=_manifest(),
    )
    assert result["results"][0]["classification"] == "READY_TO_TRANSFER"


def test_already_present_requires_concrete_implementation_evidence():
    opportunity = _opportunity("KOP-" + "3" * 16)
    with pytest.raises(TargetFitError, match="SOURCE or CONFIG"):
        validate_target_fit(
            _fit_result(
                opportunity["opportunity_id"],
                "ALREADY_PRESENT",
                target_evidence_refs=["E03"],
            ),
            opportunities=[opportunity],
            target=_target(),
            evidence_manifest=_manifest(),
        )


def test_abstract_target_cannot_claim_ready_or_already_present():
    opportunity = _opportunity(
        "KOP-" + "4" * 16,
        stage="READY_TO_TRANSFER",
        action="APPLY",
    )
    with pytest.raises(TargetFitError, match="concrete target repository"):
        validate_target_fit(
            _fit_result(
                opportunity["opportunity_id"],
                "READY_TO_TRANSFER",
                target_evidence_refs=[],
            ),
            opportunities=[opportunity],
            target=_target(repository=None),
            evidence_manifest=[],
        )


def test_abstract_target_can_be_experiment_ready_from_declared_need():
    opportunity = _opportunity("KOP-" + "5" * 16)
    result = validate_target_fit(
        _fit_result(
            opportunity["opportunity_id"],
            "EXPERIMENT_READY",
            target_evidence_refs=[],
            integration_surface=None,
        ),
        opportunities=[opportunity],
        target=_target(repository=None),
        evidence_manifest=[],
    )
    assert result["results"][0]["classification"] == "EXPERIMENT_READY"


def test_watch_cannot_be_promoted_to_experiment():
    opportunity = _opportunity(
        "KOP-" + "6" * 16,
        stage="WATCH",
        action="WATCH",
    )
    with pytest.raises(TargetFitError, match="cannot promote source action"):
        validate_target_fit(
            _fit_result(opportunity["opportunity_id"], "EXPERIMENT_READY"),
            opportunities=[opportunity],
            target=_target(),
            evidence_manifest=_manifest(),
        )


def test_target_fit_requires_exact_result_ids():
    opportunity = _opportunity("KOP-" + "7" * 16)
    with pytest.raises(TargetFitError, match="ids mismatch"):
        validate_target_fit(
            _fit_result("KOP-" + "8" * 16, "NOT_APPLICABLE"),
            opportunities=[opportunity],
            target=_target(),
            evidence_manifest=_manifest(),
        )


def test_write_target_fit_artifacts_is_deterministic(tmp_path):
    payload = {
        "schema_version": "KNOWLEDGE_TARGET_FIT_RUN_V1",
        "fit_id": "KFG-" + "1" * 16,
        "plan_id": "KTP-" + "2" * 16,
        "source_run_id": "KH-TEST",
        "prompt_version": "TARGET_FIT_PROMPT_V1R1",
        "model": "deepseek-chat",
        "target_snapshots": [],
        "classification_counts": {
            "ALREADY_PRESENT": 0,
            "NOT_APPLICABLE": 0,
            "EXPERIMENT_READY": 1,
            "READY_TO_TRANSFER": 0,
        },
        "classified_count": 1,
        "requested_count": 1,
        "errors": [],
        "usage": {},
        "results": [
            {
                "opportunity_id": "KOP-" + "9" * 16,
                "target_project_id": "project-a",
                "classification": "EXPERIMENT_READY",
                "fit_confidence": "HIGH",
                "rationale": "Fits.",
                "matched_needs": ["safe autonomous operation"],
                "integration_surface": "src/guard.py",
                "target_evidence_refs": ["E01"],
                "target_evidence": [],
                "target_repository": "acme/target",
                "target_head_sha": "a" * 40,
                "target_evidence_digest": "b" * 64,
                "source_stage": "REQUIRES_LOCAL_EXPERIMENT",
                "source_action": "EXPERIMENT",
                "source_repo": "acme/source",
                "title": "Guard mutable actions",
                "priority_score": 400,
            }
        ],
    }
    first = write_target_fit_artifacts(tmp_path / "one", payload)
    second = write_target_fit_artifacts(tmp_path / "two", payload)
    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1].read_bytes() == second[1].read_bytes()
    assert [path.name for path in first[2]] == [path.name for path in second[2]]


def test_fit_transfer_plan_batches_by_target(monkeypatch, tmp_path):
    import hidden_gems.knowledge_harvest.target_fit as target_fit

    plan = {
        "schema_version": "KNOWLEDGE_TRANSFER_PLAN_V1",
        "plan_id": "KTP-" + "3" * 16,
        "source_run_id": "KH-TEST",
        "opportunities": [
            _opportunity("KOP-" + "a" * 16),
            _opportunity("KOP-" + "b" * 16),
        ],
    }
    registry = {
        "project-a": {
            "project_id": "project-a",
            "label": "Project A",
            "repository": "acme/target",
            "needs": ["safe autonomous operation"],
        }
    }
    monkeypatch.setattr(target_fit, "target_registry", lambda path=None: registry)
    monkeypatch.setattr(
        target_fit,
        "collect_repository_evidence",
        lambda github, repository: {
            "source": {
                "head_sha": "c" * 40,
                "evidence_digest": "d" * 64,
                "evidence_manifest": [
                    {
                        "id": "E01",
                        "kind": "SOURCE",
                        "path": "src/guard.py",
                        "blob_sha": "e" * 40,
                        "content_sha256": "f" * 64,
                    }
                ],
            },
            "documents": [],
        },
    )

    class Provider:
        prompt_version = "TARGET_FIT_PROMPT_V1R1"
        model = "fake"
        budget = SimpleNamespace(snapshot=lambda: {})

        def analyze(self, *, target, opportunities, target_evidence):
            assert len(opportunities) == 2
            return {
                "results": [
                    {
                        "opportunity_id": item["opportunity_id"],
                        "classification": "EXPERIMENT_READY",
                        "fit_confidence": "HIGH",
                        "rationale": "Fits target.",
                        "matched_needs": ["safe autonomous operation"],
                        "target_evidence_refs": ["E01"],
                        "integration_surface": "src/guard.py",
                    }
                    for item in opportunities
                ]
            }

    config = SimpleNamespace(root=tmp_path)
    result = fit_transfer_plan(
        config=config,
        github=object(),
        provider=Provider(),
        plan=plan,
    )
    assert result["requested_count"] == 2
    assert result["classified_count"] == 2
    assert result["classification_counts"]["EXPERIMENT_READY"] == 2
    assert result["errors"] == []



def test_target_fit_provider_accepts_valid_batched_response(app_config):
    from hidden_gems.knowledge_harvest.target_fit import TargetFitDeepSeekProvider
    from hidden_gems.llm.base import LLMBudget

    opportunity = _opportunity("KOP-" + "c" * 16)

    class Response:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                _fit_result(
                                    opportunity["opportunity_id"],
                                    "EXPERIMENT_READY",
                                )
                            )
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                },
            }

    class Client:
        def post(self, *args, **kwargs):
            return Response()

        def close(self):
            pass

    provider = TargetFitDeepSeekProvider(
        app_config,
        api_key="test-key",
        client=Client(),
        budget=LLMBudget(max_calls=2, max_budget=1.0),
    )
    evidence = {
        "source": {
            "evidence_manifest": _manifest(),
        },
        "documents": [],
    }

    result = provider.analyze(
        target=_target(),
        opportunities=[opportunity],
        target_evidence=evidence,
    )

    assert result["results"][0]["classification"] == "EXPERIMENT_READY"
    assert provider.budget.calls_made == 1
    assert provider.budget.failures == 0



def test_target_fit_payload_compacts_large_target_evidence(app_config):
    from hidden_gems.knowledge_harvest.target_fit import TargetFitDeepSeekProvider
    from hidden_gems.llm.base import LLMBudget

    class Client:
        def close(self):
            pass

    provider = TargetFitDeepSeekProvider(
        app_config,
        api_key="test-key",
        client=Client(),
        budget=LLMBudget(max_calls=2, max_budget=1.0),
    )
    evidence = {
        "source": {
            "evidence_manifest": [
                {
                    "id": f"E{index:02d}",
                    "kind": "SOURCE",
                    "path": f"src/file{index}.py",
                    "blob_sha": "a" * 40,
                    "content_sha256": "b" * 64,
                }
                for index in range(1, 13)
            ]
        },
        "documents": [
            {
                "id": f"E{index:02d}",
                "kind": "SOURCE",
                "path": f"src/file{index}.py",
                "blob_sha": "a" * 40,
                "content_sha256": "b" * 64,
                "untrusted_text": "x" * 6000,
            }
            for index in range(1, 13)
        ],
    }
    opportunities = [
        _opportunity(f"KOP-{index:016x}")
        for index in range(1, 7)
    ]

    payload = provider._payload(
        target=_target(),
        opportunities=opportunities,
        target_evidence=evidence,
        feedback=None,
    )

    assert provider.prompt_version == "TARGET_FIT_PROMPT_V1R1"
    assert len(payload["messages"][1]["content"]) <= 48_000
