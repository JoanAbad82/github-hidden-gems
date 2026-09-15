"""Persistence methods for the canonical SQLite history."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from ..common.time import ensure_utc, parse_github_datetime, to_iso, utcnow
from ..models import (
    RUN_RESULTS,
    DeepAnalysis,
    HiddenGemScore,
    RepositoryRef,
)

_REPORT_STATES = ("NONE", "PENDING_REPORT", "REPORT_PUBLISHED")


@dataclass(frozen=True)
class RepoNotificationState:
    """What reporting needs to know about a repository's notification history."""

    github_repo_id: int
    ever_seen: bool = False
    last_notified_score: int | None = None
    last_notification_id: int | None = None
    last_notified_at: datetime | None = None
    notified_fingerprints: frozenset[str] = field(default_factory=frozenset)


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, default=str)


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class RepositoryMixin:
    """Repository, observation, score, LLM-cache, notification and run methods."""

    # -- repositories ------------------------------------------------------

    def get_repository(self, github_repo_id: int) -> dict[str, Any] | None:
        row = self._connection.execute(
            "SELECT * FROM repositories WHERE github_repo_id = ?", (int(github_repo_id),)
        ).fetchone()
        return dict(row) if row else None

    def upsert_repository(
        self,
        repo: RepositoryRef,
        *,
        stars: int = 0,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        primary_language: str | None = None,
        description: str | None = None,
        seen_at: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
        topics: Sequence[str] | None = None,
        pushed_at: datetime | None = None,
    ) -> None:
        moment = to_iso(ensure_utc(seen_at) if seen_at is not None else utcnow())
        payload = dict(metadata or {})
        if topics is not None:
            payload.setdefault("topics", list(topics))
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO repositories (
                    github_repo_id, owner, name, full_name, html_url, description, stars,
                    created_at, updated_at, pushed_at, primary_language, topics, metadata,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (github_repo_id) DO UPDATE SET
                    stars = excluded.stars,
                    description = COALESCE(excluded.description, repositories.description),
                    updated_at = COALESCE(excluded.updated_at, repositories.updated_at),
                    pushed_at = COALESCE(excluded.pushed_at, repositories.pushed_at),
                    primary_language = COALESCE(excluded.primary_language, repositories.primary_language),
                    topics = COALESCE(excluded.topics, repositories.topics),
                    metadata = COALESCE(excluded.metadata, repositories.metadata),
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    repo.github_repo_id,
                    repo.owner,
                    repo.name,
                    repo.full_name,
                    repo.html_url,
                    description,
                    int(stars or 0),
                    to_iso(created_at),
                    to_iso(updated_at),
                    to_iso(pushed_at),
                    primary_language,
                    _json(payload.get("topics", [])),
                    _json(payload) if payload else None,
                    moment,
                    moment,
                ),
            )

    # -- observations / discovery / filters / scores -----------------------

    def save_observation(
        self,
        github_repo_id: int,
        *,
        observed_at: datetime,
        run_id: str,
        readme_hash: str | None = None,
        tree_hash: str | None = None,
        dependency_hash: str | None = None,
        relevant_content_hash: str | None = None,
        activity_level: str | None = None,
        detected_areas: Sequence[str] = (),
        latest_release_tag: str | None = None,
        latest_release_at: datetime | None = None,
        latest_relevant_activity_at: datetime | None = None,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO observations (
                    github_repo_id, run_id, observed_at, readme_hash, tree_hash, dependency_hash,
                    relevant_content_hash, activity_level, detected_areas, latest_release_tag,
                    latest_release_at, latest_relevant_activity_at, evidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(github_repo_id),
                    run_id,
                    to_iso(observed_at),
                    readme_hash,
                    tree_hash,
                    dependency_hash,
                    relevant_content_hash,
                    activity_level,
                    _json(list(detected_areas)),
                    latest_release_tag,
                    to_iso(latest_release_at),
                    to_iso(latest_relevant_activity_at),
                    _json(evidence),
                ),
            )

    def save_discovery_hit(
        self, github_repo_id: int, *, run_id: str, channel: str, query_id: str, seen_at: datetime
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO discovery_hits (github_repo_id, run_id, channel, query_id, seen_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(github_repo_id), run_id, channel, query_id, to_iso(seen_at)),
            )

    def save_filter_decision(
        self,
        github_repo_id: int,
        *,
        run_id: str,
        decided_at: datetime,
        passed: bool,
        reason_code: str | None,
        evidence: Sequence[str] = (),
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO filter_decisions (github_repo_id, run_id, decided_at, passed, reason_code, evidence)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (int(github_repo_id), run_id, to_iso(decided_at), 1 if passed else 0, reason_code, _json(list(evidence))),
            )

    def save_score(
        self, github_repo_id: int, *, run_id: str, scored_at: datetime, score: HiddenGemScore
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO scores (
                    github_repo_id, run_id, scored_at, relevance, quality, activity, visibility,
                    novelty, originality, intersection, total, confidence, score_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(github_repo_id),
                    run_id,
                    to_iso(scored_at),
                    score.relevance,
                    score.quality,
                    score.activity,
                    score.visibility,
                    score.novelty,
                    score.originality,
                    score.intersection,
                    score.total,
                    score.confidence,
                    score.score_version,
                ),
            )
            connection.execute(
                "UPDATE repositories SET current_score = ? WHERE github_repo_id = ?",
                (score.total, int(github_repo_id)),
            )

    # -- LLM cache ---------------------------------------------------------

    def find_llm_analysis(
        self,
        *,
        github_repo_id: int,
        relevant_content_hash: str,
        prompt_version: str,
        schema_version: str,
        model: str,
    ) -> DeepAnalysis | None:
        row = self._connection.execute(
            """
            SELECT * FROM llm_analyses
            WHERE github_repo_id = ? AND relevant_content_hash = ? AND prompt_version = ?
              AND schema_version = ? AND model = ?
            """,
            (int(github_repo_id), relevant_content_hash, prompt_version, schema_version, model),
        ).fetchone()
        if row is None:
            return None
        repository = self.get_repository(github_repo_id)
        if repository is None:
            return None
        ref = RepositoryRef(
            github_repo_id=repository["github_repo_id"],
            owner=repository["owner"],
            name=repository["name"],
            full_name=repository["full_name"],
            html_url=repository["html_url"],
        )
        risks = _loads(row["risks"], [])
        return DeepAnalysis(
            repo=ref,
            evidence=_loads(row["evidence"], {}),
            relevance_suggestion=row["relevance_suggestion"],
            originality_suggestion=row["originality_suggestion"],
            why_interesting=row["why_interesting"],
            summary=row["summary"],
            risks=tuple(risks),
            confidence=row["confidence"] or "LOW",
            status=row["status"] or "OK",
            source="CACHE",
        )

    def save_llm_analysis(
        self,
        github_repo_id: int,
        *,
        run_id: str,
        analyzed_at: datetime,
        relevant_content_hash: str,
        prompt_version: str,
        schema_version: str,
        model: str,
        analysis: DeepAnalysis,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO llm_analyses (
                    github_repo_id, run_id, analyzed_at, relevant_content_hash, prompt_version,
                    schema_version, model, confidence, status, source, relevance_suggestion,
                    originality_suggestion, why_interesting, summary, risks, evidence,
                    input_tokens, output_tokens, cost
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (github_repo_id, relevant_content_hash, prompt_version, schema_version, model)
                DO UPDATE SET
                    run_id = excluded.run_id,
                    analyzed_at = excluded.analyzed_at,
                    confidence = excluded.confidence,
                    status = excluded.status,
                    source = excluded.source,
                    relevance_suggestion = excluded.relevance_suggestion,
                    originality_suggestion = excluded.originality_suggestion,
                    why_interesting = excluded.why_interesting,
                    summary = excluded.summary,
                    risks = excluded.risks,
                    evidence = excluded.evidence,
                    input_tokens = excluded.input_tokens,
                    output_tokens = excluded.output_tokens,
                    cost = excluded.cost
                """,
                (
                    int(github_repo_id),
                    run_id,
                    to_iso(analyzed_at),
                    relevant_content_hash,
                    prompt_version,
                    schema_version,
                    model,
                    analysis.confidence,
                    analysis.status,
                    "PROVIDER" if analysis.source == "CACHE" else analysis.source,
                    analysis.relevance_suggestion,
                    analysis.originality_suggestion,
                    analysis.why_interesting,
                    analysis.summary,
                    _json(list(analysis.risks)),
                    _json(analysis.evidence),
                    int(input_tokens),
                    int(output_tokens),
                    float(cost),
                ),
            )

    # -- releases / relationships -----------------------------------------

    def save_release(
        self,
        github_repo_id: int,
        *,
        release_id: str,
        observed_at: datetime,
        tag_name: str | None = None,
        name: str | None = None,
        published_at: datetime | None = None,
        prerelease: bool = False,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO releases (
                    github_repo_id, release_id, tag_name, name, published_at, observed_at, prerelease
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(github_repo_id),
                    str(release_id),
                    tag_name,
                    name,
                    to_iso(published_at),
                    to_iso(observed_at),
                    1 if prerelease else 0,
                ),
            )

    def save_relationship(
        self,
        github_repo_id: int,
        *,
        related_repo_id: int,
        source_type: str,
        run_id: str,
        discovered_at: datetime,
        evidence: Sequence[str] = (),
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO relationships (
                    github_repo_id, related_repo_id, source_type, run_id, discovered_at, evidence
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (int(github_repo_id), int(related_repo_id), source_type, run_id, to_iso(discovered_at), _json(list(evidence))),
            )

    # -- notifications -----------------------------------------------------

    def notification_exists(self, fingerprint: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM notifications WHERE fingerprint = ? LIMIT 1", (fingerprint,)
        ).fetchone()
        return row is not None

    def save_notification(
        self,
        github_repo_id: int,
        *,
        fingerprint: str,
        notification_type: str,
        score: int,
        notified_at: datetime,
        run_id: str,
        issue_number: int | None = None,
        previous_score: int | None = None,
    ) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO notifications (
                    github_repo_id, fingerprint, notification_type, score, previous_score,
                    issue_number, notified_at, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(github_repo_id),
                    fingerprint,
                    notification_type,
                    int(score),
                    previous_score,
                    issue_number,
                    to_iso(notified_at),
                    run_id,
                ),
            )
            return int(cursor.lastrowid or 0)

    def latest_notification(self, github_repo_id: int) -> dict[str, Any] | None:
        row = self._connection.execute(
            """
            SELECT * FROM notifications WHERE github_repo_id = ?
            ORDER BY notified_at DESC, notification_id DESC LIMIT 1
            """,
            (int(github_repo_id),),
        ).fetchone()
        return dict(row) if row else None

    def notification_state(self, github_repo_id: int) -> RepoNotificationState:
        repository = self.get_repository(github_repo_id)
        rows = self._connection.execute(
            "SELECT notification_id, fingerprint, score, notified_at FROM notifications WHERE github_repo_id = ?",
            (int(github_repo_id),),
        ).fetchall()
        fingerprints = frozenset(str(row["fingerprint"]) for row in rows)
        latest = self.latest_notification(github_repo_id)
        return RepoNotificationState(
            github_repo_id=int(github_repo_id),
            ever_seen=repository is not None,
            last_notified_score=int(latest["score"]) if latest else None,
            last_notification_id=int(latest["notification_id"]) if latest else None,
            last_notified_at=parse_github_datetime(latest["notified_at"]) if latest else None,
            notified_fingerprints=fingerprints,
        )

    # -- reports and runs --------------------------------------------------

    def start_run(
        self,
        *,
        run_id: str,
        started_at: datetime,
        dry_run: bool,
        config_version: str,
        score_version: str,
        prompt_version: str,
        budgets: Mapping[str, Any],
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, started_at, dry_run, config_version, score_version, prompt_version, budgets, report_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'NONE')
                ON CONFLICT (run_id) DO UPDATE SET
                    started_at = excluded.started_at,
                    dry_run = excluded.dry_run,
                    config_version = excluded.config_version,
                    score_version = excluded.score_version,
                    prompt_version = excluded.prompt_version,
                    budgets = excluded.budgets
                """,
                (
                    run_id,
                    to_iso(started_at),
                    1 if dry_run else 0,
                    config_version,
                    score_version,
                    prompt_version,
                    _json(dict(budgets)),
                ),
            )

    def finish_run(
        self,
        run_id: str,
        *,
        result: str,
        finished_at: datetime,
        usage: Mapping[str, Any] | None = None,
        report_fingerprint: str | None = None,
        issue_number: int | None = None,
        errors: Sequence[str] = (),
    ) -> None:
        if result not in RUN_RESULTS:
            raise ValueError(f"invalid run result: {result!r}")
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE runs SET
                    result = ?, finished_at = ?, usage = COALESCE(?, usage),
                    report_fingerprint = COALESCE(?, report_fingerprint),
                    issue_number = COALESCE(?, issue_number), errors = ?
                WHERE run_id = ?
                """,
                (
                    result,
                    to_iso(finished_at),
                    _json(dict(usage)) if usage is not None else None,
                    report_fingerprint,
                    issue_number,
                    _json(list(errors)),
                    run_id,
                ),
            )

    def save_pending_report(
        self, *, fingerprint: str, run_id: str, created_at: datetime, payload: str
    ) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE runs SET report_fingerprint = ?, report_payload = ?, report_state = 'PENDING_REPORT'
                WHERE run_id = ?
                """,
                (fingerprint, payload, run_id),
            )
            if cursor.rowcount == 0:
                connection.execute(
                    """
                    INSERT INTO runs (run_id, started_at, dry_run, report_fingerprint, report_payload, report_state)
                    VALUES (?, ?, 1, ?, ?, 'PENDING_REPORT')
                    """,
                    (run_id, to_iso(created_at), fingerprint, payload),
                )

    def find_pending_report(self, fingerprint: str | None = None) -> dict[str, Any] | None:
        if fingerprint is None:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE report_state IN ('PENDING_REPORT', 'REPORT_PUBLISHED') ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        else:
            row = self._connection.execute(
                "SELECT * FROM runs WHERE report_fingerprint = ? ORDER BY started_at DESC LIMIT 1", (fingerprint,)
            ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        return {
            "run_id": payload["run_id"],
            "fingerprint": payload["report_fingerprint"],
            "payload": payload["report_payload"],
            "report_state": payload["report_state"],
            "issue_number": payload["issue_number"],
            "issue_url": payload["issue_url"],
        }

    def mark_report_published(
        self, fingerprint: str, *, issue_number: int, issue_url: str, published_at: datetime, run_id: str
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                UPDATE runs SET report_state = 'REPORT_PUBLISHED', issue_number = ?, issue_url = ?
                WHERE report_fingerprint = ?
                """,
                (int(issue_number), issue_url, fingerprint),
            )

    def run_row(self, run_id: str) -> dict[str, Any] | None:
        row = self._connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    # -- read-only history accessors (validation / reporting) --------------

    def recent_runs(self, *, limit: int = 30, include_dry_run: bool = True) -> list[dict[str, Any]]:
        """Most recent runs first. Read-only; used by the acceptance gate."""

        sql = "SELECT * FROM runs"
        if not include_dry_run:
            sql += " WHERE dry_run = 0"
        sql += " ORDER BY started_at DESC LIMIT ?"
        rows = self._connection.execute(sql, (max(1, int(limit)),)).fetchall()
        return [dict(row) for row in rows]

    def recent_notifications(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """Most recent notification rows first. Read-only."""

        rows = self._connection.execute(
            "SELECT * FROM notifications ORDER BY notified_at DESC, notification_id DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def notifications_for_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT * FROM notifications WHERE run_id = ? ORDER BY notification_id",
            (str(run_id),),
        ).fetchall()
        return [dict(row) for row in rows]

    def count(self, table: str) -> int:
        if table not in {
            "repositories",
            "observations",
            "discovery_hits",
            "filter_decisions",
            "scores",
            "llm_analyses",
            "releases",
            "relationships",
            "notifications",
            "runs",
        }:
            raise ValueError(f"unknown table: {table}")
        row = self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return int(row[0])

    @property
    def _connection_ref(self) -> sqlite3.Connection:  # pragma: no cover - debug helper
        return self._connection
