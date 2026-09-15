"""Task 14: atomic state-branch checkpoint, optimistic parent, backup rotation."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hidden_gems.history.state_branch import (
    StateBranchManager,
    StateConflict,
    StateIntegrityError,
)


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("# project\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "initial")
    return repo


def create_database(path: Path) -> None:
    """A minimal but valid SQLite database with the canonical run table."""

    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, result TEXT)"
        )
        connection.execute("INSERT OR REPLACE INTO runs VALUES ('RUN-1', 'SUCCESS')")
        connection.commit()
    finally:
        connection.close()


def test_state_branch_is_created_and_can_be_loaded(git_repo):
    manager = StateBranchManager(git_repo)
    workdir = git_repo.parent / "state-work"
    snapshot = manager.load(workdir)
    assert snapshot.parent_sha is None

    create_database(snapshot.db_path)
    snapshot.last_run_id = "RUN-1"
    snapshot.manifest["last_run_id"] = "RUN-1"
    commit = manager.persist(snapshot, expected_parent_sha=None)

    assert git(git_repo, "rev-parse", "refs/heads/state") == commit
    files = git(git_repo, "ls-tree", "-r", "--name-only", "state").splitlines()
    assert "history.sqlite3" in files
    assert "state_manifest.json" in files

    reloaded = manager.load(git_repo.parent / "state-work-2")
    assert reloaded.parent_sha == commit
    assert reloaded.manifest["last_run_id"] == "RUN-1"
    assert reloaded.db_path.exists()


def test_failed_integrity_leaves_previous_state_commit_unchanged(git_repo):
    manager = StateBranchManager(git_repo)
    workdir = git_repo.parent / "state-work"
    snapshot = manager.load(workdir)
    create_database(snapshot.db_path)
    first = manager.persist(snapshot, expected_parent_sha=None)

    corrupted = manager.load(workdir)
    corrupted.db_path.write_bytes(b"this is not a sqlite database")
    with pytest.raises(StateIntegrityError):
        manager.persist(corrupted, expected_parent_sha=first)

    assert git(git_repo, "rev-parse", "refs/heads/state") == first


def test_stale_parent_is_refused_with_state_conflict(git_repo):
    manager = StateBranchManager(git_repo)
    workdir = git_repo.parent / "state-work"
    snapshot = manager.load(workdir)
    create_database(snapshot.db_path)
    first = manager.persist(snapshot, expected_parent_sha=None)

    stale = manager.load(workdir)
    current = manager.load(workdir)
    create_database(current.db_path)
    second = manager.persist(current, expected_parent_sha=first)
    assert second != first

    with pytest.raises(StateConflict):
        manager.persist(stale, expected_parent_sha=first)
    assert git(git_repo, "rev-parse", "refs/heads/state") == second


def test_pending_report_checkpoint_updates_the_manifest(git_repo):
    manager = StateBranchManager(git_repo)
    snapshot = manager.load(git_repo.parent / "state-work")
    create_database(snapshot.db_path)

    manager.checkpoint_pending_report(snapshot, "REPORT:abc123")

    assert snapshot.report_state == "PENDING_REPORT"
    manifest = (snapshot.workdir / "state_manifest.json").read_text(encoding="utf-8")
    assert "REPORT:abc123" in manifest
    assert "PENDING_REPORT" in manifest


def test_backup_rotation_keeps_three_backups(git_repo):
    manager = StateBranchManager(git_repo, max_backups=3)
    workdir = git_repo.parent / "state-work"
    snapshot = manager.load(workdir)
    create_database(snapshot.db_path)
    manager.persist(snapshot, expected_parent_sha=None)

    for index in range(4):
        snapshot = manager.load(workdir)
        create_database(snapshot.db_path)
        with snapshot.db_path.open("ab") as handle:
            handle.write(f"\n-- revision {index}\n".encode("utf-8"))
        manager.rotate_backups(snapshot)
        manager.persist(snapshot, expected_parent_sha=snapshot.parent_sha)

    backups = sorted((workdir / "backups").glob("*.sqlite3.gz"))
    assert len(backups) == 3
    assert snapshot.db_path.exists()
    assert (workdir / "state_manifest.json").exists()


def test_manifest_records_hash_and_never_secrets(git_repo):
    manager = StateBranchManager(git_repo)
    snapshot = manager.load(git_repo.parent / "state-work")
    create_database(snapshot.db_path)
    snapshot.manifest["last_run_id"] = "RUN-9"
    manager.persist(snapshot, expected_parent_sha=None)

    manifest_text = (snapshot.workdir / "state_manifest.json").read_text(encoding="utf-8")
    assert "db_sha256" in manifest_text
    assert "token" not in manifest_text.lower()
    assert "secret" not in manifest_text.lower()


def test_non_git_directory_is_rejected(tmp_path):
    manager = StateBranchManager(tmp_path / "not-a-repo")

    with pytest.raises(StateConflict):
        manager.load(tmp_path / "work")
