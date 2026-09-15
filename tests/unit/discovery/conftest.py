"""Task-4 fixtures: a payload normalizer implementing the frozen contract.

The canonical normalizer lives in `hidden_gems.github.repositories` (Task 3).
Discovery tests inject an equivalent local parser so discovery execution can be
verified independently of the GitHub package; a dedicated test asserts that the
default (production) parser is resolved from that package.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

import pytest

from hidden_gems.models import DiscoveryCandidate, RepositoryRef


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def _parse(payload: Mapping[str, Any], *, channels, query_ids) -> DiscoveryCandidate | None:
    if not isinstance(payload, Mapping):
        return None
    repo_id = payload.get("id")
    full_name = payload.get("full_name")
    if not repo_id or not full_name or "/" not in str(full_name):
        return None
    owner, _, name = str(full_name).partition("/")
    ref = RepositoryRef(
        github_repo_id=int(repo_id),
        owner=owner,
        name=name,
        full_name=str(full_name),
        html_url=f"https://github.com/{owner}/{name}",
    )
    license_payload = payload.get("license") or {}
    return DiscoveryCandidate(
        repo=ref,
        description=payload.get("description"),
        stars=int(payload.get("stargazers_count") or 0),
        created_at=parse_datetime(payload.get("created_at")),
        updated_at=parse_datetime(payload.get("updated_at")),
        primary_language=payload.get("language"),
        topics=tuple(payload.get("topics") or ()),
        discovery_channels=set(channels),
        matched_query_ids=set(query_ids),
        pushed_at=parse_datetime(payload["pushed_at"]) if payload.get("pushed_at") else None,
        is_fork=bool(payload.get("fork")),
        is_archived=bool(payload.get("archived")),
        is_template=bool(payload.get("is_template")),
        size_kb=payload.get("size"),
        default_branch=payload.get("default_branch"),
        license_spdx_id=license_payload.get("spdx_id"),
        open_issues=payload.get("open_issues_count"),
    )


@pytest.fixture
def payload_parser():
    return _parse
