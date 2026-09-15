"""Search helpers used by the discovery engine."""

from __future__ import annotations

from typing import Any

from hidden_gems.github.search import parse_search_items, search_page


def test_parse_search_items_returns_raw_repository_payloads():
    items = [{"id": 1, "full_name": "acme/tool"}, {"id": 2, "full_name": "acme/other"}]

    assert parse_search_items({"total_count": 2, "items": items}) == items


def test_parse_search_items_drops_malformed_entries():
    response = {"total_count": 3, "items": [{"id": 1}, "not-a-repo", None, 7]}

    assert parse_search_items(response) == [{"id": 1}]


def test_parse_search_items_handles_missing_items_and_wrong_shapes():
    assert parse_search_items({}) == []
    assert parse_search_items({"items": None}) == []
    assert parse_search_items({"items": "nope"}) == []
    assert parse_search_items(None) == []


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search_repositories(self, query: str, page: int = 1) -> dict[str, Any]:
        self.calls.append((query, page))
        return {"total_count": 1, "items": [{"id": 1}]}


def test_search_page_uses_the_shared_client():
    client = _RecordingClient()

    result = search_page(client, "agent stars:10..50", page=3)

    assert client.calls == [("agent stars:10..50", 3)]
    assert result == {"total_count": 1, "items": [{"id": 1}]}


def test_search_page_defaults_to_the_first_page():
    client = _RecordingClient()

    search_page(client, "agent")

    assert client.calls == [("agent", 1)]
