"""Area classification and quality/negative signals for the light analyzer."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from ..models import AREA_IDS

#: Fallback terms mirroring config/topics.yml when no config is supplied.
DEFAULT_AREA_TERMS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "ai_agents": {
        "keywords": (
            "agent", "agents", "llm", "language model", "rag", "tool calling",
            "function calling", "embedding", "vector store", "prompt", "orchestration",
        ),
        "dependencies": ("langchain", "llama-index", "autogen", "crewai", "pydantic-ai",
                         "openai", "anthropic", "transformers", "vllm", "ollama"),
    },
    "automation": {
        "keywords": ("automation", "workflow", "scheduler", "cron", "webhook", "ci/cd",
                     "orchestrate", "self-hosted", "rpa", "pipeline"),
        "dependencies": ("n8n", "airflow", "prefect", "temporal", "celery", "playwright",
                         "selenium", "ansible", "github-actions"),
    },
    "data": {
        "keywords": ("scraping", "scraper", "parser", "extraction", "etl", "dataframe",
                     "analytics", "data pipeline", "structured output", "ingestion"),
        "dependencies": ("pandas", "polars", "duckdb", "beautifulsoup4", "scrapy", "lxml",
                         "pyspark", "apache-arrow"),
    },
    "trading": {
        "keywords": ("trading", "backtest", "backtesting", "market data", "order book",
                     "quantitative", "broker", "portfolio", "indicator", "exchange"),
        "dependencies": ("ccxt", "backtrader", "vectorbt", "zipline", "ta-lib", "pandas-ta",
                         "ib-insync", "alpaca-py"),
    },
}

#: Keywords that only establish an area together with a companion term. This is
#: what stops an `ssh-agent` helper from being classified as an AI agent.
QUALIFIED_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "agent": ("llm", "language model", "rag", "retrieval", "prompt", "tool calling",
              "function calling", "embedding", "vector", "orchestration", "autonomous",
              "multi-agent", "gpt", "claude", "llama", "tool use"),
    "pipeline": ("data", "etl", "ingestion", "extraction", "analytics", "streaming"),
    "exchange": ("trading", "order book", "market data", "broker", "backtest"),
    "parser": ("data", "document", "html", "xml", "structured", "extraction"),
}

SOURCE_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".go", ".rs", ".java", ".rb", ".sh")
TEST_HINTS = ("tests/", "test/", "test_", "_test.", ".spec.")
DOC_HINTS = ("docs/", "doc/", "readme", ".md", ".rst")
EXAMPLE_HINTS = ("examples/", "example/", "samples/", "demo/")
CI_HINTS = (".github/workflows/", ".gitlab-ci.yml", "travis.yml", "jenkinsfile", ".circleci/")
LICENSE_HINTS = ("license", "licence", "copying")

_INSTALL_PATTERNS = (
    "pip install", "pipx install", "uv add", "npm install", "npm i ", "yarn add",
    "pnpm add", "cargo install", "go install", "docker run", "make install", "brew install",
)

_CLAIM_TERMS = ("framework", "platform", "enterprise", "production-ready", "production ready",
                "scalable", "at scale", "multi-agent", "battle tested")


def _normalise(values: Iterable[str] | None) -> str:
    return " \n".join(str(value).lower() for value in (values or ()) if value)


def _area_definitions(config: Any | None) -> Mapping[str, Mapping[str, Sequence[str]]]:
    if config is None:
        return DEFAULT_AREA_TERMS
    definitions: dict[str, Mapping[str, Sequence[str]]] = {}
    for area in getattr(config.topics, "areas", ()):
        definitions[area.id] = {
            "keywords": tuple(keyword.lower() for keyword in area.keywords),
            "dependencies": tuple(dependency.lower() for dependency in area.dependencies),
        }
    return definitions or DEFAULT_AREA_TERMS


def _companions_satisfied(text: str, keyword: str) -> bool:
    companions = QUALIFIED_KEYWORDS.get(keyword)
    if not companions:
        return True
    return any(companion in text for companion in companions)


def detect_areas(
    *,
    description: str | None,
    topics: Sequence[str],
    readme_text: str | None,
    dependency_names: Sequence[str],
    manifest_names: Sequence[str] = (),
    config: Any | None = None,
) -> frozenset[str]:
    """Return the areas with centrally verified evidence (never isolated terms)."""

    description_text = (description or "").lower()
    topic_text = _normalise(topics)
    readme = (readme_text or "").lower()
    dependencies = _normalise(dependency_names)
    manifests = _normalise(manifest_names)
    detected: set[str] = set()

    for area_id, definition in _area_definitions(config).items():
        normalised_id = area_id.replace("_", "-")
        if normalised_id in {topic.replace("_", "-").lower() for topic in topics or ()}:
            detected.add(area_id)
            continue

        keyword_hits = {
            keyword
            for keyword in definition.get("keywords", ())
            if keyword in description_text or keyword in topic_text
        }
        qualified_hits = {hit for hit in keyword_hits if _companions_satisfied(description_text + " " + topic_text, hit)}
        if qualified_hits:
            detected.add(area_id)
            continue

        if any(dependency in dependencies for dependency in definition.get("dependencies", ())):
            detected.add(area_id)
            continue

        readme_hits = [
            keyword
            for keyword in definition.get("keywords", ())
            if keyword in readme and _companions_satisfied(readme, keyword)
        ]
        if len(readme_hits) >= 2:
            detected.add(area_id)

    return frozenset(area for area in detected if area in AREA_IDS)


def quality_signals(
    *,
    tree_paths: Sequence[str],
    readme_text: str | None,
    has_license: bool,
    has_ci: bool,
    manifest_names: Sequence[str] = (),
) -> tuple[str, ...]:
    """Positive evidence keys consumed by HIDDEN_GEM_SCORE_V1 quality scoring."""

    paths = [str(path).lower() for path in tree_paths or ()]
    readme = (readme_text or "").lower()
    signals: list[str] = []

    sources = [path for path in paths if path.endswith(SOURCE_EXTENSIONS)]
    if any(path.split("/")[0] in {"src", "lib", "app", "packages"} for path in paths if "/" in path):
        signals.append("structure:src")
    if len(sources) >= 3 or len({path.split("/")[0] for path in sources if "/" in path}) >= 2:
        signals.append("structure:modules")
    if len(sources) >= 2:
        signals.append("implementation:modules")
    if len(sources) >= 6:
        signals.append("implementation:depth")

    if any(any(hint in path for hint in TEST_HINTS) for path in paths):
        signals.append("tests:suite")
    if has_license or any(any(hint in path for hint in LICENSE_HINTS) for path in paths):
        signals.append("hygiene:license")
    if has_ci:
        signals.append("hygiene:ci")
    if manifest_names:
        signals.append("hygiene:manifest")

    if len(readme) >= 800 or any(path.endswith((".md", ".rst")) for path in paths[:3]):
        signals.append("docs:readme")
    if any(pattern in readme for pattern in _INSTALL_PATTERNS):
        signals.append("docs:install_instructions")
    if any(any(hint in path for hint in EXAMPLE_HINTS) for path in paths) or "## usage" in readme:
        signals.append("usability:usage")

    return tuple(dict.fromkeys(signals))


def negative_signals(
    *,
    tree_paths: Sequence[str],
    readme_text: str | None,
    description: str | None,
) -> tuple[str, ...]:
    paths = [str(path).lower() for path in tree_paths or ()]
    readme = (readme_text or "").lower()
    sources = [path for path in paths if path.endswith(SOURCE_EXTENSIONS)]
    signals: list[str] = []

    if paths and not any(any(hint in path for hint in TEST_HINTS) for path in paths):
        signals.append("no_tests")
    if not readme or len(readme) < 200:
        signals.append("no_docs")
    if "generated by" in readme or "cookiecutter" in readme:
        signals.append("generated_content")
    if paths and len([path for path in paths if path != "readme.md"]) <= 2 and len(sources) <= 1:
        signals.append("minimal_implementation")
    claim_text = " ".join([(description or "").lower(), readme[:2000]])
    if any(term in claim_text for term in _CLAIM_TERMS) and len(sources) <= 1:
        signals.append("claim_implementation_mismatch")
    return tuple(dict.fromkeys(signals))
