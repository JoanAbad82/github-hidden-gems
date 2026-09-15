"""Task 11: deterministic notification fingerprints."""

from __future__ import annotations

from datetime import date

from hidden_gems.models import HiddenGemScore, NotificationDecision, RepositoryRef, SelectedFinding
from hidden_gems.reporting.fingerprints import (
    first_discovery_fingerprint,
    major_change_fingerprint,
    new_release_fingerprint,
    report_fingerprint,
    score_increase_fingerprint,
)


def test_fingerprint_shapes_are_frozen():
    assert first_discovery_fingerprint(42, "HIDDEN_GEM_SCORE_V1") == "FIRST_DISCOVERY:42:HIDDEN_GEM_SCORE_V1"
    assert new_release_fingerprint(42, 777) == "NEW_RELEASE:42:777"
    assert score_increase_fingerprint(42, 9, 88) == "SCORE_INCREASE:42:9:88"
    assert major_change_fingerprint(42, "abc123") == "MAJOR_CHANGE:42:abc123"


def test_fingerprints_are_stable_and_distinct():
    assert first_discovery_fingerprint(42, "V1") == first_discovery_fingerprint(42, "V1")
    assert first_discovery_fingerprint(42, "V1") != first_discovery_fingerprint(43, "V1")
    assert new_release_fingerprint(42, 1) != new_release_fingerprint(42, 2)


def test_report_fingerprint_is_deterministic_and_order_independent():
    first = _finding(1, 90, "FIRST_DISCOVERY:1:HIDDEN_GEM_SCORE_V1", rank=1)
    second = _finding(2, 80, "FIRST_DISCOVERY:2:HIDDEN_GEM_SCORE_V1", rank=2)

    forward = report_fingerprint([first, second], date(2026, 9, 15), "HIDDEN_GEM_SCORE_V1")
    reversed_ = report_fingerprint([second, first], date(2026, 9, 15), "HIDDEN_GEM_SCORE_V1")

    assert forward == reversed_
    assert forward.startswith("REPORT:")


def test_report_fingerprint_changes_with_date_score_and_membership():
    first = _finding(1, 90, "FIRST_DISCOVERY:1:HIDDEN_GEM_SCORE_V1", rank=1)
    base = report_fingerprint([first], date(2026, 9, 15), "HIDDEN_GEM_SCORE_V1")

    assert base != report_fingerprint([first], date(2026, 9, 16), "HIDDEN_GEM_SCORE_V1")
    assert base != report_fingerprint([first], date(2026, 9, 15), "HIDDEN_GEM_SCORE_V2")
    other = _finding(2, 80, "FIRST_DISCOVERY:2:HIDDEN_GEM_SCORE_V1", rank=2)
    assert base != report_fingerprint([first, other], date(2026, 9, 15), "HIDDEN_GEM_SCORE_V1")
    rescored = _finding(1, 91, "FIRST_DISCOVERY:1:HIDDEN_GEM_SCORE_V1", rank=1)
    assert base != report_fingerprint([rescored], date(2026, 9, 15), "HIDDEN_GEM_SCORE_V1")


def _finding(repo_id: int, total: int, trigger: str, *, rank: int) -> SelectedFinding:
    order = ("relevance", "quality", "activity", "visibility", "novelty", "originality",
             "intersection")
    maxima = {"relevance": 20, "quality": 20, "activity": 20, "visibility": 15, "novelty": 10,
              "originality": 10, "intersection": 5}
    values = {}
    remaining = total
    for name in order:
        values[name] = min(maxima[name], remaining)
        remaining -= values[name]
    assert remaining == 0
    score = HiddenGemScore(
        values["relevance"], values["quality"], values["activity"], values["visibility"],
        values["novelty"], values["originality"], values["intersection"], total, "HIGH",
    )
    return SelectedFinding(
        repo=RepositoryRef.from_full_name(f"acme/repo{repo_id}", repo_id),
        score=score,
        decision=NotificationDecision(
            notify=True,
            notification_type="NEW_DISCOVERY",
            trigger_fingerprint=trigger,
            previous_score=None,
            current_score=total,
        ),
        status="NEW_DISCOVERY",
        rank=rank,
    )
