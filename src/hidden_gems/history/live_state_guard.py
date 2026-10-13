"""Fail-closed checks and restorable pre-run backups for live GitHub Actions.

Only acts on the checked-out state working tree; never writes to the GitHub API.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

from .state_branch import _read_state_manifest


class LiveStateError(RuntimeError):
    """An invalid or unrecoverable state must never be published."""


_BACKUP_PATTERN = re.compile(r"^history-prev-([0-9a-f]{64})-(RUN-[A-Za-z0-9TZ]+)\.sqlite3\.gz$")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _database_last_run(db_path: Path) -> tuple[str, str, bool]:
    # Read-only and immutable: verification cannot mutate production history.
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise LiveStateError("SQLite integrity_check failed")
        row = db.execute(
            "SELECT run_id, result, dry_run FROM runs "
            "ORDER BY started_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            raise LiveStateError("history has no completed runs")
        return str(row[0]), str(row[1]), bool(row[2])
    finally:
        db.close()


def _history_rows(db_path: Path, table: str, key: str) -> tuple[tuple[str, ...], dict]:
    """Read all historical rows without modifying either SQLite database."""
    if table not in {"runs", "notifications"}:
        raise LiveStateError("unsupported historical table")
    if key not in {"run_id", "notification_id"}:
        raise LiveStateError("unsupported historical key")
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro&immutable=1", uri=True)
    db.row_factory = sqlite3.Row
    try:
        cols = tuple(row[1] for row in db.execute(f"PRAGMA table_info({table})"))
        if key not in cols:
            raise LiveStateError(f"history table {table} or key {key} is missing")
        result = {}
        for row in db.execute(f"SELECT * FROM {table}"):
            item = dict(row)
            identity = item[key]
            if identity is None or identity in result:
                raise LiveStateError(f"invalid {table} identity")
            result[identity] = item
        return cols, result
    finally:
        db.close()


def _verify_history_continuity(previous_db: Path, proposed_db: Path, *, new_run_id: str) -> None:
    """Require append-only runs/notifications, apart from explicit report publication.

    A valid SQLite hash only authenticates its current bytes: without this check
    a perfectly consistent new DB may silently discard earlier history.
    """
    old_run_cols, old_runs = _history_rows(previous_db, "runs", "run_id")
    new_run_cols, new_runs = _history_rows(proposed_db, "runs", "run_id")
    old_note_cols, old_notes = _history_rows(previous_db, "notifications", "notification_id")
    new_note_cols, new_notes = _history_rows(proposed_db, "notifications", "notification_id")
    if not set(old_run_cols).issubset(new_run_cols):
        raise LiveStateError("runs schema lost historical columns")
    if not set(old_note_cols).issubset(new_note_cols):
        raise LiveStateError("notifications schema lost historical columns")
    missing_runs = set(old_runs) - set(new_runs)
    missing_notes = set(old_notes) - set(new_notes)
    if missing_runs or missing_notes:
        raise LiveStateError(
            f"history continuity violation: lost {len(missing_runs)} runs "
            f"and {len(missing_notes)} notifications"
        )
    new_ids = set(new_runs) - set(old_runs)
    if new_ids != {new_run_id}:
        raise LiveStateError("history continuity violation: expected exactly one new run")
    for run_id, old in old_runs.items():
        new = new_runs[run_id]
        # Historical publication can legitimately complete a PENDING_REPORT
        # after reconciliation. Do not allow a different result/usage/budgets.
        published = (
            old.get("report_state") == "PENDING_REPORT"
            and new.get("report_state") == "REPORT_PUBLISHED"
            and new.get("issue_number") is not None
            and bool(new.get("issue_url"))
        )
        allowed = {"report_state", "issue_number", "issue_url"} if published else set()
        if any(old[column] != new[column] for column in old_run_cols if column not in allowed):
            raise LiveStateError(f"history continuity violation: previous run modified: {run_id}")
    for note_id, old in old_notes.items():
        new = new_notes[note_id]
        if any(old[col] != new[col] for col in old_note_cols):
            raise LiveStateError(f"history continuity violation: prior notification modified: {note_id}")
    # New notifications may only refer to an existing run in the resulting DB.
    for note_id in set(new_notes) - set(old_notes):
        run_id = new_notes[note_id].get("run_id")
        if run_id not in new_runs:
            raise LiveStateError(f"new notification refers to missing run: {note_id}")


def restore_backup(archive: Path, destination: Path) -> str:
    """Restore into a NEW location and verify the digest embedded in the name."""
    match = _BACKUP_PATTERN.fullmatch(archive.name)
    if not match:
        raise LiveStateError(f"unrecognized backup filename: {archive.name}")
    if destination.exists():
        raise LiveStateError("backup destination already exists; refusing overwrite")
    try:
        with gzip.open(archive, "rb") as source, destination.open("xb") as sink:
            shutil.copyfileobj(source, sink)
        digest = _digest(destination)
        if digest != match.group(1):
            raise LiveStateError("backup hash mismatch")
        _database_last_run(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return digest


def verify_state(state_dir: Path, *, require_live: bool = False) -> dict:
    state_dir = Path(state_dir)
    db_path = state_dir / "history.sqlite3"
    manifest_path = state_dir / "state_manifest.json"
    if not db_path.is_file() or not manifest_path.is_file():
        raise LiveStateError("state checkout must include history.sqlite3 and manifest")
    manifest = _read_state_manifest(manifest_path)
    actual_hash = _digest(db_path)
    if manifest.get("db_sha256") != actual_hash:
        raise LiveStateError("state manifest database SHA-256 mismatch")
    if manifest.get("db_bytes") != db_path.stat().st_size:
        raise LiveStateError("state manifest database size mismatch")
    run_id, result, dry_run = _database_last_run(db_path)
    if manifest.get("last_run_id") != run_id or manifest.get("last_run_result") != result:
        raise LiveStateError("manifest last run does not match SQLite")
    if require_live and dry_run:
        raise LiveStateError("last run must be a live cycle")
    backups = manifest.get("backups", [])
    if not isinstance(backups, list):
        raise LiveStateError("invalid backups index")
    for filename in backups:
        if Path(filename).name != filename:
            raise LiveStateError("invalid backup path")
        archive = state_dir / "backups" / filename
        if not archive.is_file():
            raise LiveStateError(f"referenced backup missing: {filename}")
        with tempfile.TemporaryDirectory(prefix="hidden-gems-backup-verify-") as tempdir:
            restore_backup(archive, Path(tempdir) / "restored.sqlite3")
    return {"run_id": run_id, "result": result, "sha256": actual_hash,
            "bytes": db_path.stat().st_size, "backup_count": len(backups)}


def stage_live(app_db: Path, state_dir: Path, *, max_backups: int = 3) -> dict:
    """Preserve pre-run history and stage a new, verified state for the git push."""
    app_db = Path(app_db)
    state_dir = Path(state_dir)
    if not 1 <= max_backups <= 10:
        raise LiveStateError("invalid backup retention")
    original = verify_state(state_dir)
    app_manifest_dir = app_db.parent
    # Requires finished, non-dry-run history and a matching manifest.
    current = verify_state(app_manifest_dir, require_live=True)
    if original["run_id"] == current["run_id"]:
        raise LiveStateError("refusing to persist the same run twice")
    # Fail BEFORE modifying any checked-out state file or rotating backups.
    _verify_history_continuity(
        state_dir / "history.sqlite3", app_db, new_run_id=current["run_id"]
    )
    backup_dir = state_dir / "backups"
    backup_dir.mkdir(exist_ok=True)
    old_db = state_dir / "history.sqlite3"
    name = f"history-prev-{original['sha256']}-{current['run_id']}.sqlite3.gz"
    archive = backup_dir / name
    if archive.exists():
        raise LiveStateError("backup for this run already exists")
    staged = archive.with_suffix(archive.suffix + ".tmp")
    try:
        with old_db.open("rb") as source, gzip.open(staged, "wb") as sink:
            shutil.copyfileobj(source, sink)
        os.replace(staged, archive)
        with tempfile.TemporaryDirectory(prefix="hidden-gems-backup-roundtrip-") as tmp:
            restore_backup(archive, Path(tmp) / "test.sqlite3")
        # Overwrite only the workflow's isolated checkout of the state branch.
        shutil.copy2(app_db, old_db)
        new_manifest = json.loads((app_manifest_dir / "state_manifest.json").read_text(encoding="utf-8"))
        old_manifest = _read_state_manifest(state_dir / "state_manifest.json")
        prior = list(old_manifest.get("backups", []))
        all_backups = prior + [name]
        new_manifest["backups"] = all_backups[-max_backups:]
        (state_dir / "state_manifest.json").write_text(
            json.dumps(new_manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        checked = verify_state(state_dir, require_live=True)
        if checked["run_id"] != current["run_id"]:
            raise LiveStateError("staged run ID mismatch")
        # Rotate only after successful end-to-end verification.
        for stale in all_backups[:-max_backups]:
            (backup_dir / stale).unlink()
        return checked
    finally:
        staged.unlink(missing_ok=True)


def main() -> int:
    cli = argparse.ArgumentParser()
    cli.add_argument("operation", choices=["verify", "stage-live"])
    cli.add_argument("--state-dir", required=True, type=Path)
    cli.add_argument("--app-db", type=Path)
    args = cli.parse_args()
    try:
        if args.operation == "verify":
            result = verify_state(args.state_dir)
        else:
            if args.app_db is None:
                raise LiveStateError("stage-live requires --app-db")
            result = stage_live(args.app_db, args.state_dir)
    except (LiveStateError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"RESULT=FAILED_INTEGRITY reason={type(exc).__name__}: {exc}")
        return 3
    print("VERIFIED_STATE=" + json.dumps(result, sort_keys=True))
    print("RESULT=STATE_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
