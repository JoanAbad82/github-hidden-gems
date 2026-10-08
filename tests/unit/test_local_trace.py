from __future__ import annotations

import hashlib
import json

import pytest

from hidden_gems.local_trace import (
    TraceFormatError,
    append_trace_event,
    summarize_trace,
    trace_path_from_env,
)


def test_trace_is_disabled_without_explicit_path():
    assert trace_path_from_env({}) is None


def test_jsonl_trace_is_canonical_redacted_and_deterministically_summarized(tmp_path):
    path = tmp_path / "trace.jsonl"
    append_trace_event(
        path,
        event_type="RUN_STARTED",
        run_id="RUN-1",
        recorded_at="2026-10-08T16:00:00+00:00",
        payload={
            "dry_run": True,
            "llm_enabled": False,
            "controlled_live": True,
            "live_requested": False,
            "note": "token=super-secret-value",
        },
    )
    append_trace_event(
        path,
        event_type="RUN_FINISHED",
        run_id="RUN-1",
        recorded_at="2026-10-08T16:01:00+00:00",
        payload={
            "result": "SUCCESS_NO_FINDINGS",
            "dry_run": True,
            "report_published": False,
            "errors_count": 0,
            "counts": {"reported": 0, "discovered": 3},
        },
    )

    text = path.read_text(encoding="utf-8")
    assert "super-secret-value" not in text
    assert "[REDACTED]" in text

    first = summarize_trace(path)
    second = summarize_trace(path)
    assert first == second
    assert first["source_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert first["event_count"] == 2
    assert first["run_count"] == 1
    assert first["event_counts"] == {"RUN_FINISHED": 1, "RUN_STARTED": 1}
    assert first["result_counts"] == {"SUCCESS_NO_FINDINGS": 1}
    assert first["started_without_finish"] == []
    assert first["finished_without_start"] == []
    assert first["safety_summary"] == {
        "dry_run_starts": 1,
        "live_starts": 0,
        "llm_enabled_starts": 0,
        "controlled_live_starts": 1,
    }


def test_summarizer_exposes_incomplete_run_without_guessing(tmp_path):
    path = tmp_path / "trace.jsonl"
    append_trace_event(
        path,
        event_type="RUN_STARTED",
        run_id="RUN-INCOMPLETE",
        recorded_at="2026-10-08T16:00:00+00:00",
        payload={
            "dry_run": False,
            "llm_enabled": True,
            "controlled_live": False,
            "live_requested": True,
        },
    )

    summary = summarize_trace(path)

    assert summary["started_without_finish"] == ["RUN-INCOMPLETE"]
    assert summary["finished_without_start"] == []


def test_summarizer_rejects_malformed_or_unknown_events(tmp_path):
    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(TraceFormatError, match="invalid trace line 1"):
        summarize_trace(malformed)

    unknown = tmp_path / "unknown.jsonl"
    unknown.write_text(
        json.dumps(
            {
                "schema_version": "LOCAL_TRACE_EVENT_V1",
                "event_type": "UNKNOWN",
                "run_id": "RUN-1",
                "recorded_at": "2026-10-08T16:00:00+00:00",
                "payload": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(TraceFormatError, match="unsupported event_type"):
        summarize_trace(unknown)
