"""Central GitHub REST client: retries, redaction and normalized errors.

All external GitHub reads in SPEC_V1 flow through this client, so these tests
are written against the frozen contract signatures in
``docs/superpowers/contracts/v1-module-interfaces.md``.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from hidden_gems.github.client import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubNotFound,
    GitHubRateLimited,
    GitHubServerError,
)

#: Deliberately shaped like a real installation token so redaction is exercised.
TOKEN = "ghs_" + "A1b2C3d4E5f6G7h8I9j0K1l2"


def test_get_json_returns_decoded_payload(client_factory, make_response):
    client, handler = client_factory([make_response({"full_name": "acme/tool"})])

    payload = client.get_json("/repos/acme/tool")

    assert payload == {"full_name": "acme/tool"}
    assert handler.call_count == 1
    assert handler.last_request.method == "GET"
    assert str(handler.last_request.url) == "https://api.github.com/repos/acme/tool"


def test_get_json_accepts_path_without_leading_slash(client_factory, make_response):
    client, handler = client_factory([make_response({"ok": True})])

    client.get_json("repos/acme/tool")

    assert handler.last_request.url.path == "/repos/acme/tool"


def test_get_json_forwards_query_parameters(client_factory, make_response):
    client, handler = client_factory([make_response({"ok": True})])

    client.get_json("/search/repositories", params={"q": "agent", "page": 2})

    assert dict(handler.last_request.url.params) == {"q": "agent", "page": "2"}


def test_authorization_header_is_sent_only_when_a_token_exists(client_factory, make_response):
    anonymous, anonymous_handler = client_factory([make_response({})])
    authenticated, authenticated_handler = client_factory([make_response({})], token=TOKEN)

    anonymous.get_json("/rate_limit")
    authenticated.get_json("/rate_limit")

    assert "authorization" not in anonymous_handler.last_request.headers
    assert authenticated_handler.last_request.headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(anonymous_handler.last_request.url)
    assert TOKEN not in str(authenticated_handler.last_request.url)


def test_standard_github_headers_are_sent(client_factory, make_response, github_config):
    client, handler = client_factory([make_response({})])

    client.get_json("/rate_limit")

    headers = handler.last_request.headers
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["x-github-api-version"] == github_config.api_version
    assert headers["user-agent"]


def test_timeouts_come_from_configuration(client_factory, github_config):
    client, _ = client_factory([])

    assert client.timeout.connect == github_config.connect_timeout_seconds
    assert client.timeout.read == github_config.read_timeout_seconds
    assert client.base_url == github_config.api_base_url.rstrip("/")


def test_404_raises_github_not_found(client_factory, make_response):
    client, handler = client_factory(
        [make_response({"message": "Not Found"}, status_code=404)]
    )

    with pytest.raises(GitHubNotFound) as excinfo:
        client.get_json("/repos/acme/missing")

    assert excinfo.value.status_code == 404
    assert excinfo.value.endpoint == "/repos/acme/missing"
    assert handler.call_count == 1


def test_401_raises_github_auth_error(client_factory, make_response):
    client, _ = client_factory([make_response({"message": "Bad credentials"}, status_code=401)])

    with pytest.raises(GitHubAuthError) as excinfo:
        client.get_json("/user")

    assert excinfo.value.status_code == 401
    assert excinfo.value.endpoint == "/user"


def test_403_without_rate_limit_signal_raises_github_auth_error(client_factory, make_response):
    client, _ = client_factory(
        [make_response({"message": "Resource not accessible by integration"}, status_code=403)]
    )

    with pytest.raises(GitHubAuthError):
        client.get_json("/repos/acme/private")


def test_retry_after_is_honoured_before_retrying(client_factory, make_response, sleeps):
    client, handler = client_factory(
        [
            make_response({"message": "slow down"}, status_code=429, headers={"Retry-After": "3"}),
            make_response({"full_name": "acme/tool"}),
        ]
    )

    payload = client.get_json("/repos/acme/tool")

    assert payload == {"full_name": "acme/tool"}
    assert sleeps == [3.0]
    assert handler.call_count == 2


def test_retry_after_is_capped_and_surfaces_as_rate_limited(
    client_factory, make_response, sleeps
):
    client, handler = client_factory(
        [make_response({"message": "slow down"}, status_code=403, headers={"Retry-After": "3600"})]
    )

    with pytest.raises(GitHubRateLimited) as excinfo:
        client.get_json("/repos/acme/tool")

    assert excinfo.value.retry_after == 3600.0
    assert excinfo.value.status_code == 403
    assert sleeps == []
    assert handler.call_count == 1


def test_http_date_retry_after_still_counts_as_rate_limiting(client_factory, make_response, sleeps):
    client, handler = client_factory(
        [
            make_response(
                {"message": "secondary rate limit"},
                status_code=403,
                headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
            )
        ]
    )

    with pytest.raises(GitHubRateLimited) as excinfo:
        client.get_json("/repos/acme/tool")

    assert excinfo.value.retry_after is None
    assert excinfo.value.status_code == 403
    assert sleeps == []
    assert handler.call_count == 1


def test_exhausted_retry_after_budget_raises_rate_limited(
    client_factory, make_response, github_config, sleeps
):
    responses = [
        make_response({"message": "secondary rate limit"}, status_code=429, headers={"Retry-After": "2"})
        for _ in range(github_config.max_retries + 1)
    ]
    client, handler = client_factory(responses)

    with pytest.raises(GitHubRateLimited) as excinfo:
        client.get_json("/search/repositories")

    assert excinfo.value.retry_after == 2.0
    assert handler.call_count == github_config.max_retries + 1
    assert sleeps == [2.0] * github_config.max_retries


def test_forbidden_with_zero_remaining_reports_reset_delta(
    client_factory, make_response, github_config, fixed_clock, fixed_now, sleeps
):
    reset = int((fixed_now + timedelta(seconds=600)).timestamp())
    client, _ = client_factory(
        [
            make_response(
                {"message": "API rate limit exceeded"},
                status_code=403,
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset)},
            )
        ],
        clock=fixed_clock,
    )

    with pytest.raises(GitHubRateLimited) as excinfo:
        client.get_json("/repos/acme/tool")

    assert excinfo.value.retry_after == pytest.approx(600, abs=1)
    assert sleeps == []


def test_server_errors_retry_with_exponential_backoff_then_raise(
    client_factory, make_response, github_config, sleeps
):
    responses = [
        make_response({"message": "server error"}, status_code=503)
        for _ in range(github_config.max_retries + 1)
    ]
    client, handler = client_factory(responses)

    with pytest.raises(GitHubServerError) as excinfo:
        client.get_json("/repos/acme/tool")

    assert handler.call_count == github_config.max_retries + 1
    assert sleeps == [2.0, 4.0, 8.0]
    assert excinfo.value.status_code == 503
    assert excinfo.value.endpoint == "/repos/acme/tool"


def test_backoff_never_exceeds_the_configured_cap(client_factory, make_response, github_config, sleeps):
    capped_config = replace(github_config, backoff_base_seconds=10.0, backoff_max_seconds=15.0)
    responses = [
        make_response({"message": "server error"}, status_code=500)
        for _ in range(github_config.max_retries + 1)
    ]
    client, _ = client_factory(responses, config=capped_config)

    with pytest.raises(GitHubServerError):
        client.get_json("/repos/acme/tool")

    assert sleeps == [10.0, 15.0, 15.0]


def test_transport_errors_are_retried_then_normalized(client_factory, github_config, sleeps):
    client, handler = client_factory(
        [httpx.ConnectError("connection refused") for _ in range(github_config.max_retries + 1)]
    )

    with pytest.raises(GitHubError) as excinfo:
        client.get_json("/repos/acme/tool")

    assert handler.call_count == github_config.max_retries + 1
    assert sleeps == [2.0, 4.0, 8.0]
    assert not isinstance(excinfo.value, (GitHubNotFound, GitHubAuthError, GitHubRateLimited))
    assert "ConnectError" in str(excinfo.value)


def test_transport_error_recovers_within_retry_budget(client_factory, make_response, sleeps):
    client, handler = client_factory(
        [httpx.ReadTimeout("timed out"), make_response({"ok": True})]
    )

    assert client.get_json("/rate_limit") == {"ok": True}
    assert handler.call_count == 2
    assert sleeps == [2.0]


def test_token_never_leaks_into_errors_or_logs(client_factory, make_response, caplog):
    client, _ = client_factory(
        [make_response({"message": "Bad credentials"}, status_code=401)], token=TOKEN
    )

    with caplog.at_level(logging.DEBUG, logger="hidden_gems.github"):
        with pytest.raises(GitHubAuthError) as excinfo:
            client.get_json("/repos/acme/tool")

    message = str(excinfo.value)
    assert TOKEN not in message
    assert "Authorization" not in message
    assert "authorization" not in message
    assert TOKEN not in caplog.text
    assert "Authorization" not in caplog.text


def test_token_never_leaks_when_retrying(client_factory, make_response, caplog, sleeps):
    client, _ = client_factory(
        [
            make_response({"message": "boom"}, status_code=500),
            make_response({"message": "boom"}, status_code=500),
            make_response({"message": "boom"}, status_code=500),
            make_response({"message": "boom"}, status_code=500),
        ],
        token=TOKEN,
    )

    with caplog.at_level(logging.DEBUG, logger="hidden_gems.github"):
        with pytest.raises(GitHubServerError):
            client.get_json("/repos/acme/tool")

    assert sleeps == [2.0, 4.0, 8.0]
    assert TOKEN not in caplog.text
    assert "Authorization" not in caplog.text


def test_search_repositories_returns_total_count_and_raw_items(
    client_factory, make_response, github_config
):
    items = [{"id": 1, "full_name": "acme/tool"}]
    client, handler = client_factory(
        [make_response({"total_count": 1, "incomplete_results": False, "items": items})]
    )

    payload = client.search_repositories("agent stars:10..50", page=2)

    assert payload == {"total_count": 1, "items": items}
    params = dict(handler.last_request.url.params)
    assert params["q"] == "agent stars:10..50"
    assert params["page"] == "2"
    assert params["per_page"] == str(github_config.per_page)
    assert handler.last_request.url.path == "/search/repositories"


def test_search_repositories_tolerates_missing_keys(client_factory, make_response):
    client, _ = client_factory([make_response({})])

    assert client.search_repositories("agent") == {"total_count": 0, "items": []}


def test_get_repo_metadata_returns_payload(client_factory, make_response):
    client, handler = client_factory([make_response({"id": 7, "full_name": "acme/tool"})])

    assert client.get_repo_metadata("acme/tool") == {"id": 7, "full_name": "acme/tool"}
    assert handler.last_request.url.path == "/repos/acme/tool"


def test_get_readme_decodes_base64_content(client_factory, make_response):
    readme = "# Acme Tool\n\nDoes one thing well.\n"
    encoded = base64.b64encode(readme.encode("utf-8")).decode("ascii")
    client, handler = client_factory(
        [make_response({"name": "README.md", "encoding": "base64", "content": encoded})]
    )

    assert client.get_readme("acme/tool") == readme
    assert handler.last_request.url.path == "/repos/acme/tool/readme"


def test_get_readme_decodes_line_wrapped_base64_content(client_factory, make_response):
    readme = "# Acme Tool\n" + ("Body line that GitHub would wrap.\n" * 5)
    wrapped = "\n".join(
        base64.b64encode(readme.encode("utf-8")).decode("ascii")[i : i + 60]
        for i in range(0, len(base64.b64encode(readme.encode("utf-8"))), 60)
    )
    client, _ = client_factory(
        [make_response({"encoding": "base64", "content": f"{wrapped}\n"})]
    )

    assert client.get_readme("acme/tool") == readme


def test_get_readme_returns_none_when_absent(client_factory, make_response):
    client, _ = client_factory([make_response({"message": "Not Found"}, status_code=404)])

    assert client.get_readme("acme/tool") is None


def test_get_tree_returns_tree_entries(client_factory, make_response):
    tree = [{"path": "README.md", "type": "blob", "size": 120, "sha": "abc"}]
    client, handler = client_factory([make_response({"sha": "root", "tree": tree, "truncated": False})])

    assert client.get_tree("acme/tool", "main") == tree
    assert handler.last_request.url.path == "/repos/acme/tool/git/trees/main"
    assert dict(handler.last_request.url.params) == {"recursive": "1"}


def test_get_tree_tolerates_missing_tree_key(client_factory, make_response):
    client, _ = client_factory([make_response({})])

    assert client.get_tree("acme/tool", "main") == []


def test_get_releases_are_capped_by_limit(client_factory, make_response):
    releases = [{"tag_name": f"v{i}"} for i in range(5)]
    client, handler = client_factory([make_response(releases)])

    assert client.get_releases("acme/tool", limit=3) == releases[:3]
    assert handler.last_request.url.path == "/repos/acme/tool/releases"
    assert dict(handler.last_request.url.params) == {"per_page": "3"}


def test_get_recent_commits_passes_since_and_caps_limit(client_factory, make_response):
    since = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    commits = [{"sha": f"{i:040d}"} for i in range(4)]
    client, handler = client_factory([make_response(commits)])

    result = client.get_recent_commits("acme/tool", since=since, limit=2)

    assert result == commits[:2]
    assert handler.last_request.url.path == "/repos/acme/tool/commits"
    assert dict(handler.last_request.url.params) == {
        "since": "2026-08-01T00:00:00Z",
        "per_page": "2",
    }


def test_get_recent_commits_accepts_iso_string_since(client_factory, make_response):
    client, handler = client_factory([make_response([])])

    client.get_recent_commits("acme/tool", since="2026-08-01T00:00:00Z")

    assert dict(handler.last_request.url.params)["since"] == "2026-08-01T00:00:00Z"


def test_post_json_sends_payload_and_returns_decoded_json(client_factory, make_response):
    client, handler = client_factory([make_response({"number": 12, "html_url": "https://example/12"})])

    result = client.post_json("/repos/acme/tool/issues", {"title": "report", "body": "body"})

    assert result == {"number": 12, "html_url": "https://example/12"}
    request = handler.last_request
    assert request.method == "POST"
    assert json.loads(request.content.decode("utf-8")) == {"title": "report", "body": "body"}


def test_rate_budget_tracks_response_headers(client_factory, make_response, github_config):
    reset = 1789491000
    client, _ = client_factory(
        [
            make_response(
                {"ok": True},
                headers={
                    "X-RateLimit-Limit": "5000",
                    "X-RateLimit-Remaining": "300",
                    "X-RateLimit-Reset": str(reset),
                    "X-RateLimit-Resource": "core",
                },
            )
        ]
    )

    client.get_json("/rate_limit")

    budget = client.rate_budget
    assert budget.limit == 5000
    assert budget.remaining == 300
    assert budget.reset_at == datetime.fromtimestamp(reset, tz=timezone.utc)
    assert budget.zone == "GREEN"
    assert json.loads(json.dumps(budget.snapshot()))["remaining"] == 300


def test_a_single_rate_budget_object_is_exposed(client_factory, make_response):
    client, _ = client_factory([make_response({})])

    assert client.rate_budget is client.rate_budget


def test_close_releases_the_underlying_http_client(client_factory, make_response):
    client, _ = client_factory([make_response({})])

    client.close()

    with pytest.raises(RuntimeError):
        client.get_json("/rate_limit")


def test_client_accepts_app_config(client_factory, app_config, make_response):
    client, _ = client_factory([make_response({})], config=app_config)

    assert isinstance(client, GitHubClient)
    assert client.base_url == app_config.github.api_base_url.rstrip("/")
