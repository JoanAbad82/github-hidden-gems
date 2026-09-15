"""HIDDEN_GEM_SCORE_V1.

Every function is pure and deterministic for fixed evidence and
configuration: no network, no SQLite, no implicit clock except the explicit
`as_of` argument.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Collection, Mapping, Sequence

from ..common.time import age_days, ensure_utc, utcnow
from ..config import (
    ActivityRules,
    AppConfig,
    NoveltyBand,
    QualityRules,
    ScoringConfig,
    VisibilityBand,
)
from ..models import AREA_IDS, DeepAnalysis, HiddenGemScore, LightAnalysis

PRIMARY_STAR_LIMIT = 499
EXCEPTION_STAR_MIN = 500
EXCEPTION_STAR_MAX = 2000
NOTIFICATION_THRESHOLD = 70
EXCEPTION_STAR_THRESHOLD = 80
EXCEPTIONAL_THRESHOLD = 85
RENOTIFICATION_SCORE_DELTA = 10

#: Relevance cap derived from the number of centrally verified areas.
RELEVANCE_CAP_BY_AREA_COUNT: Mapping[int, int] = {0: 0, 1: 12, 2: 15, 3: 18, 4: 20}

#: Preliminary (pre-LLM) relevance base by area count; never above 14.
RELEVANCE_BASE_BY_AREA_COUNT: Mapping[int, int] = {0: 0, 1: 8, 2: 11, 3: 13, 4: 14}

_DEFAULT_VISIBILITY_BANDS = (
    VisibilityBand(24, 15),
    VisibilityBand(99, 13),
    VisibilityBand(249, 10),
    VisibilityBand(499, 7),
    VisibilityBand(999, 4),
    VisibilityBand(1499, 3),
    VisibilityBand(2000, 1),
)

_DEFAULT_NOVELTY_BANDS = (
    NoveltyBand(15, 10),
    NoveltyBand(30, 9),
    NoveltyBand(60, 7),
    NoveltyBand(90, 5),
    NoveltyBand(180, 2),
)

_DEFAULT_ACTIVITY_RULES = ActivityRules(
    strong_recent_days=15,
    strong_recent_points=20,
    medium_recent_points=16,
    moderate_recent_days=30,
    moderate_points=12,
    weak_recent_points=7,
    stale_points=2,
    no_evidence_points=0,
)

_DEFAULT_QUALITY_RULES = QualityRules(
    implementation_max=6,
    structure_max=4,
    docs_max=4,
    tests_max=3,
    usability_max=2,
    hygiene_max=1,
)

#: signal prefix -> (points per distinct signal, cap)
QUALITY_SIGNAL_RULES: Mapping[str, tuple[int, int]] = {
    "implementation": (3, 6),
    "structure": (2, 4),
    "docs": (1, 4),
    "tests": (1, 3),
    "usability": (1, 2),
    "hygiene": (1, 1),
}

#: negative signal -> penalty
QUALITY_PENALTIES: Mapping[str, int] = {
    "claim_implementation_mismatch": 3,
    "minimal_implementation": 2,
    "no_tests": 2,
    "no_docs": 1,
    "no_license": 1,
    "generated_content": 1,
}

_DEFAULT_QUALITY_PENALTY = 1


def _scoring_config(config: AppConfig | ScoringConfig | None) -> ScoringConfig | None:
    if config is None:
        return None
    if isinstance(config, AppConfig):
        return config.scoring
    if isinstance(config, ScoringConfig):
        return config
    raise TypeError(f"unsupported configuration type: {type(config).__name__}")


def _visibility_bands(config: AppConfig | ScoringConfig | None) -> Sequence[VisibilityBand]:
    scoring = _scoring_config(config)
    return scoring.visibility_bands if scoring else _DEFAULT_VISIBILITY_BANDS


def _novelty_bands(config: AppConfig | ScoringConfig | None) -> Sequence[NoveltyBand]:
    scoring = _scoring_config(config)
    return scoring.novelty_bands if scoring else _DEFAULT_NOVELTY_BANDS


def _activity_rules(config: AppConfig | ScoringConfig | None) -> ActivityRules:
    scoring = _scoring_config(config)
    return scoring.activity_rules if scoring else _DEFAULT_ACTIVITY_RULES


def _quality_rules(config: AppConfig | ScoringConfig | None) -> QualityRules:
    scoring = _scoring_config(config)
    return scoring.quality_rules if scoring else _DEFAULT_QUALITY_RULES


def score_visibility(stars: int, *, config: AppConfig | ScoringConfig | None = None) -> int:
    """SPEC_V1 visibility bands. More than 2,000 stars scores 0 and is not notifiable."""

    if stars is None:
        return 0
    value = max(0, int(stars))
    for band in _visibility_bands(config):
        if value <= band.max_stars:
            return band.points
    return 0


def score_novelty(age_days_value: int, *, config: AppConfig | ScoringConfig | None = None) -> int:
    """SPEC_V1 novelty bands by repository age in days."""

    if age_days_value is None:
        return 0
    value = max(0, int(age_days_value))
    for band in _novelty_bands(config):
        if value <= band.max_age_days:
            return band.points
    return 0


def score_activity(
    activity_level: str,
    relevant_activity_age_days: int | None,
    *,
    config: AppConfig | ScoringConfig | None = None,
) -> int:
    """Activity points derived from the activity level plus the age of the relevant activity."""

    rules = _activity_rules(config)
    level = (activity_level or "UNKNOWN").upper()
    if level == "UNKNOWN":
        return rules.no_evidence_points
    if relevant_activity_age_days is None:
        if level == "STRONG":
            return rules.strong_recent_points
        if level == "MEDIUM":
            return rules.medium_recent_points
        if level == "WEAK":
            return rules.weak_recent_points
        return rules.stale_points

    age = max(0, int(relevant_activity_age_days))
    if age <= rules.strong_recent_days:
        if level == "STRONG":
            return rules.strong_recent_points
        if level == "MEDIUM":
            return rules.medium_recent_points
        if level == "WEAK":
            return rules.weak_recent_points
        return rules.stale_points
    if age <= rules.moderate_recent_days:
        if level in ("STRONG", "MEDIUM"):
            return rules.moderate_points
        if level == "WEAK":
            return rules.weak_recent_points
        return rules.stale_points
    if level == "WEAK":
        return rules.stale_points
    return rules.stale_points


def _signal_prefix(signal: str) -> str:
    return signal.split(":", 1)[0].strip().lower()


def _distinct_signals(signals: Sequence[str]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for signal in signals or ():
        prefix = _signal_prefix(str(signal))
        detail = str(signal)
        grouped.setdefault(prefix, set()).add(detail)
    return grouped


def score_quality(
    quality_signals: Sequence[str],
    negative_signals: Sequence[str] = (),
    *,
    deep: DeepAnalysis | None = None,
    config: AppConfig | ScoringConfig | None = None,
) -> int:
    """Quality sub-score (0..20) derived only from recorded evidence keys."""

    rules = _quality_rules(config)
    totals = {
        "implementation": rules.implementation_max,
        "structure": rules.structure_max,
        "docs": rules.docs_max,
        "tests": rules.tests_max,
        "usability": rules.usability_max,
        "hygiene": rules.hygiene_max,
    }
    grouped = _distinct_signals(quality_signals)
    points = 0
    for prefix, (per_signal, cap) in QUALITY_SIGNAL_RULES.items():
        observed = len(grouped.get(prefix, ()))
        if observed:
            points += min(cap, observed * per_signal)

    bonus = 0
    if deep is not None and deep.status == "OK" and deep.confidence == "HIGH":
        evidence = deep.evidence or {}
        if evidence.get("claim_implementation_consistent") is True:
            bonus += 2
        modules = evidence.get("core_modules_observed")
        if isinstance(modules, int) and modules >= 2:
            bonus += 2
    points += min(4, bonus)

    for signal in negative_signals or ():
        points -= QUALITY_PENALTIES.get(_signal_prefix(str(signal)), _DEFAULT_QUALITY_PENALTY)

    return max(0, min(sum(totals.values()), points))


def score_intersection(
    areas: Collection[str], *, config: AppConfig | ScoringConfig | None = None
) -> int:
    """Functional thematic intersection points by number of distinct areas."""

    scoring = _scoring_config(config)
    distinct = {area for area in (areas or ()) if area in AREA_IDS}
    table = scoring.intersection_points if scoring else {1: 0, 2: 2, 3: 4, 4: 5}
    return int(table.get(len(distinct), 0))


def required_notification_threshold(
    stars: int, *, config: AppConfig | ScoringConfig | None = None
) -> int | None:
    """70 for <=499 stars, 80 for the 500..2000 exception range, None above it."""

    scoring = _scoring_config(config)
    normal = scoring.notification_threshold if scoring else NOTIFICATION_THRESHOLD
    exception = scoring.exception_star_threshold if scoring else EXCEPTION_STAR_THRESHOLD
    value = int(stars or 0)
    if value <= PRIMARY_STAR_LIMIT:
        return normal
    if value <= EXCEPTION_STAR_MAX:
        return exception
    return None


def _verified_areas(light: LightAnalysis) -> frozenset[str]:
    return frozenset(area for area in light.detected_areas if area in AREA_IDS)


def _relevance_evidence(light: LightAnalysis, metadata: Mapping[str, Any]) -> Sequence[str]:
    evidence = metadata.get("relevance_evidence")
    if evidence:
        return tuple(str(item) for item in evidence)
    areas = sorted(_verified_areas(light))
    return tuple(f"area:{area}" for area in areas)


def _originality_evidence(metadata: Mapping[str, Any]) -> Sequence[str]:
    evidence = metadata.get("originality_evidence") or ()
    return tuple(str(item) for item in evidence)


def _relevant_activity_age_days(
    light: LightAnalysis, metadata: Mapping[str, Any], as_of: datetime
) -> int | None:
    explicit = metadata.get("relevant_activity_age_days")
    if explicit is not None:
        return max(0, int(explicit))
    if light.latest_relevant_activity_at is not None:
        return age_days(light.latest_relevant_activity_at, as_of=as_of)
    return None


def _confidence(
    light: LightAnalysis, deep: DeepAnalysis | None, verified_area_count: int
) -> str:
    strong_evidence = (verified_area_count >= 1 and len(light.quality_signals) >= 3) or verified_area_count >= 2
    deep_confidence = deep.confidence if deep is not None and deep.status == "OK" else None
    if deep_confidence == "HIGH" and strong_evidence:
        return "HIGH"
    if deep_confidence in ("HIGH", "MEDIUM") and (strong_evidence or verified_area_count >= 1):
        return "MEDIUM"
    if strong_evidence:
        return "MEDIUM"
    return "LOW"


def compute_final_score(
    light: LightAnalysis,
    deep: DeepAnalysis | None,
    metadata: Mapping[str, Any],
    *,
    config: AppConfig | ScoringConfig | None = None,
    as_of: datetime | None = None,
) -> HiddenGemScore:
    """Final HIDDEN_GEM_SCORE_V1 for one repository."""

    scoring = _scoring_config(config)
    moment = ensure_utc(as_of) if as_of is not None else utcnow()
    stars = int(metadata.get("stars", 0) or 0)
    created_at = metadata.get("created_at")
    if created_at is None:
        raise ValueError("metadata must include created_at")
    repository_age = age_days(created_at, as_of=moment)

    areas = _verified_areas(light)
    area_count = len(areas)
    relevance_base = RELEVANCE_BASE_BY_AREA_COUNT.get(area_count, 14)
    relevance_cap = RELEVANCE_CAP_BY_AREA_COUNT.get(area_count, 20)
    if scoring is not None:
        relevance_base = min(relevance_base, scoring.preliminary_relevance_max)

    deep_ok = deep is not None and deep.status == "OK"
    suggestion = deep.relevance_suggestion if deep_ok else None
    if suggestion is None:
        relevance = relevance_base
    else:
        relevance = max(relevance_base, min(int(suggestion), relevance_cap))
    relevance = max(0, min(relevance_cap, relevance))

    originality_evidence = _originality_evidence(metadata)
    no_llm_max = scoring.no_llm_originality_max if scoring else 4
    if deep_ok and deep.originality_suggestion is not None:
        originality_cap = min(10, 2 + 3 * len(originality_evidence))
        originality = max(0, min(int(deep.originality_suggestion), originality_cap))
    else:
        originality = max(0, min(no_llm_max, 2 * len(originality_evidence)))

    quality = score_quality(
        light.quality_signals, light.negative_signals, deep=deep, config=config
    )
    activity = score_activity(
        light.activity_level,
        _relevant_activity_age_days(light, metadata, moment),
        config=config,
    )
    visibility = score_visibility(stars, config=config)
    novelty = score_novelty(repository_age, config=config)
    intersection = score_intersection(areas, config=config)

    return HiddenGemScore(
        relevance=relevance,
        quality=quality,
        activity=activity,
        visibility=visibility,
        novelty=novelty,
        originality=originality,
        intersection=intersection,
        total=relevance + quality + activity + visibility + novelty + originality + intersection,
        confidence=_confidence(light, deep, area_count),
    )
