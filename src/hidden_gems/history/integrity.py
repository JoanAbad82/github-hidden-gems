"""SQLite integrity helpers (SPEC_V1 section 9)."""

from __future__ import annotations

import sqlite3
from typing import Any


def check_integrity(connection: sqlite3.Connection) -> bool:
    """True only when SQLite reports exactly `ok`."""

    try:
        row = connection.execute("PRAGMA integrity_check").fetchone()
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    except sqlite3.DatabaseError:
        return False
    if not row or str(row[0]).lower() != "ok":
        return False
    return not foreign_keys


def schema_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    except sqlite3.DatabaseError:
        return 0
    return int(row[0]) if row and row[0] is not None else 0


def required_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


CANONICAL_TABLES: frozenset[str] = frozenset(
    {
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
)


def validate_schema(connection: sqlite3.Connection) -> bool:
    try:
        tables = required_tables(connection)
    except sqlite3.DatabaseError:
        return False
    return CANONICAL_TABLES <= tables and schema_version(connection) >= 1
