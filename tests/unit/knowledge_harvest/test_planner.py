from __future__ import annotations

import json

import pytest

from hidden_gems.cli import main
from hidden_gems.knowledge_harvest.planner import (
    build_transfer_plan,
    plan_from_artifact,
    write_transfer_plan,
)


def _harvest():
    source = {
        "github_repo_id": 1,
        "full_name": "acme/source",
        "html_url": "https://github.com/acme/source",
        "head_sha": "a" * 40,
        "default_branch": "main",
        "license_spdx_id": "MIT",
        "evidence_digest": "b" * 64,
        "evidence_manifest": [
            {
                "id": "E01",
                "path": "src/guard.py",
                "blob_sha": "c" * 40,
                "category": "source",
                "kind": "SOURCE",
                "size": 100,
                "content_sha256": "d" * 64,
            },
            {
                "id": "E02",
                "path": "tests/test_guard.py",
                "blob_sha": "e" * 40,
                "category": "test",
                "kind": "TEST",
                "size": 100,
                "content_sha256": "f" * 64,
            },
            {
                "id": "E03",
                "path": "README.md",
                "blob_sha": "1" * 40,
                "category": "readme",
                "kind": "DOCUMENTATION",
                "size": 100,
                "content_sha256": "2" * 64,
            },
        ],
    }
    return {
        "schema_version": "KNOWLEDGE_HARVEST_RUN_V1",
        "run_id": "KH-TEST",
        "repositories_requested": ["acme/source"],
        "packet_count": 1,
        "opportunity_count": 3,
        "errors": [],
        "usage": {},
        "packets": [
            {
                "schema_version": "KNOWLEDGE_PACKET_V1R2",
                "prompt_version": "KNOWLEDGE_HARVEST_PROMPT_V1R3",
                "model": "deepseek-chat",
                "source": source,
                "reuse_policy": "ADAPT_CONCEPT",
                "capabilities": [],
                "patterns": [],
                "lessons": [],
                "limitations": [],
                "opportunities": [
                    {
                        "target_project_id": "project-a",
                        "action": "WATCH",
                        "title": "Watch documented mechanism",
                        "rationale": "Documented only.",
                        "expected_benefit": "Future signal.",
                        "integration_cost": "LOW",
                        "risk": "LOW",
                        "confidence": "LOW",
                        "evidence_status": "DOCUMENTED_ONLY",
                        "evidence_refs": ["E03"],
                    },
                    {
                        "target_project_id": "project-a",
                        "action": "APPLY",
                        "title": "Transfer tested guard",
                        "rationale": "Source and tests support the mechanism.",
                        "expected_benefit": "Safer local actions.",
                        "integration_cost": "LOW",
                        "risk": "LOW",
                        "confidence": "HIGH",
                        "evidence_status": "IMPLEMENTED_TESTED",
                        "evidence_refs": ["E02", "E01"],
                    },
                    {
                        "target_project_id": "project-b",
                        "action": "EXPERIMENT",
                        "title": "Experiment with guard primitive",
                        "rationale": "Implementation exists but needs local validation.",
                        "expected_benefit": "Potentially safer execution.",
                        "integration_cost": "MEDIUM",
                        "risk": "MEDIUM",
                        "confidence": "MEDIUM",
                        "evidence_status": "IMPLEMENTED",
                        "evidence_refs": ["E01"],
                    },
                ],
            }
        ],
    }


def test_transfer_plan_is_deterministic_and_prioritized():
    first = build_transfer_plan(_harvest())
    second = build_transfer_plan(_harvest())

    assert first == second
    assert first["plan_id"] == second["plan_id"]
    assert first["opportunity_count"] == 3
    assert first["target_count"] == 2
    assert [item["action"] for item in first["opportunities"]] == [
        "APPLY",
        "EXPERIMENT",
        "WATCH",
    ]
    apply = first["opportunities"][0]
    assert apply["stage"] == "READY_TO_TRANSFER"
    assert apply["evidence_refs"] == ["E01", "E02"]
    assert [item["kind"] for item in apply["evidence"]] == ["SOURCE", "TEST"]
    assert apply["opportunity_id"].startswith("KOP-")


def test_transfer_plan_can_filter_targets():
    plan = build_transfer_plan(_harvest(), targets=["project-b"])
    assert plan["target_count"] == 1
    assert plan["opportunity_count"] == 1
    assert plan["targets"][0]["target_project_id"] == "project-b"
    assert plan["opportunities"][0]["action"] == "EXPERIMENT"


def test_transfer_plan_rejects_missing_evidence():
    harvest = _harvest()
    harvest["packets"][0]["opportunities"][0]["evidence_refs"] = ["E99"]
    with pytest.raises(ValueError, match="unknown evidence ref"):
        build_transfer_plan(harvest)


def test_write_and_plan_from_artifact_are_reproducible(tmp_path):
    source = tmp_path / "knowledge_packets.json"
    source.write_text(json.dumps(_harvest()), encoding="utf-8")

    first = plan_from_artifact(source, output_dir=tmp_path / "out")
    before = first["json_path"].read_bytes()
    second = plan_from_artifact(source, output_dir=tmp_path / "out")
    after = second["json_path"].read_bytes()

    assert before == after
    assert first["plan"] == second["plan"]
    assert first["csv_path"].exists()
    assert len(first["handoff_paths"]) == 2

    handoff = json.loads(first["handoff_paths"][0].read_text(encoding="utf-8"))
    assert handoff["schema_version"] == "KNOWLEDGE_TARGET_HANDOFF_V1"
    assert handoff["plan_id"] == first["plan"]["plan_id"]


def test_write_transfer_plan_uses_stable_target_names(tmp_path):
    plan = build_transfer_plan(_harvest())
    _, _, first = write_transfer_plan(tmp_path / "one", plan)
    _, _, second = write_transfer_plan(tmp_path / "two", plan)
    assert [path.name for path in first] == [path.name for path in second]


def test_cli_plan_knowledge(tmp_path, capsys):
    source = tmp_path / "knowledge_packets.json"
    source.write_text(json.dumps(_harvest()), encoding="utf-8")
    output = tmp_path / "planned"

    result = main(
        [
            "plan-knowledge",
            "--from-harvest",
            str(source),
            "--output",
            str(output),
            "--target",
            "project-a",
        ]
    )

    captured = capsys.readouterr().out
    assert result == 0
    assert "TRANSFER_OPPORTUNITIES=2" in captured
    assert "TRANSFER_TARGETS=1" in captured
    assert "RESULT=KNOWLEDGE_TRANSFER_PLAN_SUCCESS" in captured
