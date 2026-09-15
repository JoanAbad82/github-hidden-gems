"""Task 12: two-phase, fingerprint-keyed Issue publication."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from hidden_gems.github.issues import GitHubIssuePublisher
from hidden_gems.models import (
    HiddenGemScore,
    NotificationDecision,
    RepositoryRef,
    RunSummary,
    SelectedFinding,
)
from hidden_gems.reporting.markdown import build_report, report_labels
from hidden_gems.reporting.fingerprints import report_fingerprint

STARTED = datetime(2026, 9, 15, 6, 17, tzinfo=timezone.utc)
REPOSITORY = "JoanAbad82/github-hidden-gems"


class FakeGitHubClient:
    """Minimal client double covering the endpoints the publisher uses."""

    def __init__(self) -> None:
        self.issues: list[dict] = []
        self.posts: list[tuple[str, dict]] = []

    def get_json(self, path: str, params=None):
        assert path.endswith("/issues")
        return list(self.issues)

    def post_json(self, path: str, payload):
        self.posts.append((path, payload))
        number = 100 + len(self.issues) + 1
        issue = {
            "number": number,
            "html_url": f"https://github.com/{REPOSITORY}/issues/{number}",
            "body": payload["body"],
            "title": payload["title"],
        }
        self.issues.append(issue)
        return issue


class FakePendingStore:
    """Double for the HistoryStore pending-report protocol (Task 2 owns it)."""

    def __init__(self) -> None:
        self.pending: dict[str, dict] = {}
        self.published: list[tuple[str, int]] = []

    def save_pending_report(self, *, fingerprint, run_id, created_at, payload) -> None:
        self.pending[fingerprint] = {
            "fingerprint": fingerprint,
            "run_id": run_id,
            "created_at": created_at,
            "payload": payload,
            "state": "PENDING_REPORT",
        }

    def find_pending_report(self, fingerprint=None):
        if fingerprint is None:
            return next(iter(self.pending.values()), None)
        return self.pending.get(fingerprint)

    def mark_report_published(self, fingerprint, *, issue_number, issue_url, published_at, run_id) -> None:
        record = self.pending[fingerprint]
        record["state"] = "REPORT_PUBLISHED"
        record["issue_number"] = issue_number
        record["issue_url"] = issue_url
        self.published.append((fingerprint, issue_number))


def finding(repo_id: int = 55, total: int = 91) -> SelectedFinding:
    maxima = (20, 20, 20, 15, 10, 10, 5)
    values = []
    remaining = total
    for maximum in maxima:
        take = min(maximum, remaining)
        values.append(take)
        remaining -= take
    assert remaining == 0
    repo = RepositoryRef.from_full_name("acme-labs/flowkit", repo_id)
    return SelectedFinding(
        repo=repo,
        score=HiddenGemScore(*values, total, "HIGH"),
        decision=NotificationDecision(
            notify=True,
            notification_type="NEW_DISCOVERY",
            trigger_fingerprint=f"FIRST_DISCOVERY:{repo_id}:HIDDEN_GEM_SCORE_V1",
            previous_score=None,
            current_score=total,
        ),
        status="NEW_DISCOVERY",
        rank=1,
        areas=("automation",),
        primary_language="Python",
        stars=41,
        created_at=STARTED,
    )


def run_summary() -> RunSummary:
    return RunSummary(run_id="RUN-1", result="SUCCESS", started_at=STARTED, finished_at=STARTED)


def test_crash_after_issue_creation_is_recovered_without_a_duplicate(app_config, monkeypatch):
    store = FakePendingStore()
    client = FakeGitHubClient()
    publisher = GitHubIssuePublisher(app_config, client, repository=REPOSITORY)
    findings = [finding()]
    report = build_report(findings, run_summary(), config=app_config)
    fingerprint = report_fingerprint(findings, STARTED.date(), "HIDDEN_GEM_SCORE_V1")
    labels = report_labels(findings, config=app_config)

    # Phase 1: persist the pending report, create the Issue, then crash before
    # the final SQLite confirmation.
    store.save_pending_report(
        fingerprint=fingerprint, run_id="RUN-1", created_at=STARTED, payload=report
    )
    created = publisher.publish(report, fingerprint, labels, assignee="JoanAbad82")
    assert created.created is True
    assert store.find_pending_report(fingerprint)["state"] == "PENDING_REPORT"

    # Phase 2: rerun. Adoption must find the existing Issue and not create one.
    pending = store.find_pending_report()
    adopted = publisher.publish(pending["payload"], pending["fingerprint"], labels)
    store.mark_report_published(
        adopted.fingerprint,
        issue_number=adopted.number,
        issue_url=adopted.url,
        published_at=STARTED,
        run_id="RUN-2",
    )

    assert adopted.created is False
    assert adopted.number == created.number
    assert len(client.issues) == 1
    assert store.published == [(fingerprint, created.number)]


def test_publish_sends_one_post_with_labels_and_assignee(app_config):
    client = FakeGitHubClient()
    publisher = GitHubIssuePublisher(app_config, client, repository=REPOSITORY)
    findings = [finding()]
    report = build_report(findings, run_summary(), config=app_config)
    fingerprint = report_fingerprint(findings, STARTED.date(), "HIDDEN_GEM_SCORE_V1")

    issue = publisher.publish(
        report, fingerprint, report_labels(findings, config=app_config), assignee="JoanAbad82"
    )

    assert issue.created is True
    assert len(client.posts) == 1
    path, payload = client.posts[0]
    assert path == f"/repos/{REPOSITORY}/issues"
    assert payload["assignee"] == "JoanAbad82"
    assert "discovery-report" in payload["labels"]
    assert payload["body"] == report
    assert payload["title"].startswith("GitHub Hidden Gems")


def test_repeated_publish_with_the_same_fingerprint_is_idempotent(app_config):
    client = FakeGitHubClient()
    publisher = GitHubIssuePublisher(app_config, client, repository=REPOSITORY)
    findings = [finding()]
    report = build_report(findings, run_summary(), config=app_config)
    fingerprint = report_fingerprint(findings, STARTED.date(), "HIDDEN_GEM_SCORE_V1")

    first = publisher.publish(report, fingerprint, ["discovery-report"])
    second = publisher.publish(report, fingerprint, ["discovery-report"])

    assert first.number == second.number
    assert second.created is False
    assert len(client.issues) == 1


def test_empty_report_is_never_published(app_config):
    publisher = GitHubIssuePublisher(app_config, FakeGitHubClient(), repository=REPOSITORY)

    with pytest.raises(ValueError):
        publisher.publish("", "REPORT:deadbeef", ["discovery-report"])


def test_publisher_requires_a_repository(app_config):
    with pytest.raises(ValueError):
        GitHubIssuePublisher(app_config, FakeGitHubClient(), repository="")
