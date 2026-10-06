from __future__ import annotations

import base64
import hashlib

from hidden_gems.knowledge_harvest.collector import (
    MAX_FILES,
    collect_repository_evidence,
    select_evidence_files,
)


class FakeGitHub:
    def get_repo_metadata(self, full_name):
        return {
            "id": 4242,
            "full_name": full_name,
            "html_url": f"https://github.com/{full_name}",
            "default_branch": "main",
            "license": {"spdx_id": "MIT"},
        }

    def get_recent_commits(self, full_name, limit=1):
        return [{"sha": "a" * 40}]

    def get_tree(self, full_name, ref):
        assert ref == "a" * 40
        return [
            {"path": "README.md", "type": "blob", "size": 20, "sha": "1" * 40},
            {"path": "docs/architecture.md", "type": "blob", "size": 30, "sha": "2" * 40},
            {"path": "src/session-state.ts", "type": "blob", "size": 40, "sha": "3" * 40},
            {"path": "tests/session-state.test.ts", "type": "blob", "size": 50, "sha": "4" * 40},
            {"path": "image.png", "type": "blob", "size": 50, "sha": "5" * 40},
        ]

    def get_json(self, path, params=None):
        name = path.split("/contents/", 1)[1]
        body = {
            "README.md": "# Demo\nAgent system.",
            "docs/architecture.md": "# Architecture\nState has one owner.",
            "src/session-state.ts": "export const state = 'idle';",
            "tests/session-state.test.ts": "test('state', () => true);",
        }[name]
        return {
            "encoding": "base64",
            "content": base64.b64encode(body.encode()).decode(),
        }


def test_selector_is_deterministic_and_excludes_binary():
    tree = FakeGitHub().get_tree("acme/demo", "a" * 40)
    first = select_evidence_files(tree)
    second = select_evidence_files(list(reversed(tree)))
    assert first == second
    assert len(first) <= MAX_FILES
    assert first[0]["path"] == "README.md"
    assert all(item["path"] != "image.png" for item in first)


def test_collector_pins_commit_and_emits_content_hashes():
    bundle = collect_repository_evidence(FakeGitHub(), "acme/demo")
    source = bundle["source"]
    assert source["head_sha"] == "a" * 40
    assert source["license_spdx_id"] == "MIT"
    assert source["evidence_manifest"][0]["id"] == "E01"
    assert source["evidence_manifest"][0]["path"] == "README.md"
    expected = hashlib.sha256("# Demo\nAgent system.".encode()).hexdigest()
    assert source["evidence_manifest"][0]["content_sha256"] == expected
    assert source["evidence_digest"]
    assert bundle["documents"][0]["untrusted_text"].startswith("<<UNTRUSTED_REPOSITORY_CONTENT>>")
