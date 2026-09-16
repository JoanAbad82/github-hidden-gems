"""Strict validation of LLM output against LLM_ANALYSIS_V1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError

from ..models import DeepAnalysis, RepositoryRef

PROMPT_VERSION = "DEEP_ANALYZER_PROMPT_V1R1"
SCHEMA_VERSION = "LLM_ANALYSIS_V1"

DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "llm_analysis_v1.json"

#: A maximum suggestion requires this many distinct observed evidence items.
MAX_SUGGESTION_MIN_EVIDENCE = 3

_CONFIDENCE_MAP = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "UNKNOWN": "LOW"}


class LLMValidationError(ValueError):
    """Raised when provider output is not a valid LLM_ANALYSIS_V1 object."""


def _schema(schema_path: Path | None = None) -> Mapping[str, Any]:
    path = Path(schema_path) if schema_path else DEFAULT_SCHEMA_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def validate_llm_output(payload: Any, *, schema_path: Path | None = None) -> dict[str, Any]:
    """Validate and normalize one provider answer. Never repairs silently."""

    if isinstance(payload, (bytes, str)):
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMValidationError(f"provider output is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, Mapping):
        raise LLMValidationError("provider output must be a JSON object")

    candidate = dict(payload)
    try:
        Draft202012Validator(_schema(schema_path)).validate(candidate)
    except JsonSchemaValidationError as exc:
        location = "/".join(str(part) for part in exc.absolute_path)
        raise LLMValidationError(f"schema violation at {location or '<root>'}: {exc.message}") from exc

    observed = candidate["evidence"].get("observed") or []
    relevance = candidate.get("relevance_suggestion")
    originality = candidate.get("originality_suggestion")
    if relevance == 20 and len(observed) < MAX_SUGGESTION_MIN_EVIDENCE:
        raise LLMValidationError("relevance_suggestion=20 requires at least three observed evidence items")
    if originality == 10 and len(observed) < MAX_SUGGESTION_MIN_EVIDENCE:
        raise LLMValidationError("originality_suggestion=10 requires at least three observed evidence items")
    return candidate


def to_deep_analysis(repo: RepositoryRef, payload: Mapping[str, Any]) -> DeepAnalysis:
    """Convert a validated payload into the canonical DeepAnalysis model."""

    evidence = dict(payload.get("evidence") or {})
    evidence["claims_supported"] = list(payload.get("claims_supported") or [])
    confidence = _CONFIDENCE_MAP.get(str(payload.get("confidence", "LOW")).upper(), "LOW")
    return DeepAnalysis(
        repo=repo,
        evidence=evidence,
        relevance_suggestion=payload.get("relevance_suggestion"),
        originality_suggestion=payload.get("originality_suggestion"),
        why_interesting=payload.get("why_interesting"),
        summary=payload.get("summary"),
        risks=tuple(payload.get("risks") or ()),
        confidence=confidence,
        status="OK",
        source="PROVIDER",
    )
