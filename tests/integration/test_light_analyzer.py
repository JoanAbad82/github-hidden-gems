"""Task 6: bounded light analysis, hash stability, and evidence."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

from hidden_gems.light_analysis.analyzer import LightAnalyzer
from hidden_gems.models import DiscoveryCandidate, RepositoryRef

AS_OF = datetime(2026, 9, 15, 6, 17, tzinfo=timezone.utc)

README = """# flowkit

Self-hosted workflow automation with a plugin runtime for data pipelines.

## Install

    pip install flowkit

## Usage

Run `flowkit run workflow.yml`.
"""

MANIFEST = "[project]\nname = 'flowkit'\ndependencies = ['httpx', 'pandas']\n"


def candidate(repo_id: int = 501) -> DiscoveryCandidate:
    return DiscoveryCandidate(
        repo=RepositoryRef.from_full_name("acme-labs/flowkit", repo_id),
        description="Workflow automation toolkit",
        stars=41,
        created_at=AS_OF - timedelta(days=10),
        updated_at=AS_OF - timedelta(days=1),
        primary_language="Python",
        topics=("automation", "workflow"),
        discovery_channels={"TOPIC_SEARCH"},
        matched_query_ids={"Q1"},
        default_branch="main",
        license_spdx_id="MIT",
        size_kb=400,
    )


class FakeClient:
    def __init__(self, *, tree=None, readme=README, releases=None, commits=None) -> None:
        self._tree = tree if tree is not None else default_tree()
        self._readme = readme
        self._releases = releases if releases is not None else default_releases()
        self._commits = commits if commits is not None else default_commits()
        self.requests: list[str] = []

    def get_readme(self, full_name: str) -> str | None:
        self.requests.append("readme")
        return self._readme

    def get_tree(self, full_name: str, ref: str):
        self.requests.append("tree")
        return list(self._tree)

    def get_releases(self, full_name: str, limit: int = 10):
        self.requests.append("releases")
        return list(self._releases)

    def get_recent_commits(self, full_name: str, since=None, limit: int = 20):
        self.requests.append("commits")
        return list(self._commits)

    def get_json(self, path: str, params=None):
        self.requests.append(path)
        name = path.split("/contents/", 1)[-1]
        if name != "pyproject.toml":
            raise KeyError(name)
        return {
            "encoding": "base64",
            "content": base64.b64encode(MANIFEST.encode("utf-8")).decode("ascii"),
            "size": len(MANIFEST),
        }


def default_tree() -> list[dict]:
    files = {
        "README.md": README,
        "LICENSE": "MIT",
        "pyproject.toml": MANIFEST,
        ".github/workflows/ci.yml": "name: ci\n",
        "src/flowkit/__init__.py": "",
        "src/flowkit/runtime.py": "RUNTIME = 1\n",
        "tests/test_runtime.py": "def test_ok():\n    assert True\n",
    }
    return [{"path": path, "type": "blob", "size": len(text)} for path, text in files.items()]


def default_releases() -> list[dict]:
    return [{"id": 77, "tag_name": "v0.4.0", "published_at": "2026-09-12T00:00:00Z"}]


def default_commits() -> list[dict]:
    return [
        {
            "sha": "abc",
            "commit": {
                "message": "feat: add plugin runtime",
                "author": {"date": "2026-09-14T00:00:00Z"},
            },
        },
        {
            "sha": "def",
            "commit": {
                "message": "fix: handle pipeline errors",
                "author": {"date": "2026-09-10T00:00:00Z"},
            },
        },
    ]


def test_analyzer_produces_complete_light_analysis(app_config):
    analysis = LightAnalyzer(app_config, FakeClient()).analyze(candidate(), as_of=AS_OF)

    assert analysis.detected_areas == frozenset({"automation", "data"})
    assert analysis.activity_level == "STRONG"
    assert analysis.latest_release_tag == "v0.4.0"
    assert analysis.latest_relevant_activity_at is not None
    assert analysis.evidence["manifest_names"] == ["pyproject.toml"]
    assert analysis.evidence["latest_release_id"] == 77
    assert set(analysis.quality_signals) & {"tests:suite", "hygiene:license", "hygiene:ci"}
    assert analysis.readme_hash and analysis.tree_hash and analysis.dependency_hash
    assert len(analysis.relevant_content_hash) == 64


def test_hashes_are_order_insensitive(app_config):
    first = LightAnalyzer(app_config, FakeClient()).analyze(candidate(), as_of=AS_OF)
    shuffled = list(reversed(default_tree()))
    second = LightAnalyzer(app_config, FakeClient(tree=shuffled)).analyze(candidate(), as_of=AS_OF)

    assert first.tree_hash == second.tree_hash
    assert first.relevant_content_hash == second.relevant_content_hash


def test_substantive_change_changes_the_relevant_content_hash(app_config):
    first = LightAnalyzer(app_config, FakeClient()).analyze(candidate(), as_of=AS_OF)
    changed_tree = default_tree() + [{"path": "src/flowkit/new_module.py", "type": "blob", "size": 20}]
    second = LightAnalyzer(app_config, FakeClient(tree=changed_tree)).analyze(candidate(), as_of=AS_OF)

    assert first.tree_hash != second.tree_hash
    assert first.relevant_content_hash != second.relevant_content_hash


def test_analyzer_stays_within_the_configured_tree_budget(app_config):
    tree = [
        {"path": f"src/module{index}.py", "type": "blob", "size": 10}
        for index in range(app_config.light.max_tree_items + 50)
    ]
    analysis = LightAnalyzer(app_config, FakeClient(tree=tree)).analyze(candidate(), as_of=AS_OF)

    assert analysis.evidence["file_count"] <= app_config.light.max_tree_items


def test_missing_repository_reads_degrade_gracefully(app_config):
    class Broken(FakeClient):
        def get_readme(self, full_name):
            raise RuntimeError("404")

        def get_tree(self, full_name, ref):
            raise RuntimeError("timeout")

        def get_releases(self, full_name, limit=10):
            raise RuntimeError("500")

        def get_recent_commits(self, full_name, since=None, limit=20):
            raise RuntimeError("500")

    analysis = LightAnalyzer(app_config, Broken()).analyze(candidate(), as_of=AS_OF)

    assert analysis.activity_level == "UNKNOWN"
    assert analysis.detected_areas == frozenset({"automation"})
    assert analysis.evidence["readme_present"] is False


def test_analyzer_never_executes_or_clones(app_config):
    client = FakeClient()

    analysis = LightAnalyzer(app_config, client).analyze(candidate(), as_of=AS_OF)

    assert analysis.evidence["file_count"] == len(default_tree())
    assert set(client.requests) <= {
        "readme", "tree", "releases", "commits", "/repos/acme-labs/flowkit/contents/pyproject.toml"
    }
