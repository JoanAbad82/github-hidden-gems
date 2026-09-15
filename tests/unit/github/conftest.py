"""Fixtures for the GitHub client tests.

Task-scoped fixtures deliberately live next to their tests so that parallel
task work never edits ``tests/conftest.py``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import httpx
import pytest

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "github"


class RecordedTransport:
    """Prepared-response queue that records every outgoing request.

    Items may be ``httpx.Response`` instances, exceptions to raise, or
    callables that receive the request and return a response.
    """

    def __init__(self, responses: Sequence[Any] = ()) -> None:
        self._responses: list[Any] = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError(f"unexpected request: {request.method} {request.url}")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(request)
        return item

    @property
    def call_count(self) -> int:
        return len(self.requests)

    @property
    def last_request(self) -> httpx.Request:
        return self.requests[-1]


@pytest.fixture
def github_config(app_config):
    """The frozen GitHub section of ``config/limits.yml``."""

    return app_config.limits.github


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fixed_clock(fixed_now: datetime) -> Callable[[], datetime]:
    return lambda: fixed_now


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def recorder(sleeps: list[float]) -> Callable[[float], None]:
    def _record(seconds: float) -> None:
        sleeps.append(float(seconds))

    return _record


@pytest.fixture
def make_response() -> Callable[..., httpx.Response]:
    def _make(
        payload: Any = None,
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        kwargs: dict[str, Any] = {"status_code": status_code}
        if headers is not None:
            kwargs["headers"] = dict(headers)
        if payload is None:
            return httpx.Response(**kwargs)
        if isinstance(payload, str):
            return httpx.Response(text=payload, **kwargs)
        return httpx.Response(json=payload, **kwargs)

    return _make


@pytest.fixture
def client_factory(github_config, recorder: Callable[[float], None]):
    """Build ``(client, handler)`` pairs backed by an in-memory transport."""

    def _make(
        responses: Sequence[Any] = (),
        *,
        token: str | None = None,
        config: Any = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        from hidden_gems.github.client import GitHubClient

        handler = RecordedTransport(responses)
        client = GitHubClient(
            config if config is not None else github_config,
            token=token,
            transport=httpx.MockTransport(handler),
            sleep=recorder if sleep is None else sleep,
            clock=clock,
        )
        return client, handler

    return _make


@pytest.fixture
def rate_limit_fixture() -> dict[str, Any]:
    """The recorded shape of ``GET /rate_limit`` (used to derive headers)."""

    return json.loads((FIXTURES_DIR / "rate_limit.json").read_text(encoding="utf-8"))


def rate_limit_headers(payload: Mapping[str, Any], resource: str) -> dict[str, str]:
    """Project one ``/rate_limit`` resource into the response headers GitHub sends."""

    bucket = payload["resources"][resource]
    return {
        "X-RateLimit-Limit": str(bucket["limit"]),
        "X-RateLimit-Remaining": str(bucket["remaining"]),
        "X-RateLimit-Reset": str(bucket["reset"]),
        "X-RateLimit-Resource": resource,
    }


@pytest.fixture
def headers_from_rate_limit(rate_limit_fixture: Mapping[str, Any]):
    def _headers(resource: str) -> dict[str, str]:
        return rate_limit_headers(rate_limit_fixture, resource)

    return _headers
