"""Opt-in local JSONL observability for bounded pipeline run metadata."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .common.logging import redact

TRACE_ENV_VAR = "HIDDEN_GEMS_TRACE_JSONL"
TRACE_SCHEMA_VERSION = "LOCAL_TRACE_EVENT_V1"
SUMMARY_SCHEMA_VERSION = "LOCAL_TRACE_SUMMARY_V1"
_ALLOWED_EVENT_TYPES = {"RUN_STARTED", "RUN_FINISHED"}


class TraceFormatError(ValueError):
    """Raised when a local trace cannot be deterministically summarized."""


def trace_path_from_env(environ: Mapping[str, str] | None = None) -> Path | None:
    """Return the explicitly configured local trace path, or None when disabled."""

    source = os.environ if environ is None else environ
    value = str(source.get(TRACE_ENV_VAR) or "").strip()
    if not value:
        return None
    return Path(value).expanduser().resolve()


def append_trace_event(
    path: Path | str,
    *,
    event_type: str,
    run_id: str,
    recorded_at: str,
    payload: Mapping[str, Any],
) -> None:
    """Append one canonical, redacted JSONL event to a local file."""

    if event_type not in _ALLOWED_EVENT_TYPES:
        raise TraceFormatError(f"unsupported trace event_type: {event_type}")
    if not str(run_id).strip():
        raise TraceFormatError("trace run_id is required")
    if not str(recorded_at).strip():
        raise TraceFormatError("trace recorded_at is required")

    event = {
        "schema_version": TRACE_SCHEMA_VERSION,
        "event_type": event_type,
        "run_id": str(run_id),
        "recorded_at": str(recorded_at),
        "payload": _safe_value(dict(payload)),
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(
                event,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )


def summarize_trace(path: Path | str) -> dict[str, Any]:
    """Summarize a local trace deterministically from its exact bytes."""

    source = Path(path)
    raw = source.read_bytes()
    events: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(raw.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            item = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TraceFormatError(
                f"invalid trace line {line_number}: {type(exc).__name__}"
            ) from exc
        _validate_event(item, line_number=line_number)
        events.append(item)

    event_counts: dict[str, int] = {}
    result_counts: dict[str, int] = {}
    run_ids: set[str] = set()
    started_runs: set[str] = set()
    finished_runs: set[str] = set()
    dry_run_starts = 0
    live_starts = 0
    llm_enabled_starts = 0
    controlled_live_starts = 0

    for event in events:
        event_type = str(event["event_type"])
        run_id = str(event["run_id"])
        payload = event["payload"]
        run_ids.add(run_id)
        event_counts[event_type] = event_counts.get(event_type, 0) + 1

        if event_type == "RUN_STARTED":
            started_runs.add(run_id)
            if payload.get("dry_run") is True:
                dry_run_starts += 1
            elif payload.get("dry_run") is False:
                live_starts += 1
            if payload.get("llm_enabled") is True:
                llm_enabled_starts += 1
            if payload.get("controlled_live") is True:
                controlled_live_starts += 1
        elif event_type == "RUN_FINISHED":
            finished_runs.add(run_id)
            result = str(payload.get("result") or "")
            if result:
                result_counts[result] = result_counts.get(result, 0) + 1

    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "event_count": len(events),
        "run_count": len(run_ids),
        "run_ids": sorted(run_ids),
        "event_counts": dict(sorted(event_counts.items())),
        "result_counts": dict(sorted(result_counts.items())),
        "started_without_finish": sorted(started_runs - finished_runs),
        "finished_without_start": sorted(finished_runs - started_runs),
        "safety_summary": {
            "dry_run_starts": dry_run_starts,
            "live_starts": live_starts,
            "llm_enabled_starts": llm_enabled_starts,
            "controlled_live_starts": controlled_live_starts,
        },
    }


def _validate_event(value: Any, *, line_number: int) -> None:
    if not isinstance(value, dict):
        raise TraceFormatError(f"invalid trace line {line_number}: event must be an object")
    required = {"schema_version", "event_type", "run_id", "recorded_at", "payload"}
    if set(value) != required:
        raise TraceFormatError(
            f"invalid trace line {line_number}: unexpected event shape"
        )
    if value.get("schema_version") != TRACE_SCHEMA_VERSION:
        raise TraceFormatError(
            f"invalid trace line {line_number}: unsupported schema_version"
        )
    if value.get("event_type") not in _ALLOWED_EVENT_TYPES:
        raise TraceFormatError(
            f"invalid trace line {line_number}: unsupported event_type"
        )
    if not isinstance(value.get("run_id"), str) or not value["run_id"]:
        raise TraceFormatError(f"invalid trace line {line_number}: run_id")
    if not isinstance(value.get("recorded_at"), str) or not value["recorded_at"]:
        raise TraceFormatError(f"invalid trace line {line_number}: recorded_at")
    if not isinstance(value.get("payload"), dict):
        raise TraceFormatError(f"invalid trace line {line_number}: payload")


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    return redact(str(value))
