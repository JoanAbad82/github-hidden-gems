"""GitHub rate-limit accounting and budget zones (SPEC_V1 section 11).

The orchestrator keeps non-essential work stopped while the budget is YELLOW
and stops cleanly once it is RED, so the zone must be derived from configured
floors rather than hard-coded numbers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

GREEN = "GREEN"
YELLOW = "YELLOW"
RED = "RED"
ZONES: tuple[str, ...] = (GREEN, YELLOW, RED)

#: GitHub reports which bucket produced the headers in this response header.
RESOURCE_HEADER = "X-RateLimit-Resource"
LIMIT_HEADER = "X-RateLimit-Limit"
REMAINING_HEADER = "X-RateLimit-Remaining"
RESET_HEADER = "X-RateLimit-Reset"

#: The search bucket has its own (much smaller) quota, so it uses its own floors.
SEARCH_RESOURCE = "search"


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _datetime_from_epoch(value: Any) -> datetime | None:
    epoch = _int_or_none(value)
    if epoch is None or epoch <= 0:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


class RateBudget:
    """Remaining GitHub quota plus the zone the run is currently in.

    Floors come from ``config/limits.yml`` (``limits.github``): the core
    buckets use ``rate_limit_yellow_floor`` / ``rate_limit_red_floor`` and the
    search bucket uses ``search_rate_limit_yellow_floor`` /
    ``search_rate_limit_red_floor``.

    ``limit``/``remaining``/``reset_at`` always describe the bucket that
    produced the most recent response (see ``resource``); ``search_remaining``
    additionally remembers the search quota for search gating.
    """

    def __init__(self, config: Any) -> None:
        self.yellow_floor = int(config.rate_limit_yellow_floor)
        self.red_floor = int(config.rate_limit_red_floor)
        self.search_yellow_floor = int(config.search_rate_limit_yellow_floor)
        self.search_red_floor = int(config.search_rate_limit_red_floor)
        self.remaining: int | None = None
        self.limit: int | None = None
        self.reset_at: datetime | None = None
        self.search_remaining: int | None = None
        self.resource: str | None = None

    @property
    def zone(self) -> str:
        """GREEN while there is room, YELLOW on the floor, RED at the floor.

        Unknown quota (no headers seen yet) is treated as GREEN: V1 must not
        refuse to start merely because the first response has not arrived.
        """

        if self.resource == SEARCH_RESOURCE:
            remaining = self.search_remaining
            yellow_floor = self.search_yellow_floor
            red_floor = self.search_red_floor
        else:
            remaining = self.remaining
            yellow_floor = self.yellow_floor
            red_floor = self.red_floor
        if remaining is None:
            return GREEN
        if remaining <= red_floor:
            return RED
        if remaining <= yellow_floor:
            return YELLOW
        return GREEN

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Absorb ``X-RateLimit-*`` response headers; ignore anything unusable."""

        normalized = {str(key).lower(): value for key, value in headers.items()}
        limit = _int_or_none(normalized.get(LIMIT_HEADER.lower()))
        remaining = _int_or_none(normalized.get(REMAINING_HEADER.lower()))
        reset_at = _datetime_from_epoch(normalized.get(RESET_HEADER.lower()))
        resource = normalized.get(RESOURCE_HEADER.lower())

        if limit is not None:
            self.limit = limit
        if remaining is not None:
            self.remaining = remaining
        if reset_at is not None:
            self.reset_at = reset_at
        if isinstance(resource, str) and resource.strip():
            self.resource = resource.strip()
        if self.resource == SEARCH_RESOURCE:
            if remaining is not None:
                self.search_remaining = remaining

    def snapshot(self) -> dict[str, object]:
        """JSON-serializable view for run summaries and the state manifest."""

        return {
            "zone": self.zone,
            "resource": self.resource,
            "remaining": self.remaining,
            "limit": self.limit,
            "reset_at": self.reset_at.isoformat() if self.reset_at else None,
            "search_remaining": self.search_remaining,
        }
