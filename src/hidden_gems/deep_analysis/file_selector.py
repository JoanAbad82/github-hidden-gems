"""Bounded, deterministic selection of files worth reading (SPEC_V1 §8).

Only static text files are selected, and only up to the configured per-file,
per-category and total budgets. Nothing here downloads, executes, installs or
builds candidate code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..config import AppConfig

CATEGORY_ORDER: tuple[str, ...] = ("manifest", "docs", "test", "source", "example", "config")

MANIFEST_NAMES: frozenset[str] = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "requirements-dev.txt",
        "package.json",
        "cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "composer.json",
        "gemfile",
        "pipfile",
        "environment.yml",
        "environment.yaml",
        "docker-compose.yml",
        "docker-compose.yaml",
    }
)

DOC_NAMES: frozenset[str] = frozenset(
    {"readme.md", "readme.rst", "readme.txt", "readme", "license", "license.md", "contributing.md"}
)

CONFIG_NAMES: frozenset[str] = frozenset(
    {"dockerfile", "makefile", ".editorconfig", ".pre-commit-config.yaml", "mkdocs.yml"}
)

SOURCE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".java",
        ".kt", ".rb", ".php", ".cs", ".c", ".h", ".cpp", ".hpp", ".swift", ".scala", ".sh",
        ".ps1", ".sql", ".lua", ".ex", ".exs", ".dart", ".r", ".jl", ".zsh",
    }
)

DOC_EXTENSIONS: frozenset[str] = frozenset({".md", ".rst", ".txt", ".adoc"})
CONFIG_EXTENSIONS: frozenset[str] = frozenset(
    {".yml", ".yaml", ".toml", ".ini", ".cfg", ".json", ".properties", ".env.example"}
)

#: Assets and datasets are never read by the deep analyzer.
EXCLUDED_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff", ".svg", ".pdf",
        ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar", ".whl", ".exe", ".dll", ".so", ".dylib",
        ".bin", ".onnx", ".pt", ".pth", ".safetensors", ".h5", ".pkl", ".pickle", ".npy",
        ".npz", ".parquet", ".feather", ".arrow", ".csv", ".tsv", ".xlsx", ".xls", ".db",
        ".sqlite", ".sqlite3", ".mp3", ".mp4", ".wav", ".mov", ".woff", ".woff2", ".ttf",
        ".ipynb", ".lock", ".min.js", ".map",
    }
)

EXCLUDED_DIRS: frozenset[str] = frozenset(
    {
        ".git", "node_modules", "vendor", "dist", "build", ".venv", "venv", "__pycache__",
        ".mypy_cache", ".pytest_cache", "site-packages", "target", ".next", ".nuxt", "coverage",
    }
)

_CATEGORY_LIMIT_KEY: Mapping[str, str] = {
    "manifest": "max_manifest_files",
    "docs": "max_docs_files",
    "test": "max_test_files",
    "source": "max_source_files",
}

_FALLBACK_CATEGORY_LIMITS: Mapping[str, int] = {"example": 2, "config": 2}


@dataclass(frozen=True)
class SelectedFile:
    path: str
    category: str
    reason: str
    size: int


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1].lower()


def _extension(path: str) -> str:
    name = _basename(path)
    if name.endswith(".min.js"):
        return ".min.js"
    dot = name.rfind(".")
    return name[dot:] if dot > 0 else ""


def _is_excluded(path: str) -> bool:
    parts = [part for part in path.split("/") if part]
    if any(part in EXCLUDED_DIRS for part in parts[:-1]):
        return True
    name = _basename(path)
    if name in {"package-lock.json", "yarn.lock", "poetry.lock", "cargo.lock", "go.sum", "pnpm-lock.yaml"}:
        return True
    return _extension(path) in EXCLUDED_EXTENSIONS


def _category(path: str) -> tuple[str, str] | None:
    name = _basename(path)
    lower_path = path.lower()
    if name in MANIFEST_NAMES:
        return "manifest", "recognized dependency manifest"
    if name in DOC_NAMES:
        return "docs", "project documentation"
    if lower_path.startswith("docs/") or "/docs/" in lower_path:
        return "docs", "documentation directory"
    if "test" in name or "test" in lower_path.split("/")[:-1] or name in {"conftest.py", "spec_helper.rb"}:
        return "test", "test suite evidence"
    if "example" in lower_path or "sample" in lower_path or "demo" in lower_path:
        return "example", "usage example"
    extension = _extension(path)
    if extension in SOURCE_EXTENSIONS:
        return "source", "implementation source"
    if name in CONFIG_NAMES or extension in CONFIG_EXTENSIONS:
        return "config", "project configuration"
    if extension in DOC_EXTENSIONS:
        return "docs", "project documentation"
    return None


def _category_limits(config: AppConfig) -> dict[str, int]:
    limits = dict(_FALLBACK_CATEGORY_LIMITS)
    for category, key in _CATEGORY_LIMIT_KEY.items():
        limits[category] = int(getattr(config.deep, key))
    return limits


def select_files(
    tree_entries: Sequence[Mapping[str, Any]], *, config: AppConfig
) -> list[SelectedFile]:
    """Return the highest-value readable files within every configured bound."""

    max_files = int(config.deep.max_files)
    max_file_bytes = int(config.deep.max_file_bytes)
    max_total_bytes = int(config.deep.max_total_bytes)
    limits = _category_limits(config)

    candidates: dict[str, list[SelectedFile]] = {category: [] for category in CATEGORY_ORDER}
    for entry in tree_entries or ():
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("type", "blob")) != "blob":
            continue
        path = str(entry.get("path") or "").lstrip("/")
        if not path or _is_excluded(path):
            continue
        size = int(entry.get("size") or 0)
        if size <= 0 or size > max_file_bytes:
            continue
        classified = _category(path)
        if classified is None:
            continue
        category, reason = classified
        candidates[category].append(SelectedFile(path=path, category=category, reason=reason, size=size))

    selected: list[SelectedFile] = []
    total_bytes = 0
    for category in CATEGORY_ORDER:
        items = sorted(candidates[category], key=lambda item: (item.path.count("/"), item.path))
        taken = 0
        for item in items:
            if taken >= limits.get(category, 0):
                break
            if len(selected) >= max_files:
                return selected
            if total_bytes + item.size > max_total_bytes:
                continue
            selected.append(item)
            total_bytes += item.size
            taken += 1
        if len(selected) >= max_files:
            break
    return selected
