"""Shared fakes for the Task 13 pipeline integration tests.

Kept in a non-test module so both pipeline test files can import it without
requiring `tests` to be an importable package.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone

NOW = datetime(2026, 9, 15, 6, 17, tzinfo=timezone.utc)

README = """# flowkit

Self-hosted workflow automation with a small plugin runtime.

## Install

    pip install flowkit

## Usage

Run `flowkit run workflow.yml` to execute a workflow.

## Tests

    pytest
"""

MANIFEST = "[project]\nname = 'flowkit'\nversion = '0.4.0'\ndependencies = []\n"
SOURCE = "def main():\n    return 'flowkit'\n"
TEST = "def test_main():\n    assert True\n"


def payload(
    repo_id: int,
    owner: str,
    name: str,
    *,
    stars: int = 11,
    description: str = "Workflow automation toolkit",
) -> dict:
    return {
        "id": repo_id,
        "name": name,
        "full_name": f"{owner}/{name}",
        "owner": {"login": owner},
        "html_url": f"https://github.com/{owner}/{name}",
        "description": description,
        "stargazers_count": stars,
        "created_at": "2026-09-05T00:00:00Z",
        "updated_at": "2026-09-14T00:00:00Z",
        "pushed_at": "2026-09-14T00:00:00Z",
        "language": "Python",
        "topics": ["automation", "workflow"],
        "fork": False,
        "archived": False,
        "is_template": False,
        "size": 240,
        "default_branch": "main",
        "license": {"spdx_id": "MIT"},
        "open_issues_count": 1,
    }


class FakeBudget:
    def __init__(self, zone: str = "GREEN") -> None:
        self.zone = zone
        self.remaining = 5000

    def snapshot(self) -> dict:
        return {"zone": self.zone, "remaining": self.remaining}


class FakeGitHub:
    """Serves deterministic search, README, tree, release and contents data."""

    def __init__(self, repos: list[dict], *, zone: str = "GREEN") -> None:
        self.repos = repos
        self.rate_budget = FakeBudget(zone)
        self.posts: list[tuple] = []
        self.searches: list[str] = []
        self.owner_scans: list[str] = []

    def search_repositories(self, query: str, page: int = 1) -> dict:
        self.searches.append(query)
        return {"total_count": len(self.repos), "items": [dict(repo) for repo in self.repos]}

    def get_readme(self, full_name: str) -> str:
        return README

    def get_tree(self, full_name: str, ref: str) -> list[dict]:
        files = {
            "README.md": README,
            "pyproject.toml": MANIFEST,
            "src/main.py": SOURCE,
            "tests/test_main.py": TEST,
        }
        return [{"path": path, "type": "blob", "size": len(text)} for path, text in files.items()]

    def get_releases(self, full_name: str, limit: int = 10) -> list[dict]:
        return [
            {
                "id": 9001,
                "tag_name": "v0.4.0",
                "published_at": "2026-09-12T00:00:00Z",
                "name": "v0.4.0",
            }
        ]

    def get_recent_commits(self, full_name: str, since=None, limit: int = 20) -> list[dict]:
        return [
            {
                "sha": "abc123",
                "commit": {
                    "message": "feat: add plugin runtime",
                    "author": {"date": "2026-09-14T00:00:00Z"},
                },
            }
        ]

    def get_repo_metadata(self, full_name: str) -> dict:
        for repo in self.repos:
            if repo["full_name"] == full_name:
                return dict(repo)
        raise KeyError(full_name)

    def get_json(self, path: str, params=None):
        if "/contents/" in path:
            name = path.split("/contents/", 1)[-1]
            files = {
                "README.md": README,
                "pyproject.toml": MANIFEST,
                "src/main.py": SOURCE,
                "tests/test_main.py": TEST,
            }
            if name not in files:
                raise KeyError(name)
            body = files[name]
            return {
                "encoding": "base64",
                "content": base64.b64encode(body.encode("utf-8")).decode("ascii"),
                "size": len(body),
            }
        if path.startswith("/users/"):
            self.owner_scans.append(path)
            return []
        raise KeyError(path)

    def post_json(self, path: str, payload: dict):
        self.posts.append((path, payload))
        raise AssertionError("dry run must never publish an Issue")

    def close(self) -> None:
        return None


class CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def analyze_repository(self, evidence):
        from hidden_gems.models import DeepAnalysis, RepositoryRef

        self.calls += 1
        repo = RepositoryRef(
            github_repo_id=int(evidence["github_repo_id"]),
            owner=str(evidence["repo"]).split("/")[0],
            name=str(evidence["repo"]).split("/")[1],
            full_name=str(evidence["repo"]),
            html_url=f"https://github.com/{evidence['repo']}",
        )
        return DeepAnalysis(
            repo=repo,
            evidence={"observed": ["src/main.py"]},
            relevance_suggestion=14,
            originality_suggestion=3,
            why_interesting="Compact automation runtime with real tests.",
            summary="A small workflow automation runtime.",
            risks=(),
            confidence="MEDIUM",
            status="OK",
        )


def run_context(run_id: str = "RUN-TEST-1", *, dry_run: bool = True):
    from hidden_gems.models import RunContext

    return RunContext(
        run_id=run_id,
        started_at=NOW,
        dry_run=dry_run,
        config_version="1.0.0",
        score_version="HIDDEN_GEM_SCORE_V1",
        prompt_version="DEEP_ANALYZER_PROMPT_V1",
    )
