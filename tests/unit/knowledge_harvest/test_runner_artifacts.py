from __future__ import annotations

import json

from hidden_gems.knowledge_harvest.artifacts import write_harvest_artifacts
from hidden_gems.knowledge_harvest.runner import repositories_from_candidates


def test_repositories_from_candidates_uses_report_rank(tmp_path):
    path = tmp_path / "candidates.json"
    path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "selected_for_report": True,
                        "report_rank": 2,
                        "repository": {"full_name": "acme/two"},
                    },
                    {
                        "selected_for_report": False,
                        "report_rank": None,
                        "repository": {"full_name": "acme/no"},
                    },
                    {
                        "selected_for_report": True,
                        "report_rank": 1,
                        "repository": {"full_name": "acme/one"},
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    assert repositories_from_candidates(path, top=2) == ["acme/one", "acme/two"]


def _packet(repo: str, action: str = "EXPERIMENT"):
    return {
        "schema_version": "KNOWLEDGE_PACKET_V1",
        "prompt_version": "KNOWLEDGE_HARVEST_PROMPT_V1",
        "model": "deepseek-chat",
        "source": {
            "github_repo_id": 1,
            "full_name": repo,
            "html_url": f"https://github.com/{repo}",
            "head_sha": "a" * 40,
            "default_branch": "main",
            "license_spdx_id": "MIT",
            "evidence_digest": "b" * 64,
            "evidence_manifest": [],
        },
        "reuse_policy": "ADAPT_CONCEPT",
        "capabilities": [],
        "patterns": [],
        "lessons": [],
        "opportunities": [
            {
                "target_project_id": "GITHUB_PARA_IA",
                "action": action,
                "title": "Queue discipline",
                "rationale": "A bounded queue avoids duplicate sends.",
                "expected_benefit": "Fewer race conditions.",
                "integration_cost": "LOW",
                "risk": "LOW",
                "evidence_refs": ["E01"],
            }
        ],
        "limitations": [],
    }


def test_artifacts_are_stably_sorted(tmp_path):
    first = write_harvest_artifacts(
        tmp_path,
        run_id="KH-1",
        repositories=["z/two", "a/one"],
        packets=[_packet("z/two"), _packet("a/one", "APPLY")],
        errors=(),
        usage={"calls_made": 2},
    )
    bytes_a = tuple(path.read_bytes() for path in first)
    second = write_harvest_artifacts(
        tmp_path,
        run_id="KH-1",
        repositories=["a/one", "z/two"],
        packets=[_packet("a/one", "APPLY"), _packet("z/two")],
        errors=(),
        usage={"calls_made": 2},
    )
    bytes_b = tuple(path.read_bytes() for path in second)
    assert bytes_a == bytes_b
    payload = json.loads(first[0].read_text(encoding="utf-8"))
    assert [p["source"]["full_name"] for p in payload["packets"]] == ["a/one", "z/two"]
