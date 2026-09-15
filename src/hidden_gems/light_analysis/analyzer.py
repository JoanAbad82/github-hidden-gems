"""Light analyzer: bounded README/tree/release/manifest reading (SPEC_V1 §5)."""

from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Any, Mapping, Sequence

from ..common.hashing import hash_manifests, hash_readme, hash_tree, relevant_content_hash
from ..common.time import days_ago
from ..config import AppConfig
from ..models import DiscoveryCandidate, LightAnalysis
from .activity import classify_activity
from .classification import detect_areas, negative_signals, quality_signals

MANIFEST_NAMES: tuple[str, ...] = (
    "pyproject.toml", "package.json", "requirements.txt", "setup.py", "cargo.toml",
    "go.mod", "composer.json", "gemfile", "pipfile", "pom.xml", "build.gradle",
)

MAX_MANIFESTS = 3
COMMIT_LOOKBACK_DAYS = 60
COMMIT_LIMIT = 30
RELEASE_LIMIT = 10

_GITHUB_URL = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXTERNAL_URL = re.compile(r"https?://\S+")


class LightAnalyzer:
    """Reads metadata only. Never clones, downloads or executes a repository."""

    def __init__(self, config: AppConfig, client: Any) -> None:
        self._config = config
        self._client = client

    # -- bounded reads ----------------------------------------------------

    def _readme(self, candidate: DiscoveryCandidate) -> str | None:
        try:
            return self._client.get_readme(candidate.repo.full_name)
        except Exception:
            return None

    def _tree(self, candidate: DiscoveryCandidate) -> list[Mapping[str, Any]]:
        ref = candidate.default_branch or "HEAD"
        try:
            entries = self._client.get_tree(candidate.repo.full_name, ref)
        except Exception:
            return []
        bounded = [entry for entry in entries or () if isinstance(entry, Mapping)]
        return bounded[: int(self._config.light.max_tree_items)]

    def _releases(self, candidate: DiscoveryCandidate) -> list[Mapping[str, Any]]:
        try:
            releases = self._client.get_releases(candidate.repo.full_name, RELEASE_LIMIT)
        except Exception:
            return []
        return [entry for entry in releases or () if isinstance(entry, Mapping)]

    def _commits(self, candidate: DiscoveryCandidate, as_of: datetime) -> list[Mapping[str, Any]]:
        try:
            commits = self._client.get_recent_commits(
                candidate.repo.full_name,
                since=days_ago(COMMIT_LOOKBACK_DAYS, as_of=as_of),
                limit=COMMIT_LIMIT,
            )
        except Exception:
            return []
        return [entry for entry in commits or () if isinstance(entry, Mapping)]

    def _manifest_contents(
        self, candidate: DiscoveryCandidate, tree: Sequence[Mapping[str, Any]]
    ) -> dict[str, str]:
        manifests: dict[str, str] = {}
        ref = candidate.default_branch or "HEAD"
        for entry in tree:
            path = str(entry.get("path") or "")
            name = path.rsplit("/", 1)[-1].lower()
            if name not in MANIFEST_NAMES or path.count("/") > 1:
                continue
            try:
                payload = self._client.get_json(
                    f"/repos/{candidate.repo.full_name}/contents/{path}", {"ref": ref}
                )
            except Exception:
                continue
            if not isinstance(payload, Mapping) or payload.get("encoding") != "base64":
                continue
            try:
                raw = base64.b64decode(str(payload.get("content") or ""), validate=False)
            except Exception:
                continue
            limit = int(self._config.light.max_manifest_bytes)
            manifests[path] = raw[:limit].decode("utf-8", errors="replace")
            if len(manifests) >= MAX_MANIFESTS:
                break
        return manifests

    # -- analysis ---------------------------------------------------------

    def analyze(self, candidate: DiscoveryCandidate, *, as_of: datetime) -> LightAnalysis:
        readme = self._readme(candidate)
        tree = self._tree(candidate)
        releases = self._releases(candidate)
        commits = self._commits(candidate, as_of)
        manifests = self._manifest_contents(candidate, tree)

        paths = tuple(str(entry.get("path") or "") for entry in tree)
        dependency_names = _dependency_names(manifests)
        readme_links = _links(readme, github_only=True)
        dependency_links = _links("\n".join(manifests.values()), github_only=True)

        readme_hash = hash_readme(
            readme, max_chars=int(self._config.light.max_readme_chars_for_hash)
        )
        tree_hash = hash_tree(tree)
        dependency_hash = hash_manifests(manifests)

        latest_release = releases[0] if releases else None
        latest_release_at = None
        latest_release_tag = None
        latest_release_id = None
        if latest_release is not None:
            latest_release_tag = str(latest_release.get("tag_name") or "") or None
            latest_release_id = latest_release.get("id")
            for key in ("published_at", "created_at"):
                value = latest_release.get(key)
                if value:
                    from ..common.time import parse_github_datetime

                    latest_release_at = parse_github_datetime(str(value))
                    break

        relevant_activity_at = _latest_activity(commits, latest_release_at)
        activity_level, activity_evidence = classify_activity(
            commits=commits,
            releases=releases,
            relevant_activity_at=relevant_activity_at,
            as_of=as_of,
        )
        areas = detect_areas(
            description=candidate.description,
            topics=tuple(candidate.topics or ()),
            readme_text=readme,
            dependency_names=dependency_names,
            manifest_names=tuple(manifests.keys()),
            config=self._config,
        )
        has_license = bool(candidate.license_spdx_id) or any(
            path.rsplit("/", 1)[-1].lower().startswith(("license", "licence", "copying"))
            for path in paths
        )
        has_ci = any(
            path.lower().startswith((".github/workflows/", ".circleci/"))
            or path.lower() in {".gitlab-ci.yml", ".travis.yml", "jenkinsfile"}
            for path in paths
        )
        quality = quality_signals(
            tree_paths=paths,
            readme_text=readme,
            has_license=has_license,
            has_ci=has_ci,
            manifest_names=tuple(manifests.keys()),
        )
        negatives = negative_signals(
            tree_paths=paths, readme_text=readme, description=candidate.description
        )

        evidence: dict[str, Any] = {
            "description": candidate.description,
            "stars": candidate.stars,
            "primary_language": candidate.primary_language,
            "default_branch": candidate.default_branch or "HEAD",
            "readme_present": bool(readme),
            "readme_chars": len(readme or ""),
            "tree_paths": paths,
            "file_count": len(paths),
            "source_file_count": len(
                [path for path in paths if path.lower().endswith((".py", ".ts", ".js", ".go", ".rs", ".java"))]
            ),
            "test_file_count": len(
                [path for path in paths if "test" in path.lower()]
            ),
            "doc_file_count": len(
                [path for path in paths if path.lower().endswith((".md", ".rst"))]
            ),
            "manifest_names": sorted(manifests.keys()),
            "manifest_paths": sorted(manifests.keys()),
            "dependency_names": sorted(dependency_names),
            "dependency_links": dependency_links,
            "readme_links": readme_links,
            "related_project_links": readme_links,
            "has_license": has_license,
            "has_ci": has_ci,
            "latest_release_tag": latest_release_tag,
            "latest_release_id": latest_release_id,
            "release_count": len(releases),
            "commit_count": len(commits),
            "activity": activity_evidence,
        }

        return LightAnalysis(
            repo=candidate.repo,
            detected_areas=areas,
            activity_level=activity_level,
            quality_signals=quality,
            negative_signals=negatives,
            latest_release_tag=latest_release_tag,
            latest_release_at=latest_release_at,
            latest_relevant_activity_at=relevant_activity_at,
            readme_hash=readme_hash,
            tree_hash=tree_hash,
            dependency_hash=dependency_hash,
            relevant_content_hash=relevant_content_hash(readme_hash, tree_hash, dependency_hash),
            evidence=evidence,
        )


def _dependency_names(manifests: Mapping[str, str]) -> tuple[str, ...]:
    names: list[str] = []
    for path, content in manifests.items():
        lowered = content.lower()
        for token in re.findall(r"[A-Za-z0-9._-]{2,40}", lowered):
            if token in {"name", "version", "dependencies", "devdependencies"}:
                continue
            names.append(token)
    return tuple(sorted(set(names)))


def _links(text: str | None, *, github_only: bool) -> list[str]:
    if not text:
        return []
    found: list[str] = []
    for match in _GITHUB_URL.findall(text):
        owner, name = match
        name = name[:-4] if name.endswith(".git") else name
        found.append(f"https://github.com/{owner}/{name}")
    if not github_only:
        found.extend(_EXTERNAL_URL.findall(text))
    return sorted(set(found))


def _latest_activity(
    commits: Sequence[Mapping[str, Any]], latest_release_at: datetime | None
) -> datetime | None:
    from .activity import _commit_datetime  # local import: shared helper

    candidates = [value for value in (_commit_datetime(commit) for commit in commits) if value]
    if latest_release_at is not None:
        candidates.append(latest_release_at)
    return max(candidates) if candidates else None
