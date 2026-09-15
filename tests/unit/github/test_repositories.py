"""Normalization of GitHub repository payloads into canonical records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hidden_gems.github.repositories import NORMALIZED_REPO_FIELDS, normalize_repo, payload_to_candidate


def repo_payload(**overrides: Any) -> dict[str, Any]:
    """A trimmed but structurally faithful ``GET /repos/{owner}/{repo}`` payload."""

    payload: dict[str, Any] = {
        "id": 987654321,
        "name": "tool",
        "full_name": "acme/tool",
        "html_url": "https://github.com/acme/tool",
        "owner": {"login": "acme", "type": "Organization"},
        "description": "Tiny agent runtime",
        "stargazers_count": 42,
        "created_at": "2026-08-01T10:00:00Z",
        "updated_at": "2026-09-10T08:30:00Z",
        "pushed_at": "2026-09-12T22:15:00Z",
        "language": "Python",
        "topics": ["agents", "automation"],
        "fork": False,
        "archived": False,
        "is_template": False,
        "size": 1536,
        "default_branch": "main",
        "license": {"spdx_id": "MIT", "name": "MIT License"},
        "open_issues_count": 3,
    }
    payload.update(overrides)
    return payload


def test_normalize_repo_maps_the_documented_field_set():
    record = normalize_repo(repo_payload())

    assert tuple(record) == NORMALIZED_REPO_FIELDS
    assert record["github_repo_id"] == 987654321
    assert record["owner"] == "acme"
    assert record["name"] == "tool"
    assert record["full_name"] == "acme/tool"
    assert record["html_url"] == "https://github.com/acme/tool"
    assert record["description"] == "Tiny agent runtime"
    assert record["stars"] == 42
    assert record["primary_language"] == "Python"
    assert record["topics"] == ("agents", "automation")
    assert record["is_fork"] is False
    assert record["is_archived"] is False
    assert record["is_template"] is False
    assert record["size_kb"] == 1536
    assert record["default_branch"] == "main"
    assert record["license_spdx_id"] == "MIT"
    assert record["open_issues"] == 3


def test_normalize_repo_parses_timestamps_as_utc():
    record = normalize_repo(repo_payload())

    assert record["created_at"] == datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    assert record["updated_at"] == datetime(2026, 9, 10, 8, 30, tzinfo=timezone.utc)
    assert record["pushed_at"] == datetime(2026, 9, 12, 22, 15, tzinfo=timezone.utc)


def test_normalize_repo_defaults_missing_fields_without_raising():
    record = normalize_repo({})

    assert tuple(record) == NORMALIZED_REPO_FIELDS
    assert record["github_repo_id"] is None
    assert record["owner"] is None
    assert record["stars"] is None
    assert record["created_at"] is None
    assert record["topics"] == ()
    assert record["is_fork"] is False
    assert record["is_archived"] is False
    assert record["is_template"] is False
    assert record["license_spdx_id"] is None


def test_normalize_repo_rejects_noassertion_license():
    assert normalize_repo(repo_payload(license={"spdx_id": "NOASSERTION"}))["license_spdx_id"] is None
    assert normalize_repo(repo_payload(license=None))["license_spdx_id"] is None
    assert normalize_repo(repo_payload(license={"spdx_id": " mit "}))["license_spdx_id"] == "mit"


def test_normalize_repo_ignores_malformed_timestamps_and_topics():
    record = normalize_repo(
        repo_payload(created_at="not-a-date", updated_at=None, pushed_at=12345, topics="agents")
    )

    assert record["created_at"] is None
    assert record["updated_at"] is None
    assert record["pushed_at"] is None
    assert record["topics"] == ()


def test_normalize_repo_tolerates_string_numbers_and_null_owner():
    record = normalize_repo(
        repo_payload(id="123", owner=None, stargazers_count="7", size="12", open_issues_count=None)
    )

    assert record["github_repo_id"] == 123
    assert record["owner"] is None
    assert record["stars"] == 7
    assert record["size_kb"] == 12
    assert record["open_issues"] is None


def test_normalize_repo_drops_blank_topic_entries():
    assert normalize_repo(repo_payload(topics=["agents", "", "  ", "trading"]))["topics"] == (
        "agents",
        "trading",
    )


def test_payload_to_candidate_builds_a_domain_candidate():
    candidate = payload_to_candidate(
        repo_payload(), channels={"search"}, query_ids={"core_ai_agents"}
    )

    assert candidate is not None
    assert candidate.repo.github_repo_id == 987654321
    assert candidate.repo.full_name == "acme/tool"
    assert candidate.repo.html_url == "https://github.com/acme/tool"
    assert candidate.description == "Tiny agent runtime"
    assert candidate.stars == 42
    assert candidate.created_at == datetime(2026, 8, 1, 10, 0, tzinfo=timezone.utc)
    assert candidate.updated_at == datetime(2026, 9, 10, 8, 30, tzinfo=timezone.utc)
    assert candidate.pushed_at == datetime(2026, 9, 12, 22, 15, tzinfo=timezone.utc)
    assert candidate.primary_language == "Python"
    assert candidate.topics == ("agents", "automation")
    assert candidate.discovery_channels == {"search"}
    assert candidate.matched_query_ids == {"core_ai_agents"}
    assert candidate.is_fork is False
    assert candidate.is_archived is False
    assert candidate.is_template is False
    assert candidate.size_kb == 1536
    assert candidate.default_branch == "main"
    assert candidate.license_spdx_id == "MIT"
    assert candidate.open_issues == 3


def test_payload_to_candidate_defaults_collections_and_flags():
    candidate = payload_to_candidate({**repo_payload(), "fork": True, "topics": None})

    assert candidate is not None
    assert candidate.is_fork is True
    assert candidate.topics == ()
    assert candidate.discovery_channels == set()
    assert candidate.matched_query_ids == set()


def test_payload_to_candidate_skips_incomplete_identity():
    assert payload_to_candidate(repo_payload(id=None)) is None
    assert payload_to_candidate(repo_payload(id=0)) is None
    assert payload_to_candidate(repo_payload(full_name=None)) is None
    assert payload_to_candidate(repo_payload(owner={})) is None
    assert payload_to_candidate(repo_payload(name="")) is None


def test_payload_to_candidate_skips_missing_or_invalid_timestamps():
    assert payload_to_candidate(repo_payload(created_at=None)) is None
    assert payload_to_candidate(repo_payload(updated_at="yesterday")) is None


def test_payload_to_candidate_skips_non_canonical_html_url():
    assert payload_to_candidate(repo_payload(html_url="https://github.com/acme/tool/")) is None
    assert payload_to_candidate(repo_payload(html_url="http://github.com/acme/tool")) is None
    assert payload_to_candidate(repo_payload(html_url="https://github.com/other/tool")) is None


def test_payload_to_candidate_skips_inconsistent_full_name():
    assert payload_to_candidate(repo_payload(full_name="acme/other")) is None
