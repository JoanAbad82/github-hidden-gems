"""Contract tests for repository-level GitHub Copilot custom agents."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / ".github" / "agents"
EVIDENCE_AUDITOR = AGENTS / "evidence-auditor.agent.md"


def load_agent(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} must start with YAML frontmatter"
    parts = text.split("---", 2)
    assert len(parts) == 3, f"{path.name} must contain a closing YAML frontmatter delimiter"
    profile = yaml.safe_load(parts[1])
    assert isinstance(profile, dict)
    body = parts[2].strip()
    assert body
    return profile, body


def test_all_agent_profiles_have_description_and_body():
    profiles = sorted(
        path
        for path in AGENTS.iterdir()
        if path.is_file() and path.suffix == ".md"
    )
    assert profiles, "at least one repository-level agent profile must exist"
    for path in profiles:
        profile, body = load_agent(path)
        assert isinstance(profile.get("description"), str)
        assert profile["description"].strip()
        assert body


def test_evidence_auditor_is_manual_user_invocable_and_read_only():
    profile, body = load_agent(EVIDENCE_AUDITOR)

    assert profile["name"] == "Evidence Auditor"
    assert profile["target"] == "github-copilot"
    assert profile["disable-model-invocation"] is True
    assert profile["user-invocable"] is True
    assert set(profile["tools"]) == {"read", "search", "github/*"}
    assert profile["metadata"]["safety"] == "read-only"

    forbidden_tools = {"edit", "execute", "shell", "powershell", "bash", "agent"}
    assert forbidden_tools.isdisjoint(set(profile["tools"]))

    for required in (
        "SUPPORTED",
        "PARTIALLY_SUPPORTED",
        "UNVERIFIED",
        "CONTRADICTED",
        "STALE_EVIDENCE",
        "model_classification",
        "Do not create or modify files",
        "Do not merge, push, dispatch workflows",
    ):
        assert required in body
