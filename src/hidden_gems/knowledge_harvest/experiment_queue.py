"""Deterministic experiment queue built from canonical target-fit results."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

QUEUE_SCHEMA_VERSION = "EXPERIMENT_QUEUE_V1"
RESULT_SCHEMA_VERSION = "EXPERIMENT_RESULT_V1"
SUPPORTED_PLAN_SCHEMA = "KNOWLEDGE_TRANSFER_PLAN_V1"
SUPPORTED_FIT_SCHEMA = "KNOWLEDGE_TARGET_FIT_RUN_V1"

ACTIONABLE_CLASSIFICATIONS = ("EXPERIMENT_READY", "READY_TO_TRANSFER")
FINAL_STATES = ("PASSED", "FAILED", "REJECTED")

DEFAULT_QUEUE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "schemas" / "experiment_queue_v1.json"
)
DEFAULT_RESULT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "schemas" / "experiment_result_v1.json"
)

TARGET_VALIDATION_COMMANDS: dict[str, tuple[str, ...]] = {
    "JoanAbad82/github-hidden-gems": (
        'python -m pytest -m "not live"',
        "git diff --check",
    ),
}


class ExperimentQueueError(ValueError):
    pass


def resolve_named_artifact(path: Path | str, filename: str) -> Path:
    candidate = Path(path).expanduser().resolve()
    if candidate.is_file():
        if candidate.name != filename:
            raise ExperimentQueueError(
                f"expected {filename}, got {candidate.name}"
            )
        return candidate
    if not candidate.is_dir():
        raise ExperimentQueueError(f"artifact not found: {candidate}")
    matches = sorted(candidate.rglob(filename))
    if len(matches) != 1:
        raise ExperimentQueueError(
            f"expected exactly one {filename} below {candidate}, found {len(matches)}"
        )
    return matches[0]


def load_json_artifact(
    path: Path | str,
    *,
    filename: str,
    schema_version: str,
) -> tuple[Path, dict[str, Any]]:
    artifact = resolve_named_artifact(path, filename)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    if payload.get("schema_version") != schema_version:
        raise ExperimentQueueError(
            f"unsupported {filename} schema: {payload.get('schema_version') or '<missing>'}"
        )
    return artifact, payload


def build_experiment_queue(
    plan: Mapping[str, Any],
    fit: Mapping[str, Any],
    *,
    targets: Sequence[str] | None = None,
    opportunities: Sequence[str] | None = None,
) -> dict[str, Any]:
    if plan.get("schema_version") != SUPPORTED_PLAN_SCHEMA:
        raise ExperimentQueueError("unsupported transfer plan schema")
    if fit.get("schema_version") != SUPPORTED_FIT_SCHEMA:
        raise ExperimentQueueError("unsupported target-fit schema")
    if str(plan.get("plan_id") or "") != str(fit.get("plan_id") or ""):
        raise ExperimentQueueError("target-fit plan_id does not match transfer plan")

    target_filter = {
        str(value).strip()
        for value in (targets or [])
        if str(value).strip()
    }
    opportunity_filter = {
        str(value).strip()
        for value in (opportunities or [])
        if str(value).strip()
    }

    plan_by_id = {
        str(item.get("opportunity_id") or ""): dict(item)
        for item in plan.get("opportunities", [])
        if isinstance(item, Mapping) and item.get("opportunity_id")
    }

    experiments: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    excluded_count = 0

    fit_results = sorted(
        (
            dict(item)
            for item in fit.get("results", [])
            if isinstance(item, Mapping) and item.get("opportunity_id")
        ),
        key=lambda item: (
            str(item.get("target_project_id") or ""),
            -int(item.get("priority_score", 0)),
            str(item.get("opportunity_id") or ""),
        ),
    )

    for result in fit_results:
        opportunity_id = str(result["opportunity_id"])
        target_id = str(result.get("target_project_id") or "")
        if target_filter and target_id not in target_filter:
            continue
        if opportunity_filter and opportunity_id not in opportunity_filter:
            continue

        source = plan_by_id.get(opportunity_id)
        if source is None:
            raise ExperimentQueueError(
                f"target-fit opportunity missing from transfer plan: {opportunity_id}"
            )
        if target_id != str(source.get("target_project_id") or ""):
            raise ExperimentQueueError(
                f"{opportunity_id}: target_project_id mismatch between plan and fit"
            )

        classification = str(result.get("classification") or "")
        if classification not in ACTIONABLE_CLASSIFICATIONS:
            excluded_count += 1
            continue

        target_repository = result.get("target_repository")
        target_head_sha = result.get("target_head_sha")
        target_evidence_digest = result.get("target_evidence_digest")
        if not target_repository or not target_head_sha or not target_evidence_digest:
            deferred.append(
                {
                    "opportunity_id": opportunity_id,
                    "target_project_id": target_id,
                    "classification": classification,
                    "reason": "ABSTRACT_TARGET_NO_PINNED_REPOSITORY",
                }
            )
            continue

        source_evidence = [
            {
                "id": str(item.get("id") or ""),
                "kind": str(item.get("kind") or ""),
                "path": str(item.get("path") or ""),
                "blob_sha": str(item.get("blob_sha") or ""),
                "content_sha256": str(item.get("content_sha256") or ""),
            }
            for item in source.get("evidence", [])
            if isinstance(item, Mapping)
        ]
        target_evidence = [
            {
                "id": str(item.get("id") or ""),
                "kind": str(item.get("kind") or ""),
                "path": str(item.get("path") or ""),
                "blob_sha": str(item.get("blob_sha") or ""),
                "content_sha256": str(item.get("content_sha256") or ""),
            }
            for item in result.get("target_evidence", [])
            if isinstance(item, Mapping)
        ]

        experiment_basis = {
            "fit_id": str(fit.get("fit_id") or ""),
            "plan_id": str(plan.get("plan_id") or ""),
            "opportunity_id": opportunity_id,
            "classification": classification,
            "target_project_id": target_id,
            "target_repository": str(target_repository),
            "target_head_sha": str(target_head_sha),
            "target_evidence_digest": str(target_evidence_digest),
            "source_repo": str(source.get("source_repo") or ""),
            "source_head_sha": str(source.get("head_sha") or ""),
            "source_evidence_digest": str(source.get("source_evidence_digest") or ""),
        }
        experiment_id = "EXP-" + _digest_json(experiment_basis)[:16]
        expected_benefit = str(source.get("expected_benefit") or "").strip()
        title = str(source.get("title") or "").strip()
        target_label = str(target_repository)
        hypothesis = (
            f'Adapting "{title}" to {target_label} will produce the expected benefit: '
            f"{expected_benefit}"
        )
        invariant = (
            f"The bounded experiment must demonstrate the expected benefit on target commit "
            f"{target_head_sha} without weakening existing validation, provenance, or trust boundaries."
        )
        required_commands = list(
            TARGET_VALIDATION_COMMANDS.get(str(target_repository), ("git diff --check",))
        )
        success_criteria = [
            "A focused deterministic regression test demonstrates the intended behavior.",
            "All required target validation commands pass.",
            "No external repository code is cloned, installed, imported, built, tested, or executed.",
            "The experiment changes only the minimum local surface needed to test the hypothesis.",
        ]
        falsifier = (
            f"Reject the hypothesis if a focused local test cannot demonstrate: {expected_benefit} "
            "without weakening an existing invariant or causing any required validation command to fail."
        )
        rollback = (
            f"Discard the isolated experiment branch/worktree and retain only the immutable result artifact "
            f"for {experiment_id}; never merge automatically."
        )

        experiments.append(
            {
                "experiment_id": experiment_id,
                "opportunity_id": opportunity_id,
                "state": "QUEUED",
                "gate_classification": classification,
                "target_project_id": target_id,
                "target_repository": str(target_repository),
                "target_head_sha": str(target_head_sha),
                "target_evidence_digest": str(target_evidence_digest),
                "target_evidence": target_evidence,
                "source_repo": str(source.get("source_repo") or ""),
                "source_head_sha": str(source.get("head_sha") or ""),
                "source_evidence_digest": str(source.get("source_evidence_digest") or ""),
                "source_stage": str(source.get("stage") or ""),
                "source_action": str(source.get("action") or ""),
                "source_evidence_status": str(source.get("evidence_status") or ""),
                "source_evidence": source_evidence,
                "title": title,
                "hypothesis": hypothesis,
                "invariant_under_test": invariant,
                "integration_surface": result.get("integration_surface"),
                "expected_benefit": expected_benefit,
                "risk": str(source.get("risk") or ""),
                "integration_cost": str(source.get("integration_cost") or ""),
                "source_confidence": str(source.get("confidence") or ""),
                "fit_confidence": str(result.get("fit_confidence") or ""),
                "priority_score": int(source.get("priority_score", 0)),
                "required_validation_commands": required_commands,
                "success_criteria": success_criteria,
                "falsifier": falsifier,
                "rollback": rollback,
                "execution_policy": {
                    "isolated_branch": True,
                    "branch_prefix": f"experiment/{experiment_id.lower()}",
                    "no_auto_merge": True,
                    "no_external_code_execution": True,
                    "max_scope": "BOUNDED_LOCAL_EXPERIMENT",
                },
            }
        )

    experiments.sort(
        key=lambda item: (
            -int(item["priority_score"]),
            0 if item["gate_classification"] == "READY_TO_TRANSFER" else 1,
            str(item["target_project_id"]),
            str(item["opportunity_id"]),
        )
    )
    deferred.sort(
        key=lambda item: (
            str(item["target_project_id"]),
            str(item["opportunity_id"]),
        )
    )

    queue_basis = {
        "fit_id": str(fit.get("fit_id") or ""),
        "plan_id": str(plan.get("plan_id") or ""),
        "experiment_ids": [item["experiment_id"] for item in experiments],
        "deferred": deferred,
    }
    payload = {
        "schema_version": QUEUE_SCHEMA_VERSION,
        "queue_id": "EXQ-" + _digest_json(queue_basis)[:16],
        "fit_id": str(fit.get("fit_id") or ""),
        "plan_id": str(plan.get("plan_id") or ""),
        "source_run_id": str(fit.get("source_run_id") or plan.get("source_run_id") or ""),
        "eligible_classifications": list(ACTIONABLE_CLASSIFICATIONS),
        "experiment_count": len(experiments),
        "deferred_count": len(deferred),
        "excluded_count": excluded_count,
        "experiments": experiments,
        "deferred": deferred,
    }
    _validate_schema(payload, DEFAULT_QUEUE_SCHEMA_PATH, "experiment queue")
    return payload


def queue_from_artifacts(
    *,
    plan_source: Path | str,
    fit_source: Path | str,
    output_dir: Path | str | None = None,
    targets: Sequence[str] | None = None,
    opportunities: Sequence[str] | None = None,
) -> dict[str, Any]:
    plan_path, plan = load_json_artifact(
        plan_source,
        filename="knowledge_transfer_plan.json",
        schema_version=SUPPORTED_PLAN_SCHEMA,
    )
    fit_path, fit = load_json_artifact(
        fit_source,
        filename="knowledge_target_fit.json",
        schema_version=SUPPORTED_FIT_SCHEMA,
    )
    queue = build_experiment_queue(
        plan,
        fit,
        targets=targets,
        opportunities=opportunities,
    )
    output = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else fit_path.parent / "experiment-queue"
    )
    json_path, csv_path = write_experiment_queue(output, queue)
    return {
        "queue": queue,
        "json_path": json_path,
        "csv_path": csv_path,
        "plan_path": plan_path,
        "fit_path": fit_path,
    }


def write_experiment_queue(
    output_dir: Path | str,
    payload: Mapping[str, Any],
) -> tuple[Path, Path]:
    candidate = dict(payload)
    _validate_schema(candidate, DEFAULT_QUEUE_SCHEMA_PATH, "experiment queue")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "experiment_queue.json"
    csv_path = directory / "experiment_queue.csv"

    _atomic_write(json_path, _json_text(candidate))
    fields = (
        "experiment_id",
        "opportunity_id",
        "state",
        "gate_classification",
        "target_project_id",
        "target_repository",
        "target_head_sha",
        "source_repo",
        "source_head_sha",
        "title",
        "priority_score",
        "risk",
        "integration_cost",
        "source_confidence",
        "fit_confidence",
        "integration_surface",
        "expected_benefit",
    )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for item in candidate.get("experiments", []):
        writer.writerow(
            {
                field: item.get(field) if item.get(field) is not None else ""
                for field in fields
            }
        )
    _atomic_write(csv_path, buffer.getvalue())
    return json_path, csv_path


def build_experiment_result(
    *,
    queue: Mapping[str, Any],
    experiment_id: str,
    state: str,
    observations: Sequence[str],
    checks: Sequence[Mapping[str, Any]],
    falsifier_triggered: bool,
    conclusion: str,
    experiment_head_sha: str | None = None,
    evidence_files: Sequence[str] = (),
) -> dict[str, Any]:
    if state not in FINAL_STATES:
        raise ExperimentQueueError(
            f"final experiment state must be one of {', '.join(FINAL_STATES)}"
        )
    experiment = next(
        (
            item
            for item in queue.get("experiments", [])
            if isinstance(item, Mapping) and item.get("experiment_id") == experiment_id
        ),
        None,
    )
    if experiment is None:
        raise ExperimentQueueError(f"unknown experiment_id: {experiment_id}")

    payload = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "queue_id": str(queue.get("queue_id") or ""),
        "experiment_id": experiment_id,
        "opportunity_id": str(experiment.get("opportunity_id") or ""),
        "state": state,
        "target_repository": str(experiment.get("target_repository") or ""),
        "target_base_sha": str(experiment.get("target_head_sha") or ""),
        "experiment_head_sha": experiment_head_sha,
        "falsifier_triggered": bool(falsifier_triggered),
        "observations": [str(value) for value in observations],
        "checks": [dict(item) for item in checks],
        "conclusion": str(conclusion),
        "evidence_files": sorted(set(str(value) for value in evidence_files)),
        "no_auto_merge": True,
    }
    _validate_schema(payload, DEFAULT_RESULT_SCHEMA_PATH, "experiment result")
    return payload


def write_experiment_result(
    output_dir: Path | str,
    payload: Mapping[str, Any],
) -> Path:
    candidate = dict(payload)
    _validate_schema(candidate, DEFAULT_RESULT_SCHEMA_PATH, "experiment result")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{candidate['experiment_id'].lower()}-result.json"
    _atomic_write(path, _json_text(candidate))
    return path


def _validate_schema(
    payload: Mapping[str, Any],
    schema_path: Path,
    label: str,
) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        Draft202012Validator(schema).validate(dict(payload))
    except JsonSchemaValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise ExperimentQueueError(
            f"{label} schema violation at {location}: {exc.message}"
        ) from exc


def _digest_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
