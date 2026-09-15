from __future__ import annotations

import sqlite3
from pathlib import Path

from hidden_gems.history.database import HistoryStore

CANONICAL_TABLES = {
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
    "schema_migrations",
}


def table_names(store: HistoryStore) -> set[str]:
    with store.transaction() as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def test_open_creates_every_canonical_table(store: HistoryStore):
    assert CANONICAL_TABLES <= table_names(store)


def test_schema_migrations_records_version_one(store: HistoryStore):
    with store.transaction() as connection:
        versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations").fetchall()]
    assert 1 in versions


def test_foreign_keys_are_enabled(store: HistoryStore):
    with store.transaction() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_new_database_passes_integrity_check(store: HistoryStore):
    assert store.integrity_check() is True


def test_open_is_idempotent(history_path: Path):
    first = HistoryStore.open(history_path)
    first.close()
    second = HistoryStore.open(history_path)
    try:
        assert second.integrity_check() is True
    finally:
        second.close()


def test_corrupted_database_fails_integrity_check(tmp_path: Path):
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"this is not a sqlite database at all" * 64)
    store = HistoryStore.open(path)
    try:
        assert store.integrity_check() is False
    finally:
        store.close()


def test_foreign_key_violation_is_rejected(store: HistoryStore):
    import pytest

    with pytest.raises(sqlite3.IntegrityError):
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO observations (github_repo_id, run_id, observed_at) VALUES (?, ?, ?)",
                (999999, "run-x", "2026-09-15T12:00:00Z"),
            )


def test_transaction_rolls_back_on_exception(store: HistoryStore, repo_ref):
    import pytest

    with pytest.raises(RuntimeError):
        with store.transaction():
            store.upsert_repository(repo_ref, stars=3, seen_at=None)
            raise RuntimeError("forced")
    assert store.get_repository(repo_ref.github_repo_id) is None


def test_migrate_is_safe_to_run_twice(store: HistoryStore):
    store.migrate()
    store.migrate()
    assert store.integrity_check() is True
