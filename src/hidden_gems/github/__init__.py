"""GitHub access boundary.

``GitHubClient`` is the only programmatic path to the GitHub API (SPEC_V1
section 12). Rate-limit accounting lives beside it so the orchestrator can
read a single :class:`RateBudget` snapshot when deciding whether to keep
working.
"""

from hidden_gems.github.client import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubNotFound,
    GitHubRateLimited,
    GitHubServerError,
)
from hidden_gems.github.rate_limits import GREEN, RED, YELLOW, RateBudget

__all__ = [
    "GREEN",
    "RED",
    "YELLOW",
    "GitHubAuthError",
    "GitHubClient",
    "GitHubError",
    "GitHubNotFound",
    "GitHubRateLimited",
    "GitHubServerError",
    "RateBudget",
]
