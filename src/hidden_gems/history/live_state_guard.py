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
