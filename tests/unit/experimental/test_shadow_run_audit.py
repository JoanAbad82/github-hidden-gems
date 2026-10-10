"""Isolation and contract tests for experimental post-run shadow reviewer."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from hidden_gems.experimental import shadow_run_audit as shadow
from hidden_gems.experimental.replay_integrity import ReplayIntegrityError
from tests.unit.experimental.test_replay_integrity import _payload, _write_pair


RUN = {
    "id": 38052574236, "run_attempt": 1, "name": "daily-discovery",
    "event": "schedule", "status": "completed", "conclusion": "success",
    "head_sha": "a" * 40, "head_branch": "main",
    "created_at": "2026-10-10T12:36:24Z",
}
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "run_candidates_v1.json"


def test_github_cli_rejects_write_commands_and_untrusted_endpoints(monkeypatch):
    with pytest.raises(RuntimeError, match="non_readonly"):
        shadow._gh("pr", "merge", "34")
    with pytest.raises(RuntimeError, match="outside_readonly_allowlist"):
        shadow._json_api("repos/someone/else/actions/runs")
    invoked = []
    def fake_run(*args, **kwargs):
        invoked.append(args)
        return subprocess.CompletedProcess([], 0, '{"workflow_runs":[]}', '')
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shadow.shutil, "which", lambda cmd: "gh")
    assert shadow._json_api(
        f"repos/{shadow.REPOSITORY}/actions/workflows/{shadow.WORKFLOW}/runs?per_page=10"
    ) == {"workflow_runs": []}
    assert invoked[0][0][:4] == ["gh", "api", "--method", "GET"]


def test_discovery_run_filter(monkeypatch):
    skip = {"id": 1, "run_attempt": 1, "status":"in_progress", "name":"daily-discovery", "event":"schedule"}
    other = {**RUN, "id": 5, "name":"some-other-workflow"}
    monkeypatch.setattr(shadow, "_json_api", lambda _: {"workflow_runs":[RUN,skip,other]})
    assert shadow._discovery_runs(10, None) == [RUN]


def test_download_path_validation_rejects_hidden_extras(tmp_path):
    folder = tmp_path / "RUN-20261010T123637Z"
    folder.mkdir()
    (folder / "candidates.json").write_text("{}")
    (folder / "candidates.csv").write_text("header\n")
    assert shadow._validated_files(tmp_path)[0].name == "candidates.json"
    (folder / "inject.sh").write_text("echo do-not-execute")
    with pytest.raises(ValueError, match="unexpected_artifact_files"):
        shadow._validated_files(tmp_path)


def test_download_rejects_mismatched_or_many_pairs(tmp_path):
    folder = tmp_path / "RUN-20261010T123637Z"
    folder.mkdir()
    (folder / "candidates.json").write_text("{}")
    (tmp_path / "candidates.csv").write_text("header\n")
    with pytest.raises(ValueError, match="mismatched_parent"):
        shadow._validated_files(tmp_path)
    (folder / "candidates.csv").write_text("header\n")
    with pytest.raises(ValueError, match="exactly_one"):
        shadow._validated_files(tmp_path)


@pytest.mark.parametrize("bad", [
    {"schema":"INVALID","runs":{}},
    {"schema":"HIDDEN_GEMS_EXTERNAL_SHA256_V1","runs":{"BAD":{"json_sha256":"x","csv_sha256":"y"}}},
    {"schema":"HIDDEN_GEMS_EXTERNAL_SHA256_V1","runs":{"RUN-20261010T123637Z":{"json_sha256":"a"*64}}},
])
def test_external_trust_manifest_rejects_invalid_values(tmp_path,bad):
    p=tmp_path/"trust.json"
    p.write_text(json.dumps(bad))
    with pytest.raises(RuntimeError):
        shadow._trusted_records(p)


def _fixture_download(_run, target: Path):
    p = target / "RUN-20261010T123637Z"
    p.mkdir()
    payload = _payload()
    payload["run"]["run_id"] = "RUN-20261010T123637Z"
    j, c, jb, cb = _write_pair(p, payload)
    return j, c, 123


def test_shadow_reports_consistency_and_does_not_rewrite_results(monkeypatch,tmp_path):
    out=tmp_path/"reports"
    monkeypatch.setattr(shadow,"_discovery_runs",lambda *_:[RUN])
    monkeypatch.setattr(shadow,"_read_artifact",_fixture_download)
    got=shadow.audit_once(destination=out,schema_path=SCHEMA_PATH,
                           trusted_index=None,max_runs=5,pinned_run=None)
    assert got=={"checked":1,"pass":1,"failed":0,"skipped":0}
    records=list((out/"run_reports").glob("*.json"))
    assert len(records)==1
    first_bytes=records[0].read_bytes()
    rec=json.loads(first_bytes)
    assert rec["result"]=="PASS_CONSISTENCY_ONLY"
    assert rec["checks"]["matched_expected_digests"] is False
    assert rec["integrity_provenance_verified"] is False
    assert rec["candidate_count"]==0
    assert rec["does_not_gate_publication"] is True
    rerun=shadow.audit_once(destination=out,schema_path=SCHEMA_PATH,
                           trusted_index=None,max_runs=5,pinned_run=None)
    assert rerun["skipped"]==1 and rerun["checked"]==0
    assert records[0].read_bytes()==first_bytes


def test_shadow_uses_external_digest_pair_but_never_claims_provenance(monkeypatch,tmp_path):
    payload = _payload()
    payload["run"]["run_id"] = "RUN-20261010T123637Z"
    j,c,jb,cb=_write_pair(tmp_path,payload)
    manifest=tmp_path/"external_trust.json"
    manifest.write_text(json.dumps({
        "schema":"HIDDEN_GEMS_EXTERNAL_SHA256_V1",
        "runs":{"RUN-20261010T123637Z":{
            "json_sha256":hashlib.sha256(jb).hexdigest(),
            "csv_sha256":hashlib.sha256(cb).hexdigest()
        }}
    }))
    monkeypatch.setattr(shadow,"_discovery_runs",lambda *_:[RUN])
    monkeypatch.setattr(shadow,"_read_artifact",_fixture_download)
    result=shadow.audit_once(destination=tmp_path/"output",schema_path=SCHEMA_PATH,
                             trusted_index=manifest,max_runs=5,pinned_run=38052574236)
    assert result["pass"]==1
    rec=json.loads(next((tmp_path/"output"/"run_reports").glob("*.json")).read_text())
    assert rec["checks"]["matched_expected_digests"] is True
    assert rec["integrity_provenance_verified"] is False


def test_shadow_failure_isolated_from_upstream_and_does_not_run_tools(monkeypatch,tmp_path):
    monkeypatch.setattr(shadow,"_discovery_runs",lambda *_:[RUN])
    monkeypatch.setattr(shadow,"_read_artifact",lambda *_: (_ for _ in ()).throw(ReplayIntegrityError("bad")))
    got=shadow.audit_once(destination=tmp_path/"out",schema_path=SCHEMA_PATH,
                           trusted_index=None,max_runs=2,pinned_run=None)
    assert got["failed"]==1
    rec=json.loads(next((tmp_path/"out"/"run_reports").glob("*.json")).read_text())
    assert rec["result"]=="FAIL" and rec["error"]=="artifact_inconsistent"
    assert rec["does_not_gate_publication"] is True


def _zip_payload(contents: dict[str, bytes], *, symlink: bool = False) -> bytes:
    import io
    import zipfile
    import stat
    stream=io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, value in contents.items():
            info=zipfile.ZipInfo(name)
            info.compress_type=zipfile.ZIP_DEFLATED
            if symlink:
                info.create_system=3
                info.external_attr=(stat.S_IFLNK | 0o777) << 16
            z.writestr(info,value)
    return stream.getvalue()


def test_safe_zip_inspected_before_extraction(monkeypatch,tmp_path):
    from pathlib import Path
    names={
        "RUN-20261010T123637Z/candidates.json":b"{}",
        "RUN-20261010T123637Z/candidates.csv":b"x\n",
    }
    shadow._extract_validated_zip(_zip_payload(names),tmp_path)
    assert sorted(f.name for f in (tmp_path/"RUN-20261010T123637Z").iterdir()) == [
        "candidates.csv","candidates.json"
    ]


@pytest.mark.parametrize("bad_entries",[
    {"../evil.json":b"x","RUN-20261010T123637Z/candidates.csv":b"y"},
    {"RUN-20261010T123637Z/candidates.json":b"x",
     "RUN-20261011T123637Z/candidates.csv":b"x"},
    {"RUN-20261010T123637Z/candidates.json":b"x",
     "RUN-20261010T123637Z/extra.sh":b"exit 0"},
])
def test_rejects_malicious_zip_paths_before_writing(tmp_path,bad_entries):
    with pytest.raises(ValueError):
        shadow._extract_validated_zip(_zip_payload(bad_entries),tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_rejects_symlink_zip_entries(tmp_path):
    entries={
        "RUN-20261010T123637Z/candidates.json":b"x",
        "RUN-20261010T123637Z/candidates.csv":b"y"
    }
    with pytest.raises(ValueError,match="nonregular"):
        shadow._extract_validated_zip(_zip_payload(entries,symlink=True),tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_zip_download_is_get_only_and_size_limited(monkeypatch):
    import subprocess
    seen=[]
    def download(args,**kwargs):
        seen.append(args)
        return subprocess.CompletedProcess(args,0,b"PK"+b"x"*20,b"")
    monkeypatch.setattr(shadow.subprocess,"run",download)
    assert shadow._artifact_archive_bytes(111)==b"PK"+b"x"*20
    assert seen[0][0:4]==["gh","api","--method","GET"]
    assert seen[0][4].endswith("/actions/artifacts/111/zip")
    with pytest.raises(ValueError):
        shadow._artifact_archive_bytes(0)
    monkeypatch.setattr(shadow,"MAX_ARTIFACT_ZIP_BYTES",5)
    with pytest.raises(ValueError,match="exceeds_bound"):
        shadow._artifact_archive_bytes(111)


def test_metadata_artifact_size_guard_before_download(monkeypatch,tmp_path):
    monkeypatch.setattr(shadow,"_json_api",lambda _: {"artifacts":[{
        "name":"hidden-gems-run-38052574236-1","id":111,
        "expired":False,"size_in_bytes":shadow.MAX_ARTIFACT_ZIP_BYTES+1
    }]})
    monkeypatch.setattr(shadow,"_artifact_archive_bytes",lambda *_: (_ for _ in ()).throw(
        AssertionError("should not download oversized artifacts")))
    with pytest.raises(ValueError,match="zip_size"):
        shadow._read_artifact(RUN,tmp_path)

def test_legacy_pre_v1_runs_are_excluded_before_downloading(monkeypatch):
    older = {**RUN, "id": 12, "created_at": "2026-10-06T13:20:00Z"}
    monkeypatch.setattr(shadow, "_json_api", lambda _: {"workflow_runs": [older, RUN]})
    assert shadow._discovery_runs(10, None) == [RUN]
