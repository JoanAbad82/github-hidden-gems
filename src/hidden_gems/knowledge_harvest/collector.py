"""Deterministic static evidence collection for KNOWLEDGE_HARVEST_V1."""

from __future__ import annotations

import base64
import hashlib
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from ..security.untrusted_content import wrap_untrusted

MAX_FILES = 16
MAX_FILE_BYTES = 120_000
MAX_CHARS_PER_FILE = 6_000
MAX_TOTAL_CHARS = 32_000

_TEXT_EXTENSIONS = {
    ".md", ".rst", ".txt", ".adoc", ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx",
    ".mjs", ".cjs", ".rs", ".go", ".java", ".kt", ".rb", ".php", ".cs", ".c",
    ".h", ".cpp", ".hpp", ".swift", ".scala", ".sh", ".ps1", ".sql", ".lua",
    ".toml", ".yml", ".yaml", ".json", ".ini", ".cfg", ".properties", ".bend",
}
_SOURCE_EXTENSIONS = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs", ".go",
    ".java", ".kt", ".rb", ".php", ".cs", ".c", ".h", ".cpp", ".hpp", ".swift",
    ".scala", ".sh", ".ps1", ".sql", ".lua", ".bend",
}
_CONFIG_NAMES = {
    "package.json", "pyproject.toml", "cargo.toml", "go.mod", "pom.xml",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", "makefile",
}
_EXCLUDED_PARTS = {
    ".git", "node_modules", "vendor", "dist", "build", "target", ".venv", "venv",
    "__pycache__", "coverage", ".next", ".nuxt", "site-packages",
}
_KEYWORDS = (
    "architecture", "design", "rfc", "agent", "orchestr", "route", "routing",
    "dispatch", "provider", "fallback", "guard", "security", "permission",
    "approval", "sandbox", "state", "session", "journal", "queue", "reconnect",
    "recovery", "resume", "checkpoint", "worktree", "artifact", "evidence",
    "invariant", "protocol", "workflow", "concurrency",
)
_CATEGORY_WEIGHT = {
    "readme": 120,
    "safety": 110,
    "state": 105,
    "routing": 100,
    "architecture": 95,
    "test": 90,
    "source": 80,
    "config": 70,
    "docs": 60,
}


def _path_parts(path: str) -> tuple[str, ...]:
    return tuple(part.lower() for part in PurePosixPath(path).parts)


def _extension(path: str) -> str:
    return PurePosixPath(path).suffix.lower()


def _is_text_candidate(path: str, size: int) -> bool:
    if size <= 0 or size > MAX_FILE_BYTES:
        return False
    parts = _path_parts(path)
    if any(part in _EXCLUDED_PARTS for part in parts[:-1]):
        return False
    name = PurePosixPath(path).name.lower()
    return name in _CONFIG_NAMES or _extension(path) in _TEXT_EXTENSIONS


def _artifact_kind(path: str) -> str:
    """Classify provenance strength independently from thematic category."""

    lower = path.lower()
    name = PurePosixPath(path).name.lower()
    parts = _path_parts(path)
    if "test" in parts or "tests" in parts or name.startswith("test") or ".test." in name or ".spec." in name:
        return "TEST"
    if name in _CONFIG_NAMES:
        return "CONFIG"
    if _extension(path) in _SOURCE_EXTENSIONS:
        return "SOURCE"
    return "DOCUMENTATION"


def _category(path: str) -> str:
    lower = path.lower()
    name = PurePosixPath(path).name.lower()
    parts = _path_parts(path)
    if lower == "readme.md" or name in {"readme", "readme.md", "readme.rst", "readme.txt"} and len(parts) == 1:
        return "readme"
    if any(term in lower for term in ("security", "guard", "permission", "approval", "sandbox")):
        return "safety"
    if any(term in lower for term in ("state", "session", "journal", "queue", "reconnect", "recovery", "resume", "checkpoint", "worktree")):
        return "state"
    if any(term in lower for term in ("agent", "orchestr", "route", "routing", "dispatch", "provider", "fallback")):
        return "routing"
    if any(term in lower for term in ("architecture", "design", "/rfc", "rfc-")):
        return "architecture"
    if "test" in parts or "tests" in parts or name.startswith("test") or ".test." in name or ".spec." in name:
        return "test"
    if name in _CONFIG_NAMES:
        return "config"
    if _extension(path) in _SOURCE_EXTENSIONS:
        return "source"
    return "docs"


def _score(entry: Mapping[str, Any]) -> tuple[int, int, str]:
    path = str(entry.get("path") or "")
    category = _category(path)
    lower = path.lower()
    keyword_hits = sum(1 for keyword in _KEYWORDS if keyword in lower)
    depth = path.count("/")
    # Stable descending score, then shallow paths, then lexical path.
    return (_CATEGORY_WEIGHT[category] + min(keyword_hits, 6) * 5, -depth, path)


def select_evidence_files(
    tree: Sequence[Mapping[str, Any]], *, max_files: int = MAX_FILES
) -> list[dict[str, Any]]:
    """Select high-value text files deterministically from a pinned tree."""

    candidates: list[dict[str, Any]] = []
    for raw in tree or ():
        if not isinstance(raw, Mapping) or str(raw.get("type") or "blob") != "blob":
            continue
        path = str(raw.get("path") or "").lstrip("/")
        size = int(raw.get("size") or 0)
        blob_sha = str(raw.get("sha") or "")
        if not path or len(blob_sha) != 40 or not _is_text_candidate(path, size):
            continue
        candidates.append(
            {
                "path": path,
                "size": size,
                "blob_sha": blob_sha,
                "category": _category(path),
                "kind": _artifact_kind(path),
            }
        )

    ordered = sorted(
        candidates,
        key=lambda item: (
            -_score(item)[0],
            -_score(item)[1],
            _score(item)[2],
        ),
    )

    # Avoid allowing one category to consume the whole budget.
    caps = {
        "readme": 1,
        "architecture": 4,
        "safety": 4,
        "state": 4,
        "routing": 4,
        "test": 4,
        "source": 4,
        "config": 2,
        "docs": 3,
    }
    taken: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for item in ordered:
        category = item["category"]
        if taken.get(category, 0) >= caps[category]:
            continue
        selected.append(item)
        taken[category] = taken.get(category, 0) + 1
        if len(selected) >= max_files:
            break
    return selected


def _read_text(client: Any, full_name: str, path: str, ref: str) -> str | None:
    try:
        payload = client.get_json(
            f"/repos/{full_name}/contents/{path}",
            {"ref": ref},
        )
    except Exception:
        return None
    if not isinstance(payload, Mapping):
        return None
    content = payload.get("content")
    if payload.get("encoding") != "base64" or not isinstance(content, str):
        return None
    try:
        raw = base64.b64decode(content, validate=False)
    except Exception:
        return None
    return raw[:MAX_FILE_BYTES].decode("utf-8", errors="replace")


def collect_repository_evidence(client: Any, full_name: str) -> dict[str, Any]:
    """Collect a bounded evidence bundle pinned to the current default-branch commit."""

    metadata = client.get_repo_metadata(full_name)
    repo_id = int(metadata.get("id") or 0)
    if repo_id <= 0:
        raise ValueError(f"repository id unavailable for {full_name}")
    default_branch = str(metadata.get("default_branch") or "main")
    commits = client.get_recent_commits(full_name, limit=1)
    if not commits or not isinstance(commits[0], Mapping):
        raise ValueError(f"head commit unavailable for {full_name}")
    head_sha = str(commits[0].get("sha") or "")
    if len(head_sha) != 40:
        raise ValueError(f"invalid head sha for {full_name}")

    tree = client.get_tree(full_name, head_sha)
    selected = select_evidence_files(tree)
    documents: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    total_chars = 0

    for index, item in enumerate(selected, start=1):
        if total_chars >= MAX_TOTAL_CHARS:
            break
        text = _read_text(client, full_name, item["path"], head_sha)
        if text is None:
            continue
        remaining = MAX_TOTAL_CHARS - total_chars
        clipped = text[: min(MAX_CHARS_PER_FILE, remaining)]
        if not clipped:
            continue
        evidence_id = f"E{len(documents) + 1:02d}"
        content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        manifest_item = {
            "id": evidence_id,
            "path": item["path"],
            "blob_sha": item["blob_sha"],
            "category": item["category"],
            "kind": item["kind"],
            "size": int(item["size"]),
            "content_sha256": content_sha256,
        }
        manifest.append(manifest_item)
        documents.append(
            {
                **manifest_item,
                "untrusted_text": wrap_untrusted(clipped),
            }
        )
        total_chars += len(clipped)

    if not documents:
        raise ValueError(f"no readable knowledge evidence for {full_name}")

    digest_material = "\n".join(
        f"{item['id']}|{item['path']}|{item['blob_sha']}|{item['category']}|{item['kind']}|{item['content_sha256']}"
        for item in manifest
    )
    evidence_digest = hashlib.sha256(digest_material.encode("utf-8")).hexdigest()
    license_payload = metadata.get("license")
    license_spdx = (
        str(license_payload.get("spdx_id"))
        if isinstance(license_payload, Mapping) and license_payload.get("spdx_id")
        else None
    )
    if license_spdx == "NOASSERTION":
        license_spdx = None

    return {
        "source": {
            "github_repo_id": repo_id,
            "full_name": str(metadata.get("full_name") or full_name),
            "html_url": str(metadata.get("html_url") or f"https://github.com/{full_name}"),
            "head_sha": head_sha,
            "default_branch": default_branch,
            "license_spdx_id": license_spdx,
            "evidence_digest": evidence_digest,
            "evidence_manifest": manifest,
        },
        "documents": documents,
    }
