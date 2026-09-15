"""Reference corpus and V1 acceptance metrics (Task 16).

The corpus is a frozen human-labelled dataset (GOOD / MAYBE / BAD) with
adversarial cases. It measures:

* deterministic hard-filter outcomes,
* score bands for the deterministic (no-LLM) path,
* the Useful Discovery Rate = (GOOD + MAYBE notified) / all notified.

Acceptance floor: 70% Good+Maybe among notified. A notified BAD case is a
precision defect; a BAD case at >= 85 is an exceptional false positive and is
reported as a critical calibration warning.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from hidden_gems.config import AppConfig, load_config
from hidden_gems.filtering.hard_filter import FilterEvidence, evaluate_candidate
from hidden_gems.models import (
    DeepAnalysis,
    DiscoveryCandidate,
    LightAnalysis,
    RepositoryRef,
)
from hidden_gems.scoring.hidden_gem_v1 import compute_final_score, required_notification_threshold

CORPUS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "reference_corpus"
MANIFEST = yaml.safe_load((CORPUS_DIR / "manifest.yml").read_text(encoding="utf-8"))
AS_OF = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def build_candidate(payload: dict) -> DiscoveryCandidate:
    ref = RepositoryRef.from_full_name(str(payload["full_name"]), int(payload["github_repo_id"]))
    return DiscoveryCandidate(
        repo=ref,
        description=payload.get("description"),
        stars=int(payload.get("stars", 0)),
        created_at=_dt(payload["created_at"]),
        updated_at=_dt(payload["updated_at"]),
        primary_language=payload.get("primary_language"),
        topics=tuple(payload.get("topics", ())),
        discovery_channels={"TOPIC_SEARCH"},
        matched_query_ids={"Q_CORPUS"},
        pushed_at=_dt(payload.get("updated_at")),
        is_fork=bool(payload.get("is_fork", False)),
        is_archived=bool(payload.get("is_archived", False)),
        is_template=bool(payload.get("is_template", False)),
        size_kb=payload.get("size_kb"),
        default_branch=payload.get("default_branch", "main"),
        license_spdx_id=payload.get("license_spdx_id"),
    )


def load_fixture(entry: dict) -> dict:
    return json.loads((CORPUS_DIR / entry["fixture"]).read_text(encoding="utf-8"))


def build_evidence(fixture: dict) -> FilterEvidence:
    payload = fixture.get("evidence", {})
    return FilterEvidence(
        readme_text=payload.get("readme_text"),
        tree_paths=tuple(payload.get("tree_paths", ())),
        manifest_names=tuple(payload.get("manifest_names", ())),
        commit_messages=tuple(payload.get("commit_messages", ())),
        total_size_kb=payload.get("total_size_kb"),
    )


def build_light(candidate: DiscoveryCandidate, fixture: dict) -> LightAnalysis | None:
    payload = fixture.get("light")
    if not payload:
        return None
    return LightAnalysis(
        repo=candidate.repo,
        detected_areas=frozenset(payload.get("areas", ())),
        activity_level=payload.get("activity_level", "UNKNOWN"),
        quality_signals=tuple(payload.get("quality_signals", ())),
        negative_signals=tuple(payload.get("negative_signals", ())),
        latest_release_tag=None,
        latest_release_at=None,
        latest_relevant_activity_at=AS_OF,
        readme_hash="corpus-readme",
        tree_hash="corpus-tree",
        dependency_hash="corpus-deps",
        relevant_content_hash="corpus-content",
        evidence={"prompt_injection_signal": bool(payload.get("prompt_injection_signal", False))},
    )


def build_metadata(candidate: DiscoveryCandidate, fixture: dict) -> dict:
    payload = fixture.get("light", {})
    return {
        "stars": candidate.stars,
        "created_at": candidate.created_at,
        "relevant_activity_age_days": payload.get("activity_age_days"),
        "relevance_evidence": tuple(payload.get("relevance_evidence", ())),
        "originality_evidence": tuple(payload.get("originality_evidence", ())),
    }


def evaluate_case(entry: dict, config: AppConfig) -> dict:
    fixture = load_fixture(entry)
    candidate = build_candidate(fixture["candidate"])
    evidence = build_evidence(fixture)
    decision = evaluate_candidate(candidate, evidence, config=config)
    light = build_light(candidate, fixture)
    score = None
    notified = False
    if light is not None:
        score = compute_final_score(light, None, build_metadata(candidate, fixture), config=config, as_of=AS_OF)
        threshold = required_notification_threshold(candidate.stars, config=config)
        notified = threshold is not None and score.total >= threshold and score.confidence != "LOW"
    return {
        "id": entry["id"],
        "class": entry["class"],
        "decision": decision,
        "score": score,
        "notified": notified,
        "expect_notified": bool(entry["expect_notified"]),
    }


CASES = MANIFEST["cases"]
RESULTS = {entry["id"]: evaluate_case(entry, load_config(Path(__file__).resolve().parents[2])) for entry in CASES}


def test_corpus_size_and_labels_are_frozen():
    assert 20 <= len(CASES) <= 40, "SPEC requires a reference corpus of 20-40 labelled repositories"
    labelled = {entry["id"]: entry["class"] for entry in CASES}
    assert set(labelled.values()) <= {"GOOD", "MAYBE", "BAD"}
    assert sum(1 for value in labelled.values() if value == "GOOD") >= 5
    assert sum(1 for value in labelled.values() if value == "BAD") >= 5
    assert len(set(labelled)) == len(CASES), "corpus ids must be unique"


def test_mandatory_adversarial_cases_are_present():
    ids = {entry["id"] for entry in CASES}
    required = {
        "marketing_spam",
        "zero_star_data_extractor",
        "tutorial_notebooks",
        "explicit_template",
        "old_reactivated_rag",
        "huge_popular_excellent",
        "prompt_injection_readme",
        "duplicate_multi_query",
    }
    assert required <= ids


@pytest.mark.parametrize("entry", CASES, ids=[entry["id"] for entry in CASES])
def test_expected_hard_filter_outcome(entry, app_config: AppConfig):
    result = RESULTS[entry["id"]]
    expected = entry["hard_filter"]
    if expected == "PASS":
        assert result["decision"].passed is True, f'{entry["id"]} should pass the hard filter'
    else:
        accepted = set(entry.get("accept_codes", [expected]))
        accepted.add(expected)
        assert result["decision"].reason_code in accepted, (
            f'{entry["id"]} expected one of {sorted(accepted)}, got {result["decision"].reason_code}'
        )
        assert result["decision"].evidence, "every rejection must carry evidence"


@pytest.mark.parametrize(
    "entry",
    [entry for entry in CASES if entry["hard_filter"] == "PASS" and "score_band" in entry],
    ids=[entry["id"] for entry in CASES if entry["hard_filter"] == "PASS" and "score_band" in entry],
)
def test_expected_score_band(entry, app_config: AppConfig):
    result = RESULTS[entry["id"]]
    assert result["score"] is not None, f'{entry["id"]} needs light evidence to be scored'
    low, high = entry["score_band"]
    assert low <= result["score"].total <= high, (
        f'{entry["id"]} scored {result["score"].total}, outside the accepted band [{low}, {high}]'
    )


def test_notification_expectations_match_thresholds(app_config: AppConfig):
    for entry in CASES:
        result = RESULTS[entry["id"]]
        if not result["expect_notified"]:
            continue
        assert result["notified"] is True, f'{entry["id"]} was expected to be notified'


def test_popular_repository_is_never_notifiable(app_config: AppConfig):
    entry = next(item for item in CASES if item["id"] == "huge_popular_excellent")
    fixture = load_fixture(entry)
    candidate = build_candidate(fixture["candidate"])
    assert candidate.stars > 2000
    assert required_notification_threshold(candidate.stars, config=app_config) is None
    assert RESULTS[entry["id"]]["notified"] is False


def test_no_bad_case_is_ever_notified():
    bad_notified = [entry["id"] for entry in CASES if entry["class"] == "BAD" and RESULTS[entry["id"]]["notified"]]
    assert bad_notified == [], f"precision defect: BAD cases notified -> {bad_notified}"


def test_prompt_injection_never_inflates_the_score(app_config: AppConfig):
    entry = next(item for item in CASES if item["id"] == "prompt_injection_readme")
    fixture = load_fixture(entry)
    assert "IGNORE PREVIOUS INSTRUCTIONS" in (fixture["evidence"]["readme_text"] or "")
    assert RESULTS[entry["id"]]["score"].total < app_config.scoring.exceptional_threshold
    assert RESULTS[entry["id"]]["notified"] is False


def test_useful_discovery_rate_meets_the_acceptance_floor(capsys):
    notified = [entry for entry in CASES if RESULTS[entry["id"]]["notified"]]
    useful = [entry for entry in notified if entry["class"] in ("GOOD", "MAYBE")]
    rate = 1.0 if not notified else len(useful) / len(notified)
    exceptional = [entry for entry in CASES if RESULTS[entry["id"]]["score"] and RESULTS[entry["id"]]["score"].total >= 85]
    exceptional_bad = [entry["id"] for entry in exceptional if entry["class"] == "BAD"]
    print(
        f"USEFUL_DISCOVERY_RATE={rate:.2%} notified={len(notified)} useful={len(useful)} "
        f"exceptional={len(exceptional)} exceptional_bad={exceptional_bad}"
    )
    assert rate >= MANIFEST["minimum_useful_discovery_rate"], (
        f"Useful Discovery Rate {rate:.2%} is below the {MANIFEST['minimum_useful_discovery_rate']:.0%} floor"
    )
    assert exceptional_bad == [], f"exceptional false positives block acceptance: {exceptional_bad}"
    assert notified, "the corpus must exercise the notification path"


def test_corpus_is_deterministic(app_config: AppConfig):
    first = evaluate_case(CASES[0], app_config)
    second = evaluate_case(CASES[0], app_config)
    assert first["score"] == second["score"]
