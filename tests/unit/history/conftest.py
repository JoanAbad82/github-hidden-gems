from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from hidden_gems.models import RepositoryRef

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def history_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "history.sqlite3"


@pytest.fixture
def store(history_path: Path):
    from hidden_gems.history.database import HistoryStore

    instance = HistoryStore.open(history_path)
    yield instance
    instance.close()


@pytest.fixture
def repo_ref() -> RepositoryRef:
    return RepositoryRef.from_full_name("acme/gem", 4242)
