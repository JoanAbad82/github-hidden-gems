"""End-to-end pipeline orchestration with explicit phase boundaries."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .common.logging import get_logger
from .common.time import utcnow
from .config import AppConfig
from .deep_analysis.analyzer import DeepAnalyzer
from .discovery.engine import run_discovery
from .filtering.hard_filter import evaluate_candidate
from .github.issues import GitHubIssuePublisher
from .light_analysis.analyzer import LightAnalyzer
from .llm.base import LLMBudget, LLMBudgetExceeded, DisabledLLMProvider, LLMProviderError
from .llm.validator import PROMPT_VERSION
from .models import (
    DiscoveryCandidate,
    HiddenGemScore,
    LightAnalysis,
    RepositoryRef,
    RunContext,
    RunSummary,
    SelectedFinding,
)
from .relationships.explorer import explore_relationships
from .reporting.fingerprints import (
    major_change_fingerprint,
    new_release_fingerprint,
    report_fingerprint,
)
from .reporting.markdown import build_report, report_labels
from .reporting.selector import make_notification_decision, select_report_candidates
from .scoring.hidden_gem_v1 import compute_final_score
from .scoring.preliminary import compute_preliminary_score, maximum_possible_score

LOGGER = get_logger("hidden_gems.orchestrator")

REJECT_LOW_MAX_SCORE = "REJECT_LOW_MAX_SCORE"


def run_pipeline(
    config: AppConfig,
    history: Any,
    github: Any,
    llm: Any,
    context: RunContext,
    *,
    publisher: Any = None,
    as_of: datetime | None = None,
    llm_enabled: bool | None = None,
) -> RunSummary:
    """Run one full discovery cycle. Individual failures stay fail-soft."""

    moment = as_of or context.started_at or utcnow()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    run_date = moment.date()
    budgets = _budgets(config)
    counts: dict[str, int] = {
        "discovered": 0,
        "filtered_in": 0,
        "rejected": 0,
        "light_analyzed": 0,
        "related": 0,
        "pruned_low_max_score": 0,
        "deep_analyzed": 0,
        "scored": 0,
        "notifiable": 0,
        "reported": 0,
        "llm_candidate_cap_skipped": 0,
    }
    errors: list[str] = []
    result = "SUCCESS"
    report = ""
    fingerprint: str | None = None
    issue = None
    llm_budget = getattr(llm, "budget", None)
    if llm_budget is None:
        llm_budget = LLMBudget(
            max_calls=int(config.llm.max_llm_calls_per_run),
            max_budget=float(config.llm.max_llm_budget_per_run),
        )
    use_llm = bool(config.llm.enabled_default) if llm_enabled is None else bool(llm_enabled)
    # SPEC_V1 section 8: MAX_LLM_CANDIDATES_PER_RUN bounds how many repositories
    # may reach the semantic provider, independently of the call budget.
    llm_candidate_cap = int(config.llm.max_llm_candidates_per_run)
    llm_candidates_enriched = 0

    history.start_run(
        run_id=context.run_id,
        started_at=context.started_at,
        dry_run=context.dry_run,
        config_version=context.config_version or config.config_version,
        score_version=config.scoring.score_version,
        prompt_version=PROMPT_VERSION,
        budgets=budgets,
    )

    try:
        discovery = run_discovery(config, github, as_of=run_date)
        counts["discovered"] = len(discovery.candidates)
        if discovery.errors:
            errors.append(f"discovery_errors={discovery.errors}")
        rate_limited = discovery.stopped_reason == "RATE_LIMIT_RED"
        _record_discovery_hits(history, discovery.candidates, run_id=context.run_id, seen_at=moment)

        admitted: list[DiscoveryCandidate] = []
        for candidate in discovery.candidates:
            decision = evaluate_candidate(candidate, config=config)
            _persist_seen(history, candidate, moment)
            history.save_filter_decision(
                candidate.repo.github_repo_id,
                run_id=context.run_id,
                decided_at=moment,
                passed=decision.passed,
                reason_code=decision.reason_code,
                evidence=decision.evidence,
            )
            if decision.passed:
                admitted.append(candidate)
            else:
                counts["rejected"] += 1
        counts["filtered_in"] = len(admitted)

        analyzer = LightAnalyzer(config, github)
        lights: list[tuple[DiscoveryCandidate, LightAnalysis]] = []
        light_budget = int(budgets["max_light_analysis"])
        for candidate in admitted[:light_budget]:
            analyzed = _light_analyze(
                analyzer, history, candidate, context, moment, errors
            )
            if analyzed is not None:
                lights.append((candidate, analyzed))
        counts["light_analyzed"] = len(lights)

        if not rate_limited:
            related = _expand_relationships(
                config=config,
                github=github,
                history=history,
                analyzer=analyzer,
                lights=lights,
                seen_ids={candidate.repo.github_repo_id for candidate in discovery.candidates},
                context=context,
                moment=moment,
                remaining_light=max(0, light_budget - len(lights)),
                errors=errors,
            )
            counts["related"] = len(related)
            for candidate, analysis in related:
                lights.append((candidate, analysis))

        findings: list[SelectedFinding] = []
        deep_budget = int(budgets["max_deep_analysis"])
        ranked = _rank_by_preliminary(config, lights, moment)
        for candidate, analysis, preliminary in ranked:
            maximum = maximum_possible_score(
                preliminary, notification_threshold=config.scoring.notification_threshold
            )
            if not maximum.can_reach_notification:
                counts["pruned_low_max_score"] += 1
                history.save_filter_decision(
                    candidate.repo.github_repo_id,
                    run_id=context.run_id,
                    decided_at=moment,
                    passed=False,
                    reason_code=REJECT_LOW_MAX_SCORE,
                    evidence=(f"maximum_possible_score={maximum.total}",),
                )
                continue
            if counts["deep_analyzed"] >= deep_budget:
                continue
            counts["deep_analyzed"] += 1

            deep = None
            enrich = use_llm and llm_candidates_enriched < llm_candidate_cap
            if use_llm and not enrich:
                counts["llm_candidate_cap_skipped"] += 1
            try:
                deep = DeepAnalyzer(config, github).analyze(analysis)
                deep = _maybe_enrich(config, llm, deep, enrich, llm_budget, errors)
                if enrich:
                    llm_candidates_enriched += 1
            except Exception as exc:  # fail-soft per candidate
                errors.append(f"deep:{candidate.repo.github_repo_id}:{type(exc).__name__}")

            score = compute_final_score(
                analysis,
                deep,
                _scoring_metadata(candidate),
                config=config,
                as_of=moment,
            )
            history.save_score(
                candidate.repo.github_repo_id,
                run_id=context.run_id,
                scored_at=moment,
                score=score,
            )
            counts["scored"] += 1

            decision = make_notification_decision(
                score=score,
                stars=candidate.stars,
                state=history.notification_state(candidate.repo.github_repo_id),
                release_fingerprint=_release_fingerprint(candidate, analysis),
                content_fingerprint=major_change_fingerprint(
                    candidate.repo.github_repo_id, analysis.relevant_content_hash
                ),
                config=config,
            )
            if not decision.notify:
                continue
            counts["notifiable"] += 1
            findings.append(_selected_finding(candidate, analysis, deep, score, decision))

        selected = select_report_candidates(findings, config=config)
        counts["reported"] = len(selected)
        if selected:
            summary_for_report = RunSummary(
                run_id=context.run_id,
                result="SUCCESS",
                started_at=context.started_at,
                dry_run=context.dry_run,
                counts=dict(counts),
            )
            report = build_report(selected, summary_for_report, config=config)
            fingerprint = report_fingerprint(
                selected, run_date, config.scoring.score_version
            )
            if not context.dry_run:
                issue = _publish(
                    config=config,
                    github=github,
                    history=history,
                    publisher=publisher,
                    selected=selected,
                    report=report,
                    fingerprint=fingerprint,
                    context=context,
                    moment=moment,
                )

        if rate_limited:
            result = "PARTIAL_SUCCESS_RATE_LIMIT"
        elif errors:
            result = "PARTIAL_SUCCESS"
        elif not selected:
            result = "SUCCESS_NO_FINDINGS"
        else:
            result = "SUCCESS"
    except Exception as exc:  # unexpected phase failure: persist what we have
        errors.append(f"pipeline:{type(exc).__name__}:{exc}")
        result = "PARTIAL_SUCCESS"
        LOGGER.error("pipeline failed: %s", type(exc).__name__)
    finally:
        usage = dict(llm_budget.snapshot())
        usage["candidate_cap_skipped"] = int(counts["llm_candidate_cap_skipped"])
        usage["llm_candidates_used"] = int(llm_candidates_enriched)
        usage["counts"] = {key: int(value) for key, value in counts.items()}
        context.usage.update(usage)
        summary = RunSummary(
            run_id=context.run_id,
            result=result,
            started_at=context.started_at,
            finished_at=utcnow(),
            dry_run=context.dry_run,
            counts=dict(counts),
            usage=usage,
            report_fingerprint=fingerprint,
            issue=issue,
            errors=tuple(errors),
        )
        try:
            history.finish_run(
                context.run_id,
                result=result,
                finished_at=summary.finished_at,
                usage=usage,
                report_fingerprint=fingerprint,
                issue_number=getattr(issue, "number", None),
                errors=errors,
            )
        except Exception as exc:  # pragma: no cover - persistence failure is reported
            LOGGER.error("finish_run failed: %s", type(exc).__name__)
        LOGGER.info(
            "run %s finished result=%s discovered=%d reported=%d",
            context.run_id,
            result,
            counts["discovered"],
            counts["reported"],
        )
    return summary


# -- phase helpers --------------------------------------------------------


def _budgets(config: AppConfig) -> dict[str, Any]:
    return {
        "max_raw_candidates": int(config.limits.run_budgets.get("max_raw_candidates", 1000)),
        "max_light_analysis": int(config.limits.run_budgets.get("max_light_analysis", 200)),
        "max_relationship_seeds": int(
            config.limits.run_budgets.get(
                "max_relationship_seeds", config.discovery.max_relationship_seeds
            )
        ),
        "max_deep_analysis": int(config.limits.run_budgets.get("max_deep_analysis", 25)),
        "max_llm_calls_per_run": int(config.llm.max_llm_calls_per_run),
        "max_llm_candidates_per_run": int(config.llm.max_llm_candidates_per_run),
    }


def _record_discovery_hits(
    history: Any, candidates: Sequence[DiscoveryCandidate], *, run_id: str, seen_at: datetime
) -> None:
    for candidate in candidates:
        _persist_seen(history, candidate, seen_at)
        channels = candidate.discovery_channels or {"UNKNOWN"}
        queries = candidate.matched_query_ids or {"UNKNOWN"}
        for channel in sorted(channels):
            for query_id in sorted(queries):
                history.save_discovery_hit(
                    candidate.repo.github_repo_id,
                    run_id=run_id,
                    channel=channel,
                    query_id=query_id,
                    seen_at=seen_at,
                )


def _persist_seen(history: Any, candidate: DiscoveryCandidate, moment: datetime) -> None:
    """Persist the repositories row before any child row references it."""

    history.upsert_repository(
        candidate.repo,
        stars=candidate.stars,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
        primary_language=candidate.primary_language,
        description=candidate.description,
        seen_at=moment,
        topics=candidate.topics,
        pushed_at=candidate.pushed_at,
    )


def _light_analyze(
    analyzer: LightAnalyzer,
    history: Any,
    candidate: DiscoveryCandidate,
    context: RunContext,
    moment: datetime,
    errors: list[str],
) -> LightAnalysis | None:
    try:
        analysis = analyzer.analyze(candidate, as_of=moment)
    except Exception as exc:
        errors.append(f"light:{candidate.repo.github_repo_id}:{type(exc).__name__}")
        return None
    try:
        history.upsert_repository(
            candidate.repo,
            stars=candidate.stars,
            created_at=candidate.created_at,
            updated_at=candidate.updated_at,
            primary_language=candidate.primary_language,
            description=candidate.description,
            seen_at=moment,
        )
        history.save_observation(
            candidate.repo.github_repo_id,
            observed_at=moment,
            run_id=context.run_id,
            readme_hash=analysis.readme_hash,
            tree_hash=analysis.tree_hash,
            dependency_hash=analysis.dependency_hash,
            relevant_content_hash=analysis.relevant_content_hash,
            activity_level=analysis.activity_level,
            detected_areas=sorted(analysis.detected_areas),
            latest_release_tag=analysis.latest_release_tag,
            latest_release_at=analysis.latest_release_at,
            latest_relevant_activity_at=analysis.latest_relevant_activity_at,
            evidence=analysis.evidence,
        )
    except Exception as exc:
        errors.append(f"history:{candidate.repo.github_repo_id}:{type(exc).__name__}")
    return analysis


def _expand_relationships(
    *,
    config: AppConfig,
    github: Any,
    history: Any,
    analyzer: LightAnalyzer,
    lights: Sequence[tuple[DiscoveryCandidate, LightAnalysis]],
    seen_ids: set[int],
    context: RunContext,
    moment: datetime,
    remaining_light: int,
    errors: list[str],
) -> list[tuple[DiscoveryCandidate, LightAnalysis]]:
    if remaining_light <= 0 or not lights:
        return []
    seeds = [analysis for _, analysis in lights[: config.discovery.max_relationship_seeds]]
    try:
        candidates = explore_relationships(
            config=config, client=github, seeds=seeds, existing_repo_ids=seen_ids
        )
    except Exception as exc:
        errors.append(f"relationships:{type(exc).__name__}")
        return []

    expanded: list[tuple[DiscoveryCandidate, LightAnalysis]] = []
    for candidate in candidates[:remaining_light]:
        decision = evaluate_candidate(candidate, config=config)
        _persist_seen(history, candidate, moment)
        history.save_filter_decision(
            candidate.repo.github_repo_id,
            run_id=context.run_id,
            decided_at=moment,
            passed=decision.passed,
            reason_code=decision.reason_code,
            evidence=decision.evidence,
        )
        if not decision.passed:
            continue
        history.save_discovery_hit(
            candidate.repo.github_repo_id,
            run_id=context.run_id,
            channel="RELATIONSHIP_EXPLORATION",
            query_id="RELATIONSHIP_EXPLORATION",
            seen_at=moment,
        )
        analyzed = _light_analyze(analyzer, history, candidate, context, moment, errors)
        if analyzed is not None:
            expanded.append((candidate, analyzed))
    return expanded


def _rank_by_preliminary(
    config: AppConfig, lights: Sequence[tuple[DiscoveryCandidate, LightAnalysis]], moment: datetime
) -> list[tuple[DiscoveryCandidate, LightAnalysis, Any]]:
    ranked = []
    for candidate, analysis in lights:
        preliminary = compute_preliminary_score(
            analysis, _scoring_metadata(candidate), config=config, as_of=moment
        )
        ranked.append((candidate, analysis, preliminary))
    ranked.sort(
        key=lambda item: (
            -item[2].achieved,
            -item[2].pending_max,
            item[0].repo.github_repo_id,
        )
    )
    return ranked


def _scoring_metadata(candidate: DiscoveryCandidate) -> dict[str, Any]:
    return {
        "stars": candidate.stars,
        "created_at": candidate.created_at,
        "relevance_evidence": tuple(
            f"topic:{topic}" for topic in candidate.topics
        ),
        "originality_evidence": (),
        "description": candidate.description,
        "primary_language": candidate.primary_language,
    }


def _bounded_error_text(value: Any, *, max_chars: int = 240) -> str:
    text = " ".join(str(value or "unknown").split())
    return text[:max_chars] or "unknown"


def _llm_error(deep: Any, category: Any, detail: Any | None = None) -> str:
    repo_id = getattr(getattr(deep, "repo", None), "github_repo_id", "unknown")
    parts = ["llm", str(repo_id), _bounded_error_text(category, max_chars=80)]
    if detail is not None:
        parts.append(_bounded_error_text(detail))
    return ":".join(parts)


def _maybe_enrich(
    config: AppConfig,
    llm: Any,
    deep: Any,
    use_llm: bool,
    budget: LLMBudget,
    errors: list[str],
) -> Any:
    if deep is None or deep.status != "OK":
        return deep
    provider = llm
    if provider is None:
        if not use_llm:
            return DisabledLLMProvider().analyze_repository(deep.evidence)
        return deep
    if not use_llm:
        return deep
    if not budget.can_call():
        errors.append(_llm_error(deep, "budget_exhausted"))
        return deep
    try:
        enriched = provider.analyze_repository(deep.evidence)
    except (LLMBudgetExceeded, LLMProviderError) as exc:
        errors.append(_llm_error(deep, type(exc).__name__, exc))
        return deep
    except Exception as exc:
        errors.append(_llm_error(deep, type(exc).__name__, exc))
        return deep
    if getattr(enriched, "status", "OK") != "OK":
        evidence = getattr(enriched, "evidence", {})
        failure = evidence.get("failure", "failed") if isinstance(evidence, Mapping) else "failed"
        reason = evidence.get("failure_reason") if isinstance(evidence, Mapping) else None
        errors.append(_llm_error(deep, failure, reason))
        return deep
    deep.relevance_suggestion = enriched.relevance_suggestion
    deep.originality_suggestion = enriched.originality_suggestion
    deep.why_interesting = enriched.why_interesting
    deep.summary = enriched.summary
    if enriched.risks:
        deep.risks = tuple({*deep.risks, *enriched.risks})
    if enriched.confidence == "HIGH" or deep.confidence == "LOW":
        deep.confidence = enriched.confidence
    deep.source = getattr(enriched, "source", "PROVIDER")
    if isinstance(enriched.evidence, Mapping):
        deep.evidence.setdefault("llm_evidence", enriched.evidence)
    return deep


def _release_fingerprint(candidate: DiscoveryCandidate, analysis: LightAnalysis) -> str | None:
    release_id = (analysis.evidence or {}).get("latest_release_id")
    if release_id is None:
        return None
    return new_release_fingerprint(candidate.repo.github_repo_id, release_id)


def _selected_finding(
    candidate: DiscoveryCandidate,
    analysis: LightAnalysis,
    deep: Any,
    score: HiddenGemScore,
    decision: Any,
) -> SelectedFinding:
    return SelectedFinding(
        repo=candidate.repo,
        score=score,
        decision=decision,
        status="NEW_DISCOVERY" if decision.previous_score is None else "UPDATE",
        rank=1,
        light=analysis,
        deep=deep,
        areas=tuple(sorted(analysis.detected_areas)),
        previous_score=decision.previous_score,
        latest_release_tag=analysis.latest_release_tag,
        latest_relevant_activity_at=analysis.latest_relevant_activity_at,
        primary_language=candidate.primary_language,
        stars=candidate.stars,
        created_at=candidate.created_at,
    )


def _publish(
    *,
    config: AppConfig,
    github: Any,
    history: Any,
    publisher: Any,
    selected: Sequence[SelectedFinding],
    report: str,
    fingerprint: str,
    context: RunContext,
    moment: datetime,
):
    history.save_pending_report(
        fingerprint=fingerprint,
        run_id=context.run_id,
        created_at=moment,
        payload=report,
    )
    active = publisher or GitHubIssuePublisher(config, github)
    assignee = os.environ.get("NOTIFICATION_GITHUB_LOGIN") or None
    issue = active.publish(
        report, fingerprint, report_labels(selected, config=config), assignee=assignee
    )
    history.mark_report_published(
        fingerprint,
        issue_number=issue.number,
        issue_url=issue.url,
        published_at=moment,
        run_id=context.run_id,
    )
    for finding in selected:
        history.save_notification(
            finding.repo.github_repo_id,
            fingerprint=finding.decision.trigger_fingerprint or f"REPORT:{fingerprint}",
            notification_type=finding.status,
            score=finding.score.total,
            notified_at=moment,
            run_id=context.run_id,
            issue_number=issue.number,
            previous_score=finding.previous_score,
        )
    return issue
