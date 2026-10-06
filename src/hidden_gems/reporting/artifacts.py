"""Deterministic machine-readable artifacts for each discovery run."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..models import (
    DeepAnalysis,
    DiscoveryCandidate,
    HiddenGemScore,
    LightAnalysis,
    NotificationDecision,
    RunContext,
    SelectedFinding,
)

SCHEMA_VERSION = "RUN_CANDIDATES_V1"

_CONFIDENCE_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

_CSV_FIELDS = (
    "run_id",
    "report_rank",
    "selected_for_report",
    "github_repo_id",
    "full_name",
    "html_url",
    "stars",
    "created_at",
    "updated_at",
    "pushed_at",
    "primary_language",
    "topics",
    "discovery_channels",
    "matched_query_ids",
    "areas",
    "activity_level",
    "score_total",
    "score_relevance",
    "score_quality",
    "score_activity",
    "score_visibility",
    "score_novelty",
    "score_originality",
    "score_intersection",
    "score_confidence",
    "score_version",
    "notify",
    "notification_type",
    "previous_score",
    "current_score",
    "deep_status",
    "deep_source",
    "deep_confidence",
    "deep_summary",
    "why_interesting",
    "risks_json",
    "light_evidence_json",
    "deep_evidence_json",
)


@dataclass(frozen=True)
class ScoredCandidateArtifact:
    """One scored candidate captured before report selection."""

    candidate: DiscoveryCandidate
    light: LightAnalysis
    deep: DeepAnalysis | None
    score: HiddenGemScore
    decision: NotificationDecision


def artifact_paths(root: Path | str, run_id: str) -> tuple[Path, Path]:
    directory = Path(root) / "artifacts" / str(run_id)
    return directory / "candidates.json", directory / "candidates.csv"


def write_run_artifacts(
    root: Path | str,
    *,
    context: RunContext,
    result: str,
    counts: Mapping[str, int],
    errors: Sequence[str],
    candidates: Sequence[ScoredCandidateArtifact],
    selected: Sequence[SelectedFinding],
) -> tuple[Path, Path]:
    """Write canonical JSON and CSV snapshots for one pipeline execution."""

    json_path, csv_path = artifact_paths(root, context.run_id)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    selected_ranks = {
        finding.repo.github_repo_id: int(finding.rank)
        for finding in selected
    }
    ordered = sorted(candidates, key=_ordering_key)
    records = [
        _record(item, report_rank=selected_ranks.get(item.candidate.repo.github_repo_id))
        for item in ordered
    ]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "run": {
            "run_id": context.run_id,
            "started_at": _iso(context.started_at),
            "dry_run": bool(context.dry_run),
            "config_version": context.config_version,
            "score_version": context.score_version,
            "prompt_version": context.prompt_version,
            "result": result,
            "counts": {key: int(value) for key, value in sorted(counts.items())},
            "errors": [str(value) for value in errors],
        },
        "candidate_count": len(records),
        "reported_count": len(selected_ranks),
        "candidates": records,
    }
    _atomic_write(
        json_path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(_csv_row(context.run_id, record))
    _atomic_write(csv_path, buffer.getvalue())
    return json_path, csv_path


def _ordering_key(item: ScoredCandidateArtifact) -> tuple:
    score = item.score
    return (
        -score.total,
        _CONFIDENCE_RANK.get(score.confidence, len(_CONFIDENCE_RANK)),
        -score.novelty,
        -score.visibility,
        -score.activity,
        item.candidate.repo.github_repo_id,
    )


def _record(item: ScoredCandidateArtifact, *, report_rank: int | None) -> dict[str, Any]:
    candidate = item.candidate
    light = item.light
    deep = item.deep
    score = item.score
    decision = item.decision
    return {
        "report_rank": report_rank,
        "selected_for_report": report_rank is not None,
        "repository": {
            "github_repo_id": candidate.repo.github_repo_id,
            "owner": candidate.repo.owner,
            "name": candidate.repo.name,
            "full_name": candidate.repo.full_name,
            "html_url": candidate.repo.html_url,
            "description": candidate.description,
            "stars": int(candidate.stars),
            "created_at": _iso(candidate.created_at),
            "updated_at": _iso(candidate.updated_at),
            "pushed_at": _iso(candidate.pushed_at),
            "primary_language": candidate.primary_language,
            "topics": sorted(str(value) for value in candidate.topics),
            "discovery_channels": sorted(str(value) for value in candidate.discovery_channels),
            "matched_query_ids": sorted(str(value) for value in candidate.matched_query_ids),
        },
        "score": {
            "total": score.total,
            "relevance": score.relevance,
            "quality": score.quality,
            "activity": score.activity,
            "visibility": score.visibility,
            "novelty": score.novelty,
            "originality": score.originality,
            "intersection": score.intersection,
            "confidence": score.confidence,
            "score_version": score.score_version,
        },
        "notification": {
            "notify": bool(decision.notify),
            "notification_type": decision.notification_type,
            "trigger_fingerprint": decision.trigger_fingerprint,
            "previous_score": decision.previous_score,
            "current_score": decision.current_score,
        },
        "light_analysis": {
            "detected_areas": sorted(str(value) for value in light.detected_areas),
            "activity_level": light.activity_level,
            "quality_signals": sorted(str(value) for value in light.quality_signals),
            "negative_signals": sorted(str(value) for value in light.negative_signals),
            "latest_release_tag": light.latest_release_tag,
            "latest_release_at": _iso(light.latest_release_at),
            "latest_relevant_activity_at": _iso(light.latest_relevant_activity_at),
            "readme_hash": light.readme_hash,
            "tree_hash": light.tree_hash,
            "dependency_hash": light.dependency_hash,
            "relevant_content_hash": light.relevant_content_hash,
            "evidence": _json_safe(light.evidence),
        },
        "deep_analysis": None if deep is None else {
            "status": deep.status,
            "source": deep.source,
            "confidence": deep.confidence,
            "relevance_suggestion": deep.relevance_suggestion,
            "originality_suggestion": deep.originality_suggestion,
            "summary": deep.summary,
            "why_interesting": deep.why_interesting,
            "risks": sorted(str(value) for value in deep.risks),
            "evidence": _json_safe(deep.evidence),
        },
    }


def _csv_row(run_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    repo = record["repository"]
    score = record["score"]
    notification = record["notification"]
    light = record["light_analysis"]
    deep = record["deep_analysis"] or {}
    return {
        "run_id": run_id,
        "report_rank": record["report_rank"] if record["report_rank"] is not None else "",
        "selected_for_report": str(bool(record["selected_for_report"])).lower(),
        "github_repo_id": repo["github_repo_id"],
        "full_name": repo["full_name"],
        "html_url": repo["html_url"],
        "stars": repo["stars"],
        "created_at": repo["created_at"] or "",
        "updated_at": repo["updated_at"] or "",
        "pushed_at": repo["pushed_at"] or "",
        "primary_language": repo["primary_language"] or "",
        "topics": ";".join(repo["topics"]),
        "discovery_channels": ";".join(repo["discovery_channels"]),
        "matched_query_ids": ";".join(repo["matched_query_ids"]),
        "areas": ";".join(light["detected_areas"]),
        "activity_level": light["activity_level"],
        "score_total": score["total"],
        "score_relevance": score["relevance"],
        "score_quality": score["quality"],
        "score_activity": score["activity"],
        "score_visibility": score["visibility"],
        "score_novelty": score["novelty"],
        "score_originality": score["originality"],
        "score_intersection": score["intersection"],
        "score_confidence": score["confidence"],
        "score_version": score["score_version"],
        "notify": str(bool(notification["notify"])).lower(),
        "notification_type": notification["notification_type"] or "",
        "previous_score": notification["previous_score"] if notification["previous_score"] is not None else "",
        "current_score": notification["current_score"],
        "deep_status": deep.get("status", ""),
        "deep_source": deep.get("source", ""),
        "deep_confidence": deep.get("confidence", ""),
        "deep_summary": deep.get("summary") or "",
        "why_interesting": deep.get("why_interesting") or "",
        "risks_json": _compact_json(deep.get("risks", [])),
        "light_evidence_json": _compact_json(light.get("evidence", {})),
        "deep_evidence_json": _compact_json(deep.get("evidence", {})),
    }


def _compact_json(value: Any) -> str:
    return json.dumps(_json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value, key=str)]
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return _iso(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)
