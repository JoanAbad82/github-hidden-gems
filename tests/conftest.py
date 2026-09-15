"""Shared pytest fixtures.

Task-specific fixtures live next to their tests so parallel work stays
conflict-free.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - belt and braces
    sys.path.insert(0, str(REPO_ROOT / "src"))

CONFIG_FILENAMES = ("discovery.yml", "topics.yml", "scoring.yml", "limits.yml")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def app_config(repo_root: Path):
    from hidden_gems.config import load_config

    return load_config(repo_root)


def _load_canonical_config() -> dict[str, dict]:
    return {
        name: yaml.safe_load((REPO_ROOT / "config" / name).read_text(encoding="utf-8"))
        for name in CONFIG_FILENAMES
    }


@pytest.fixture
def canonical_config_tree(tmp_path: Path):
    """Write a canonical config tree, optionally with extra (unknown) keys."""

    def _make(
        target: Path | str | None = None,
        *,
        extra_limits: dict | None = None,
        extra_discovery: dict | None = None,
        extra_scoring: dict | None = None,
        extra_topics: dict | None = None,
    ) -> Path:
        root = Path(target) if target is not None else tmp_path
        config_dir = root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        data = copy.deepcopy(_load_canonical_config())
        for name, extras in (
            ("limits.yml", extra_limits),
            ("discovery.yml", extra_discovery),
            ("scoring.yml", extra_scoring),
            ("topics.yml", extra_topics),
        ):
            if extras:
                data[name].update(extras)
        for name, payload in data.items():
            (config_dir / name).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return root

    return _make
