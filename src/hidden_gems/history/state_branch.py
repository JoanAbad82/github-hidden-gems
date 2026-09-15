"""Atomic persistence of canonical state on the project's `state` branch.

The `state` branch holds `history.sqlite3`, `state_manifest.json` and rotating
compressed backups. Persistence is optimistic: the caller must pass the parent
commit it loaded, so two concurrent runs can never overwrite each other.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..common.time import utcnow

MANIFEST_SCHEMA_VERSION = "STATE_MANIFEST_V1"

#: Manifest keys frozen by `state_manifest.schema.json`.
MANIFEST_KEYS: tuple[str, ...] = (
    "schema_version",
    "state_timestamp",
    "db_sha256",
    "db_bytes",
    "schema_migration_version",
    "last_run_id",
    "last_run_result",
    "report_state",
    "pending_report_fingerprint",
    "backups",
)

REPORT_STATES: tuple[str, ...] = ("IDLE", "PENDING_REPORT", "REPORT_PUBLISHED")


def write_state_manifest(
    db_path: Path,
    *,
    run_id: str | None = None,
    run_result: str | None = None,
    report_state: str = "IDLE",
    report_fingerprint: str | None = None,
    manifest_path: Path | None = None,
    moment: datetime | None = None,
    schema_migration_version: int | None = None,
    backups: Sequence[str] | None = None,
) -> Path:
    """Write (or refresh) the `state` manifest beside the canonical database.

    The manifest records only technical, non-secret facts about the state
    database. It never includes environment values, tokens or report bodies.
    """

    db_path = Path(db_path)
    target = Path(manifest_path) if manifest_path is not None else db_path.with_name("state_manifest.json")
    previous: dict[str, Any] = {}
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            loaded = {}
        if isinstance(loaded, dict):
            previous = {key: value for key, value in loaded.items() if key in MANIFEST_KEYS}

    if report_state not in REPORT_STATES:
        raise ValueError(f"invalid report_state: {report_state!r}")
    timestamp = (moment or utcnow()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    manifest: dict[str, Any] = dict(previous)
    manifest["schema_version"] = MANIFEST_SCHEMA_VERSION
    manifest["state_timestamp"] = timestamp
    manifest["report_state"] = report_state
    manifest["last_run_id"] = run_id if run_id is not None else previous.get("last_run_id")
    manifest["last_run_result"] = (
        run_result if run_result is not None else previous.get("last_run_result")
    )
    manifest["pending_report_fingerprint"] = (
        report_fingerprint if report_state == "PENDING_REPORT" else None
    )
    if schema_migration_version is not None:
        manifest["schema_migration_version"] = int(schema_migration_version)
    if backups is not None:
        manifest["backups"] = list(backups)
    if db_path.exists():
        manifest["db_sha256"] = hashlib.sha256(db_path.read_bytes()).hexdigest()
        manifest["db_bytes"] = db_path.stat().st_size

    manifest = {key: manifest[key] for key in MANIFEST_KEYS if key in manifest}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


class StateConflict(RuntimeError):
    """Raised when the state branch moved underneath the caller."""


class StateIntegrityError(RuntimeError):
    """Raised when the state database fails its integrity check."""


@dataclass
class StateSnapshot:
    workdir: Path
    db_path: Path
    manifest: dict[str, Any] = field(default_factory=dict)
    parent_sha: str | None = None
    last_run_id: str | None = None
    report_state: str = "IDLE"


class StateBranchManager:
    def __init__(
        self,
        repo_root: Path,
        *,
        branch: str = "state",
        db_filename: str = "history.sqlite3",
        manifest_filename: str = "state_manifest.json",
        max_backups: int = 3,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.branch = branch
        self.db_filename = db_filename
        self.manifest_filename = manifest_filename
        self.max_backups = int(max_backups)
        self.backups_dir = "backups"

    # -- git helpers ------------------------------------------------------

    def _git(self, *args: str, check: bool = True, env: Mapping[str, str] | None = None) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True,
            text=True,
            env={**os.environ, **(env or {})},
            check=False,
        )
        if check and completed.returncode != 0:
            raise StateConflict(
                f"git {' '.join(args)} failed: {completed.stderr.strip() or completed.stdout.strip()}"
            )
        return completed.stdout.strip()

    def _require_repo(self) -> None:
        if not self.repo_root.exists():
            raise StateConflict(f"repository root does not exist: {self.repo_root}")
        out = self._git("rev-parse", "--is-inside-work-tree", check=False)
        if out != "true":
            raise StateConflict(f"not a git working tree: {self.repo_root}")

    def current_sha(self) -> str | None:
        out = self._git("rev-parse", "--verify", "--quiet", f"refs/heads/{self.branch}", check=False)
        return out or None

    # -- load -------------------------------------------------------------

    def load(self, workdir: Path) -> StateSnapshot:
        self._require_repo()
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        parent_sha = self.current_sha()
        if parent_sha:
            self._git("--work-tree", str(workdir), "checkout", parent_sha, "--", ".")
        manifest_path = workdir / self.manifest_filename
        manifest: dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                manifest = {}
        return StateSnapshot(
            workdir=workdir,
            db_path=workdir / self.db_filename,
            manifest=manifest,
            parent_sha=parent_sha,
            last_run_id=manifest.get("last_run_id"),
            report_state=manifest.get("report_state", "IDLE"),
        )

    # -- checkpoints ------------------------------------------------------

    def checkpoint_pending_report(self, snapshot: StateSnapshot, report_fingerprint: str) -> None:
        snapshot.manifest["report_state"] = "PENDING_REPORT"
        snapshot.manifest["pending_report_fingerprint"] = report_fingerprint
        snapshot.report_state = "PENDING_REPORT"
        self._write_manifest(snapshot)

    def rotate_backups(self, snapshot: StateSnapshot) -> None:
        if not snapshot.db_path.exists():
            return
        backups = snapshot.workdir / self.backups_dir
        backups.mkdir(parents=True, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%dT%H%M%S%fZ")
        target = backups / f"{snapshot.db_path.stem}-{stamp}.sqlite3.gz"
        with snapshot.db_path.open("rb") as source, gzip.open(target, "wb") as sink:
            shutil.copyfileobj(source, sink)

        written = sorted(backups.glob("*.sqlite3.gz"))
        for stale in written[: max(0, len(written) - self.max_backups)]:
            stale.unlink()
        snapshot.manifest["backups"] = [
            item.name for item in sorted(backups.glob("*.sqlite3.gz"))
        ]
        self._write_manifest(snapshot)

    def _write_manifest(self, snapshot: StateSnapshot) -> None:
        manifest = dict(snapshot.manifest)
        manifest.setdefault("schema_version", MANIFEST_SCHEMA_VERSION)
        manifest["state_timestamp"] = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        if snapshot.db_path.exists():
            manifest["db_sha256"] = hashlib.sha256(snapshot.db_path.read_bytes()).hexdigest()
            manifest["db_bytes"] = snapshot.db_path.stat().st_size
        snapshot.manifest = manifest
        (snapshot.workdir / self.manifest_filename).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    # -- persistence ------------------------------------------------------

    def verify_database(self, snapshot: StateSnapshot) -> None:
        if not snapshot.db_path.exists():
            raise StateIntegrityError(f"missing state database: {snapshot.db_path}")
        if not _sqlite_integrity_ok(snapshot.db_path):
            raise StateIntegrityError("state database failed PRAGMA integrity_check")

    def persist(self, snapshot: StateSnapshot, expected_parent_sha: str | None) -> str:
        self._require_repo()
        current = self.current_sha()
        if current != expected_parent_sha:
            raise StateConflict(
                f"state branch moved: expected {expected_parent_sha!r}, found {current!r}"
            )
        self.verify_database(snapshot)
        self._write_manifest(snapshot)

        env = {"GIT_INDEX_FILE": str(Path(tempfile.mkdtemp()) / "state-index")}
        try:
            for relative, absolute in self._state_files(snapshot):
                blob = self._hash_file(absolute)
                self._git(
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"100644,{blob},{relative}",
                    env=env,
                )
            tree = self._git("write-tree", env=env)
            message = f"state: run {snapshot.last_run_id or 'unknown'}"
            args = ["commit-tree", tree, "-m", message]
            if current:
                args = ["commit-tree", tree, "-p", current, "-m", message]
            env2 = {**os.environ, "GIT_AUTHOR_NAME": "hidden-gems-bot",
                    "GIT_AUTHOR_EMAIL": "hidden-gems-bot@localhost",
                    "GIT_COMMITTER_NAME": "hidden-gems-bot",
                    "GIT_COMMITTER_EMAIL": "hidden-gems-bot@localhost"}
            completed = subprocess.run(
                ["git", "-C", str(self.repo_root), *args],
                capture_output=True, text=True, env=env2, check=False,
            )
            if completed.returncode != 0:
                raise StateConflict(completed.stderr.strip() or "commit-tree failed")
            commit = completed.stdout.strip()
            if current:
                self._git("update-ref", f"refs/heads/{self.branch}", commit, current)
            else:
                self._git("update-ref", f"refs/heads/{self.branch}", commit)
        finally:
            shutil.rmtree(Path(env["GIT_INDEX_FILE"]).parent, ignore_errors=True)
        snapshot.parent_sha = commit
        return commit

    def _hash_file(self, path: Path) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.repo_root), "hash-object", "-w", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise StateConflict(completed.stderr.strip() or "hash-object failed")
        return completed.stdout.strip()

    def _state_files(self, snapshot: StateSnapshot) -> list[tuple[str, Path]]:
        files: list[tuple[str, Path]] = []
        for path in sorted(snapshot.workdir.rglob("*")):
            if path.is_dir() or path.name == ".git":
                continue
            relative = path.relative_to(snapshot.workdir).as_posix()
            if relative.startswith(".git/"):
                continue
            files.append((relative, path))
        return files


def _sqlite_integrity_ok(path: Path) -> bool:
    """Read-only PRAGMA integrity check (never migrates or writes)."""

    import sqlite3

    connection = None
    try:
        connection = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and str(row[0]).lower() == "ok"
    except Exception:
        return False
    finally:
        if connection is not None:
            connection.close()
