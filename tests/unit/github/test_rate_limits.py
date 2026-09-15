"""Rate-budget zone accounting (SPEC_V1 section 11: GREEN / YELLOW / RED)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from hidden_gems.github.rate_limits import GREEN, RED, YELLOW, RateBudget


def _headers(
    *,
    remaining: int | str,
    limit: int | str = 5000,
    reset: int | str = 1789491000,
    resource: str = "core",
) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset),
        "X-RateLimit-Resource": resource,
    }


def test_zone_is_green_above_yellow_floor(github_config):
    budget = RateBudget(github_config)

    budget.update_from_headers(_headers(remaining=github_config.rate_limit_yellow_floor + 1))

    assert budget.zone == GREEN


def test_zone_is_yellow_at_yellow_floor_and_above_red_floor(github_config):
    budget = RateBudget(github_config)

    budget.update_from_headers(_headers(remaining=github_config.rate_limit_yellow_floor))
    assert budget.zone == YELLOW

    budget.update_from_headers(_headers(remaining=github_config.rate_limit_red_floor + 1))
    assert budget.zone == YELLOW


def test_zone_is_red_at_and_below_red_floor(github_config):
    budget = RateBudget(github_config)

    budget.update_from_headers(_headers(remaining=github_config.rate_limit_red_floor))
    assert budget.zone == RED

    budget.update_from_headers(_headers(remaining=0))
    assert budget.zone == RED


def test_unknown_state_is_green_and_empty(github_config):
    budget = RateBudget(github_config)

    assert budget.zone == GREEN
    assert budget.remaining is None
    assert budget.limit is None
    assert budget.reset_at is None
    assert budget.search_remaining is None


def test_search_resource_uses_search_floors(github_config):
    budget = RateBudget(github_config)

    budget.update_from_headers(
        _headers(remaining=github_config.search_rate_limit_yellow_floor + 1, resource="search")
    )
    assert budget.zone == GREEN

    budget.update_from_headers(
        _headers(remaining=github_config.search_rate_limit_yellow_floor, resource="search")
    )
    assert budget.zone == YELLOW

    budget.update_from_headers(
        _headers(remaining=github_config.search_rate_limit_red_floor, resource="search")
    )
    assert budget.zone == RED


def test_search_headers_also_record_search_remaining(github_config):
    budget = RateBudget(github_config)

    budget.update_from_headers(_headers(remaining=7, resource="search"))

    assert budget.search_remaining == 7
    assert budget.remaining == 7


def test_zone_floors_follow_the_most_recent_resource(github_config):
    budget = RateBudget(github_config)

    # 51 is YELLOW against the core floors (yellow 200 / red 50) but GREEN
    # against the much smaller search floors (yellow 10 / red 5).
    budget.update_from_headers(_headers(remaining=51, resource="core"))
    assert budget.zone == YELLOW

    budget.update_from_headers(_headers(remaining=51, resource="search"))
    assert budget.zone == GREEN


def test_update_from_headers_parses_epoch_reset_into_utc(github_config):
    budget = RateBudget(github_config)
    reset_epoch = 1789491000

    budget.update_from_headers(_headers(remaining=1200, limit=5000, reset=reset_epoch))

    assert budget.limit == 5000
    assert budget.remaining == 1200
    assert budget.reset_at == datetime.fromtimestamp(reset_epoch, tz=timezone.utc)
    assert budget.reset_at.tzinfo is timezone.utc


def test_unparseable_headers_are_ignored(github_config):
    budget = RateBudget(github_config)

    budget.update_from_headers(
        {
            "X-RateLimit-Limit": "not-a-number",
            "X-RateLimit-Remaining": "?",
            "X-RateLimit-Reset": "later",
        }
    )

    assert budget.limit is None
    assert budget.remaining is None
    assert budget.reset_at is None
    assert budget.zone == GREEN


def test_missing_headers_leave_previous_values_intact(github_config):
    budget = RateBudget(github_config)
    budget.update_from_headers(_headers(remaining=300, limit=5000))

    budget.update_from_headers({"X-RateLimit-Remaining": "250"})

    assert budget.remaining == 250
    assert budget.limit == 5000


def test_snapshot_is_json_serializable(github_config):
    budget = RateBudget(github_config)
    budget.update_from_headers(_headers(remaining=12, limit=30, resource="search"))

    snapshot = budget.snapshot()

    assert snapshot["zone"] == GREEN
    assert snapshot["remaining"] == 12
    assert snapshot["limit"] == 30
    assert snapshot["search_remaining"] == 12
    assert json.loads(json.dumps(snapshot)) == snapshot


def test_recorded_rate_limit_fixture_headers_drive_the_zone(
    github_config, headers_from_rate_limit
):
    budget = RateBudget(github_config)

    budget.update_from_headers(headers_from_rate_limit("core"))

    assert budget.remaining == 4999
    assert budget.zone == GREEN
    assert budget.search_remaining is None

    budget.update_from_headers(headers_from_rate_limit("search"))

    assert budget.search_remaining == 28
    assert budget.zone == GREEN


def test_zone_is_one_of_the_three_canonical_values(github_config):
    budget = RateBudget(github_config)
    budget.update_from_headers(_headers(remaining=0))

    assert budget.zone in {GREEN, YELLOW, RED}
    assert budget.zone == RED


@pytest.mark.parametrize("attribute", ["remaining", "limit", "reset_at", "search_remaining"])
def test_public_accounting_attributes_exist(github_config, attribute):
    assert hasattr(RateBudget(github_config), attribute)
