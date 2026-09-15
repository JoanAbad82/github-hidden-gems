from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hidden_gems.models import DiscoveryCandidate, RepositoryRef

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "repos"


def parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def build_candidate(payload: dict) -> DiscoveryCandidate:
    ref = RepositoryRef.from_full_name(payload["full_name"], int(payload["github_repo_id"]))
    return DiscoveryCandidate(
        repo=ref,
        description=payload.get("description"),
        stars=int(payload.get("stars", 0)),
        created_at=parse_dt(payload["created_at"]),
        updated_at=parse_dt(payload["updated_at"]),
        primary_language=payload.get("primary_language"),
        topics=tuple(payload.get("topics", ())),
        discovery_channels={"TOPIC_SEARCH"},
        matched_query_ids={"Q_TEST"},
        pushed_at=parse_dt(payload.get("pushed_at") or payload["updated_at"]),
        is_fork=bool(payload.get("is_fork", False)),
        is_archived=bool(payload.get("is_archived", False)),
        is_template=bool(payload.get("is_template", False)),
        size_kb=payload.get("size_kb"),
        default_branch=payload.get("default_branch", "main"),
        license_spdx_id=payload.get("license_spdx_id"),
    )


def load_case(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def filter_case():
    def _load(name: str):
        from hidden_gems.filtering.hard_filter import FilterEvidence

        payload = load_case(name)
        candidate = build_candidate(payload["candidate"])
        evidence_payload = payload.get("evidence", {})
        evidence = FilterEvidence(
            readme_text=evidence_payload.get("readme_text"),
            tree_paths=tuple(evidence_payload.get("tree_paths", ())),
            manifest_names=tuple(evidence_payload.get("manifest_names", ())),
            commit_messages=tuple(evidence_payload.get("commit_messages", ())),
            total_size_kb=evidence_payload.get("total_size_kb"),
        )
        return candidate, evidence, payload["expected"]

    return _load
