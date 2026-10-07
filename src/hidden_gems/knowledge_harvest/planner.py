"""Deterministic downstream planning for harvested knowledge."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

PLAN_SCHEMA_VERSION = "KNOWLEDGE_TRANSFER_PLAN_V1"
HANDOFF_SCHEMA_VERSION = "KNOWLEDGE_TARGET_HANDOFF_V1"
SUPPORTED_RUN_SCHEMA = "KNOWLEDGE_HARVEST_RUN_V1"

ACTION_WEIGHTS = {"APPLY": 400, "EXPERIMENT": 300, "WATCH": 100, "DISCARD": 0}
CONFIDENCE_WEIGHTS = {"HIGH": 30, "MEDIUM": 20, "LOW": 10}
EVIDENCE_WEIGHTS = {
    "IMPLEMENTED_TESTED": 40,
    "IMPLEMENTED": 30,
    "PARTIAL_IMPLEMENTATION": 20,
    "DOCUMENTED_ONLY": 10,
}
RISK_WEIGHTS = {"LOW": 30, "MEDIUM": 15, "HIGH": 0}
COST_WEIGHTS = {"LOW": 20, "MEDIUM": 10, "HIGH": 0}
STAGE_BY_ACTION = {
    "APPLY": "READY_TO_TRANSFER",
    "EXPERIMENT": "REQUIRES_LOCAL_EXPERIMENT",
    "WATCH": "WATCH",
    "DISCARD": "DISCARD",
}


def resolve_harvest_artifact(path: Path | str) -> Path:
    candidate = Path(path).expanduser().resolve()
    if candidate.is_file():
        return candidate
    if not candidate.is_dir():
        raise ValueError(f"harvest artifact not found: {candidate}")
    matches = sorted(candidate.rglob("knowledge_packets.json"))
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one knowledge_packets.json below {candidate}, found {len(matches)}"
        )
    return matches[0]


def load_harvest_artifact(path: Path | str) -> tuple[Path, dict[str, Any]]:
    artifact = resolve_harvest_artifact(path)
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SUPPORTED_RUN_SCHEMA:
        raise ValueError(
            f"unsupported harvest schema: {payload.get('schema_version') or '<missing>'}"
        )
    if not isinstance(payload.get("packets"), list):
        raise ValueError("harvest artifact packets must be an array")
    return artifact, payload


def build_transfer_plan(
    harvest: Mapping[str, Any],
    *,
    targets: Sequence[str] | None = None,
) -> dict[str, Any]:
    if harvest.get("schema_version") != SUPPORTED_RUN_SCHEMA:
        raise ValueError("unsupported harvest schema")

    target_filter = {
        str(value).strip() for value in (targets or []) if str(value).strip()
    }
    source_digest = _digest_json(harvest)
    opportunities: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    packets = sorted(
        (packet for packet in harvest.get("packets", []) if isinstance(packet, Mapping)),
        key=lambda packet: str((packet.get("source") or {}).get("full_name") or "").lower(),
    )
    for packet in packets:
        source = packet.get("source") or {}
        source_repo = str(source.get("full_name") or "")
        head_sha = str(source.get("head_sha") or "")
        evidence_digest = str(source.get("evidence_digest") or "")
        manifest = {
            str(item.get("id")): item
            for item in source.get("evidence_manifest", [])
            if isinstance(item, Mapping) and item.get("id")
        }

        for opportunity in packet.get("opportunities", []):
            if not isinstance(opportunity, Mapping):
                continue
            target = str(opportunity.get("target_project_id") or "")
            if target_filter and target not in target_filter:
                continue

            refs = sorted({str(value) for value in opportunity.get("evidence_refs", [])})
            evidence = []
            for ref in refs:
                item = manifest.get(ref)
                if item is None:
                    raise ValueError(f"{source_repo}: unknown evidence ref {ref}")
                evidence.append(
                    {
                        "id": ref,
                        "kind": str(item.get("kind") or ""),
                        "path": str(item.get("path") or ""),
                        "blob_sha": str(item.get("blob_sha") or ""),
                        "content_sha256": str(item.get("content_sha256") or ""),
                    }
                )

            canonical = {
                "source_repo": source_repo,
                "head_sha": head_sha,
                "target_project_id": target,
                "action": str(opportunity.get("action") or ""),
                "title": str(opportunity.get("title") or ""),
                "evidence_refs": refs,
            }
            opportunity_id = "KOP-" + _digest_json(canonical)[:16]
            if opportunity_id in seen_ids:
                continue
            seen_ids.add(opportunity_id)

            action = str(opportunity.get("action") or "")
            confidence = str(opportunity.get("confidence") or "")
            evidence_status = str(opportunity.get("evidence_status") or "")
            risk = str(opportunity.get("risk") or "")
            cost = str(opportunity.get("integration_cost") or "")
            score = (
                ACTION_WEIGHTS.get(action, -1000)
                + CONFIDENCE_WEIGHTS.get(confidence, 0)
                + EVIDENCE_WEIGHTS.get(evidence_status, 0)
                + RISK_WEIGHTS.get(risk, 0)
                + COST_WEIGHTS.get(cost, 0)
            )

            opportunities.append(
                {
                    "opportunity_id": opportunity_id,
                    "target_project_id": target,
                    "stage": STAGE_BY_ACTION.get(action, "UNKNOWN"),
                    "priority_score": score,
                    "action": action,
                    "title": str(opportunity.get("title") or ""),
                    "rationale": str(opportunity.get("rationale") or ""),
                    "expected_benefit": str(opportunity.get("expected_benefit") or ""),
                    "integration_cost": cost,
                    "risk": risk,
                    "confidence": confidence,
                    "evidence_status": evidence_status,
                    "source_repo": source_repo,
                    "head_sha": head_sha,
                    "source_evidence_digest": evidence_digest,
                    "evidence_refs": refs,
                    "evidence": evidence,
                }
            )

    opportunities.sort(key=_priority_sort_key)
    target_summaries = []
    for target in sorted({item["target_project_id"] for item in opportunities}):
        selected = [item for item in opportunities if item["target_project_id"] == target]
        target_summaries.append(
            {
                "target_project_id": target,
                "opportunity_count": len(selected),
                "ready_to_transfer": sum(
                    item["stage"] == "READY_TO_TRANSFER" for item in selected
                ),
                "requires_local_experiment": sum(
                    item["stage"] == "REQUIRES_LOCAL_EXPERIMENT" for item in selected
                ),
                "watch": sum(item["stage"] == "WATCH" for item in selected),
                "discard": sum(item["stage"] == "DISCARD" for item in selected),
            }
        )

    plan_basis = {
        "source_digest": source_digest,
        "source_run_id": str(harvest.get("run_id") or ""),
        "opportunity_ids": [item["opportunity_id"] for item in opportunities],
    }
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "source_schema_version": SUPPORTED_RUN_SCHEMA,
        "source_run_id": str(harvest.get("run_id") or ""),
        "source_digest": source_digest,
        "plan_id": "KTP-" + _digest_json(plan_basis)[:16],
        "priority_policy": {
            "action": dict(ACTION_WEIGHTS),
            "confidence": dict(CONFIDENCE_WEIGHTS),
            "evidence_status": dict(EVIDENCE_WEIGHTS),
            "risk": dict(RISK_WEIGHTS),
            "integration_cost": dict(COST_WEIGHTS),
        },
        "opportunity_count": len(opportunities),
        "target_count": len(target_summaries),
        "targets": target_summaries,
        "opportunities": opportunities,
    }


def write_transfer_plan(
    output_dir: Path | str,
    plan: Mapping[str, Any],
) -> tuple[Path, Path, list[Path]]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "knowledge_transfer_plan.json"
    csv_path = directory / "knowledge_transfer_plan.csv"
    targets_dir = directory / "targets"
    targets_dir.mkdir(parents=True, exist_ok=True)

    _atomic_write(json_path, _json_text(plan))

    fields = (
        "opportunity_id",
        "target_project_id",
        "stage",
        "priority_score",
        "action",
        "title",
        "source_repo",
        "head_sha",
        "confidence",
        "evidence_status",
        "risk",
        "integration_cost",
        "evidence_refs",
        "expected_benefit",
        "rationale",
    )
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for item in plan.get("opportunities", []):
        writer.writerow(
            {
                field: (
                    ";".join(item.get(field, []))
                    if field == "evidence_refs"
                    else item.get(field, "")
                )
                for field in fields
            }
        )
    _atomic_write(csv_path, buffer.getvalue())

    handoff_paths: list[Path] = []
    for target in plan.get("targets", []):
        target_id = str(target["target_project_id"])
        items = [
            item
            for item in plan.get("opportunities", [])
            if item.get("target_project_id") == target_id
        ]
        handoff = {
            "schema_version": HANDOFF_SCHEMA_VERSION,
            "plan_id": plan["plan_id"],
            "source_run_id": plan["source_run_id"],
            "source_digest": plan["source_digest"],
            "target_project_id": target_id,
            "opportunity_count": len(items),
            "opportunities": items,
        }
        path = targets_dir / _target_filename(target_id)
        _atomic_write(path, _json_text(handoff))
        handoff_paths.append(path)
    return json_path, csv_path, handoff_paths


def plan_from_artifact(
    source: Path | str,
    *,
    output_dir: Path | str | None = None,
    targets: Sequence[str] | None = None,
) -> dict[str, Any]:
    artifact, harvest = load_harvest_artifact(source)
    plan = build_transfer_plan(harvest, targets=targets)
    output = (
        Path(output_dir).expanduser().resolve()
        if output_dir is not None
        else artifact.parent / "transfer-plan"
    )
    json_path, csv_path, handoffs = write_transfer_plan(output, plan)
    return {
        "plan": plan,
        "json_path": json_path,
        "csv_path": csv_path,
        "handoff_paths": handoffs,
    }


def _priority_sort_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        -int(item.get("priority_score", 0)),
        str(item.get("target_project_id") or "").lower(),
        str(item.get("source_repo") or "").lower(),
        str(item.get("title") or "").lower(),
        str(item.get("opportunity_id") or ""),
    )


def _digest_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _target_filename(target: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", target.lower()).strip("-") or "target"
    suffix = hashlib.sha256(target.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{suffix}.json"


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
