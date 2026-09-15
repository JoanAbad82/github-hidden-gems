"""Deterministic rejection rules.

Every rule returns the independent signals it observed, so a rejection is
always explainable and a single weak signal can never disqualify a repository.
Aggressive with noise, conservative with innovation: few stars, an unknown
author, a single contributor, no releases, a non-priority language or extreme
youth are *not* rejection reasons.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from ..config import AppConfig
from ..models import AREA_IDS, DiscoveryCandidate

FILTER_PASS = "PASS"

REASON_FORK = "REJECT_FORK"
REASON_ARCHIVED = "REJECT_ARCHIVED"
REASON_EMPTY = "REJECT_EMPTY"
REASON_TUTORIAL = "REJECT_TUTORIAL"
REASON_TEMPLATE = "REJECT_TEMPLATE"
REASON_DEMO = "REJECT_DEMO"
REASON_SPAM = "REJECT_SPAM"
REASON_IRRELEVANT = "REJECT_IRRELEVANT"
REASON_LOW_MAX_SCORE = "REJECT_LOW_MAX_SCORE"

#: Terms that, on their own, carry enough weight to establish a real area signal.
STRONG_AREA_TERMS: frozenset[str] = frozenset(
    {
        "llm",
        "llms",
        "language model",
        "language models",
        "rag",
        "retrieval augmented",
        "embedding",
        "embeddings",
        "vector store",
        "vector database",
        "tool calling",
        "function calling",
        "prompt engineering",
        "multi-agent",
        "agent framework",
        "ai agent",
        "llm agent",
        "autonomous agent",
        "backtest",
        "backtesting",
        "market data",
        "order book",
        "quantitative trading",
        "trading bot",
        "algorithmic trading",
        "web scraping",
        "scraper",
        "data extraction",
        "extraction",
        "etl",
        "data pipeline",
        "document parsing",
        "workflow automation",
        "task automation",
        "self-hosted",
        "browser automation",
        "job scheduler",
        "ci/cd",
        "webhook automation",
    }
)

#: Terms that only count when they appear together with other evidence.
WEAK_AREA_TERMS: frozenset[str] = frozenset(
    {
        "agent",
        "agents",
        "automation",
        "workflow",
        "workflows",
        "pipeline",
        "scheduler",
        "cron",
        "webhook",
        "trading",
        "broker",
        "portfolio",
        "indicator",
        "exchange",
        "quantitative",
        "data",
        "dataset",
        "analytics",
        "parser",
        "parsing",
        "scraping",
        "ingestion",
        "dataframe",
        "dashboard",
        "memory",
        "retrieval",
        "orchestration",
    }
)

DEFAULT_AREA_TERMS: Mapping[str, tuple[str, ...]] = {
    "ai_agents": (
        "llm",
        "language model",
        "rag",
        "embedding",
        "vector store",
        "tool calling",
        "multi-agent",
        "agent framework",
        "ai agent",
        "prompt",
        "agent",
        "agents",
        "retrieval",
        "memory",
        "orchestration",
    ),
    "automation": (
        "workflow automation",
        "task automation",
        "self-hosted",
        "browser automation",
        "job scheduler",
        "ci/cd",
        "automation",
        "workflow",
        "scheduler",
        "cron",
        "webhook",
        "rpa",
    ),
    "data": (
        "web scraping",
        "scraper",
        "data extraction",
        "extraction",
        "etl",
        "data pipeline",
        "document parsing",
        "scraping",
        "parser",
        "parsing",
        "ingestion",
        "dataframe",
        "analytics",
        "dataset",
        "data",
    ),
    "trading": (
        "algorithmic trading",
        "backtest",
        "backtesting",
        "market data",
        "order book",
        "quantitative trading",
        "trading bot",
        "trading",
        "broker",
        "portfolio",
        "indicator",
        "exchange",
    ),
}

SOURCE_SUFFIXES = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".rb",
    ".php",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".swift",
    ".scala",
    ".sh",
    ".lua",
    ".ex",
    ".exs",
    ".sql",
)

IGNORED_PATHS = (
    "readme",
    "license",
    "licence",
    "copying",
    ".gitignore",
    "contributing",
    "code_of_conduct",
    "changelog",
)

_PROMO_PATTERNS = (
    "revolutionary",
    "world's best",
    "worlds best",
    "best ever",
    "guaranteed",
    "10x",
    "passive income",
    "get rich",
    "buy now",
    "join now",
    "money machine",
    "100% free money",
)

_TUTORIAL_DESCRIPTION = (
    "tutorial",
    "step by step",
    "learn how to",
    "course",
    "bootcamp",
    "guide for beginners",
    "for beginners",
    "educational",
)

_TUTORIAL_README = (
    "this repository is a learning exercise",
    "follow this course",
    "step by step",
    "tutorial series",
    "for beginners",
    "learning purposes",
)

_TEMPLATE_DESCRIPTION = (
    "template",
    "boilerplate",
    "starter kit",
    "starter template",
    "scaffold",
    "cookiecutter",
)

_TEMPLATE_README = (
    "boilerplate",
    "starter kit",
    "scaffold",
    "rename the placeholders",
    "use this template",
    "cookiecutter",
)

_DEMO_DESCRIPTION = (
    "demo",
    "sample app",
    "example app",
    "proof of concept",
    "poc",
    "playground",
    "showcase",
)

_DEMO_README = (
    "not intended for production",
    "for demonstration",
    "demo purposes",
    "sample application",
    "conference talk",
    "playground",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def candidate_text(candidate: DiscoveryCandidate, evidence: Any | None = None) -> str:
    parts = [
        candidate.repo.name,
        candidate.repo.full_name,
        candidate.description or "",
        " ".join(candidate.topics or ()),
    ]
    if evidence is not None:
        parts.append(getattr(evidence, "readme_text", "") or "")
        parts.append(" ".join(getattr(evidence, "manifest_names", ()) or ()))
    return _normalize(" ".join(parts))


def tree_paths(evidence: Any | None) -> tuple[str, ...]:
    if evidence is None:
        return ()
    return tuple(getattr(evidence, "tree_paths", ()) or ())


def is_source_path(path: str) -> bool:
    lowered = path.lower()
    return lowered.endswith(SOURCE_SUFFIXES)


def is_ignored_path(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in IGNORED_PATHS)


def source_paths(evidence: Any | None) -> tuple[str, ...]:
    return tuple(path for path in tree_paths(evidence) if is_source_path(path))


def minimal_implementation(evidence: Any | None) -> bool:
    return len(source_paths(evidence)) <= 2


def has_tests(evidence: Any | None) -> bool:
    return any(
        path.lower().startswith("tests/")
        or "/tests/" in path.lower()
        or path.lower().startswith("test_")
        or path.lower().endswith("_test.py")
        for path in tree_paths(evidence)
    )


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle in text for needle in needles)


def fork_reason(candidate: DiscoveryCandidate) -> tuple[str, ...]:
    if candidate.is_fork:
        return ("github:is_fork=true",)
    return ()


def archived_reason(candidate: DiscoveryCandidate) -> tuple[str, ...]:
    if candidate.is_archived:
        return ("github:is_archived=true",)
    return ()


def empty_reason(candidate: DiscoveryCandidate, evidence: Any | None) -> tuple[str, ...]:
    paths = tree_paths(evidence)
    if paths:
        meaningful = [path for path in paths if not is_ignored_path(path)]
        if not meaningful:
            return (f"tree:only_boilerplate_files={len(paths)}",)
        return ()
    size = getattr(evidence, "total_size_kb", None)
    if size is None:
        size = candidate.size_kb
    if size == 0:
        return ("size_kb=0", "tree:entries=0")
    if not paths and size is None and not candidate.description and not candidate.topics:
        return ("metadata:no_description_or_topics", "tree:unknown")
    return ()


def area_scores(candidate: DiscoveryCandidate, evidence: Any | None, config: AppConfig | None) -> dict[str, int]:
    """Weighted thematic evidence per area (strong term = 2, weak term = 1)."""

    text = candidate_text(candidate, evidence)
    topics = {topic.lower() for topic in (candidate.topics or ())}
    scores: dict[str, int] = {area: 0 for area in AREA_IDS}
    for area in AREA_IDS:
        terms = _area_terms(area, config)
        score = 0
        counted: set[str] = set()
        for term in terms:
            normalized = _plain_term(term)
            if not normalized:
                continue
            stem = _term_stem(normalized)
            if stem in counted:
                # Singular/plural variants of one word are a single signal, so
                # "ssh-agent ... user agents" cannot look like two pieces of
                # independent evidence.
                continue
            if normalized in topics:
                counted.add(stem)
                score += 2 if normalized in STRONG_AREA_TERMS else 1
                continue
            if normalized in text:
                counted.add(stem)
                score += 2 if normalized in STRONG_AREA_TERMS else 1
        if config is not None:
            dependencies = (config.topics.by_id[area].dependencies if area in config.topics.by_id else ())
            if any(dep.lower() in text for dep in dependencies):
                score += 2
        scores[area] = score
    return scores


def _term_stem(term: str) -> str:
    """Fold simple plural forms so one word never counts twice."""

    if len(term) > 3 and term.endswith("s") and not term.endswith("ss"):
        return term[:-1]
    return term


_SEARCH_QUALIFIER = re.compile(r"\b(?:in|created|pushed|stars|language|topic):\S+")


def _plain_term(term: str) -> str:
    """Convert a configured search term into the plain text it looks for.

    `config/topics.yml` stores GitHub search syntax (quoted phrases and
    qualifiers). Repository text never contains those quotes, so matching the
    raw string would silently disable every phrase term.
    """

    cleaned = _SEARCH_QUALIFIER.sub(" ", str(term))
    return cleaned.replace('"', " ").strip().lower()


def _area_terms(area: str, config: AppConfig | None) -> Sequence[str]:
    if config is not None and area in config.topics.by_id:
        area_config = config.topics.by_id[area]
        return tuple(area_config.keywords) + tuple(area_config.search_terms)
    return DEFAULT_AREA_TERMS.get(area, ())


def is_irrelevant(candidate: DiscoveryCandidate, evidence: Any | None, config: AppConfig | None) -> bool:
    """A repository is irrelevant only when *no* area reaches a central signal."""

    scores = area_scores(candidate, evidence, config)
    return max(scores.values(), default=0) < 2


def tutorial_signals(candidate: DiscoveryCandidate, evidence: Any | None) -> tuple[str, ...]:
    signals: list[str] = []
    name = candidate.repo.name.lower()
    topics = {topic.lower() for topic in (candidate.topics or ())}
    description = _normalize(candidate.description or "")
    readme = _normalize(getattr(evidence, "readme_text", "") or "")

    if any(token in name for token in ("tutorial", "course", "workshop", "bootcamp", "101")):
        signals.append("name:tutorial_wording")
    if topics & {"tutorial", "course", "learning", "workshop", "bootcamp"}:
        signals.append("topic:tutorial")
    if _contains_any(description, _TUTORIAL_DESCRIPTION):
        signals.append("description:tutorial_wording")
    if _contains_any(readme, _TUTORIAL_README):
        signals.append("readme:tutorial_wording")
    paths = tree_paths(evidence)
    notebooks = [path for path in paths if path.lower().endswith(".ipynb")]
    if notebooks and len(source_paths(evidence)) <= 2:
        signals.append("tree:notebook_only")
    elif minimal_implementation(evidence) and paths:
        signals.append("tree:minimal_implementation")
    return tuple(signals)


def template_signals(candidate: DiscoveryCandidate, evidence: Any | None) -> tuple[str, ...]:
    topics = {topic.lower() for topic in (candidate.topics or ())}
    if candidate.is_template or "template" in topics:
        return ("github:template_metadata=true",)

    signals: list[str] = []
    name = candidate.repo.name.lower()
    description = _normalize(candidate.description or "")
    readme = _normalize(getattr(evidence, "readme_text", "") or "")
    if any(token in name for token in ("template", "boilerplate", "starter")):
        signals.append("name:template_wording")
    if topics & {"boilerplate", "starter", "scaffold", "cookiecutter"}:
        signals.append("topic:template_wording")
    if _contains_any(description, _TEMPLATE_DESCRIPTION):
        signals.append("description:template_wording")
    if _contains_any(readme, _TEMPLATE_README):
        signals.append("readme:template_wording")
    if any("{{" in path or "<project" in path.lower() or "placeholder" in path.lower() for path in tree_paths(evidence)):
        signals.append("tree:placeholder_markers")
    if minimal_implementation(evidence) and not has_tests(evidence) and tree_paths(evidence):
        signals.append("tree:no_application_code")
    return tuple(signals)


def demo_signals(candidate: DiscoveryCandidate, evidence: Any | None) -> tuple[str, ...]:
    signals: list[str] = []
    name = candidate.repo.name.lower()
    topics = {topic.lower() for topic in (candidate.topics or ())}
    description = _normalize(candidate.description or "")
    readme = _normalize(getattr(evidence, "readme_text", "") or "")
    if any(token in name for token in ("demo", "sample", "example", "playground", "poc")):
        signals.append("name:demo_wording")
    if topics & {"demo", "sample", "example", "playground"}:
        signals.append("topic:demo_wording")
    if _contains_any(description, _DEMO_DESCRIPTION):
        signals.append("description:demo_wording")
    if _contains_any(readme, _DEMO_README):
        signals.append("readme:demo_wording")
    if minimal_implementation(evidence) and not has_tests(evidence) and tree_paths(evidence):
        signals.append("tree:minimal_implementation")
    return tuple(signals)


def spam_signals(candidate: DiscoveryCandidate, evidence: Any | None) -> tuple[str, ...]:
    signals: list[str] = []
    description = candidate.description or ""
    readme = getattr(evidence, "readme_text", "") or ""
    blob = _normalize(f"{description} {readme}")
    if _contains_any(blob, _PROMO_PATTERNS):
        signals.append("text:promotional_superlatives")
    if description and sum(1 for char in description if char.isupper()) >= max(12, len(description) // 2):
        signals.append("text:excessive_caps")
    if blob.count("http://") + blob.count("https://") >= 3:
        signals.append("text:link_farm")
    if not source_paths(evidence) and tree_paths(evidence):
        signals.append("tree:no_source_code")
    return tuple(signals)


def semantic_rejection(candidate: DiscoveryCandidate, evidence: Any | None) -> tuple[str | None, tuple[str, ...]]:
    """Two independent weak signals are required for every semantic rejection."""

    checks = (
        (REASON_TUTORIAL, tutorial_signals(candidate, evidence)),
        (REASON_TEMPLATE, template_signals(candidate, evidence)),
        (REASON_DEMO, demo_signals(candidate, evidence)),
        (REASON_SPAM, spam_signals(candidate, evidence)),
    )
    for reason, signals in checks:
        if len(signals) >= 2:
            return reason, signals
    return None, ()
