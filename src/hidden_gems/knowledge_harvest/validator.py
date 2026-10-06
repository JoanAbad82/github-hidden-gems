"""Strict validation for KNOWLEDGE_ANALYSIS_V1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

ANALYSIS_SCHEMA_VERSION = "KNOWLEDGE_ANALYSIS_V1"
PACKET_SCHEMA_VERSION = "KNOWLEDGE_PACKET_V1"
PROMPT_VERSION = "KNOWLEDGE_HARVEST_PROMPT_V1"

DEFAULT_ANALYSIS_SCHEMA = Path(__file__).resolve().parents[3] / "schemas" / "knowledge_analysis_v1.json"
DEFAULT_TARGETS_PATH = Path(__file__).resolve().parents[3] / "config" / "knowledge_targets.json"


class KnowledgeValidationError(ValueError):
    pass


def load_targets(path: Path | None = None) -> dict[str, Any]:
    payload = json.loads((path or DEFAULT_TARGETS_PATH).read_text(encoding="utf-8"))
    targets = payload.get("targets")
    if not isinstance(targets, list) or not targets:
        raise KnowledgeValidationError("knowledge target registry is empty")
    ids: set[str] = set()
    for item in targets:
        if not isinstance(item, Mapping):
            raise KnowledgeValidationError("knowledge target must be an object")
        project_id = str(item.get("project_id") or "")
        if not project_id or project_id in ids:
            raise KnowledgeValidationError("knowledge target project_id must be unique and non-empty")
        ids.add(project_id)
    return payload


def validate_analysis(
    payload: Any,
    *,
    evidence_ids: Sequence[str],
    target_ids: Sequence[str],
    schema_path: Path | None = None,
) -> dict[str, Any]:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise KnowledgeValidationError(f"provider output is not JSON: {exc.msg}") from exc
    if not isinstance(payload, Mapping):
        raise KnowledgeValidationError("provider output must be an object")

    schema = json.loads((schema_path or DEFAULT_ANALYSIS_SCHEMA).read_text(encoding="utf-8"))
    candidate = dict(payload)
    try:
        Draft202012Validator(schema).validate(candidate)
    except JsonSchemaValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        raise KnowledgeValidationError(f"schema violation at {location}: {exc.message}") from exc

    allowed_evidence = set(str(value) for value in evidence_ids)
    allowed_targets = set(str(value) for value in target_ids)
    seen_pattern_ids: set[str] = set()

    for pattern in candidate.get("patterns", []):
        pattern_id = str(pattern["id"])
        if pattern_id in seen_pattern_ids:
            raise KnowledgeValidationError(f"duplicate pattern id: {pattern_id}")
        seen_pattern_ids.add(pattern_id)
        _validate_refs(pattern["evidence_refs"], allowed_evidence)

    for lesson in candidate.get("lessons", []):
        _validate_refs(lesson["evidence_refs"], allowed_evidence)

    for opportunity in candidate.get("opportunities", []):
        _validate_refs(opportunity["evidence_refs"], allowed_evidence)
        target = str(opportunity["target_project_id"])
        if target not in allowed_targets:
            raise KnowledgeValidationError(f"unknown target_project_id: {target}")
        if opportunity["action"] == "APPLY" and opportunity["risk"] != "LOW":
            raise KnowledgeValidationError("APPLY opportunities must have LOW risk")

    return candidate


def _validate_refs(values: Sequence[str], allowed: set[str]) -> None:
    refs = set(str(value) for value in values)
    unknown = sorted(refs - allowed)
    if unknown:
        raise KnowledgeValidationError(f"unknown evidence refs: {', '.join(unknown)}")
