"""Canonical SQLite history (the only module that writes the database)."""

from .database import HistoryStore
from .integrity import CANONICAL_TABLES, check_integrity, schema_version, validate_schema
from .repository import RepoNotificationState

__all__ = [
    "CANONICAL_TABLES",
    "HistoryStore",
    "RepoNotificationState",
    "check_integrity",
    "schema_version",
    "validate_schema",
]
