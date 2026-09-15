from __future__ import annotations

from datetime import timedelta

from hidden_gems.models import DeepAnalysis, HiddenGemScore
from tests.unit.history.conftest import NOW


def test_upsert_repository_is_idempotent_and_updates_stars(store, repo_ref):
    store.upsert_repository(repo_ref, stars=3, seen_at=NOW)
    store.upsert_repository(repo_ref, stars=9, seen_at=NOW + timedelta(days=1))
    row = store.get_repository(repo_ref.github_repo_id)
    assert row is not None
    assert row["stars"] == 9
    assert row["full_name"] == "acme/gem"


def test_repository_identity_is_the_github_id(store, repo_ref):
    store.upsert_repository(repo_ref, stars=1, seen_at=NOW)
    row = store.get_repository(repo_ref.github_repo_id)
    assert row["github_repo_id"] == repo_ref.github_repo_id
    assert store.get_repository(999) is None


def test_observation_and_discovery_hit_are_persisted(store, repo_ref):
    store.upsert_repository(repo_ref, stars=5, seen_at=NOW)
    store.save_discovery_hit(repo_ref.github_repo_id, run_id="run-1", channel="TOPIC_SEARCH", query_id="Q1", seen_at=NOW)
    store.save_discovery_hit(repo_ref.github_repo_id, run_id="run-1", channel="TOPIC_SEARCH", query_id="Q1", seen_at=NOW)
    store.save_observation(
        repo_ref.github_repo_id,
        observed_at=NOW,
        run_id="run-1",
        readme_hash="r",
        tree_hash="t",
        dependency_hash="d",
        relevant_content_hash="c",
        activity_level="STRONG",
        detected_areas=["ai_agents"],
        evidence={"readme_chars": 120},
    )
    with store.transaction() as connection:
        hits = connection.execute("SELECT COUNT(*) FROM discovery_hits").fetchone()[0]
        observations = connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    assert hits == 1, "duplicate discovery hits for the same query must not duplicate rows"
    assert observations == 1


def test_filter_decisions_and_scores_are_persisted(store, repo_ref):
    store.upsert_repository(repo_ref, stars=5, seen_at=NOW)
    store.save_filter_decision(
        repo_ref.github_repo_id, run_id="run-1", decided_at=NOW, passed=False,
        reason_code="REJECT_TUTORIAL", evidence=("readme:tutorial_wording", "tree:notebook_only"),
    )
    score = HiddenGemScore(11, 15, 20, 15, 10, 2, 2, 75, "MEDIUM")
    store.save_score(repo_ref.github_repo_id, run_id="run-1", scored_at=NOW, score=score)
    with store.transaction() as connection:
        decision = connection.execute("SELECT passed, reason_code, evidence FROM filter_decisions").fetchone()
        saved = connection.execute("SELECT total, confidence, score_version FROM scores").fetchone()
    assert decision[0] == 0 and decision[1] == "REJECT_TUTORIAL"
    assert "notebook_only" in decision[2]
    assert tuple(saved) == (75, "MEDIUM", "HIDDEN_GEM_SCORE_V1")
    row = store.get_repository(repo_ref.github_repo_id)
    assert row["current_score"] == 75


def test_llm_cache_round_trip_and_miss(store, repo_ref):
    store.upsert_repository(repo_ref, stars=5, seen_at=NOW)
    analysis = DeepAnalysis(
        repo=repo_ref,
        relevance_suggestion=14,
        originality_suggestion=6,
        why_interesting="unique capability",
        summary="summary",
        risks=("early stage",),
        confidence="HIGH",
        evidence={"verified_areas": ["ai_agents"]},
    )
    store.save_llm_analysis(
        repo_ref.github_repo_id,
        run_id="run-1",
        analyzed_at=NOW,
        relevant_content_hash="hash-1",
        prompt_version="DEEP_ANALYZER_PROMPT_V1",
        schema_version="LLM_ANALYSIS_V1",
        model="deepseek-chat",
        analysis=analysis,
        input_tokens=1200,
        output_tokens=300,
        cost=0.01,
    )
    cached = store.find_llm_analysis(
        github_repo_id=repo_ref.github_repo_id,
        relevant_content_hash="hash-1",
        prompt_version="DEEP_ANALYZER_PROMPT_V1",
        schema_version="LLM_ANALYSIS_V1",
        model="deepseek-chat",
    )
    assert cached is not None
    assert cached.relevance_suggestion == 14
    assert cached.risks == ("early stage",)
    assert cached.source == "CACHE"
    assert (
        store.find_llm_analysis(
            github_repo_id=repo_ref.github_repo_id,
            relevant_content_hash="hash-2",
            prompt_version="DEEP_ANALYZER_PROMPT_V1",
            schema_version="LLM_ANALYSIS_V1",
            model="deepseek-chat",
        )
        is None
    )


def test_notifications_are_append_only_and_fingerprint_unique(store, repo_ref):
    import sqlite3

    import pytest

    store.upsert_repository(repo_ref, stars=5, seen_at=NOW)
    first = store.save_notification(
        repo_ref.github_repo_id,
        fingerprint="FIRST_DISCOVERY:4242:HIDDEN_GEM_SCORE_V1",
        notification_type="NEW_DISCOVERY",
        score=75,
        notified_at=NOW,
        run_id="run-1",
    )
    assert first > 0
    assert store.notification_exists("FIRST_DISCOVERY:4242:HIDDEN_GEM_SCORE_V1") is True
    with pytest.raises(sqlite3.IntegrityError):
        store.save_notification(
            repo_ref.github_repo_id,
            fingerprint="FIRST_DISCOVERY:4242:HIDDEN_GEM_SCORE_V1",
            notification_type="NEW_DISCOVERY",
            score=75,
            notified_at=NOW,
            run_id="run-1",
        )
    latest = store.latest_notification(repo_ref.github_repo_id)
    assert latest["score"] == 75


def test_notification_state_derives_from_history(store, repo_ref):
    store.upsert_repository(repo_ref, stars=5, seen_at=NOW)
    state = store.notification_state(repo_ref.github_repo_id)
    assert state.ever_seen is True
    assert state.last_notified_score is None
    store.save_notification(
        repo_ref.github_repo_id,
        fingerprint="SCORE_INCREASE:4242:1:75",
        notification_type="UPDATE",
        score=72,
        notified_at=NOW,
        run_id="run-1",
    )
    state = store.notification_state(repo_ref.github_repo_id)
    assert state.last_notified_score == 72
    assert "SCORE_INCREASE:4242:1:75" in state.notified_fingerprints


def test_pending_report_protocol(store):
    store.start_run(
        run_id="run-1",
        started_at=NOW,
        dry_run=False,
        config_version="1.0.0",
        score_version="HIDDEN_GEM_SCORE_V1",
        prompt_version="DEEP_ANALYZER_PROMPT_V1",
        budgets={"max_raw_candidates": 1000},
    )
    store.save_pending_report(fingerprint="REPORT:abc", run_id="run-1", created_at=NOW, payload="# report body")
    pending = store.find_pending_report("REPORT:abc")
    assert pending is not None
    assert pending["payload"] == "# report body"
    assert pending["report_state"] == "PENDING_REPORT"
    assert store.find_pending_report("REPORT:missing") is None
    store.mark_report_published("REPORT:abc", issue_number=7, issue_url="https://example/7", published_at=NOW, run_id="run-1")
    published = store.find_pending_report("REPORT:abc")
    assert published["report_state"] == "REPORT_PUBLISHED"
    assert published["issue_number"] == 7


def test_runs_lifecycle_and_results(store):
    store.start_run(
        run_id="run-2",
        started_at=NOW,
        dry_run=True,
        config_version="1.0.0",
        score_version="HIDDEN_GEM_SCORE_V1",
        prompt_version="DEEP_ANALYZER_PROMPT_V1",
        budgets={"max_raw_candidates": 1000},
    )
    store.finish_run(
        "run-2",
        result="SUCCESS_NO_FINDINGS",
        finished_at=NOW + timedelta(minutes=2),
        usage={"seen": 12},
        errors=("GitHubNotFound: /repos/x",),
    )
    with store.transaction() as connection:
        row = connection.execute("SELECT result, dry_run, usage, errors FROM runs WHERE run_id = ?", ("run-2",)).fetchone()
    assert row[0] == "SUCCESS_NO_FINDINGS"
    assert row[1] == 1
    assert "seen" in row[2]
    assert "GitHubNotFound" in row[3]


def test_unknown_run_result_is_rejected(store):
    import pytest

    store.start_run(
        run_id="run-3",
        started_at=NOW,
        dry_run=True,
        config_version="1.0.0",
        score_version="HIDDEN_GEM_SCORE_V1",
        prompt_version="DEEP_ANALYZER_PROMPT_V1",
        budgets={},
    )
    with pytest.raises(ValueError):
        store.finish_run("run-3", result="MAYBE", finished_at=NOW)


def test_failed_transaction_does_not_leave_partial_repository(store, repo_ref):
    import pytest

    with pytest.raises(RuntimeError):
        with store.transaction():
            store.upsert_repository(repo_ref, stars=42, seen_at=NOW)
            store.save_notification(
                repo_ref.github_repo_id,
                fingerprint="FIRST_DISCOVERY:4242",
                notification_type="NEW_DISCOVERY",
                score=80,
                notified_at=NOW,
                run_id="run-1",
            )
            raise RuntimeError("forced")
    assert store.get_repository(repo_ref.github_repo_id) is None
    assert store.notification_exists("FIRST_DISCOVERY:4242") is False
