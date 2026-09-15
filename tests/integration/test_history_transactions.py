from __future__ import annotations

from datetime import timedelta

from hidden_gems.history.database import HistoryStore
from hidden_gems.models import RepositoryRef

NOW = __import__("datetime").datetime(2026, 9, 15, 12, 0, tzinfo=__import__("datetime").timezone.utc)


def test_two_stores_can_share_one_state_database(tmp_path):
    path = tmp_path / "history.sqlite3"
    first = HistoryStore.open(path)
    second = HistoryStore.open(path)
    try:
        ref = RepositoryRef.from_full_name("acme/one", 1)
        other = RepositoryRef.from_full_name("acme/two", 2)
        first.upsert_repository(ref, stars=1, seen_at=NOW)
        second.upsert_repository(other, stars=2, seen_at=NOW + timedelta(minutes=1))
        assert first.get_repository(2)["stars"] == 2
        assert second.get_repository(1)["stars"] == 1
    finally:
        first.close()
        second.close()


def test_state_survives_reopen(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = HistoryStore.open(path)
    ref = RepositoryRef.from_full_name("acme/persist", 77)
    store.upsert_repository(ref, stars=5, seen_at=NOW)
    store.save_notification(
        ref.github_repo_id,
        fingerprint="FIRST_DISCOVERY:77",
        notification_type="NEW_DISCOVERY",
        score=71,
        notified_at=NOW,
        run_id="run-1",
    )
    store.close()

    reopened = HistoryStore.open(path)
    try:
        assert reopened.integrity_check() is True
        assert reopened.notification_exists("FIRST_DISCOVERY:77") is True
        assert reopened.latest_notification(77)["score"] == 71
    finally:
        reopened.close()


def test_run_and_observation_are_correlated_by_run_id(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = HistoryStore.open(path)
    try:
        ref = RepositoryRef.from_full_name("acme/correlated", 88)
        store.upsert_repository(ref, stars=0, seen_at=NOW)
        store.start_run(
            run_id="run-42",
            started_at=NOW,
            dry_run=True,
            config_version="1.0.0",
            score_version="HIDDEN_GEM_SCORE_V1",
            prompt_version="DEEP_ANALYZER_PROMPT_V1",
            budgets={"max_raw_candidates": 1000},
        )
        store.save_discovery_hit(ref.github_repo_id, run_id="run-42", channel="TOPIC_SEARCH", query_id="Q1", seen_at=NOW)
        store.save_observation(ref.github_repo_id, run_id="run-42", observed_at=NOW, relevant_content_hash="h")
        store.finish_run("run-42", result="SUCCESS", finished_at=NOW + timedelta(minutes=1))
        with store.transaction() as connection:
            observation = connection.execute("SELECT run_id FROM observations").fetchone()[0]
            hit = connection.execute("SELECT run_id FROM discovery_hits").fetchone()[0]
        assert observation == "run-42"
        assert hit == "run-42"
    finally:
        store.close()
