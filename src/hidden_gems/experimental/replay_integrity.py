"""Read-only integrity checks for existing RUN_CANDIDATES_V1 artifacts.

The byte digests only provide cryptographic tamper evidence when compared with
values obtained from an independently trusted manifest.  Without that external
trust anchor, coordinated rewriting of both JSON and CSV cannot be detected
cryptographically; artifact-supplied hashes are deliberately never trusted.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import jsonschema

from hidden_gems.reporting.artifacts import _CSV_FIELDS, _csv_row


MAX_BYTES = 8 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


class ReplayIntegrityError(ValueError):
    """An artifact pair failed a closed integrity check."""


@dataclass(frozen=True, slots=True)
class RunPairAudit:
    """Immutable successful audit result."""

    run_id: str
    candidate_count: int
    reported_count: int
    json_sha256: str
    csv_sha256: str
    validated: bool = True


def validate_run_pair(
    json_path: Path | str,
    csv_path: Path | str,
    schema_path: Path | str,
    expected_sha256_json: str | None = None,
    expected_sha256_csv: str | None = None,
) -> RunPairAudit:
    """Validate and byte-replay one JSON/CSV artifact pair without writing."""

    json_bytes = _read_bounded(json_path, "JSON")
    csv_bytes = _read_bounded(csv_path, "CSV")
    schema_bytes = _read_bounded(schema_path, "schema")
    json_digest = hashlib.sha256(json_bytes).hexdigest()
    csv_digest = hashlib.sha256(csv_bytes).hexdigest()
    _check_digest("JSON", json_digest, expected_sha256_json)
    _check_digest("CSV", csv_digest, expected_sha256_csv)

    payload = _parse_object(json_bytes, "JSON artifact")
    schema = _parse_object(schema_bytes, "JSON schema")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(payload)
    except jsonschema.exceptions.SchemaError as exc:
        raise ReplayIntegrityError("invalid Draft 2020-12 schema") from exc
    except jsonschema.exceptions.ValidationError as exc:
        raise ReplayIntegrityError(f"JSON artifact does not match schema: {exc.message}") from exc

    run_id, candidate_count, reported_count = _validate_semantics(payload)
    expected_csv = _render_csv(run_id, payload["candidates"])
    if not hmac.compare_digest(csv_bytes, expected_csv):
        raise ReplayIntegrityError("CSV bytes do not exactly replay from JSON")

    return RunPairAudit(
        run_id=run_id,
        candidate_count=candidate_count,
        reported_count=reported_count,
        json_sha256=json_digest,
        csv_sha256=csv_digest,
    )


def _read_bounded(path: Path | str, label: str) -> bytes:
    try:
        with Path(path).open("rb") as handle:
            content = handle.read(MAX_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise ReplayIntegrityError(f"cannot read {label} input") from exc
    if len(content) > MAX_BYTES:
        raise ReplayIntegrityError(f"{label} input exceeds maximum size of {MAX_BYTES} bytes")
    return content


def _parse_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        text = content.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ReplayIntegrityError, OverflowError) as exc:
        if isinstance(exc, ReplayIntegrityError):
            raise
        raise ReplayIntegrityError(f"invalid strict UTF-8 {label}") from exc
    if not isinstance(value, dict):
        raise ReplayIntegrityError(f"{label} must contain a JSON object")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayIntegrityError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ReplayIntegrityError(f"non-finite JSON constant: {value}")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ReplayIntegrityError(f"overflowed or non-finite JSON number: {value}")
    return parsed


def _check_digest(label: str, actual: str, expected: str | None) -> None:
    if expected is None:
        return
    if not isinstance(expected, str) or _SHA256_PATTERN.fullmatch(expected) is None:
        raise ReplayIntegrityError(f"invalid trusted {label} SHA-256 digest")
    if not hmac.compare_digest(actual, expected.lower()):
        raise ReplayIntegrityError(f"trusted {label} SHA-256 digest mismatch")


def _validate_semantics(payload: dict[str, Any]) -> tuple[str, int, int]:
    candidates = payload["candidates"]
    candidate_count = payload["candidate_count"]
    reported_count = payload["reported_count"]
    run_id = payload["run"]["run_id"]
    if candidate_count != len(candidates):
        raise ReplayIntegrityError("candidate_count does not match candidates")

    repo_ids: set[int] = set()
    ranks: list[int] = []
    for candidate in candidates:
        repo_id = candidate["repository"]["github_repo_id"]
        if repo_id in repo_ids:
            raise ReplayIntegrityError("github_repo_id values must be unique")
        repo_ids.add(repo_id)
        rank = candidate["report_rank"]
        selected = candidate["selected_for_report"]
        if selected != (rank is not None):
            raise ReplayIntegrityError("selected_for_report does not match report_rank")
        if rank is not None:
            ranks.append(rank)

    if len(ranks) != len(set(ranks)):
        raise ReplayIntegrityError("selected report ranks must be unique")
    if sorted(ranks) != list(range(1, len(ranks) + 1)):
        raise ReplayIntegrityError("selected report ranks must be contiguous from one")
    if reported_count != len(ranks):
        raise ReplayIntegrityError("reported_count does not match selected candidates")
    counts = payload["run"]["counts"]
    if "reported" in counts and counts["reported"] != reported_count:
        raise ReplayIntegrityError("run reported count does not match reported_count")
    return run_id, candidate_count, reported_count


def _render_csv(run_id: str, candidates: Iterable[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for candidate in candidates:
        writer.writerow(_csv_row(run_id, candidate))
    return output.getvalue().encode("utf-8", errors="strict")


__all__ = [
    "MAX_BYTES",
    "ReplayIntegrityError",
    "RunPairAudit",
    "validate_run_pair",
]
