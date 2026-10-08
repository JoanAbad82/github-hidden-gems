from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

from hidden_gems.models import (
    DeepAnalysis,
    DiscoveryCandidate,
    HiddenGemScore,
    LightAnalysis,
    NotificationDecision,
    RepositoryRef,
    RunContext,
    SelectedFinding,
)
from hidden_gems.reporting.artifacts import (
    SCHEMA_VERSION,
    ScoredCandidateArtifact,
    read_run_artifact,
    write_run_artifacts,
)


NOW = datetime(2026, 10, 6, 13, 22, 2, tzinfo=timezone.utc)


def _artifact(repo_id: int, name: str, total: int) -> ScoredCandidateArtifact:
    repo = RepositoryRef.from_full_name(f"acme/{name}", repo_id)
    candidate = DiscoveryCandidate(
        repo=repo,
        description=f"{name} description",
        stars=repo_id % 20,
        created_at=NOW,
        updated_at=NOW,
        pushed_at=NOW,
        primary_language="Python",
        topics=("agents", "automation"),
        discovery_channels={"SEARCH"},
        matched_query_ids={"q2", "q1"},
        default_branch="main",
    )
    light = LightAnalysis(
        repo=repo,
        detected_areas=frozenset({"automation", "ai_agents"}),
        activity_level="STRONG",
        quality_signals=("tests", "manifest"),
        negative_signals=(),
        latest_release_tag="v1.0.0",
        latest_release_at=NOW,
        latest_relevant_activity_at=NOW,
        readme_hash=f"readme-{repo_id}",
        tree_hash=f"tree-{repo_id}",
        dependency_hash=f"deps-{repo_id}",
        relevant_content_hash=f"content-{repo_id}",
        evidence={"tree_paths": ["src/main.py", "tests/test_main.py"], "nested": {"b": 2, "a": 1}},
    )
    deep = DeepAnalysis(
        repo=repo,
        evidence={"observed": ["src/main.py"]},
        relevance_suggestion=15,
        originality_suggestion=4,
        why_interesting="Useful automation primitive.",
        summary="Compact automation repository.",
        risks=("young project",),
        confidence="MEDIUM",
        status="OK",
        source="PROVIDER",
    )
    score = HiddenGemScore(
        relevance=20,
        quality=20,
        activity=20,
        visibility=15,
        novelty=max(0, total - 85),
        originality=5,
        intersection=5,
        total=total,
        confidence="MEDIUM",
    )
    decision = NotificationDecision(
        notify=True,
        notification_type="NEW_DISCOVERY",
        trigger_fingerprint=f"first:{repo_id}",
        previous_score=None,
        current_score=total,
    )
    return ScoredCandidateArtifact(candidate, light, deep, score, decision)


def _context() -> RunContext:
    return RunContext(
        run_id="RUN-20261006T132202Z",
        started_at=NOW,
        dry_run=True,
        config_version="1.0.0",
        score_version="HIDDEN_GEM_SCORE_V1",
        prompt_version="DEEP_ANALYZER_PROMPT_V1",
    )


def test_run_artifacts_are_deterministic_and_ranked(tmp_path):
    lower = _artifact(2002, "lower", 85)
    higher = _artifact(2001, "higher", 90)
    selected = [
        SelectedFinding(
            repo=higher.candidate.repo,
            score=higher.score,
            decision=higher.decision,
            status="NEW_DISCOVERY",
            rank=1,
        )
    ]

    paths_a = write_run_artifacts(
        tmp_path,
        context=_context(),
        result="SUCCESS",
        counts={"reported": 1, "scored": 2},
        errors=(),
        candidates=[lower, higher],
        selected=selected,
    )
    bytes_a = tuple(path.read_bytes() for path in paths_a)

    paths_b = write_run_artifacts(
        tmp_path,
        context=_context(),
        result="SUCCESS",
        counts={"scored": 2, "reported": 1},
        errors=(),
        candidates=[higher, lower],
        selected=selected,
    )
    bytes_b = tuple(path.read_bytes() for path in paths_b)

    assert bytes_a == bytes_b

    payload = json.loads(paths_a[0].read_text(encoding="utf-8"))
    schema_path = Path(__file__).resolve().parents[3] / "schemas" / "run_candidates_v1.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["candidate_count"] == 2
    assert payload["reported_count"] == 1
    assert [item["repository"]["full_name"] for item in payload["candidates"]] == [
        "acme/higher",
        "acme/lower",
    ]
    assert payload["candidates"][0]["selected_for_report"] is True
    assert payload["candidates"][0]["report_rank"] == 1
    assert payload["candidates"][0]["light_analysis"]["evidence"]["nested"] == {"a": 1, "b": 2}

    with paths_a[1].open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [row["full_name"] for row in rows] == ["acme/higher", "acme/lower"]
    assert rows[0]["selected_for_report"] == "true"
    assert rows[0]["score_total"] == "90"


def test_empty_run_still_emits_both_artifacts(tmp_path):
    json_path, csv_path = write_run_artifacts(
        tmp_path,
        context=_context(),
        result="SUCCESS_NO_FINDINGS",
        counts={"scored": 0, "reported": 0},
        errors=(),
        candidates=(),
        selected=(),
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["candidate_count"] == 0
    assert payload["candidates"] == []
    assert csv_path.read_text(encoding="utf-8").startswith("run_id,report_rank,selected_for_report,")



def test_read_run_artifact_missing_is_fail_soft(tmp_path):
    result = read_run_artifact(tmp_path / "missing.json")

    assert result.status == "MISSING"
    assert result.payload is None
    assert result.error is None


def test_read_run_artifact_malformed_is_fail_soft(tmp_path):
    path = tmp_path / "candidates.json"
    path.write_text("{not-json", encoding="utf-8")

    result = read_run_artifact(path)

    assert result.status == "MALFORMED"
    assert result.payload is None
    assert result.error.startswith("JSONDecodeError:")


def test_read_run_artifact_schema_mismatch_is_fail_soft(tmp_path):
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps({"schema_version": "RUN_CANDIDATES_V0", "candidates": []}),
        encoding="utf-8",
    )

    result = read_run_artifact(path)

    assert result.status == "SCHEMA_MISMATCH"
    assert result.payload is None
    assert result.error


def test_read_run_artifact_valid_snapshot_round_trip(tmp_path):
    json_path, _ = write_run_artifacts(
        tmp_path,
        context=_context(),
        result="SUCCESS_NO_FINDINGS",
        counts={"scored": 0, "reported": 0},
        errors=(),
        candidates=(),
        selected=(),
    )

    result = read_run_artifact(json_path)

    assert result.status == "OK"
    assert result.payload is not None
    assert result.payload["schema_version"] == "RUN_CANDIDATES_V1"
    assert result.payload["candidate_count"] == 0
