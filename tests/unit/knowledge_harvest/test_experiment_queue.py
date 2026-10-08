from __future__ import annotations

import json

import pytest

from hidden_gems.knowledge_harvest.experiment_queue import (
    ExperimentQueueError,
    build_experiment_queue,
    build_experiment_result,
    queue_from_artifacts,
    write_experiment_queue,
    write_experiment_result,
)


def _plan():
    base = {
        "target_project_id": "github-hidden-gems",
        "priority_score": 410,
        "title": "Graceful degradation",
        "rationale": "Bounded experiment.",
        "expected_benefit": "Higher pipeline availability.",
        "integration_cost": "LOW",
        "risk": "LOW",
        "confidence": "HIGH",
        "evidence_status": "IMPLEMENTED",
        "source_repo": "acme/source",
        "head_sha": "a" * 40,
        "source_evidence_digest": "b" * 64,
        "evidence_refs": ["E01"],
        "evidence": [
            {
                "id": "E01",
                "kind": "SOURCE",
                "path": "src/source.py",
                "blob_sha": "c" * 40,
                "content_sha256": "d" * 64,
            }
        ],
    }
    experiment = dict(base)
    experiment.update(
        {
            "opportunity_id": "KOP-" + "1" * 16,
            "stage": "REQUIRES_LOCAL_EXPERIMENT",
            "action": "EXPERIMENT",
        }
    )
    already = dict(base)
    already.update(
        {
            "opportunity_id": "KOP-" + "2" * 16,
            "stage": "REQUIRES_LOCAL_EXPERIMENT",
            "action": "EXPERIMENT",
        }
    )
    abstract = dict(base)
    abstract.update(
        {
            "opportunity_id": "KOP-" + "3" * 16,
            "target_project_id": "GITHUB_PARA_IA",
            "stage": "REQUIRES_LOCAL_EXPERIMENT",
            "action": "EXPERIMENT",
        }
    )
    ready = dict(base)
    ready.update(
        {
            "opportunity_id": "KOP-" + "4" * 16,
            "stage": "READY_TO_TRANSFER",
            "action": "APPLY",
            "evidence_status": "IMPLEMENTED_TESTED",
        }
    )
    return {
        "schema_version": "KNOWLEDGE_TRANSFER_PLAN_V1",
        "plan_id": "KTP-" + "a" * 16,
        "source_run_id": "KH-TEST",
        "opportunities": [experiment, already, abstract, ready],
    }


def _fit():
    evidence = [
        {
            "id": "E01",
            "kind": "SOURCE",
            "path": "src/target.py",
            "blob_sha": "e" * 40,
            "content_sha256": "f" * 64,
        }
    ]

    def row(opportunity_id, classification, target="github-hidden-gems", repo=True):
        return {
            "opportunity_id": opportunity_id,
            "target_project_id": target,
            "classification": classification,
            "model_classification": classification,
            "applicable": True,
            "core_behavior_present": classification == "ALREADY_PRESENT",
            "fit_confidence": "HIGH",
            "rationale": "Grounded target fit.",
            "matched_needs": ["failure recovery"],
            "integration_surface": "src/target.py",
            "target_evidence_refs": ["E01"] if repo else [],
            "target_evidence": evidence if repo else [],
            "target_repository": "JoanAbad82/github-hidden-gems" if repo else None,
            "target_head_sha": "1" * 40 if repo else None,
            "target_evidence_digest": "2" * 64 if repo else None,
            "source_stage": "REQUIRES_LOCAL_EXPERIMENT",
            "source_action": "EXPERIMENT",
            "source_repo": "acme/source",
            "title": "Graceful degradation",
            "priority_score": 410,
        }

    ready = row("KOP-" + "4" * 16, "READY_TO_TRANSFER")
    ready["source_stage"] = "READY_TO_TRANSFER"
    ready["source_action"] = "APPLY"
    return {
        "schema_version": "KNOWLEDGE_TARGET_FIT_RUN_V1",
        "fit_id": "KFG-" + "b" * 16,
        "plan_id": "KTP-" + "a" * 16,
        "source_run_id": "KH-TEST",
        "results": [
            row("KOP-" + "1" * 16, "EXPERIMENT_READY"),
            row("KOP-" + "2" * 16, "ALREADY_PRESENT"),
            row("KOP-" + "3" * 16, "EXPERIMENT_READY", target="GITHUB_PARA_IA", repo=False),
            ready,
        ],
    }


def test_queue_keeps_only_actionable_concrete_targets():
    queue = build_experiment_queue(_plan(), _fit())

    assert queue["experiment_count"] == 2
    assert queue["deferred_count"] == 1
    assert queue["excluded_count"] == 1
    assert [item["gate_classification"] for item in queue["experiments"]] == [
        "READY_TO_TRANSFER",
        "EXPERIMENT_READY",
    ]
    assert queue["deferred"][0]["reason"] == "ABSTRACT_TARGET_NO_PINNED_REPOSITORY"
    assert queue["experiments"][0]["state"] == "QUEUED"
    assert queue["experiments"][0]["execution_policy"]["no_auto_merge"] is True


def test_queue_is_deterministic():
    first = build_experiment_queue(_plan(), _fit())
    second = build_experiment_queue(_plan(), _fit())

    assert first == second
    assert first["queue_id"] == second["queue_id"]
    assert first["experiments"][0]["experiment_id"] == second["experiments"][0]["experiment_id"]


def test_queue_filter_by_opportunity():
    queue = build_experiment_queue(
        _plan(),
        _fit(),
        opportunities=["KOP-" + "1" * 16],
    )
    assert queue["experiment_count"] == 1
    assert queue["experiments"][0]["opportunity_id"] == "KOP-" + "1" * 16


def test_queue_rejects_mismatched_plan():
    fit = _fit()
    fit["plan_id"] = "KTP-" + "c" * 16
    with pytest.raises(ExperimentQueueError, match="plan_id"):
        build_experiment_queue(_plan(), fit)


def test_queue_artifacts_are_byte_stable(tmp_path):
    queue = build_experiment_queue(_plan(), _fit())
    first = write_experiment_queue(tmp_path / "one", queue)
    second = write_experiment_queue(tmp_path / "two", queue)
    assert first[0].read_bytes() == second[0].read_bytes()
    assert first[1].read_bytes() == second[1].read_bytes()


def test_queue_from_artifacts_round_trip(tmp_path):
    plan = tmp_path / "knowledge_transfer_plan.json"
    fit = tmp_path / "knowledge_target_fit.json"
    plan.write_text(json.dumps(_plan()), encoding="utf-8")
    fit.write_text(json.dumps(_fit()), encoding="utf-8")

    result = queue_from_artifacts(
        plan_source=plan,
        fit_source=fit,
        output_dir=tmp_path / "queue",
    )

    assert result["queue"]["experiment_count"] == 2
    assert result["json_path"].exists()
    assert result["csv_path"].exists()


def test_experiment_result_is_schema_validated_and_persisted(tmp_path):
    queue = build_experiment_queue(
        _plan(),
        _fit(),
        opportunities=["KOP-" + "1" * 16],
    )
    experiment = queue["experiments"][0]
    result = build_experiment_result(
        queue=queue,
        experiment_id=experiment["experiment_id"],
        state="PASSED",
        observations=["Focused regression test demonstrates the expected behavior."],
        checks=[
            {
                "command": 'python -m pytest -m "not live"',
                "exit_code": 0,
                "result": "PASS",
            }
        ],
        falsifier_triggered=False,
        conclusion="The bounded local experiment passed.",
        experiment_head_sha="3" * 40,
        evidence_files=["tests/test_example.py"],
    )
    path = write_experiment_result(tmp_path, result)

    assert result["state"] == "PASSED"
    assert result["no_auto_merge"] is True
    assert json.loads(path.read_text(encoding="utf-8")) == result



def test_cli_queue_experiments(tmp_path, capsys):
    from hidden_gems.cli import main

    plan = tmp_path / "knowledge_transfer_plan.json"
    fit = tmp_path / "knowledge_target_fit.json"
    plan.write_text(json.dumps(_plan()), encoding="utf-8")
    fit.write_text(json.dumps(_fit()), encoding="utf-8")

    result = main(
        [
            "queue-experiments",
            "--from-plan",
            str(plan),
            "--from-fit",
            str(fit),
            "--output",
            str(tmp_path / "queue"),
            "--opportunity",
            "KOP-" + "1" * 16,
        ]
    )

    captured = capsys.readouterr().out
    assert result == 0
    assert "EXPERIMENT_QUEUE_READY=1" in captured
    assert "EXPERIMENT_QUEUE_DEFERRED=0" in captured
    assert "RESULT=EXPERIMENT_QUEUE_SUCCESS" in captured
