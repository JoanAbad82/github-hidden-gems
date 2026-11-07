from __future__ import annotations

import csv
import hashlib
import io
import json
import socket
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from hidden_gems.reporting.artifacts import _CSV_FIELDS, _csv_row
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
from hidden_gems.reporting.artifacts import ScoredCandidateArtifact, write_run_artifacts


SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "run_candidates_v1.json"
EMPTY_JSON_SHA256 = "eafb49970bc03f7769b4dec275c5f38dcae320f1228c19b3d446f08872fcdb5a"
EMPTY_CSV_SHA256 = "adff72d4ccef33c85a543602839a91933f3389c1b3d79000cb4f642f33790da9"
UNICODE_JSON_SHA256 = "bf6fa1093ba1e13be0cf79296a5aa3aaa14dec812a65e2a9636910e6d8497c8e"
UNICODE_CSV_SHA256 = "23fb2d682f21777272e6a17c4ba24e4a60e3b24f64e2e7d637f2004c3379151f"


def _candidate(*, repo_id: int = 41, rank: int | None = 1) -> dict[str, Any]:
    return {
        "report_rank": rank,
        "selected_for_report": rank is not None,
        "repository": {
            "github_repo_id": repo_id,
            "owner": "josé",
            "name": "gema-💎",
            "full_name": "josé/gema-💎",
            "html_url": "https://github.com/josé/gema-💎",
            "description": "Útil — 日本語",
            "stars": 7,
            "created_at": "2026-10-10T00:00:00Z",
            "updated_at": None,
            "pushed_at": "2026-10-10T01:00:00Z",
            "primary_language": "Python",
            "topics": ["agents", "unicode-ñ"],
            "discovery_channels": ["SEARCH"],
            "matched_query_ids": ["q1"],
        },
        "score": {
            "total": 90,
            "relevance": 20,
            "quality": 20,
            "activity": 20,
            "visibility": 15,
            "novelty": 5,
            "originality": 5,
            "intersection": 5,
            "confidence": "HIGH",
            "score_version": "HIDDEN_GEM_SCORE_V1",
        },
        "notification": {
            "notify": True,
            "notification_type": "NEW_DISCOVERY",
            "trigger_fingerprint": "first:41",
            "previous_score": None,
            "current_score": 90,
        },
        "light_analysis": {
            "detected_areas": ["ai_agents"],
            "activity_level": "STRONG",
            "quality_signals": ["tests"],
            "negative_signals": [],
            "latest_release_tag": "v1.0.0",
            "latest_release_at": "2026-10-10T00:00:00Z",
            "latest_relevant_activity_at": "2026-10-10T01:00:00Z",
            "readme_hash": "readme",
            "tree_hash": "tree",
            "dependency_hash": "deps",
            "relevant_content_hash": "content",
            "evidence": {"note": "café"},
        },
        "deep_analysis": {
            "status": "OK",
            "source": "PROVIDER",
            "confidence": "MEDIUM",
            "relevance_suggestion": 15,
            "originality_suggestion": 4,
            "summary": "Résumé",
            "why_interesting": "Pequeño y útil",
            "risks": ["young project"],
            "evidence": {"path": "src/ação.py"},
        },
    }


def _payload(candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    records = [] if candidates is None else candidates
    return {
        "schema_version": "RUN_CANDIDATES_V1",
        "run": {
            "run_id": "RUN-UNICODE-001",
            "started_at": "2026-10-10T00:00:00Z",
            "dry_run": True,
            "config_version": "1.0.0",
            "score_version": "HIDDEN_GEM_SCORE_V1",
            "prompt_version": "DEEP_ANALYZER_PROMPT_V1",
            "result": "SUCCESS" if records else "SUCCESS_NO_FINDINGS",
            "counts": {"reported": sum(item["selected_for_report"] for item in records)},
            "errors": [],
        },
        "candidate_count": len(records),
        "reported_count": sum(item["selected_for_report"] for item in records),
        "candidates": records,
    }


def _write_pair(tmp_path: Path, payload: dict[str, Any]) -> tuple[Path, Path, bytes, bytes]:
    json_bytes = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in payload["candidates"]:
        writer.writerow(_csv_row(payload["run"]["run_id"], record))
    csv_bytes = output.getvalue().encode()
    json_path = tmp_path / "candidates.json"
    csv_path = tmp_path / "candidates.csv"
    json_path.write_bytes(json_bytes)
    csv_path.write_bytes(csv_bytes)
    return json_path, csv_path, json_bytes, csv_bytes


def _write_producer_pair(tmp_path: Path, *, include_unicode: bool) -> tuple[Path, Path, bytes, bytes]:
    started_at = datetime(2026, 10, 10, tzinfo=timezone.utc)
    context = RunContext(
        run_id="RUN-UNICODE-001",
        started_at=started_at,
        dry_run=True,
        config_version="1.0.0",
        score_version="HIDDEN_GEM_SCORE_V1",
        prompt_version="DEEP_ANALYZER_PROMPT_V1",
    )
    artifacts: tuple[ScoredCandidateArtifact, ...] = ()
    selected: tuple[SelectedFinding, ...] = ()
    if include_unicode:
        repo = RepositoryRef.from_full_name("acme/gema", 41)
        candidate = DiscoveryCandidate(
            repo=repo,
            description="Útil — 日本語",
            stars=7,
            created_at=started_at,
            updated_at=None,
            pushed_at=started_at,
            primary_language="Python",
            topics=("agents", "unicode-ñ"),
            discovery_channels={"SEARCH"},
            matched_query_ids={"q1"},
            default_branch="main",
        )
        light = LightAnalysis(
            repo=repo,
            detected_areas=frozenset({"ai_agents"}),
            activity_level="STRONG",
            quality_signals=("tests",),
            negative_signals=(),
            latest_release_tag="v1.0.0",
            latest_release_at=started_at,
            latest_relevant_activity_at=started_at,
            readme_hash="readme",
            tree_hash="tree",
            dependency_hash="deps",
            relevant_content_hash="content",
            evidence={"note": "café"},
        )
        deep = DeepAnalysis(
            repo=repo,
            status="OK",
            source="PROVIDER",
            confidence="MEDIUM",
            relevance_suggestion=15,
            originality_suggestion=4,
            summary="Résumé",
            why_interesting="Pequeño y útil",
            risks=("young project",),
            evidence={"path": "src/ação.py"},
        )
        score = HiddenGemScore(20, 20, 20, 15, 5, 5, 5, 90, "HIGH")
        decision = NotificationDecision(True, "NEW_DISCOVERY", "first:41", None, 90)
        artifact = ScoredCandidateArtifact(candidate, light, deep, score, decision)
        finding = SelectedFinding(repo, score, decision, "NEW_DISCOVERY", 1)
        artifacts = (artifact,)
        selected = (finding,)
    json_path, csv_path = write_run_artifacts(
        tmp_path,
        context=context,
        result="SUCCESS" if include_unicode else "SUCCESS_NO_FINDINGS",
        counts={"reported": len(selected)},
        errors=(),
        candidates=artifacts,
        selected=selected,
    )
    return json_path, csv_path, json_path.read_bytes(), csv_path.read_bytes()


def _validate(json_path: Path, csv_path: Path, **kwargs: str):
    from hidden_gems.experimental.replay_integrity import validate_run_pair

    return validate_run_pair(json_path, csv_path, SCHEMA_PATH, **kwargs)


def test_validates_empty_run_with_golden_result(tmp_path: Path) -> None:
    json_path, csv_path, json_bytes, csv_bytes = _write_producer_pair(tmp_path, include_unicode=False)

    result = _validate(json_path, csv_path)

    assert result.run_id == "RUN-UNICODE-001"
    assert result.candidate_count == 0
    assert result.reported_count == 0
    assert result.json_sha256 == hashlib.sha256(json_bytes).hexdigest()
    assert result.csv_sha256 == hashlib.sha256(csv_bytes).hexdigest()
    assert result.validated is True
    assert result.matched_expected_digests is False
    assert result.json_sha256 == EMPTY_JSON_SHA256
    assert result.csv_sha256 == EMPTY_CSV_SHA256
    assert csv_bytes == (",".join(_CSV_FIELDS) + "\n").encode()
    with pytest.raises((AttributeError, TypeError)):
        result.run_id = "changed"


def test_validates_nonempty_unicode_and_replays_deterministically(tmp_path: Path) -> None:
    json_path, csv_path, json_bytes, csv_bytes = _write_producer_pair(tmp_path, include_unicode=True)
    kwargs = {
        "expected_sha256_json": hashlib.sha256(json_bytes).hexdigest(),
        "expected_sha256_csv": hashlib.sha256(csv_bytes).hexdigest(),
    }

    first = _validate(json_path, csv_path, **kwargs)
    second = _validate(json_path, csv_path, **kwargs)

    assert first == second
    assert "Résumé".encode() in csv_bytes
    assert first.candidate_count == 1
    assert first.reported_count == 1
    assert first.matched_expected_digests is True
    assert first.json_sha256 == UNICODE_JSON_SHA256
    assert first.csv_sha256 == UNICODE_CSV_SHA256


def test_rejects_schema_byte_mismatch_before_jsonschema_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hidden_gems.experimental import replay_integrity

    json_path, csv_path, _, _ = _write_pair(tmp_path, _payload())
    schema_path = tmp_path / "schema.json"
    schema_path.write_bytes(SCHEMA_PATH.read_bytes() + b"\n")

    def fail_validation(*args: object, **kwargs: object) -> None:
        raise AssertionError("jsonschema validation ran before the schema digest check")

    monkeypatch.setattr(replay_integrity.jsonschema.Draft202012Validator, "check_schema", fail_validation)
    with pytest.raises(ValueError, match="schema SHA-256"):
        replay_integrity.validate_run_pair(json_path, csv_path, schema_path)


def test_remote_schema_ref_is_rejected_without_urllib_or_socket_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hidden_gems.experimental import replay_integrity

    json_path, csv_path, _, _ = _write_pair(tmp_path, _payload())
    schema_path = tmp_path / "schema.json"
    malicious_schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": "https://attacker.invalid/schema.json"}
    schema_bytes = (json.dumps(malicious_schema) + "\n").encode()
    schema_path.write_bytes(schema_bytes)
    monkeypatch.setattr(replay_integrity, "RUN_CANDIDATES_V1_SCHEMA_SHA256", hashlib.sha256(schema_bytes).hexdigest())
    calls = {"urllib": 0, "socket": 0}

    def fail_urllib(*args: object, **kwargs: object) -> None:
        calls["urllib"] += 1
        raise AssertionError("urllib network access attempted")

    def fail_socket(*args: object, **kwargs: object) -> None:
        calls["socket"] += 1
        raise AssertionError("socket network access attempted")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urllib)
    monkeypatch.setattr(socket, "create_connection", fail_socket)
    with pytest.raises(ValueError, match="schema reference"):
        replay_integrity.validate_run_pair(json_path, csv_path, schema_path)
    assert calls == {"urllib": 0, "socket": 0}


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef", "$recursiveRef"])
def test_rejects_nonfragment_schema_references_recursively(keyword: str) -> None:
    from hidden_gems.experimental.replay_integrity import ReplayIntegrityError, _validate_schema_references

    schema = {"$defs": {"safe": {"type": "string"}}, "allOf": [{keyword: "other.json#/$defs/safe"}]}
    with pytest.raises(ReplayIntegrityError, match="schema reference"):
        _validate_schema_references(schema)


def test_rejects_missing_local_schema_reference() -> None:
    from hidden_gems.experimental.replay_integrity import ReplayIntegrityError, _validate_schema_references

    with pytest.raises(ReplayIntegrityError, match="schema reference"):
        _validate_schema_references({"$defs": {}, "$ref": "#/$defs/missing"})


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_rejects_nonstandard_json_constants(tmp_path: Path, constant: str) -> None:
    json_path, csv_path, json_bytes, _ = _write_pair(tmp_path, _payload())
    json_path.write_bytes(json_bytes.replace(b'"SUCCESS_NO_FINDINGS"', constant.encode()))

    with pytest.raises(ValueError):
        _validate(json_path, csv_path)


def test_rejects_overflowed_float(tmp_path: Path) -> None:
    json_path, csv_path, json_bytes, _ = _write_pair(tmp_path, _payload())
    json_path.write_bytes(json_bytes.replace(b'"SUCCESS_NO_FINDINGS"', b"1e999"))

    with pytest.raises(ValueError):
        _validate(json_path, csv_path)


def test_rejects_duplicate_keys_at_nested_depth(tmp_path: Path) -> None:
    json_path, csv_path, json_bytes, _ = _write_pair(tmp_path, _payload())
    json_path.write_bytes(json_bytes.replace(b'"dry_run": true,', b'"dry_run": true,\n    "dry_run": false,'))

    with pytest.raises(ValueError, match="duplicate"):
        _validate(json_path, csv_path)


@pytest.mark.parametrize("bad_json", [b"\xff", b'{"schema_version":'])
def test_rejects_invalid_utf8_and_truncated_json(tmp_path: Path, bad_json: bytes) -> None:
    json_path, csv_path, _, _ = _write_pair(tmp_path, _payload())
    json_path.write_bytes(bad_json)

    with pytest.raises(ValueError):
        _validate(json_path, csv_path)


@pytest.mark.parametrize("mutation", ["truncate", "change", "reorder"])
def test_rejects_csv_tampering(tmp_path: Path, mutation: str) -> None:
    candidates = [_candidate(repo_id=41, rank=1), _candidate(repo_id=42, rank=None)]
    candidates[1]["repository"]["full_name"] = "acme/second"
    candidates[1]["repository"]["github_repo_id"] = 42
    json_path, csv_path, _, csv_bytes = _write_pair(tmp_path, _payload(candidates))
    if mutation == "truncate":
        changed = csv_bytes[:-4]
    elif mutation == "change":
        changed = csv_bytes.replace(b"Python", b"Rust", 1)
    else:
        lines = csv_bytes.splitlines(keepends=True)
        changed = b"".join([lines[0], lines[2], lines[1]])
    csv_path.write_bytes(changed)

    with pytest.raises(ValueError, match="CSV"):
        _validate(json_path, csv_path)


def _semantic_cases() -> list[tuple[str, dict[str, Any]]]:
    duplicate_repo = _payload([_candidate(repo_id=41, rank=1), _candidate(repo_id=41, rank=2)])
    duplicate_rank = _payload([_candidate(repo_id=41, rank=1), _candidate(repo_id=42, rank=1)])
    rank_gap = _payload([_candidate(repo_id=41, rank=2)])
    forged_rank = _payload([_candidate(repo_id=41, rank=1)])
    forged_rank["candidates"][0]["selected_for_report"] = False
    wrong_count = _payload([_candidate()])
    wrong_count["candidate_count"] = 2
    wrong_reported = _payload([_candidate()])
    wrong_reported["reported_count"] = 0
    return [
        ("duplicate repo id", duplicate_repo),
        ("duplicate rank", duplicate_rank),
        ("non-contiguous rank", rank_gap),
        ("forged report rank", forged_rank),
        ("candidate count", wrong_count),
        ("reported count", wrong_reported),
    ]


@pytest.mark.parametrize(("case", "payload"), _semantic_cases())
def test_rejects_semantic_adversarials(tmp_path: Path, case: str, payload: dict[str, Any]) -> None:
    json_path, csv_path, _, _ = _write_pair(tmp_path, deepcopy(payload))

    with pytest.raises(ValueError):
        _validate(json_path, csv_path)


def test_trusted_hash_rejects_coordinated_rewrite(tmp_path: Path) -> None:
    json_path, csv_path, original_json, original_csv = _write_pair(tmp_path, _payload([_candidate()]))
    changed = _payload([_candidate(repo_id=99)])
    _write_pair(tmp_path, changed)

    with pytest.raises(ValueError, match="SHA-256"):
        _validate(
            json_path,
            csv_path,
            expected_sha256_json=hashlib.sha256(original_json).hexdigest(),
            expected_sha256_csv=hashlib.sha256(original_csv).hexdigest(),
        )


@pytest.mark.parametrize("provided", ["json", "csv"])
def test_expected_digests_must_be_supplied_as_a_pair(tmp_path: Path, provided: str) -> None:
    json_path, csv_path, json_bytes, csv_bytes = _write_pair(tmp_path, _payload())
    kwargs = (
        {"expected_sha256_json": hashlib.sha256(json_bytes).hexdigest()}
        if provided == "json"
        else {"expected_sha256_csv": hashlib.sha256(csv_bytes).hexdigest()}
    )
    with pytest.raises(ValueError, match="pair"):
        _validate(json_path, csv_path, **kwargs)


def test_metadata_tampering_can_be_consistent_but_not_digest_matched(tmp_path: Path) -> None:
    original_json_path, original_csv_path, original_json, original_csv = _write_pair(
        tmp_path, _payload([_candidate()])
    )
    tampered = _payload([_candidate()])
    tampered["run"]["errors"] = ["concealed metadata rewrite"]
    json_path, csv_path, tampered_json, tampered_csv = _write_pair(tmp_path, tampered)

    consistency_only = _validate(json_path, csv_path)
    assert consistency_only.validated is True
    assert consistency_only.matched_expected_digests is False

    with pytest.raises(ValueError, match="SHA-256"):
        _validate(
            json_path,
            csv_path,
            expected_sha256_json=hashlib.sha256(original_json).hexdigest(),
            expected_sha256_csv=hashlib.sha256(original_csv).hexdigest(),
        )

    artifact_supplied = _validate(
        json_path,
        csv_path,
        expected_sha256_json=hashlib.sha256(tampered_json).hexdigest(),
        expected_sha256_csv=hashlib.sha256(tampered_csv).hexdigest(),
    )
    assert artifact_supplied.matched_expected_digests is True
    assert original_json_path == json_path
    assert original_csv_path == csv_path


def test_rejects_oversized_input(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from hidden_gems.experimental import replay_integrity

    json_path, csv_path, _, _ = _write_pair(tmp_path, _payload())
    monkeypatch.setattr(replay_integrity, "MAX_BYTES", 32)

    with pytest.raises(ValueError, match="size"):
        replay_integrity.validate_run_pair(json_path, csv_path, SCHEMA_PATH)


def test_validation_performs_no_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    json_path, csv_path, _, _ = _write_pair(tmp_path, _payload([_candidate()]))

    def fail_write(*args: object, **kwargs: object) -> None:
        raise AssertionError("validator attempted a write")

    monkeypatch.setattr(Path, "write_bytes", fail_write)
    monkeypatch.setattr(Path, "write_text", fail_write)
    assert _validate(json_path, csv_path).validated is True
