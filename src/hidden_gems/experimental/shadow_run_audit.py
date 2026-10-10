"""Offline-safe shadow review of public Hidden Gems discovery artifacts.

Uses only GitHub CLI read endpoints and artifact download. All reports are
stored outside any Git repo. Never mutates GitHub or discovery state.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import stat
import tempfile
import zipfile
from datetime import datetime, timezone

from hidden_gems.experimental.replay_integrity import (
    ReplayIntegrityError, validate_run_pair
)

REPOSITORY = "JoanAbad82/github-hidden-gems"
WORKFLOW = "daily_discovery.yml"
RUN_ID_RE = re.compile(r"RUN-\d{8}T\d{6}Z\Z")
MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_ARTIFACT_ZIP_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_FILES = 24
SUMMARY_FIELDS = (
    "github_run_id", "github_run_attempt", "artifact_id", "result", "run_id",
    "candidates", "reported", "json_sha256", "csv_sha256",
    "matched_expected_digests", "external_anchor_used", "error"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _gh(*args: str, timeout: int = 80) -> str:
    if shutil.which("gh") is None:
        raise RuntimeError("gh_cli_not_found")
    # Whitelist exclusively read-only subcommands. No gh issue/pr/git actions.
    if not (args[:2] == ("api", "--method") and len(args) >= 4 and args[2] == "GET"):
        raise RuntimeError("non_readonly_github_command_denied")
    completed = subprocess.run(
        ["gh", *args], capture_output=True, text=True,
        check=False, timeout=timeout, encoding="utf-8", errors="replace"
    )
    if completed.returncode:
        raise RuntimeError("github_read_failed")
    if len(completed.stdout) > 4_000_000:
        raise RuntimeError("github_metadata_oversize")
    return completed.stdout


def _json_api(endpoint: str) -> dict:
    if not endpoint.startswith(f"repos/{REPOSITORY}/actions/"):
        raise RuntimeError("endpoint_outside_readonly_allowlist")
    value = json.loads(_gh("api", "--method", "GET", endpoint))
    if type(value) is not dict:
        raise ValueError("unexpected_github_response")
    return value


def _discovery_runs(limit: int, pinned_run: int | None) -> list[dict]:
    if pinned_run is not None:
        obj = _json_api(f"repos/{REPOSITORY}/actions/runs/{pinned_run}")
        runs = [obj]
    else:
        obj = _json_api(
            f"repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs?per_page={limit}"
        )
        runs = obj.get("workflow_runs", [])
        if type(runs) is not list:
            raise RuntimeError("invalid_workflow_runs")
    result = []
    for run in runs:
        if type(run) is not dict or run.get("status") != "completed":
            continue
        if run.get("name") != "daily-discovery":
            continue
        if run.get("event") not in ("schedule", "workflow_dispatch"):
            continue
        if type(run.get("id")) is not int or type(run.get("run_attempt")) is not int:
            continue
        result.append(run)
    return sorted(result, key=lambda r: r["id"])


def _trusted_records(path: Path | None) -> dict:
    if path is None:
        return {}
    # TRUST CONFIG MUST be supplied from a separately verified local source.
    obj = json.loads(path.read_text(encoding="utf-8"))
    if type(obj) is not dict or obj.get("schema") != "HIDDEN_GEMS_EXTERNAL_SHA256_V1":
        raise RuntimeError("invalid_external_trust_manifest")
    records = obj.get("runs")
    if type(records) is not dict:
        raise RuntimeError("invalid_trust_records")
    for key, value in records.items():
        if type(key) is not str or not RUN_ID_RE.fullmatch(key):
            raise RuntimeError("invalid_trusted_run_id")
        if type(value) is not dict or set(value) != {"json_sha256", "csv_sha256"}:
            raise RuntimeError("invalid_trusted_digest_pair")
        if any(
            type(value[f]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", value[f]) is None
            for f in ("json_sha256", "csv_sha256")
        ):
            raise RuntimeError("invalid_trusted_digest_format")
    return records


def _safe_error(exc: Exception) -> str:
    # Only expected classifier, no possibly sensitive exception text.
    if isinstance(exc, ReplayIntegrityError):
        label = "artifact_inconsistent"
    else:
        label = {
            "RuntimeError": "github_or_artifact_boundary_error",
            "TimeoutExpired": "github_download_timeout",
            "ValueError": "metadata_parse_error",
            "OSError": "local_io_error",
        }.get(type(exc).__name__, "unexpected_error")
    return label


def _validated_files(download_dir: Path) -> tuple[Path, Path]:
    files: list[Path] = []
    size = 0
    for folder, _, names in os.walk(download_dir, followlinks=False):
        for name in names:
            file = Path(folder) / name
            if file.is_symlink() or not file.is_file():
                raise ValueError("artifact_symlink_or_nonfile")
            if not file.resolve().is_relative_to(download_dir.resolve()):
                raise ValueError("path_escape")
            size += file.stat().st_size
            files.append(file)
            if len(files) > MAX_ARTIFACT_FILES or size > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("artifact_exceeds_resource_limits")
    found = {basename: [f for f in files if f.name == basename]
             for basename in ("candidates.json", "candidates.csv")}
    if any(len(paths) != 1 for paths in found.values()):
        raise ValueError("expected_exactly_one_artifact_pair")
    j, c = found["candidates.json"][0], found["candidates.csv"][0]
    if j.parent != c.parent:
        raise ValueError("artifact_pair_mismatched_parent")
    if len(files) != 2:
        raise ValueError("unexpected_artifact_files")
    if not RUN_ID_RE.fullmatch(j.parent.name):
        raise ValueError("invalid_artifact_run_directory")
    return j, c


def _artifact_archive_bytes(artifact_id: int) -> bytes:
    """Download a single allowed artifact as bytes, never run or auto-unpack."""
    if type(artifact_id) is not int or artifact_id < 1:
        raise ValueError("invalid_artifact_id")
    proc = subprocess.run(
        ["gh", "api", "--method", "GET",
         f"repos/{REPOSITORY}/actions/artifacts/{artifact_id}/zip"],
        capture_output=True, check=False, timeout=90,
    )
    if proc.returncode:
        raise RuntimeError("artifact_zip_download_failed")
    if len(proc.stdout) > MAX_ARTIFACT_ZIP_BYTES:
        raise ValueError("artifact_download_exceeds_bound")
    if not proc.stdout.startswith(b"PK"):
        raise ValueError("downloaded_content_not_zip")
    return proc.stdout


def _extract_validated_zip(content: bytes, destination: Path) -> None:
    """Inspect ZIP central directory before extracting exactly the expected pair."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        infos = archive.infolist()
        if len(infos) != 2:
            raise ValueError("invalid_archive_file_count")
        seen = set()
        total = 0
        for info in infos:
            parts = info.filename.split("/")
            if (len(parts) != 2 or not RUN_ID_RE.fullmatch(parts[0])
                    or parts[1] not in ("candidates.json", "candidates.csv")
                    or info.filename in seen or info.is_dir()):
                raise ValueError("malicious_archive_path_or_duplicate")
            seen.add(info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if mode not in (0, stat.S_IFREG):
                raise ValueError("archive_contains_nonregular_file")
            if info.file_size > 8 * 1024 * 1024 or info.file_size < 1:
                raise ValueError("archive_file_size_out_of_bounds")
            total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("archive_uncompressed_size_out_of_bounds")
        parents = {name.split("/")[0] for name in seen}
        if len(parents) != 1:
            raise ValueError("different_run_ids_in_archive")
        for info in infos:
            path = destination / info.filename
            path.parent.mkdir(exist_ok=True)
            # Bounded read + verified ZIP CRC; never invoke downloaded code.
            with archive.open(info, "r") as incoming:
                data = incoming.read(info.file_size + 1)
            if len(data) != info.file_size:
                raise ValueError("archive_entry_length_mismatch")
            with path.open("xb") as output:
                output.write(data)


def _read_artifact(run: dict, tmp: Path) -> tuple[Path, Path, int]:
    num = run["id"]
    data = _json_api(f"repos/{REPOSITORY}/actions/runs/{num}/artifacts?per_page=50")
    arts = data.get("artifacts", [])
    name = f"hidden-gems-run-{num}-{run['run_attempt']}"
    chosen = [a for a in arts if type(a) is dict and a.get("name") == name and not a.get("expired")]
    if len(chosen) != 1:
        raise ValueError("missing_or_ambiguous_artifact")
    meta = chosen[0]
    if type(meta.get("size_in_bytes")) is not int or not 0 < meta["size_in_bytes"] <= MAX_ARTIFACT_ZIP_BYTES:
        raise ValueError("artifact_zip_size_out_of_bounds")
    data = _artifact_archive_bytes(meta["id"])
    _extract_validated_zip(data, tmp)
    j, c = _validated_files(tmp)
    return j, c, meta["id"]

def _write_exclusive(path: Path, content: str) -> None:
    # Never overwrite evidence of a previous observation.
    with path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(content)


def audit_once(
    *, destination: Path, schema_path: Path,
    trusted_index: Path | None, max_runs: int, pinned_run: int | None,
) -> dict[str, int]:
    destination.mkdir(parents=True, exist_ok=True)
    trusted = _trusted_records(trusted_index)
    results_dir = destination / "run_reports"
    results_dir.mkdir(exist_ok=True)
    counts = {"checked": 0, "pass": 0, "failed": 0, "skipped": 0}
    for run in _discovery_runs(max_runs, pinned_run):
        run_num = run["id"]
        attempt = run["run_attempt"]
        result_path = results_dir / f"github-{run_num}-attempt-{attempt}.json"
        if result_path.exists():
            counts["skipped"] += 1
            continue
        record = {
            "schema": "HIDDEN_GEMS_SHADOW_REPORT_V1",
            "timestamp_utc": _now(),
            "source_repo": REPOSITORY,
            "workflow_run_id": run_num,
            "workflow_run_attempt": attempt,
            "source_workflow_conclusion": run.get("conclusion"),
            "source_workflow_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_num}",
            "source_head_sha": run.get("head_sha"),
            "shadow_is_read_only": True,
            "does_not_gate_publication": True,
            "result": "FAIL",
            "checks": {},
            "integrity_provenance_verified": False,
        }
        try:
            with tempfile.TemporaryDirectory(prefix="shadow-inbox-", dir=destination) as tmp:
                j, c, artifact_id = _read_artifact(run, Path(tmp))
                embedded_run_id = j.parent.name
                digests = trusted.get(embedded_run_id)
                audit = validate_run_pair(
                    j, c, schema_path,
                    digests["json_sha256"] if digests else None,
                    digests["csv_sha256"] if digests else None,
                )
                if audit.run_id != embedded_run_id:
                    raise ValueError("artifact_run_id_mismatch")
                record.update({
                    "result": "PASS_WITH_EXTERNAL_DIGEST_MATCH" if digests else "PASS_CONSISTENCY_ONLY",
                    "artifact_id": artifact_id,
                    "run_id": audit.run_id,
                    "candidate_count": audit.candidate_count,
                    "reported_count": audit.reported_count,
                    "json_sha256": audit.json_sha256,
                    "csv_sha256": audit.csv_sha256,
                    "checks": {
                        "schema_semantic_csv_consistency": True,
                        "external_digest_pair_supplied": bool(digests),
                        "matched_expected_digests": audit.matched_expected_digests,
                        "trusted_digest_origin_proven": False,
                    },
                })
                counts["pass"] += 1
        except (Exception) as e:
            # Deliberately separate failed audits from successful discovery.
            record["error"] = _safe_error(e)
            counts["failed"] += 1
        _write_exclusive(result_path, json.dumps(record, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
        counts["checked"] += 1
    # Derived local index, no GitHub writes, never reads/writes production state.
    all_records = []
    for report in sorted(results_dir.glob("github-*-attempt-*.json")):
        obj = json.loads(report.read_text(encoding="utf-8"))
        all_records.append(obj)
    latest = {
        "schema": "HIDDEN_GEMS_SHADOW_INDEX_V1",
        "updated_utc": _now(), "source_repo": REPOSITORY,
        "records": len(all_records), "results": counts,
        "integrity_provenance_verified": False,
    }
    index_tmp = destination / "SHADOW_LATEST.json.tmp"
    index_tmp.write_text(json.dumps(latest, sort_keys=True, indent=2)+"\n", encoding="utf-8")
    index_tmp.replace(destination / "SHADOW_LATEST.json")
    csv_tmp = destination / "SHADOW_SUMMARY.csv.tmp"
    with csv_tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS, lineterminator="\n")
        w.writeheader()
        for obj in all_records:
            checks = obj.get("checks", {})
            w.writerow({
                "github_run_id": obj["workflow_run_id"],
                "github_run_attempt": obj["workflow_run_attempt"],
                "artifact_id": obj.get("artifact_id", ""),
                "result": obj["result"],
                "run_id": obj.get("run_id", ""),
                "candidates": obj.get("candidate_count", ""),
                "reported": obj.get("reported_count", ""),
                "json_sha256": obj.get("json_sha256", ""),
                "csv_sha256": obj.get("csv_sha256", ""),
                "matched_expected_digests": checks.get("matched_expected_digests", False),
                "external_anchor_used": checks.get("external_digest_pair_supplied", False),
                "error": obj.get("error", ""),
            })
    csv_tmp.replace(destination / "SHADOW_SUMMARY.csv")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Hidden Gems post-run shadow validation")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--schema", type=Path, required=True)
    parser.add_argument("--trusted-index", type=Path)
    parser.add_argument("--max-runs", type=int, default=15)
    parser.add_argument("--run-id", type=int, help="GitHub workflow run ID for controlled replay")
    args = parser.parse_args()
    if not 1 <= args.max_runs <= 40 or args.run_id is not None and args.run_id < 1:
        parser.error("invalid run count or GitHub run ID")
    try:
        result = audit_once(
            destination=args.output, schema_path=args.schema,
            trusted_index=args.trusted_index,
            max_runs=args.max_runs, pinned_run=args.run_id,
        )
    except Exception as exc:
        print(json.dumps({"shadow":"ERROR", "reason":_safe_error(exc)}))
        return 2
    print(json.dumps({"shadow":"DONE", **result},sort_keys=True))
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
