"""The only code path allowed to create GitHub Issues (SPEC_V1 §10)."""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from ..config import AppConfig
from ..models import IssueRef

DEFAULT_LABEL_SCAN_LIMIT = 100


class GitHubIssuePublisher:
    """Idempotent Issue publisher keyed by REPORT_FINGERPRINT."""

    def __init__(
        self,
        config: AppConfig,
        client: Any,
        *,
        repository: str | None = None,
        label_scan_limit: int = DEFAULT_LABEL_SCAN_LIMIT,
    ) -> None:
        self._config = config
        self._client = client
        self._scan_limit = int(label_scan_limit)
        self.repository = repository or os.environ.get("GITHUB_REPOSITORY") or ""
        owner, _, name = self.repository.partition("/")
        if not owner or not name:
            raise ValueError("publisher requires a repository as 'owner/name'")

    # -- discovery of an already published report -------------------------

    def find_by_fingerprint(self, fingerprint: str) -> IssueRef | None:
        if not fingerprint:
            raise ValueError("fingerprint is required")
        for issue in self._list_report_issues():
            if fingerprint in str(issue.get("body") or ""):
                return IssueRef(
                    number=int(issue["number"]),
                    url=str(issue.get("html_url") or ""),
                    fingerprint=fingerprint,
                    created=False,
                )
        return None

    def _report_label(self) -> str:
        labels = self._config.reporting.labels
        return labels[0] if labels else "discovery-report"

    def _list_report_issues(self) -> list[Mapping[str, Any]]:
        payload = self._client.get_json(
            f"/repos/{self.repository}/issues",
            {"labels": self._report_label(), "state": "all", "per_page": self._scan_limit},
        )
        if not isinstance(payload, list):
            return []
        return [issue for issue in payload if isinstance(issue, Mapping)]

    # -- publication ------------------------------------------------------

    def publish(
        self,
        report: str,
        fingerprint: str,
        labels: Sequence[str],
        assignee: str | None = None,
    ) -> IssueRef:
        if not report.strip():
            raise ValueError("refusing to publish an empty report")

        existing = self.find_by_fingerprint(fingerprint)
        if existing is not None:
            return existing

        payload: dict[str, Any] = {
            "title": self._title(report),
            "body": report,
            "labels": [str(label) for label in labels],
        }
        if assignee:
            payload["assignee"] = assignee

        created = self._client.post_json(f"/repos/{self.repository}/issues", payload)
        return IssueRef(
            number=int(created["number"]),
            url=str(created.get("html_url") or ""),
            fingerprint=fingerprint,
            created=True,
        )

    @staticmethod
    def _title(report: str) -> str:
        for line in report.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
            if stripped:
                return stripped[:120]
        return "GitHub Hidden Gems report"
