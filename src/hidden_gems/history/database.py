"""SQLite connection, migrations and transaction handling.

`history` is the only module allowed to write SQLite (SPEC_V1 section 12).
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .integrity import check_integrity, validate_schema
from .repository import RepositoryMixin

logger = logging.getLogger("hidden_gems.history")

DEFAULT_MIGRATIONS_DIRNAME = Path("migrations") / "sqlite"


def _sql_statements(script: str) -> list[str]:
    """Split a migration script into individual statements.

    ``sqlite3.Connection.executescript`` commits any open transaction, which
    would break the store's explicit transaction handling, so migrations are
    executed statement by statement inside one transaction.
    """

    without_comments = "\n".join(
        line for line in script.splitlines() if not line.strip().startswith("--")
    )
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


class HistoryStore(RepositoryMixin):
    """Canonical SQLite history store."""

    def __init__(self, path: Path | str, *, migrations_dir: Path | None = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrations_dir = Path(migrations_dir) if migrations_dir else None
        self._depth = 0
        self._degraded = False
        self._connection = sqlite3.connect(str(self.path), isolation_level=None, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self.migrate()
        except sqlite3.DatabaseError as exc:  # corrupted or unreadable database
            self._degraded = True
            logger.warning("history database is unusable: %s", type(exc).__name__)

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def open(cls, path: Path | str, *, migrations_dir: Path | None = None) -> "HistoryStore":
        return cls(path, migrations_dir=migrations_dir)

    def close(self) -> None:
        try:
            self._connection.close()
        except sqlite3.Error:  # pragma: no cover - defensive
            pass

    def __enter__(self) -> "HistoryStore":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def degraded(self) -> bool:
        return self._degraded

    # -- migrations --------------------------------------------------------

    def _migration_files(self) -> list[Path]:
        directory = self.migrations_dir
        if directory is None:
            candidate = Path(__file__).resolve().parents[3] / DEFAULT_MIGRATIONS_DIRNAME
            directory = candidate if candidate.is_dir() else None
        if directory is None or not directory.is_dir():
            return []
        return sorted(directory.glob("*.sql"))

    def migrate(self) -> None:
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        applied = {
            int(row[0])
            for row in self._connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for path in self._migration_files():
            try:
                version = int(path.name.split("_", 1)[0])
            except ValueError:  # pragma: no cover - defensive
                continue
            if version in applied:
                continue
            with self.transaction() as connection:
                for statement in _sql_statements(path.read_text(encoding="utf-8")):
                    connection.execute(statement)
                connection.execute(
                    "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
                    (version,),
                )
            applied.add(version)

    # -- transactions ------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on exception; safe to nest."""

        if self._depth > 0:
            self._depth += 1
            try:
                yield self._connection
            finally:
                self._depth -= 1
            return

        self._connection.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield self._connection
        except BaseException:
            self._depth = 0
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._depth = 0
            self._connection.execute("COMMIT")

    # -- integrity ---------------------------------------------------------

    def integrity_check(self) -> bool:
        if self._degraded:
            return False
        if not check_integrity(self._connection):
            return False
        return validate_schema(self._connection)
