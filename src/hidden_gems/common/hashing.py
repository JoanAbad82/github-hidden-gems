"""Deterministic content hashing.

Hashes are order-insensitive with respect to API item ordering and stable
across runs for identical normalized content. They are used for AI cache
reuse (`relevant_content_hash`) and for change detection.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_text(text: str) -> str:
    """Normalize line endings, strip BOM and trailing whitespace per line."""

    if text is None:
        return ""
    cleaned = text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in cleaned.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def hash_text(text: str) -> str:
    return sha256_text(normalize_text(text))


def hash_blob(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_readme(text: str | None, *, max_chars: int | None = None) -> str:
    normalized = normalize_text(text or "")
    if max_chars is not None and max_chars > 0:
        normalized = normalized[:max_chars]
    return sha256_text(normalized)


def hash_tree(entries: Iterable[Any]) -> str:
    """Hash a repository tree regardless of the order entries arrive in.

    Each entry may be a mapping with `path`, `type`, `size` keys or an object
    exposing those attributes.
    """

    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, Mapping):
            path = str(entry.get("path", ""))
            kind = str(entry.get("type", ""))
            size = entry.get("size", 0)
        else:
            path = str(getattr(entry, "path", ""))
            kind = str(getattr(entry, "type", ""))
            size = getattr(entry, "size", 0)
        normalized.append({"path": path, "type": kind, "size": int(size or 0)})
    normalized.sort(key=lambda item: (item["path"], item["type"]))
    return sha256_text(canonical_json(normalized))


def hash_manifests(manifests: Mapping[str, str]) -> str:
    """Hash recognized dependency manifests by path, independent of dict order."""

    payload = {
        path: sha256_text(normalize_text(content))
        for path, content in sorted(manifests.items(), key=lambda item: item[0])
    }
    return sha256_text(canonical_json(payload))


def combine_hashes(parts: Sequence[str]) -> str:
    return sha256_text(canonical_json(list(parts)))


def relevant_content_hash(readme_hash: str, tree_hash: str, dependency_hash: str) -> str:
    """Cache key component for AI analyses and change detection."""

    return combine_hashes([readme_hash, tree_hash, dependency_hash])
