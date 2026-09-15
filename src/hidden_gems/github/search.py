"""Small search helpers shared by the discovery engine.

Query construction belongs to ``hidden_gems.discovery.queries``; this module
only turns search responses into usable repository payloads so the engine never
parses GitHub's response envelope itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids an import cycle
    from hidden_gems.github.client import GitHubClient


def parse_search_items(response: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    """Raw repository payloads from ``GET /search/repositories``.

    Malformed items are dropped rather than crashing a whole daily run.
    """

    if not isinstance(response, Mapping):
        return []
    items = response.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return []
    return [item for item in items if isinstance(item, Mapping)]


def search_page(client: "GitHubClient", query: str, page: int = 1) -> dict[str, Any]:
    """Perform one search page through the shared client."""

    return client.search_repositories(query, page=page)
