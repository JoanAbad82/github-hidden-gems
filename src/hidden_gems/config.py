"""Strict, fail-closed configuration loading for SPEC_V1.

Configuration is validated before any external call. Unknown keys, invalid
ranges and inconsistent frozen invariants are fatal (`FAILED_CONFIGURATION`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .models import AREA_IDS, HiddenGemScore

CONFIG_FILES: tuple[str, ...] = (
    "discovery.yml",
    "topics.yml",
    "scoring.yml",
    "limits.yml",
)

FROZEN_INVARIANTS = {
    "primary_star_limit": 499,
    "exception_star_band": (500, 2000),
    "exception_star_threshold": 80,
    "notification_threshold": 70,
    "exceptional_threshold": 85,
    "renotification_score_delta": 10,
    "normal_report_max": 5,
    "absolute_report_max": 10,
    "relationship_depth": 1,
}


class ConfigError(Exception):
    """Configuration is invalid, missing or inconsistent."""

    code = "FAILED_CONFIGURATION"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _require_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigError(f"{context} must be a mapping, got {type(value).__name__}")
    return value


def _check_keys(mapping: Mapping[str, Any], allowed: Sequence[str], context: str) -> None:
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise ConfigError(
            f"unknown key(s) in {context}: {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})"
        )
    missing = sorted(set(allowed) - set(mapping))
    if missing:
        raise ConfigError(f"missing key(s) in {context}: {', '.join(missing)}")


def _require_int(value: Any, context: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{context} must be an integer, got {value!r}")
    if minimum is not None and value < minimum:
        raise ConfigError(f"{context} must be >= {minimum}, got {value}")
    return value


def _require_number(value: Any, context: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{context} must be a number, got {value!r}")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ConfigError(f"{context} must be >= {minimum}, got {number}")
    return number


def _require_str(value: Any, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ConfigError(f"{context} must be a non-empty string, got {value!r}")
    return value


def _require_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{context} must be a boolean, got {value!r}")
    return value


def _require_str_list(value: Any, context: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ConfigError(f"{context} must be a list of strings, got {value!r}")
    items = tuple(_require_str(item, f"{context}[{i}]") for i, item in enumerate(value))
    if not allow_empty and not items:
        raise ConfigError(f"{context} must not be empty")
    return items


def _require_int_list(value: Any, context: str, *, length: int | None = None) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ConfigError(f"{context} must be a list of integers, got {value!r}")
    items = tuple(_require_int(item, f"{context}[{i}]", minimum=0) for i, item in enumerate(value))
    if length is not None and len(items) != length:
        raise ConfigError(f"{context} must have exactly {length} entries, got {len(items)}")
    return items


def _require_pair_list(value: Any, context: str) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ConfigError(f"{context} must be a list of [min, max] pairs, got {value!r}")
    pairs: list[tuple[int, int]] = []
    for i, item in enumerate(value):
        if not isinstance(item, Sequence) or isinstance(item, (str, bytes)) or len(item) != 2:
            raise ConfigError(f"{context}[{i}] must be a [min, max] pair, got {item!r}")
        low = _require_int(item[0], f"{context}[{i}].min", minimum=0)
        high = _require_int(item[1], f"{context}[{i}].max", minimum=0)
        if high < low:
            raise ConfigError(f"{context}[{i}] has max < min: {item!r}")
        pairs.append((low, high))
    if not pairs:
        raise ConfigError(f"{context} must not be empty")
    return tuple(pairs)


@dataclass(frozen=True)
class AreaConfig:
    id: str
    label: str
    weight: int
    search_terms: tuple[str, ...]
    keywords: tuple[str, ...]
    dependencies: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.id not in AREA_IDS:
            raise ConfigError(f"unknown area id: {self.id!r}")


@dataclass(frozen=True)
class TopicsConfig:
    config_version: str
    areas: tuple[AreaConfig, ...]

    @property
    def by_id(self) -> Mapping[str, AreaConfig]:
        return {area.id: area for area in self.areas}

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(area.id for area in self.areas)


@dataclass(frozen=True)
class RotatingGroup:
    id: str
    template: str
    area_pairs: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class DiscoveryConfig:
    config_version: str
    preferred_languages: tuple[str, ...]
    novelty_windows_days: tuple[int, ...]
    activity_windows_days: tuple[int, ...]
    star_bands: tuple[tuple[int, int], ...]
    exception_star_band: tuple[int, int]
    primary_star_limit: int
    query_star_bands: tuple[tuple[int, int], ...]
    query_created_within_days: int
    query_pushed_within_days: int
    results_per_query: int
    query_templates: Mapping[str, str]
    core_templates: tuple[str, ...]
    rotating_groups: tuple[RotatingGroup, ...]
    forbidden_solo_query_terms: tuple[str, ...]
    relationship_depth: int
    max_relationship_seeds: int
    relationship_sources: tuple[str, ...]


@dataclass(frozen=True)
class VisibilityBand:
    max_stars: int
    points: int


@dataclass(frozen=True)
class NoveltyBand:
    max_age_days: int
    points: int


@dataclass(frozen=True)
class ActivityRules:
    strong_recent_days: int
    strong_recent_points: int
    medium_recent_points: int
    moderate_recent_days: int
    moderate_points: int
    weak_recent_points: int
    stale_points: int
    no_evidence_points: int


@dataclass(frozen=True)
class QualityRules:
    implementation_max: int
    structure_max: int
    docs_max: int
    tests_max: int
    usability_max: int
    hygiene_max: int

    @property
    def total_max(self) -> int:
        return (
            self.implementation_max
            + self.structure_max
            + self.docs_max
            + self.tests_max
            + self.usability_max
            + self.hygiene_max
        )


@dataclass(frozen=True)
class ScoringConfig:
    config_version: str
    score_version: str
    weights: Mapping[str, int]
    visibility_bands: tuple[VisibilityBand, ...]
    novelty_bands: tuple[NoveltyBand, ...]
    intersection_points: Mapping[int, int]
    activity_rules: ActivityRules
    quality_rules: QualityRules
    preliminary_relevance_max: int
    preliminary_originality_max: int
    no_llm_originality_max: int
    notification_threshold: int
    exceptional_threshold: int
    exception_star_threshold: int
    renotification_score_delta: int
    preliminary_prune_threshold: int


@dataclass(frozen=True)
class GitHubConfig:
    config_version: str
    api_base_url: str
    api_version: str
    connect_timeout_seconds: float
    read_timeout_seconds: float
    max_retries: int
    backoff_base_seconds: float
    backoff_max_seconds: float
    rate_limit_yellow_floor: int
    rate_limit_red_floor: int
    search_rate_limit_yellow_floor: int
    search_rate_limit_red_floor: int
    per_page: int


@dataclass(frozen=True)
class LightConfig:
    config_version: str
    max_tree_items: int
    max_readme_bytes: int
    max_manifest_bytes: int
    max_readme_chars_for_hash: int


@dataclass(frozen=True)
class DeepConfig:
    config_version: str
    max_files: int
    max_file_bytes: int
    max_total_bytes: int
    max_docs_files: int
    max_test_files: int
    max_source_files: int
    max_manifest_files: int


@dataclass(frozen=True)
class LLMConfig:
    config_version: str
    enabled_default: bool
    provider: str
    model: str
    api_base_url: str
    api_key_env_var: str
    timeout_seconds: float
    max_llm_candidates_per_run: int
    max_llm_calls_per_run: int
    max_input_tokens_per_repo: int
    max_output_tokens_per_repo: int
    max_llm_budget_per_run: float
    max_retries_per_candidate: int
    cost_per_1k_input_tokens: float
    cost_per_1k_output_tokens: float


@dataclass(frozen=True)
class ReportingConfig:
    config_version: str
    normal_max: int
    absolute_max: int
    extra_positions_min_score: int
    labels: tuple[str, ...]
    exceptional_label: str
    update_label: str
    max_description_chars: int


@dataclass(frozen=True)
class StateConfig:
    config_version: str
    state_branch: str
    database_filename: str
    manifest_filename: str
    max_backups: int


@dataclass(frozen=True)
class LimitsConfig:
    config_version: str
    run_budgets: Mapping[str, int]
    github: GitHubConfig
    light: LightConfig
    deep: DeepConfig
    llm: LLMConfig


@dataclass(frozen=True)
class AppConfig:
    root: Path
    config_version: str
    discovery: DiscoveryConfig
    topics: TopicsConfig
    scoring: ScoringConfig
    limits: LimitsConfig
    reporting: ReportingConfig
    state: StateConfig
    github: GitHubConfig
    light: LightConfig
    deep: DeepConfig
    llm: LLMConfig

    @property
    def area_ids(self) -> tuple[str, ...]:
        return self.topics.ids

    @property
    def budgets(self) -> Mapping[str, int]:
        return self.limits.run_budgets


def _load_yaml(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise ConfigError(f"missing configuration file: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise ConfigError(f"invalid YAML in {path.name}: {exc}") from exc
    if raw is None:
        raise ConfigError(f"empty configuration file: {path.name}")
    return _require_mapping(raw, path.name)


def _parse_topics(raw: Mapping[str, Any], version: str) -> TopicsConfig:
    _check_keys(raw, ("config_version", "areas"), "topics.yml")
    areas_raw = raw["areas"]
    if not isinstance(areas_raw, Sequence) or isinstance(areas_raw, (str, bytes)):
        raise ConfigError("topics.yml: areas must be a list")
    areas: list[AreaConfig] = []
    allowed_area_keys = ("id", "label", "weight", "search_terms", "keywords", "dependencies")
    for index, item in enumerate(areas_raw):
        mapping = _require_mapping(item, f"topics.yml areas[{index}]")
        _check_keys(mapping, allowed_area_keys, f"topics.yml areas[{index}]")
        areas.append(
            AreaConfig(
                id=_require_str(mapping["id"], f"areas[{index}].id"),
                label=_require_str(mapping["label"], f"areas[{index}].label"),
                weight=_require_int(mapping["weight"], f"areas[{index}].weight", minimum=1),
                search_terms=_require_str_list(mapping["search_terms"], f"areas[{index}].search_terms"),
                keywords=_require_str_list(mapping["keywords"], f"areas[{index}].keywords"),
                dependencies=_require_str_list(mapping["dependencies"], f"areas[{index}].dependencies"),
            )
        )
    return TopicsConfig(config_version=version, areas=tuple(areas))


def _parse_discovery(raw: Mapping[str, Any], version: str) -> DiscoveryConfig:
    allowed = (
        "config_version",
        "preferred_languages",
        "novelty_windows_days",
        "activity_windows_days",
        "star_bands",
        "exception_star_band",
        "primary_star_limit",
        "query_star_bands",
        "query_created_within_days",
        "query_pushed_within_days",
        "results_per_query",
        "query_templates",
        "core_templates",
        "rotating_groups",
        "forbidden_solo_query_terms",
        "relationship_depth",
        "max_relationship_seeds",
        "relationship_sources",
    )
    _check_keys(raw, allowed, "discovery.yml")

    templates_raw = _require_mapping(raw["query_templates"], "discovery.yml query_templates")
    template_names = ("new_repository", "recently_active", "topic_search", "intersection")
    _check_keys(templates_raw, template_names, "discovery.yml query_templates")
    templates = {name: _require_str(templates_raw[name], f"query_templates.{name}") for name in template_names}
    for name, template in templates.items():
        if "{term}" not in template and "{term_a}" not in template:
            raise ConfigError(f"query_templates.{name} must reference a search term placeholder")

    core_templates = _require_str_list(raw["core_templates"], "discovery.yml core_templates")
    for name in core_templates:
        if name not in templates:
            raise ConfigError(f"core_templates references unknown template {name!r}")

    groups_raw = raw["rotating_groups"]
    if not isinstance(groups_raw, Sequence) or isinstance(groups_raw, (str, bytes)) or not groups_raw:
        raise ConfigError("discovery.yml rotating_groups must be a non-empty list")
    groups: list[RotatingGroup] = []
    for index, item in enumerate(groups_raw):
        mapping = _require_mapping(item, f"rotating_groups[{index}]")
        _check_keys(mapping, ("id", "template", "area_pairs"), f"rotating_groups[{index}]")
        template = _require_str(mapping["template"], f"rotating_groups[{index}].template")
        if template not in templates:
            raise ConfigError(f"rotating_groups[{index}] references unknown template {template!r}")
        pairs_raw = mapping["area_pairs"]
        if not isinstance(pairs_raw, Sequence) or isinstance(pairs_raw, (str, bytes)) or not pairs_raw:
            raise ConfigError(f"rotating_groups[{index}].area_pairs must be a non-empty list")
        pairs: list[tuple[str, str]] = []
        for pair_index, pair in enumerate(pairs_raw):
            if not isinstance(pair, Sequence) or isinstance(pair, (str, bytes)) or len(pair) != 2:
                raise ConfigError(f"rotating_groups[{index}].area_pairs[{pair_index}] must be a pair of area ids")
            first = _require_str(pair[0], f"rotating_groups[{index}].area_pairs[{pair_index}][0]")
            second = _require_str(pair[1], f"rotating_groups[{index}].area_pairs[{pair_index}][1]")
            if first == second:
                raise ConfigError(f"rotating_groups[{index}].area_pairs[{pair_index}] repeats area {first!r}")
            pairs.append((first, second))
        groups.append(
            RotatingGroup(
                id=_require_str(mapping["id"], f"rotating_groups[{index}].id"),
                template=template,
                area_pairs=tuple(pairs),
            )
        )

    return DiscoveryConfig(
        config_version=version,
        preferred_languages=_require_str_list(raw["preferred_languages"], "discovery.yml preferred_languages"),
        novelty_windows_days=_require_int_list(raw["novelty_windows_days"], "discovery.yml novelty_windows_days"),
        activity_windows_days=_require_int_list(raw["activity_windows_days"], "discovery.yml activity_windows_days"),
        star_bands=_require_pair_list(raw["star_bands"], "discovery.yml star_bands"),
        exception_star_band=tuple(  # type: ignore[arg-type]
            _require_int_list(raw["exception_star_band"], "discovery.yml exception_star_band", length=2)
        ),
        primary_star_limit=_require_int(raw["primary_star_limit"], "discovery.yml primary_star_limit", minimum=1),
        query_star_bands=_require_pair_list(raw["query_star_bands"], "discovery.yml query_star_bands"),
        query_created_within_days=_require_int(
            raw["query_created_within_days"], "discovery.yml query_created_within_days", minimum=1
        ),
        query_pushed_within_days=_require_int(
            raw["query_pushed_within_days"], "discovery.yml query_pushed_within_days", minimum=1
        ),
        results_per_query=_require_int(raw["results_per_query"], "discovery.yml results_per_query", minimum=1),
        query_templates=templates,
        core_templates=core_templates,
        rotating_groups=tuple(groups),
        forbidden_solo_query_terms=_require_str_list(
            raw["forbidden_solo_query_terms"], "discovery.yml forbidden_solo_query_terms", allow_empty=True
        ),
        relationship_depth=_require_int(raw["relationship_depth"], "discovery.yml relationship_depth", minimum=1),
        max_relationship_seeds=_require_int(
            raw["max_relationship_seeds"], "discovery.yml max_relationship_seeds", minimum=1
        ),
        relationship_sources=_require_str_list(raw["relationship_sources"], "discovery.yml relationship_sources"),
    )


def _parse_scoring(raw: Mapping[str, Any], version: str) -> ScoringConfig:
    allowed = (
        "config_version",
        "score_version",
        "weights",
        "visibility_bands",
        "novelty_bands",
        "intersection_points",
        "activity_rules",
        "quality_rules",
        "preliminary_relevance_max",
        "preliminary_originality_max",
        "no_llm_originality_max",
        "notification_threshold",
        "exceptional_threshold",
        "exception_star_threshold",
        "renotification_score_delta",
        "preliminary_prune_threshold",
    )
    _check_keys(raw, allowed, "scoring.yml")

    weights_raw = _require_mapping(raw["weights"], "scoring.yml weights")
    _check_keys(weights_raw, tuple(HiddenGemScore.DIMENSIONS), "scoring.yml weights")
    weights = {dim: _require_int(weights_raw[dim], f"weights.{dim}", minimum=0) for dim in HiddenGemScore.DIMENSIONS}

    visibility: list[VisibilityBand] = []
    for index, item in enumerate(_require_list(raw["visibility_bands"], "scoring.yml visibility_bands")):
        mapping = _require_mapping(item, f"visibility_bands[{index}]")
        _check_keys(mapping, ("max_stars", "points"), f"visibility_bands[{index}]")
        visibility.append(
            VisibilityBand(
                max_stars=_require_int(mapping["max_stars"], f"visibility_bands[{index}].max_stars", minimum=0),
                points=_require_int(mapping["points"], f"visibility_bands[{index}].points", minimum=0),
            )
        )

    novelty: list[NoveltyBand] = []
    for index, item in enumerate(_require_list(raw["novelty_bands"], "scoring.yml novelty_bands")):
        mapping = _require_mapping(item, f"novelty_bands[{index}]")
        _check_keys(mapping, ("max_age_days", "points"), f"novelty_bands[{index}]")
        novelty.append(
            NoveltyBand(
                max_age_days=_require_int(mapping["max_age_days"], f"novelty_bands[{index}].max_age_days", minimum=0),
                points=_require_int(mapping["points"], f"novelty_bands[{index}].points", minimum=0),
            )
        )

    intersection_raw = _require_mapping(raw["intersection_points"], "scoring.yml intersection_points")
    _check_keys(intersection_raw, ("1", "2", "3", "4"), "scoring.yml intersection_points")
    intersection = {
        int(key): _require_int(value, f"intersection_points.{key}", minimum=0) for key, value in intersection_raw.items()
    }

    activity_raw = _require_mapping(raw["activity_rules"], "scoring.yml activity_rules")
    activity_keys = (
        "strong_recent_days",
        "strong_recent_points",
        "medium_recent_points",
        "moderate_recent_days",
        "moderate_points",
        "weak_recent_points",
        "stale_points",
        "no_evidence_points",
    )
    _check_keys(activity_raw, activity_keys, "scoring.yml activity_rules")
    activity = ActivityRules(
        **{key: _require_int(activity_raw[key], f"activity_rules.{key}", minimum=0) for key in activity_keys}
    )

    quality_raw = _require_mapping(raw["quality_rules"], "scoring.yml quality_rules")
    quality_keys = (
        "implementation_max",
        "structure_max",
        "docs_max",
        "tests_max",
        "usability_max",
        "hygiene_max",
    )
    _check_keys(quality_raw, quality_keys, "scoring.yml quality_rules")
    quality = QualityRules(
        **{key: _require_int(quality_raw[key], f"quality_rules.{key}", minimum=0) for key in quality_keys}
    )

    return ScoringConfig(
        config_version=version,
        score_version=_require_str(raw["score_version"], "scoring.yml score_version"),
        weights=weights,
        visibility_bands=tuple(visibility),
        novelty_bands=tuple(novelty),
        intersection_points=intersection,
        activity_rules=activity,
        quality_rules=quality,
        preliminary_relevance_max=_require_int(
            raw["preliminary_relevance_max"], "scoring.yml preliminary_relevance_max", minimum=0
        ),
        preliminary_originality_max=_require_int(
            raw["preliminary_originality_max"], "scoring.yml preliminary_originality_max", minimum=0
        ),
        no_llm_originality_max=_require_int(
            raw["no_llm_originality_max"], "scoring.yml no_llm_originality_max", minimum=0
        ),
        notification_threshold=_require_int(
            raw["notification_threshold"], "scoring.yml notification_threshold", minimum=0
        ),
        exceptional_threshold=_require_int(
            raw["exceptional_threshold"], "scoring.yml exceptional_threshold", minimum=0
        ),
        exception_star_threshold=_require_int(
            raw["exception_star_threshold"], "scoring.yml exception_star_threshold", minimum=0
        ),
        renotification_score_delta=_require_int(
            raw["renotification_score_delta"], "scoring.yml renotification_score_delta", minimum=1
        ),
        preliminary_prune_threshold=_require_int(
            raw["preliminary_prune_threshold"], "scoring.yml preliminary_prune_threshold", minimum=0
        ),
    )


def _require_list(value: Any, context: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise ConfigError(f"{context} must be a non-empty list, got {value!r}")
    return value


def _parse_limits(raw: Mapping[str, Any]) -> tuple[LimitsConfig, ReportingConfig, StateConfig, str]:
    _check_keys(raw, ("config_version", "run_budgets", "github", "light_analysis", "deep_analysis", "llm", "reporting", "state"), "limits.yml")
    version = _require_str(raw["config_version"], "limits.yml config_version")

    budget_raw = _require_mapping(raw["run_budgets"], "limits.yml run_budgets")
    budget_keys = ("max_raw_candidates", "max_light_analysis", "max_relationship_seeds", "max_deep_analysis")
    _check_keys(budget_raw, budget_keys, "limits.yml run_budgets")
    budgets = {key: _require_int(budget_raw[key], f"run_budgets.{key}", minimum=1) for key in budget_keys}

    github_raw = _require_mapping(raw["github"], "limits.yml github")
    github_keys = (
        "api_base_url",
        "api_version",
        "connect_timeout_seconds",
        "read_timeout_seconds",
        "max_retries",
        "backoff_base_seconds",
        "backoff_max_seconds",
        "rate_limit_yellow_floor",
        "rate_limit_red_floor",
        "search_rate_limit_yellow_floor",
        "search_rate_limit_red_floor",
        "per_page",
    )
    _check_keys(github_raw, github_keys, "limits.yml github")
    github = GitHubConfig(
        config_version=version,
        api_base_url=_require_str(github_raw["api_base_url"], "github.api_base_url"),
        api_version=_require_str(github_raw["api_version"], "github.api_version"),
        connect_timeout_seconds=_require_number(
            github_raw["connect_timeout_seconds"], "github.connect_timeout_seconds", minimum=1
        ),
        read_timeout_seconds=_require_number(
            github_raw["read_timeout_seconds"], "github.read_timeout_seconds", minimum=1
        ),
        max_retries=_require_int(github_raw["max_retries"], "github.max_retries", minimum=0),
        backoff_base_seconds=_require_number(github_raw["backoff_base_seconds"], "github.backoff_base_seconds", minimum=0),
        backoff_max_seconds=_require_number(github_raw["backoff_max_seconds"], "github.backoff_max_seconds", minimum=0),
        rate_limit_yellow_floor=_require_int(
            github_raw["rate_limit_yellow_floor"], "github.rate_limit_yellow_floor", minimum=0
        ),
        rate_limit_red_floor=_require_int(github_raw["rate_limit_red_floor"], "github.rate_limit_red_floor", minimum=0),
        search_rate_limit_yellow_floor=_require_int(
            github_raw["search_rate_limit_yellow_floor"], "github.search_rate_limit_yellow_floor", minimum=0
        ),
        search_rate_limit_red_floor=_require_int(
            github_raw["search_rate_limit_red_floor"], "github.search_rate_limit_red_floor", minimum=0
        ),
        per_page=_require_int(github_raw["per_page"], "github.per_page", minimum=1),
    )

    light_raw = _require_mapping(raw["light_analysis"], "limits.yml light_analysis")
    light_keys = ("max_tree_items", "max_readme_bytes", "max_manifest_bytes", "max_readme_chars_for_hash")
    _check_keys(light_raw, light_keys, "limits.yml light_analysis")
    light = LightConfig(
        config_version=version,
        **{key: _require_int(light_raw[key], f"light_analysis.{key}", minimum=1) for key in light_keys},
    )

    deep_raw = _require_mapping(raw["deep_analysis"], "limits.yml deep_analysis")
    deep_keys = (
        "max_files",
        "max_file_bytes",
        "max_total_bytes",
        "max_docs_files",
        "max_test_files",
        "max_source_files",
        "max_manifest_files",
    )
    _check_keys(deep_raw, deep_keys, "limits.yml deep_analysis")
    deep = DeepConfig(
        config_version=version,
        **{key: _require_int(deep_raw[key], f"deep_analysis.{key}", minimum=1) for key in deep_keys},
    )

    llm_raw = _require_mapping(raw["llm"], "limits.yml llm")
    llm_keys = (
        "enabled_default",
        "provider",
        "model",
        "api_base_url",
        "api_key_env_var",
        "timeout_seconds",
        "max_llm_candidates_per_run",
        "max_llm_calls_per_run",
        "max_input_tokens_per_repo",
        "max_output_tokens_per_repo",
        "max_llm_budget_per_run",
        "max_retries_per_candidate",
        "cost_per_1k_input_tokens",
        "cost_per_1k_output_tokens",
    )
    _check_keys(llm_raw, llm_keys, "limits.yml llm")
    llm = LLMConfig(
        config_version=version,
        enabled_default=_require_bool(llm_raw["enabled_default"], "llm.enabled_default"),
        provider=_require_str(llm_raw["provider"], "llm.provider"),
        model=_require_str(llm_raw["model"], "llm.model"),
        api_base_url=_require_str(llm_raw["api_base_url"], "llm.api_base_url"),
        api_key_env_var=_require_str(llm_raw["api_key_env_var"], "llm.api_key_env_var"),
        timeout_seconds=_require_number(llm_raw["timeout_seconds"], "llm.timeout_seconds", minimum=1),
        max_llm_candidates_per_run=_require_int(
            llm_raw["max_llm_candidates_per_run"], "llm.max_llm_candidates_per_run", minimum=0
        ),
        max_llm_calls_per_run=_require_int(
            llm_raw["max_llm_calls_per_run"], "llm.max_llm_calls_per_run", minimum=0
        ),
        max_input_tokens_per_repo=_require_int(
            llm_raw["max_input_tokens_per_repo"], "llm.max_input_tokens_per_repo", minimum=1
        ),
        max_output_tokens_per_repo=_require_int(
            llm_raw["max_output_tokens_per_repo"], "llm.max_output_tokens_per_repo", minimum=1
        ),
        max_llm_budget_per_run=_require_number(
            llm_raw["max_llm_budget_per_run"], "llm.max_llm_budget_per_run", minimum=0
        ),
        max_retries_per_candidate=_require_int(
            llm_raw["max_retries_per_candidate"], "llm.max_retries_per_candidate", minimum=0
        ),
        cost_per_1k_input_tokens=_require_number(
            llm_raw["cost_per_1k_input_tokens"], "llm.cost_per_1k_input_tokens", minimum=0
        ),
        cost_per_1k_output_tokens=_require_number(
            llm_raw["cost_per_1k_output_tokens"], "llm.cost_per_1k_output_tokens", minimum=0
        ),
    )

    reporting_raw = _require_mapping(raw["reporting"], "limits.yml reporting")
    reporting_keys = (
        "normal_max",
        "absolute_max",
        "extra_positions_min_score",
        "labels",
        "exceptional_label",
        "update_label",
        "max_description_chars",
    )
    _check_keys(reporting_raw, reporting_keys, "limits.yml reporting")
    reporting = ReportingConfig(
        config_version=version,
        normal_max=_require_int(reporting_raw["normal_max"], "reporting.normal_max", minimum=1),
        absolute_max=_require_int(reporting_raw["absolute_max"], "reporting.absolute_max", minimum=1),
        extra_positions_min_score=_require_int(
            reporting_raw["extra_positions_min_score"], "reporting.extra_positions_min_score", minimum=0
        ),
        labels=_require_str_list(reporting_raw["labels"], "reporting.labels"),
        exceptional_label=_require_str(reporting_raw["exceptional_label"], "reporting.exceptional_label"),
        update_label=_require_str(reporting_raw["update_label"], "reporting.update_label"),
        max_description_chars=_require_int(
            reporting_raw["max_description_chars"], "reporting.max_description_chars", minimum=1
        ),
    )

    state_raw = _require_mapping(raw["state"], "limits.yml state")
    state_keys = ("state_branch", "database_filename", "manifest_filename", "max_backups")
    _check_keys(state_raw, state_keys, "limits.yml state")
    state = StateConfig(
        config_version=version,
        state_branch=_require_str(state_raw["state_branch"], "state.state_branch"),
        database_filename=_require_str(state_raw["database_filename"], "state.database_filename"),
        manifest_filename=_require_str(state_raw["manifest_filename"], "state.manifest_filename"),
        max_backups=_require_int(state_raw["max_backups"], "state.max_backups", minimum=1),
    )

    limits = LimitsConfig(
        config_version=version,
        run_budgets=budgets,
        github=github,
        light=light,
        deep=deep,
        llm=llm,
    )
    return limits, reporting, state, version


def load_config(root: Path | str) -> AppConfig:
    """Load and validate the canonical V1 configuration tree."""

    root_path = Path(root).resolve()
    config_dir = root_path / "config"
    if not config_dir.is_dir():
        raise ConfigError(f"missing config directory: {config_dir}")

    raw = {name: _load_yaml(config_dir / name) for name in CONFIG_FILES}
    versions = {
        name: _require_str(payload.get("config_version"), f"{name} config_version") for name, payload in raw.items()
    }
    unique_versions = set(versions.values())
    if len(unique_versions) != 1:
        raise ConfigError(f"config_version mismatch across configuration files: {versions}")
    version = next(iter(unique_versions))

    topics = _parse_topics(raw["topics.yml"], version)
    discovery = _parse_discovery(raw["discovery.yml"], version)
    scoring = _parse_scoring(raw["scoring.yml"], version)
    limits, reporting, state, _ = _parse_limits(raw["limits.yml"])

    config = AppConfig(
        root=root_path,
        config_version=version,
        discovery=discovery,
        topics=topics,
        scoring=scoring,
        limits=limits,
        reporting=reporting,
        state=state,
        github=limits.github,
        light=limits.light,
        deep=limits.deep,
        llm=limits.llm,
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    """Cross-file validation of the frozen V1 invariants. Never touches the network."""

    scoring = config.scoring
    if set(scoring.weights) != set(HiddenGemScore.DIMENSIONS):
        raise ConfigError("scoring weights must cover exactly the seven HiddenGemScore dimensions")
    if sum(scoring.weights.values()) != 100:
        raise ConfigError(f"scoring weights must sum to 100, got {sum(scoring.weights.values())}")
    for dimension, maximum in HiddenGemScore.MAXIMA.items():
        if scoring.weights[dimension] != maximum:
            raise ConfigError(
                f"scoring weight for {dimension} must be {maximum} (SPEC_V1), got {scoring.weights[dimension]}"
            )

    if not scoring.visibility_bands:
        raise ConfigError("scoring.visibility_bands must not be empty")
    previous = -1
    for band in scoring.visibility_bands:
        if band.max_stars <= previous:
            raise ConfigError("scoring.visibility_bands must be strictly increasing by max_stars")
        previous = band.max_stars
    if scoring.visibility_bands[0].points <= scoring.visibility_bands[-1].points:
        raise ConfigError("visibility points must decrease as visibility grows")

    previous_age = -1
    for band in scoring.novelty_bands:
        if band.max_age_days <= previous_age:
            raise ConfigError("scoring.novelty_bands must be strictly increasing by max_age_days")
        previous_age = band.max_age_days

    if scoring.intersection_points != {1: 0, 2: 2, 3: 4, 4: 5}:
        raise ConfigError(f"intersection_points must be {{1:0, 2:2, 3:4, 4:5}}, got {scoring.intersection_points}")

    if not 0 < scoring.notification_threshold < scoring.exceptional_threshold <= 100:
        raise ConfigError("scoring thresholds must satisfy 0 < notification < exceptional <= 100")
    if scoring.exception_star_threshold < scoring.notification_threshold:
        raise ConfigError("exception_star_threshold must be >= notification_threshold")
    if scoring.preliminary_prune_threshold > scoring.notification_threshold:
        raise ConfigError("preliminary_prune_threshold must not exceed notification_threshold")
    if scoring.quality_rules.total_max != HiddenGemScore.MAXIMA["quality"]:
        raise ConfigError(
            f"quality rules must total {HiddenGemScore.MAXIMA['quality']}, got {scoring.quality_rules.total_max}"
        )
    if scoring.activity_rules.strong_recent_points > HiddenGemScore.MAXIMA["activity"]:
        raise ConfigError("activity rules exceed the activity maximum")

    if config.discovery.relationship_depth != FROZEN_INVARIANTS["relationship_depth"]:
        raise ConfigError("relationship_depth must be exactly 1 in V1")
    if config.discovery.primary_star_limit != FROZEN_INVARIANTS["primary_star_limit"]:
        raise ConfigError("primary_star_limit must be 499 in V1")
    if tuple(config.discovery.exception_star_band) != FROZEN_INVARIANTS["exception_star_band"]:
        raise ConfigError("exception_star_band must be (500, 2000) in V1")

    if config.reporting.normal_max > config.reporting.absolute_max:
        raise ConfigError("reporting.normal_max must not exceed reporting.absolute_max")
    if config.reporting.absolute_max > FROZEN_INVARIANTS["absolute_report_max"]:
        raise ConfigError("reporting.absolute_max must not exceed 10")
    if config.reporting.normal_max != FROZEN_INVARIANTS["normal_report_max"]:
        raise ConfigError("reporting.normal_max must be 5 in V1")
    if config.reporting.absolute_max != FROZEN_INVARIANTS["absolute_report_max"]:
        raise ConfigError("reporting.absolute_max must be 10 in V1")
    if config.reporting.extra_positions_min_score != FROZEN_INVARIANTS["exceptional_threshold"]:
        raise ConfigError("reporting.extra_positions_min_score must be 85 in V1")

    if len(config.topics.areas) != len(AREA_IDS):
        raise ConfigError(f"topics must define exactly {len(AREA_IDS)} areas")
    if set(config.topics.ids) != set(AREA_IDS):
        raise ConfigError(f"topics areas must be exactly {list(AREA_IDS)}, got {list(config.topics.ids)}")
    if len(set(area.weight for area in config.topics.areas)) != 1:
        raise ConfigError("all four areas must carry equal base weight")

    known_areas = set(config.topics.ids)
    for group in config.discovery.rotating_groups:
        for first, second in group.area_pairs:
            if first not in known_areas or second not in known_areas:
                raise ConfigError(f"rotating group {group.id} references unknown area(s): {first}, {second}")

    if config.limits.run_budgets["max_deep_analysis"] > config.limits.run_budgets["max_light_analysis"]:
        raise ConfigError("max_deep_analysis must not exceed max_light_analysis")
    if config.limits.llm.max_llm_calls_per_run < config.limits.llm.max_llm_candidates_per_run:
        raise ConfigError("max_llm_calls_per_run must be >= max_llm_candidates_per_run")

    for language in config.discovery.preferred_languages:
        if not language.strip():
            raise ConfigError("preferred_languages must not contain blank entries")


def resolve_llm_enabled(config: AppConfig, env: Mapping[str, str] | None = None) -> bool:
    """LLM_ENABLED env var wins over the config default; the pipeline works with it false."""

    environment = os.environ if env is None else env
    raw = environment.get("LLM_ENABLED")
    if raw is None or str(raw).strip() == "":
        return bool(config.llm.enabled_default)
    value = str(raw).strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"LLM_ENABLED must be a boolean, got {raw!r}")
