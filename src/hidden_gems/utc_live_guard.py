"""Fail-closed UTC authorization window for the frozen V1 pilot.

Only used by the scheduled workflow; deliberately has no activation path.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

REPOSITORY = "JoanAbad82/github-hidden-gems"
BASELINE_MAIN_SHA = "4bf4de69a634a5a3a743ecbd63e5350e7b143106"  # audit provenance only
SCORING_SHA256 = "5c97f97fea0c27e09bd7b25f7798282206365b68badb3f9957a125973f98ec92"
WINDOW_START = datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc)
# Conservative producer cutoff (1h before legal end, 45m Actions job timeout).
PRODUCER_CUTOFF = datetime(2026, 11, 26, 23, 0, tzinfo=timezone.utc)
ABSOLUTE_END = datetime(2026, 11, 27, 0, 0, tzinfo=timezone.utc)


class UTCWindowDenied(RuntimeError):
    """No live side effect may proceed when the UTC pilot contract is unmet."""


def require_live_window(
    phase: str,
    *,
    now: datetime | None = None,
    environ: Mapping[str, str] | None = None,
) -> datetime:
    """Check a fresh clock and the immutable live-run identity at each boundary.

    GITHUB_SHA necessarily changes when this patch is deployed to main; the
    checked-out SHA is compared to the triggering SHA by the workflow.
    The scoring file is pinned by content SHA-256 instead of a stale commit.
    This is not an atomic transaction with GitHub's remote API.
    """
    e = os.environ if environ is None else environ
    if e.get("HIDDEN_GEMS_V1_UTC_GUARD") != "1":
        raise UTCWindowDenied("V1_UTC_GUARD_DISABLED")
    if e.get("GITHUB_ACTIONS") != "true" or e.get("GITHUB_EVENT_NAME") != "schedule":
        raise UTCWindowDenied("V1_UTC_EVENT_NOT_SCHEDULE")
    if e.get("GITHUB_REF") != "refs/heads/main":
        raise UTCWindowDenied("V1_UTC_WRONG_GIT_REF")
    if e.get("GITHUB_RUN_ATTEMPT") != "1":
        raise UTCWindowDenied("V1_UTC_RERUN_FORBIDDEN")
    if e.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise UTCWindowDenied("V1_UTC_WRONG_REPOSITORY")
    if not re.fullmatch(r"[0-9a-f]{40}", e.get("GITHUB_SHA") or ""):
        raise UTCWindowDenied("V1_UTC_MALFORMED_GITHUB_SHA")
    if e.get("LLM_ENABLED") != "false":
        raise UTCWindowDenied("V1_UTC_LLM_MUST_REMAIN_FALSE")
    scoring_path = Path(__file__).resolve().parents[2] / "config" / "scoring.yml"
    try:
        sha = hashlib.sha256(scoring_path.read_bytes()).hexdigest()
    except OSError:
        raise UTCWindowDenied("V1_UTC_SCORING_NOT_VERIFIABLE") from None
    if sha != SCORING_SHA256:
        raise UTCWindowDenied("V1_UTC_SCORING_SHA_DRIFT")
    at = datetime.now(timezone.utc) if now is None else now
    if at.tzinfo is None or at.utcoffset() is None:
        raise UTCWindowDenied("V1_UTC_NAIVE_CLOCK")
    utc = at.astimezone(timezone.utc)
    if not WINDOW_START <= utc < PRODUCER_CUTOFF:
        raise UTCWindowDenied("V1_UTC_OUTSIDE_PRODUCER_WINDOW")
    return utc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen V1 UTC live authorization barrier")
    parser.add_argument("--phase", required=True, choices=(
        "mode", "pre-run", "pre-stage", "pre-state", "pre-push"
    ))
    args = parser.parse_args(argv)
    at = require_live_window(args.phase)
    print(f"V1_UTC_GUARD=PASS phase={args.phase} utc={at.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
