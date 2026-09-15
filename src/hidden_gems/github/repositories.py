"""Normalization of raw GitHub repository payloads into canonical records.

GitHub payloads are wide and full of nulls. The rest of the pipeline consumes
either the flat normalized record below or a validated
:class:`~hidden_gems.models.DiscoveryCandidate`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Mapping

from hidden_gems.common.time import parse_github_datetime
from hidden_gems.models import DiscoveryCandidate, ModelError, RepositoryRef

#: Exactly the keys produced by :func:`normalize_repo`.
NORMALIZED_REPO_FIELDS: tuple[str, ...] = (
    "github_repo_id",
    "owner",
    "name",
    "full_name",
    "html_url",
    "description",
    "stars",
    "created_at",
    "updated_at",
    "pushed_at",
    "primary_language",
    "topics",
    "is_fork",
    "is_archived",
    "is_template",
    "size_kb",
    "default_branch",
    "license_spdx_id",
    "open_issues",
)

#: GitHub reports this SPDX id when it could not identify a license.
NO_LICENSE_ID = "NOASSERTION"


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _str_or_none(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _datetime_or_none(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_github_datetime(value)
    except ValueError:
        return None


def _owner_login(payload: Mapping[str, Any]) -> str | None:
    owner = payload.get("owner")
    if isinstance(owner, Mapping):
        return _str_or_none(owner.get("login"))
    return _str_or_none(payload.get("owner_login"))


def _license_spdx_id(payload: Mapping[str, Any]) -> str | None:
    license_payload = payload.get("license")
    if not isinstance(license_payload, Mapping):
        return None
    spdx = _str_or_none(license_payload.get("spdx_id"))
    if spdx is None or spdx.upper() == NO_LICENSE_ID:
        return None
    return spdx


def _topics(payload: Mapping[str, Any]) -> tuple[str, ...]:
    topics = payload.get("topics")
    if not isinstance(topics, (list, tuple)):
        return ()
    return tuple(topic for topic in (_str_or_none(item) for item in topics) if topic)


def normalize_repo(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten one GitHub repository payload into the canonical field set.

    Timestamps are timezone-aware UTC :class:`datetime` objects (or ``None``
    when GitHub omitted or malformed them); every other missing value is
    ``None`` rather than a guess.
    """

    return {
        "github_repo_id": _int_or_none(payload.get("id")),
        "owner": _owner_login(payload),
        "name": _str_or_none(payload.get("name")),
        "full_name": _str_or_none(payload.get("full_name")),
        "html_url": _str_or_none(payload.get("html_url")),
        "description": _str_or_none(payload.get("description")),
        "stars": _int_or_none(payload.get("stargazers_count")),
        "created_at": _datetime_or_none(payload.get("created_at")),
        "updated_at": _datetime_or_none(payload.get("updated_at")),
        "pushed_at": _datetime_or_none(payload.get("pushed_at")),
        "primary_language": _str_or_none(payload.get("language")),
        "topics": _topics(payload),
        "is_fork": bool(payload.get("fork", False)),
        "is_archived": bool(payload.get("archived", False)),
        "is_template": bool(payload.get("is_template", False)),
        "size_kb": _int_or_none(payload.get("size")),
        "default_branch": _str_or_none(payload.get("default_branch")),
        "license_spdx_id": _license_spdx_id(payload),
        "open_issues": _int_or_none(payload.get("open_issues_count")),
    }


def payload_to_candidate(
    payload: Mapping[str, Any],
    *,
    channels: Iterable[str] = (),
    query_ids: Iterable[str] = (),
) -> DiscoveryCandidate | None:
    """Build a :class:`DiscoveryCandidate`, or ``None`` when identity is unusable.

    The discovery engine must survive partial or hostile payloads, so anything
    that cannot form a canonical :class:`RepositoryRef` with creation and
    update timestamps is skipped instead of raising.
    """

    if not isinstance(payload, Mapping):
        return None
    record = normalize_repo(payload)
    repo_id = record["github_repo_id"]
    owner = record["owner"]
    name = record["name"]
    full_name = record["full_name"]
    html_url = record["html_url"]
    created_at = record["created_at"]
    updated_at = record["updated_at"]
    if not repo_id or not owner or not name or not full_name or not html_url:
        return None
    if created_at is None or updated_at is None:
        return None
    try:
        repo = RepositoryRef(
            github_repo_id=repo_id,
            owner=owner,
            name=name,
            full_name=full_name,
            html_url=html_url,
        )
    except ModelError:
        return None
    return DiscoveryCandidate(
        repo=repo,
        description=record["description"],
        stars=record["stars"] or 0,
        created_at=created_at,
        updated_at=updated_at,
        primary_language=record["primary_language"],
        topics=record["topics"],
        discovery_channels=set(channels),
        matched_query_ids=set(query_ids),
        pushed_at=record["pushed_at"],
        is_fork=record["is_fork"],
        is_archived=record["is_archived"],
        is_template=record["is_template"],
        size_kb=record["size_kb"],
        default_branch=record["default_branch"],
        license_spdx_id=record["license_spdx_id"],
        open_issues=record["open_issues"],
    )
