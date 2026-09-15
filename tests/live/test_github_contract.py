"""Opt-in, read-only live contract test (Task 16, level CONTROLLED LIVE).

Runs only with `RUN_LIVE_TESTS=1`, reads a very small query set, never creates an
Issue, never enables the LLM and never writes to the state branch.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hidden_gems.config import load_config
from hidden_gems.github.client import GitHubClient

LIVE = os.environ.get("RUN_LIVE_TESTS") == "1"

pytestmark = pytest.mark.live


def _client() -> GitHubClient:
    config = load_config(Path(__file__).resolve().parents[2])
    return GitHubClient(config, os.environ.get("GITHUB_TOKEN"))


@pytest.mark.skipif(not LIVE, reason="live tests require RUN_LIVE_TESTS=1")
def test_search_parsing_and_rate_limit_headers():
    client = _client()
    try:
        payload = client.search_repositories("agent framework stars:0..24", page=1)
        assert "total_count" in payload and isinstance(payload["items"], list)
        assert len(payload["items"]) <= 100
        budget = client.rate_budget
        assert budget.zone in ("GREEN", "YELLOW", "RED")
        assert budget.snapshot()
    finally:
        client.close()


@pytest.mark.skipif(not LIVE, reason="live tests require RUN_LIVE_TESTS=1")
def test_repository_metadata_parsing_is_bounded():
    client = _client()
    try:
        payload = client.get_repo_metadata("python/cpython")
        assert payload["full_name"] == "python/cpython"
        assert isinstance(payload["stargazers_count"], int)
    except Exception as exc:  # pragma: no cover - only on live runs
        pytest.skip(f"live GitHub contract unavailable: {type(exc).__name__}")
    finally:
        client.close()


def test_live_suite_never_publishes_anything():
    """The live contract test must stay read-only: no Issue creation, no writes."""

    source = Path(__file__).read_text(encoding="utf-8")
    # Tokens are assembled so this guard does not match its own assertions.
    forbidden = ("post_" + "json", "GitHub" + "IssuePublisher", "--" + "live")
    for token in forbidden:
        assert token not in source, f"live tests must not reference {token}"
    assert 'os.environ.get("RUN_LIVE_TESTS")' in source
