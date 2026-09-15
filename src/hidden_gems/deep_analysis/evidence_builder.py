"""Deterministic deep evidence bundle (before optional LLM enrichment)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..config import AppConfig
from ..models import LightAnalysis, RepositoryRef
from ..security.untrusted_content import contains_prompt_injection, wrap_untrusted
from .file_selector import SelectedFile

OBSERVED_KEYS = (
    "file_count",
    "source_file_count",
    "test_file_count",
    "doc_file_count",
    "manifest_names",
    "top_level_entries",
    "detected_areas",
    "activity_level",
    "readme_present",
    "categories",
)

INFERRED_KEYS = ("project_scale", "implementation_depth", "documentation_level", "packaging")

UNKNOWN_KEYS = (
    "runtime_behaviour",
    "test_results",
    "data_quality",
    "third_party_service_claims",
)

_CLAIM_PATTERNS: Mapping[str, tuple[str, ...]] = {
    "multi_agent": ("multi-agent", "multi agent", "agent swarm", "multiple agents"),
    "framework": ("framework", "platform", "infrastructure"),
    "production_ready": ("production-ready", "production ready", "battle tested", "enterprise"),
    "scale": ("scalable", "high performance", "at scale", "millions of"),
}

_HEAVY_CLAIM_KEYS = ("multi_agent", "framework", "production_ready", "scale")


def _observed(repo: RepositoryRef, light: LightAnalysis, files: Sequence[SelectedFile], config: AppConfig) -> dict[str, Any]:
    evidence = light.evidence or {}
    categories: dict[str, list[str]] = {}
    for item in files:
        categories.setdefault(item.category, []).append(item.path)
    tree_paths = tuple(str(path) for path in evidence.get("tree_paths") or ())
    manifest_names = tuple(
        sorted({item.path.rsplit("/", 1)[-1] for item in files if item.category == "manifest"})
    )
    return {
        "file_count": int(evidence.get("file_count") or len(tree_paths) or len(files)),
        "source_file_count": int(
            evidence.get("source_file_count") or len(categories.get("source", ()))
        ),
        "test_file_count": int(evidence.get("test_file_count") or len(categories.get("test", ()))),
        "doc_file_count": int(evidence.get("doc_file_count") or len(categories.get("docs", ()))),
        "manifest_names": manifest_names,
        "top_level_entries": sorted(
            {path.split("/")[0] for path in (*tree_paths, *(item.path for item in files))}
        ),
        "detected_areas": sorted(light.detected_areas),
        "activity_level": light.activity_level,
        "readme_present": bool(evidence.get("readme_present", light.readme_hash != "")),
        "quality_signals": list(light.quality_signals),
        "negative_signals": list(light.negative_signals),
        "categories": {key: sorted(value) for key, value in sorted(categories.items())},
        "selected_files": [
            {"path": item.path, "category": item.category, "reason": item.reason, "size": item.size}
            for item in files
        ],
        "max_files_budget": int(config.deep.max_files),
        "repository": {
            "full_name": repo.full_name,
            "github_repo_id": repo.github_repo_id,
            "html_url": repo.html_url,
        },
        "description": evidence.get("description"),
        "stars": evidence.get("stars"),
        "primary_language": evidence.get("primary_language"),
    }


def _claim_checks(readme_text: str | None, observed: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compare README claims with what the tree actually implements."""

    text = (readme_text or "").lower()
    checks: list[dict[str, Any]] = []
    source_files = int(observed.get("source_file_count") or 0)
    file_count = int(observed.get("file_count") or 0)
    for claim, patterns in _CLAIM_PATTERNS.items():
        if not any(pattern in text for pattern in patterns):
            continue
        supported = True
        if claim in _HEAVY_CLAIM_KEYS and source_files <= 1:
            supported = False
        if claim == "scale" and file_count <= 3:
            supported = False
        checks.append(
            {
                "claim": claim,
                "supported_by_implementation": supported,
                "basis": f"source_file_count={source_files}, file_count={file_count}",
            }
        )
    return checks


def build_evidence(
    *,
    repo: RepositoryRef,
    light: LightAnalysis,
    files: Sequence[tuple[SelectedFile, str]],
    config: AppConfig,
) -> dict[str, Any]:
    """Build the deep evidence bundle, distinguishing observed/inferred/unknown."""

    selected = [item for item, _ in files]
    contents = {item.path: text for item, text in files}
    observed = _observed(repo, light, selected, config)

    readme_text = contents.get("README.md") or contents.get("README.md".lower())
    if readme_text is None:
        for path, text in contents.items():
            if path.rsplit("/", 1)[-1].lower().startswith("readme"):
                readme_text = text
                break

    flagged = sorted(path for path, text in contents.items() if contains_prompt_injection(text))
    claim_checks = _claim_checks(readme_text, observed)
    mismatches = [check["claim"] for check in claim_checks if not check["supported_by_implementation"]]

    scale = "small" if observed["file_count"] <= 10 else "medium"
    if observed["file_count"] > 60:
        scale = "large"
    depth = "shallow"
    if observed["source_file_count"] >= 4:
        depth = "moderate"
    if observed["source_file_count"] >= 10:
        depth = "substantial"
    documentation = "minimal"
    if observed["readme_present"]:
        documentation = "present"
    if observed["doc_file_count"] >= 2:
        documentation = "structured"

    inferred = {
        "project_scale": scale,
        "implementation_depth": depth,
        "documentation_level": documentation,
        "packaging": "declared" if observed["manifest_names"] else "undeclared",
    }

    unknown = list(UNKNOWN_KEYS)

    return {
        "repo": repo.full_name,
        "github_repo_id": repo.github_repo_id,
        "observed": observed,
        "inferred": inferred,
        "unknown": unknown,
        "claims": [check["claim"] for check in claim_checks],
        "claim_checks": claim_checks,
        "claim_implementation_mismatch": mismatches,
        "prompt_injection_signal": bool(flagged),
        "prompt_injection_files": flagged,
        "untrusted_content": {
            item.path: wrap_untrusted(contents[item.path], max_chars=min(2000, config.deep.max_file_bytes))
            for item in selected
        },
        "description": observed.get("description"),
        "stars": observed.get("stars"),
        "primary_language": observed.get("primary_language"),
    }
