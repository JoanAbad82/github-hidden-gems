"""REPORT_FORMAT_V1: the user-facing Markdown report."""

from __future__ import annotations

from datetime import date
from typing import Sequence

from ..config import AppConfig
from ..models import NOTIFICATION_STATUS_UPDATE, SelectedFinding, RunSummary
from ..security.sanitization import sanitize_inline, sanitize_markdown_text
from ..scoring.hidden_gem_v1 import EXCEPTIONAL_THRESHOLD, NOTIFICATION_THRESHOLD
from .fingerprints import report_fingerprint

DEFAULT_LABELS = ("discovery-report",)
DEFAULT_EXCEPTIONAL_LABEL = "exceptional-findings"
DEFAULT_UPDATE_LABEL = "has-updates"

_NO_DESCRIPTION = "No description provided by the repository."


def _areas(finding: SelectedFinding) -> list[str]:
    if finding.areas:
        return [sanitize_inline(area, max_chars=40) for area in finding.areas]
    if finding.light is not None:
        return [sanitize_inline(area, max_chars=40) for area in sorted(finding.light.detected_areas)]
    return []


def _summary(finding: SelectedFinding) -> str:
    if finding.deep is not None and finding.deep.summary:
        return sanitize_markdown_text(finding.deep.summary)
    if finding.deep is not None and finding.deep.evidence.get("description"):
        return sanitize_markdown_text(str(finding.deep.evidence["description"]))
    if finding.light is not None and finding.light.evidence.get("description"):
        return sanitize_markdown_text(str(finding.light.evidence["description"]))
    return _NO_DESCRIPTION


def _why_interesting(finding: SelectedFinding) -> str:
    if finding.deep is not None and finding.deep.why_interesting:
        return sanitize_markdown_text(finding.deep.why_interesting)
    areas = _areas(finding)
    if areas:
        return f"Matches the {'/'.join(areas)} area(s) with verifiable repository evidence."
    return "Deterministic evidence only; no semantic enrichment was available for this run."


def _status_line(finding: SelectedFinding) -> str:
    if finding.status != NOTIFICATION_STATUS_UPDATE:
        return "NEW DISCOVERY"
    previous = finding.previous_score if finding.previous_score is not None else finding.decision.previous_score
    if previous is None:
        return "UPDATE"
    delta = finding.score.total - previous
    sign = "+" if delta >= 0 else ""
    return f"UPDATE (previous {previous} → {finding.score.total}, {sign}{delta})"


def _iso(value) -> str:
    if value is None:
        return "unknown"
    return value.date().isoformat() if hasattr(value, "date") else str(value)


def _entry(index: int, finding: SelectedFinding) -> list[str]:
    score = finding.score
    kind = "EXCEPTIONAL" if score.total >= EXCEPTIONAL_THRESHOLD else "INTERESTING"
    repo = finding.repo
    areas = ", ".join(_areas(finding)) or "unknown"
    lines = [
        f"### {index}. [{repo.owner}/{repo.name}]({repo.html_url}) — {score.total}/100 ({kind})",
        "",
        f"- **What it does:** {_summary(finding)}",
        f"- **Why it may interest you:** {_why_interesting(finding)}",
        f"- **Stars:** {int(finding.stars)} · **Created:** {_iso(finding.created_at)}"
        f" · **Last relevant activity:** {_iso(finding.latest_relevant_activity_at)}",
        f"- **Primary language:** {sanitize_inline(finding.primary_language or 'unknown')}"
        f" · **Related areas:** {areas}",
        f"- **Hidden Gem Score:** {score.total}/100 · **Confidence:** {score.confidence}"
        f" · **Status:** {_status_line(finding)}",
    ]
    if finding.latest_release_tag:
        lines.append(f"- **Latest release:** {sanitize_inline(finding.latest_release_tag, max_chars=60)}")
    if finding.deep is not None and finding.deep.risks:
        risks = "; ".join(sanitize_inline(risk, max_chars=120) for risk in finding.deep.risks)
        lines.append(f"- **Risks / caveats:** {risks}")
    lines.append(f"- **Link:** {repo.html_url}")
    lines.append("")
    return lines


def build_report(
    findings: Sequence[SelectedFinding], run_summary: RunSummary, *, config: AppConfig | None = None
) -> str:
    """Render REPORT_FORMAT_V1. No findings means no report at all."""

    ordered = list(findings)
    if not ordered:
        return ""

    run_date = _run_date(run_summary)
    score_version = ordered[0].score.score_version
    fingerprint = report_fingerprint(ordered, run_date, score_version)
    threshold = config.scoring.notification_threshold if config else NOTIFICATION_THRESHOLD

    lines = [
        f"# GitHub Hidden Gems — {run_date.isoformat()}",
        "",
        f"{len(ordered)} repository(ies) reached the notification threshold "
        f"(score >= {threshold}).",
        "",
    ]
    for index, finding in enumerate(ordered, start=1):
        lines.extend(_entry(index, finding))

    lines.extend(
        [
            "---",
            f"<sub>RUN_ID={run_summary.run_id} · SCORE_VERSION={score_version}"
            f" · REPORT_FINGERPRINT={fingerprint}</sub>",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def report_labels(
    findings: Sequence[SelectedFinding], *, config: AppConfig | None = None
) -> list[str]:
    labels = list(config.reporting.labels if config else DEFAULT_LABELS)
    exceptional_label = (
        config.reporting.exceptional_label if config else DEFAULT_EXCEPTIONAL_LABEL
    )
    update_label = config.reporting.update_label if config else DEFAULT_UPDATE_LABEL
    threshold = config.reporting.extra_positions_min_score if config else EXCEPTIONAL_THRESHOLD

    if any(finding.score.total >= threshold for finding in findings) and exceptional_label not in labels:
        labels.append(exceptional_label)
    if any(finding.status == NOTIFICATION_STATUS_UPDATE for finding in findings) and update_label not in labels:
        labels.append(update_label)
    return labels


def _run_date(run_summary: RunSummary) -> date:
    started = run_summary.started_at
    return started.date() if hasattr(started, "date") else date.today()
