"""Central GitHub REST client (SPEC_V1 sections 3 and 11).

Every programmatic GitHub read/write flows through :class:`GitHubClient`, which
owns authentication, timeouts, bounded retries with exponential backoff,
rate-limit accounting and error normalization.

Security invariants:

* the token is sent only as a ``Bearer`` ``Authorization`` header, never in a
  URL, query string or log line;
* exception messages and log records carry the endpoint path and status code
  only -- never headers, tokens or response bodies.
"""

from __future__ import annotations

import base64
import binascii
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import httpx

from hidden_gems.common.logging import get_logger
from hidden_gems.common.time import to_iso, utcnow
from hidden_gems.github.rate_limits import RateBudget

logger = get_logger("hidden_gems.github")

ACCEPT_HEADER = "application/vnd.github+json"
USER_AGENT = "github-hidden-gems/0.1"
RETRY_AFTER_HEADER = "Retry-After"
REMAINING_HEADER = "X-RateLimit-Remaining"
RESET_HEADER = "X-RateLimit-Reset"

#: ``per_page`` is capped by the GitHub API itself.
MAX_PER_PAGE = 100
_DEFAULT_TIMEOUT_SECONDS = 5.0


class GitHubError(Exception):
    """Normalized GitHub failure that never carries headers or credentials."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint


class GitHubNotFound(GitHubError):
    """404 from the GitHub API."""


class GitHubAuthError(GitHubError):
    """401/403 caused by credentials or permissions, not by quota."""


class GitHubServerError(GitHubError):
    """5xx that survived the retry budget."""


class GitHubRateLimited(GitHubError):
    """403/429 caused by quota, with the wait GitHub asked for (if any)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        endpoint: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, endpoint=endpoint)
        self.retry_after = retry_after


def _normalize_path(path: str) -> str:
    if not path.startswith("/"):
        return f"/{path}"
    return path


def _per_page_for(limit: int) -> int:
    return max(1, min(int(limit), MAX_PER_PAGE))


def _github_config(config: Any) -> Any:
    """Accept either an ``AppConfig`` or its ``limits.github`` section."""

    inner = getattr(config, "github", None)
    return inner if inner is not None else config


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


class GitHubClient:
    """Rate-aware GitHub REST client shared by every pipeline stage."""

    def __init__(
        self,
        config: Any,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = _github_config(config)
        self._token = token or None
        self._sleep = sleep if sleep is not None else time.sleep
        self._clock = clock if clock is not None else utcnow
        self.base_url = str(self._config.api_base_url).rstrip("/")
        self.timeout = httpx.Timeout(
            _DEFAULT_TIMEOUT_SECONDS,
            connect=self._config.connect_timeout_seconds,
            read=self._config.read_timeout_seconds,
        )
        self._rate_budget = RateBudget(self._config)
        headers = {
            "Accept": ACCEPT_HEADER,
            "X-GitHub-Api-Version": str(self._config.api_version),
            "User-Agent": USER_AGENT,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            transport=transport,
        )

    # ------------------------------------------------------------------ public

    @property
    def rate_budget(self) -> RateBudget:
        return self._rate_budget

    def close(self) -> None:
        self._client.close()

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post_json(self, path: str, payload: Mapping[str, Any]) -> Any:
        return self._request("POST", path, json_body=dict(payload))

    def search_repositories(self, query: str, page: int = 1) -> dict[str, Any]:
        payload = self.get_json(
            "/search/repositories",
            params={"q": query, "page": int(page), "per_page": self._config.per_page},
        )
        if not isinstance(payload, Mapping):
            raise GitHubError("unexpected search payload", endpoint="/search/repositories")
        items = payload.get("items")
        return {
            "total_count": _int_or_none(payload.get("total_count")) or 0,
            "items": list(items) if isinstance(items, list) else [],
        }

    def get_repo_metadata(self, full_name: str) -> dict[str, Any]:
        payload = self.get_json(f"/repos/{full_name}")
        if not isinstance(payload, Mapping):
            raise GitHubError(
                f"unexpected repository payload for {full_name}", endpoint=f"/repos/{full_name}"
            )
        return dict(payload)

    def get_readme(self, full_name: str) -> str | None:
        endpoint = f"/repos/{full_name}/readme"
        try:
            payload = self.get_json(endpoint)
        except GitHubNotFound:
            return None
        if not isinstance(payload, Mapping):
            return None
        content = payload.get("content")
        if not isinstance(content, str) or not content:
            return None
        if payload.get("encoding") != "base64":
            return content
        try:
            decoded = base64.b64decode(content, validate=False)
        except (binascii.Error, ValueError):
            return None
        return decoded.decode("utf-8", errors="replace")

    def get_tree(self, full_name: str, ref: str) -> list[dict[str, Any]]:
        payload = self.get_json(f"/repos/{full_name}/git/trees/{ref}", params={"recursive": "1"})
        if not isinstance(payload, Mapping):
            return []
        tree = payload.get("tree")
        return list(tree) if isinstance(tree, list) else []

    def get_releases(self, full_name: str, limit: int = 10) -> list[dict[str, Any]]:
        payload = self.get_json(
            f"/repos/{full_name}/releases", params={"per_page": _per_page_for(limit)}
        )
        return list(payload)[:limit] if isinstance(payload, list) else []

    def get_recent_commits(
        self,
        full_name: str,
        since: datetime | str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": _per_page_for(limit)}
        if since is not None:
            params["since"] = to_iso(since) if isinstance(since, datetime) else str(since)
        payload = self.get_json(f"/repos/{full_name}/commits", params=params)
        return list(payload)[:limit] if isinstance(payload, list) else []

    # ----------------------------------------------------------------- private

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> Any:
        endpoint = _normalize_path(path)
        attempt = 0
        while True:
            try:
                response = self._client.request(
                    method, endpoint, params=params, json=json_body
                )
            except httpx.TransportError as exc:
                if attempt >= self._config.max_retries:
                    raise GitHubError(
                        f"github {method} {endpoint} failed after {attempt + 1} attempts "
                        f"({type(exc).__name__})",
                        endpoint=endpoint,
                    ) from None
                self._backoff(attempt, endpoint, type(exc).__name__)
                attempt += 1
                continue

            self._rate_budget.update_from_headers(response.headers)
            status = response.status_code

            if 200 <= status < 300:
                if not response.content:
                    return None
                try:
                    return response.json()
                except ValueError:
                    raise GitHubError(
                        f"github {method} {endpoint} returned a non-JSON body",
                        status_code=status,
                        endpoint=endpoint,
                    ) from None

            if status == 404:
                raise GitHubNotFound(
                    f"github {method} {endpoint} returned 404", status_code=404, endpoint=endpoint
                )
            if status == 401:
                raise GitHubAuthError(
                    f"github {method} {endpoint} returned 401 (check GITHUB_TOKEN)",
                    status_code=401,
                    endpoint=endpoint,
                )
            if status in (403, 429):
                rate_limited, retry_after = self._rate_limit_signal(response)
                if status == 403 and not rate_limited:
                    raise GitHubAuthError(
                        f"github {method} {endpoint} returned 403 (insufficient permission)",
                        status_code=403,
                        endpoint=endpoint,
                    )
                if (
                    retry_after is not None
                    and attempt < self._config.max_retries
                    and retry_after <= self._config.backoff_max_seconds
                ):
                    logger.warning(
                        "github rate limited, waiting before retry: endpoint=%s status=%s",
                        endpoint,
                        status,
                    )
                    self._sleep(retry_after)
                    attempt += 1
                    continue
                if retry_after is None:
                    message = f"github {method} {endpoint} rate limited ({status})"
                else:
                    message = (
                        f"github {method} {endpoint} rate limited "
                        f"(retry-after={retry_after:g}s, status={status})"
                    )
                raise GitHubRateLimited(
                    message,
                    status_code=status,
                    endpoint=endpoint,
                    retry_after=retry_after,
                )
            if status >= 500:
                if attempt >= self._config.max_retries:
                    raise GitHubServerError(
                        f"github {method} {endpoint} returned {status} after {attempt + 1} attempts",
                        status_code=status,
                        endpoint=endpoint,
                    )
                self._backoff(attempt, endpoint, f"HTTP {status}")
                attempt += 1
                continue
            raise GitHubError(
                f"github {method} {endpoint} returned {status}",
                status_code=status,
                endpoint=endpoint,
            )

    def _backoff(self, attempt: int, endpoint: str, reason: str) -> None:
        delay = min(
            self._config.backoff_base_seconds * (2**attempt),
            self._config.backoff_max_seconds,
        )
        logger.warning(
            "github request retry: endpoint=%s attempt=%s delay=%ss reason=%s",
            endpoint,
            attempt + 1,
            delay,
            reason,
        )
        self._sleep(delay)

    def _rate_limit_signal(self, response: httpx.Response) -> tuple[bool, float | None]:
        """Whether a 403/429 is quota-related, and how long GitHub asked us to wait.

        ``Retry-After`` is normally a number of seconds, but the header may also
        carry an HTTP date; it is then still a rate-limit signal even though no
        delay can be derived from it.
        """

        raw = response.headers.get(RETRY_AFTER_HEADER)
        remaining = _int_or_none(response.headers.get(REMAINING_HEADER))
        reset_epoch = _int_or_none(response.headers.get(RESET_HEADER))
        if raw:
            try:
                return True, max(0.0, float(str(raw).strip()))
            except ValueError:
                return True, None
        if remaining == 0 and reset_epoch:
            reset_at = datetime.fromtimestamp(reset_epoch, tz=timezone.utc)
            return True, max(0.0, (reset_at - self._clock()).total_seconds())
        return remaining == 0, None
