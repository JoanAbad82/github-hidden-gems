"""Seven-cycle V1 acceptance gate (SPEC_V1 section 13, Task 18).

The gate is deliberately conservative:

* it never invents cycles -- missing days or fewer than seven consecutive real
  daily runs keep the status `PENDING_MULTI_DAY_VALIDATION`;
* it never claims a metric it cannot compute from evidence (an ungraded
  notification keeps the gate pending instead of being counted as useful);
* a single hard-safety violation (corruption, duplicate Issue, budget overrun,
  concurrent state conflict, exposed secret) fails the gate permanently for the
  evaluated window.

Everything here is read-only and deterministic; no network and no SQLite writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

STATUS_ACCEPTED = "V1_ACCEPTED"
STATUS_NOT_ACCEPTED = "V1_NOT_ACCEPTED"
STATUS_PENDING = "PENDING_MULTI_DAY_VALIDATION"

PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"

GRADE_GOOD = "GOOD"
GRADE_MAYBE = "MAYBE"
GRADE_BAD = "BAD"
GRADES: tuple[str, ...] = (GRADE_GOOD, GRADE_MAYBE, GRADE_BAD)

USEFUL_GRADES: frozenset[str] = frozenset({GRADE_GOOD, GRADE_MAYBE})

#: Acceptable terminal states for one cycle (SPEC_V1 section 9).
CYCLE_RESULTS: tuple[str, ...] = (
    "SUCCESS",
    "SUCCESS_NO_FINDINGS",
    "PARTIAL_SUCCESS",
    "PARTIAL_SUCCESS_RATE_LIMIT",
)

SILENT_RESULT = "SUCCESS_NO_FINDINGS"


class AcceptanceError(ValueError):
    """Raised when acceptance evidence is structurally invalid."""


@dataclass(frozen=True)
class NotificationGrade:
    """One notified repository graded by a human (GOOD / MAYBE / BAD)."""

    github_repo_id: int
    grade: str
    score: int
    note: str = ""

    def __post_init__(self) -> None:
        if self.grade not in GRADES:
            raise AcceptanceError(f"invalid grade: {self.grade!r}")


@dataclass(frozen=True)
class CycleEvidence:
    """Everything the gate knows about one daily cycle."""

    run_id: str
    run_date: date
    result: str
    dry_run: bool = False
    integrity_ok: bool = True
    issues_created: int = 0
    duplicate_issues: int = 0
    budget_overruns: int = 0
    state_conflicts: int = 0
    secret_exposures: int = 0
    notifications: tuple[NotificationGrade, ...] = ()
    ungraded_notifications: int = 0
    llm_calls: int = 0
    llm_cache_hits: int = 0
    llm_cost: float = 0.0
    stage_counts: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.result not in CYCLE_RESULTS:
            raise AcceptanceError(f"invalid cycle result: {self.result!r}")
        if self.run_date is None:
            raise AcceptanceError("cycle requires a run_date")


@dataclass(frozen=True)
class AcceptanceCriteria:
    """Frozen acceptance floors (SPEC_V1 section 13)."""

    required_cycles: int = 7
    useful_discovery_rate_floor: float = 0.70
    exceptional_threshold: int = 85
    require_live_cycles: bool = True


@dataclass(frozen=True)
class CriterionResult:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class AcceptanceReport:
    status: str
    criteria: tuple[CriterionResult, ...]
    metrics: Mapping[str, Any] = field(default_factory=dict)
    blocking: tuple[str, ...] = ()

    def criterion(self, name: str) -> CriterionResult | None:
        for item in self.criteria:
            if item.name == name:
                return item
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "blocking": list(self.blocking),
            "metrics": dict(self.metrics),
            "criteria": [
                {"name": item.name, "status": item.status, "detail": item.detail}
                for item in self.criteria
            ],
        }


# -- helpers --------------------------------------------------------------


def _trailing_consecutive(cycles: Sequence[CycleEvidence]) -> list[CycleEvidence]:
    """The most recent unbroken run of consecutive daily cycles."""

    ordered = sorted(cycles, key=lambda cycle: cycle.run_date)
    if not ordered:
        return []
    tail = [ordered[-1]]
    for item in reversed(ordered[:-1]):
        if (tail[-1].run_date - item.run_date).days == 1:
            tail.append(item)
        else:
            break
    return list(reversed(tail))


def _window(cycles: Sequence[CycleEvidence], criteria: AcceptanceCriteria) -> list[CycleEvidence]:
    return _trailing_consecutive(cycles)[-int(criteria.required_cycles) :]


def _sum(cycles: Sequence[CycleEvidence], attribute: str) -> int:
    return sum(int(getattr(cycle, attribute, 0) or 0) for cycle in cycles)


def _useful_discovery_rate(window: Sequence[CycleEvidence]) -> tuple[float | None, int, int]:
    graded = [grade for cycle in window for grade in cycle.notifications]
    if not graded:
        return None, 0, 0
    useful = sum(1 for grade in graded if grade.grade in USEFUL_GRADES)
    return useful / len(graded), useful, len(graded)


def _criteria_cycle_count(
    cycles: Sequence[CycleEvidence], criteria: AcceptanceCriteria
) -> CriterionResult:
    consecutive = len(_trailing_consecutive(cycles))
    required = int(criteria.required_cycles)
    if consecutive >= required:
        return CriterionResult(
            "seven_consecutive_daily_cycles",
            PASS,
            f"{consecutive} consecutive daily cycles (required {required})",
        )
    return CriterionResult(
        "seven_consecutive_daily_cycles",
        PENDING,
        f"{consecutive} consecutive daily cycles out of the required {required}",
    )


def _hard_safety_criteria(
    window: Sequence[CycleEvidence], criteria: AcceptanceCriteria
) -> list[CriterionResult]:
    results: list[CriterionResult] = []
    if not window:
        for name, _attribute, label in (
            ("sqlite_integrity", "integrity_ok", "integrity check"),
            ("no_duplicate_issues", "duplicate_issues", "duplicate Issues"),
            ("no_budget_overruns", "budget_overruns", "budget overruns"),
            ("no_concurrent_state_conflicts", "state_conflicts", "concurrent state conflicts"),
            ("no_secret_exposures", "secret_exposures", "exposed secrets"),
        ):
            results.append(
                CriterionResult(name, PENDING, f"no evaluated cycles yet; {label} unproven")
            )
        return results
    checks = (
        ("sqlite_integrity", "integrity_ok", "cycles with a failed integrity check"),
        ("no_duplicate_issues", "duplicate_issues", "duplicate Issues"),
        ("no_budget_overruns", "budget_overruns", "budget overruns"),
        ("no_concurrent_state_conflicts", "state_conflicts", "concurrent state conflicts"),
        ("no_secret_exposures", "secret_exposures", "exposed secrets"),
    )
    for name, attribute, label in checks:
        if attribute == "integrity_ok":
            violations = sum(1 for cycle in window if not cycle.integrity_ok)
        else:
            violations = _sum(window, attribute)
        status = PASS if violations == 0 else FAIL
        detail = f"0 {label}" if violations == 0 else f"{violations} {label}"
        results.append(CriterionResult(name, status, f"{detail} across {len(window)} cycles"))
    return results


def _silent_day_criterion(window: Sequence[CycleEvidence]) -> CriterionResult:
    if not window:
        return CriterionResult(
            "silent_day_behaviour", PENDING, "no evaluated cycles yet; silent days unproven"
        )
    violations = [
        cycle.run_id
        for cycle in window
        if cycle.issues_created == 0
        and not cycle.notifications
        and cycle.ungraded_notifications == 0
        and cycle.result != SILENT_RESULT
    ]
    if violations:
        return CriterionResult(
            "silent_day_behaviour",
            FAIL,
            "cycles with no findings that did not end as SUCCESS_NO_FINDINGS: "
            + ", ".join(violations),
        )
    silent = [
        cycle.run_id
        for cycle in window
        if cycle.issues_created == 0 and not cycle.notifications and cycle.result == SILENT_RESULT
    ]
    return CriterionResult(
        "silent_day_behaviour",
        PASS,
        f"{len(silent)} silent day(s) ended as {SILENT_RESULT} with no Issue",
    )


def _grading_criterion(window: Sequence[CycleEvidence], criteria: AcceptanceCriteria) -> list[CriterionResult]:
    ungraded = _sum(window, "ungraded_notifications")
    rate, useful, total = _useful_discovery_rate(window)
    results: list[CriterionResult] = []
    if total == 0:
        results.append(
            CriterionResult("useful_discovery_rate", PENDING, "no graded notifications yet")
        )
    elif ungraded:
        results.append(
            CriterionResult(
                "useful_discovery_rate",
                PENDING,
                f"{ungraded} notified repository/repositories still ungraded "
                f"({useful}/{total} graded useful so far)",
            )
        )
    else:
        floor = float(criteria.useful_discovery_rate_floor)
        status = PASS if rate is not None and rate >= floor else FAIL
        results.append(
            CriterionResult(
                "useful_discovery_rate",
                status,
                f"useful discovery rate {rate:.0%} GOOD+MAYBE over {total} notified repositories "
                f"(floor {floor:.0%})",
            )
        )

    exceptional_bad = [
        grade
        for cycle in window
        for grade in cycle.notifications
        if grade.score >= int(criteria.exceptional_threshold) and grade.grade == GRADE_BAD
    ]
    if not window:
        results.append(
            CriterionResult(
                "exceptional_calibration", PENDING, "no evaluated cycles yet; calibration unproven"
            )
        )
    elif exceptional_bad:
        results.append(
            CriterionResult(
                "exceptional_calibration",
                FAIL,
                "exceptional (>= 85) findings graded BAD: "
                + ", ".join(str(grade.github_repo_id) for grade in exceptional_bad),
            )
        )
    else:
        results.append(
            CriterionResult(
                "exceptional_calibration",
                PASS,
                f"no BAD finding at or above {int(criteria.exceptional_threshold)} points",
            )
        )
    return results


def _production_cycle_criterion(
    window: Sequence[CycleEvidence], criteria: AcceptanceCriteria
) -> CriterionResult:
    if not window:
        return CriterionResult(
            "production_publication_cycles",
            PENDING,
            "no cycles evaluated yet; live publication unproven",
        )
    dry = [cycle.run_id for cycle in window if cycle.dry_run]
    if not criteria.require_live_cycles:
        return CriterionResult(
            "production_publication_cycles",
            PASS,
            "dry-run cycles accepted by configuration",
        )
    if dry:
        return CriterionResult(
            "production_publication_cycles",
            PENDING,
            f"dry-run cycles cannot prove live publication: {', '.join(dry)}",
        )
    return CriterionResult(
        "production_publication_cycles", PASS, f"{len(window)} non-dry-run cycle(s)"
    )


def evaluate_acceptance(
    cycles: Sequence[CycleEvidence],
    *,
    criteria: AcceptanceCriteria | None = None,
) -> AcceptanceReport:
    """Evaluate the V1 acceptance gate over the supplied cycle evidence."""

    rules = criteria or AcceptanceCriteria()
    window = _window(cycles, rules)
    results: list[CriterionResult] = [_criteria_cycle_count(cycles, rules)]
    results.extend(_hard_safety_criteria(window, rules))
    results.append(_silent_day_criterion(window))
    results.extend(_grading_criterion(window, rules))
    results.append(_production_cycle_criterion(window, rules))

    blocking = tuple(item.detail for item in results if item.status == FAIL)
    if blocking:
        status = STATUS_NOT_ACCEPTED
    elif any(item.status == PENDING for item in results):
        status = STATUS_PENDING
        blocking = tuple(item.detail for item in results if item.status == PENDING)
    else:
        status = STATUS_ACCEPTED

    rate, useful, total = _useful_discovery_rate(window)
    metrics: dict[str, Any] = {
        "cycles_observed": len(cycles),
        "consecutive_cycles": len(_trailing_consecutive(cycles)),
        "window_cycles": len(window),
        "notified_repositories": total,
        "useful_notifications": useful,
        "useful_discovery_rate": rate,
        "issues_created": _sum(window, "issues_created"),
        "dry_run_cycles": sum(1 for cycle in window if cycle.dry_run),
        "ungraded_notifications": _sum(window, "ungraded_notifications"),
        "llm_calls": _sum(window, "llm_calls"),
        "llm_cache_hits": _sum(window, "llm_cache_hits"),
        "llm_cost": round(sum(float(cycle.llm_cost or 0.0) for cycle in window), 6),
        "candidates_discovered": sum(
            int(cycle.stage_counts.get("discovered", 0) or 0) for cycle in window
        ),
        "candidates_light_analyzed": sum(
            int(cycle.stage_counts.get("light_analyzed", 0) or 0) for cycle in window
        ),
        "candidates_deep_analyzed": sum(
            int(cycle.stage_counts.get("deep_analyzed", 0) or 0) for cycle in window
        ),
        "candidates_reported": sum(
            int(cycle.stage_counts.get("reported", 0) or 0) for cycle in window
        ),
    }
    if window:
        per_cycle_cost = sum(float(cycle.llm_cost or 0.0) for cycle in window) / len(window)
        metrics["projected_monthly_llm_cost"] = round(per_cycle_cost * 30, 6)
    if window:
        metrics["window_start"] = window[0].run_date.isoformat()
        metrics["window_end"] = window[-1].run_date.isoformat()

    return AcceptanceReport(status=status, criteria=tuple(results), metrics=metrics, blocking=blocking)


# -- rendering ------------------------------------------------------------


def render_acceptance_markdown(report: AcceptanceReport) -> str:
    """Render the acceptance report; the last line is the single STATUS= line."""

    lines = [
        "# GitHub Hidden Gems V1 — acceptance report",
        "",
        f"Generated at: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "## Criteria",
        "",
        "| Criterion | Status | Evidence |",
        "|---|---|---|",
    ]
    for item in report.criteria:
        lines.append(f"| `{item.name}` | {item.status} | {item.detail} |")
    lines.extend(["", "## Metrics", "", "| Metric | Value |", "|---|---|"])
    for key in sorted(report.metrics):
        value = report.metrics[key]
        lines.append(f"| `{key}` | {'n/a' if value is None else value} |")
    if report.blocking:
        lines.extend(["", "## Blocking / pending reasons", ""])
        for reason in report.blocking:
            lines.append(f"- {reason}")
    lines.extend(
        [
            "",
            "## Status",
            "",
            "The status below is derived only from persisted run evidence; seven real",
            "consecutive daily cycles (plus human grading of every notified repository)",
            "are required before `V1_ACCEPTED` can appear.",
            "",
            f"STATUS={report.status}",
        ]
    )
    return "\n".join(lines) + "\n"


# -- evidence loading -----------------------------------------------------


def cycles_from_history(
    store: Any,
    *,
    limit: int = 30,
    gradings: Mapping[int, NotificationGrade] | Sequence[NotificationGrade] | None = None,
) -> list[CycleEvidence]:
    """Rebuild cycle evidence from the canonical SQLite history (read-only).

    Only what the database can prove is derived; human grading is supplied
    separately and an ungraded notification keeps the gate pending.
    """

    grade_by_repo = _index_gradings(gradings)
    runs = list(store.recent_runs(limit=limit))
    notifications = list(getattr(store, "recent_notifications", lambda limit=200: [])(limit=200))

    run_ids = {str(row["run_id"]) for row in runs}
    by_run: dict[str, list[Mapping[str, Any]]] = {run_id: [] for run_id in run_ids}
    issue_numbers: dict[int, set[str]] = {}
    for row in notifications:
        run_id = str(row.get("run_id") or "")
        if run_id in by_run:
            by_run[run_id].append(row)
        issue_number = row.get("issue_number")
        if issue_number is not None:
            issue_numbers.setdefault(int(issue_number), set()).add(str(row.get("run_id") or ""))

    duplicate_issue_numbers = {
        number for number, run_ids_for_issue in issue_numbers.items() if len(run_ids_for_issue) > 1
    }

    cycles: list[CycleEvidence] = []
    for row in runs:
        run_id = str(row["run_id"])
        usage = _as_mapping(row.get("usage"))
        errors = _as_sequence(row.get("errors"))
        graded: list[NotificationGrade] = []
        ungraded = 0
        for notification in by_run.get(run_id, []):
            repo_id = int(notification["github_repo_id"])
            grade = grade_by_repo.get(repo_id)
            if grade is None:
                ungraded += 1
                continue
            graded.append(
                NotificationGrade(
                    github_repo_id=repo_id,
                    grade=grade.grade,
                    score=int(notification.get("score") or grade.score),
                    note=grade.note,
                )
            )
        issue_number = row.get("issue_number")
        cycles.append(
            CycleEvidence(
                run_id=run_id,
                run_date=_run_date(row),
                result=str(row.get("result") or "PARTIAL_SUCCESS"),
                dry_run=bool(row.get("dry_run")),
                integrity_ok=not any("integrity" in error.lower() for error in errors),
                issues_created=1 if issue_number else 0,
                duplicate_issues=1 if issue_number is not None and int(issue_number) in duplicate_issue_numbers else 0,
                budget_overruns=_budget_overruns(usage),
                state_conflicts=sum(1 for error in errors if "stateconflict" in error.lower()),
                secret_exposures=sum(1 for error in errors if _looks_like_secret(error)),
                notifications=tuple(graded),
                ungraded_notifications=ungraded,
                llm_calls=int(usage.get("calls_made") or 0),
                llm_cache_hits=int(usage.get("cache_hits") or 0),
                llm_cost=float(usage.get("cost") or 0.0),
                stage_counts=_stage_counts(usage),
            )
        )
    return cycles


def load_gradings(source: Any) -> dict[int, NotificationGrade]:
    """Load human gradings from a mapping or a YAML/JSON payload."""

    if source is None:
        return {}
    payload = source
    if isinstance(source, (str, bytes)) or hasattr(source, "read_text"):
        import json
        from pathlib import Path

        text = Path(source).read_text(encoding="utf-8")
        payload = json.loads(text) if text.lstrip().startswith("{") else _load_yaml(text)
    if isinstance(payload, Mapping) and "gradings" in payload:
        payload = payload["gradings"]
    entries: list[Any] = []
    if isinstance(payload, Mapping):
        entries = [
            {"github_repo_id": key, **(value if isinstance(value, Mapping) else {"grade": value})}
            for key, value in payload.items()
        ]
    elif isinstance(payload, Sequence):
        entries = list(payload)
    gradings: dict[int, NotificationGrade] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise AcceptanceError(f"invalid grading entry: {entry!r}")
        repo_id = entry.get("github_repo_id", entry.get("repo_id"))
        if repo_id is None:
            raise AcceptanceError(f"grading entry without github_repo_id: {entry!r}")
        gradings[int(repo_id)] = NotificationGrade(
            github_repo_id=int(repo_id),
            grade=str(entry.get("grade") or "").upper(),
            score=int(entry.get("score") or 0),
            note=str(entry.get("note") or ""),
        )
    return gradings


# -- internal helpers -----------------------------------------------------


def _index_gradings(
    gradings: Mapping[int, NotificationGrade] | Sequence[NotificationGrade] | None,
) -> dict[int, NotificationGrade]:
    if gradings is None:
        return {}
    if isinstance(gradings, Mapping):
        return {int(key): value for key, value in gradings.items()}
    return {int(item.github_repo_id): item for item in gradings}


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        import json

        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


def _as_sequence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
        except ValueError:
            return (value,)
        return _as_sequence(parsed)
    if isinstance(value, Sequence):
        return tuple(str(item) for item in value)
    return (str(value),)


def _run_date(row: Mapping[str, Any]) -> date:
    raw = str(row.get("started_at") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError as exc:  # pragma: no cover - malformed persisted evidence
        raise AcceptanceError(f"invalid run start timestamp: {raw!r}") from exc


def _budget_overruns(usage: Mapping[str, Any]) -> int:
    overruns = 0
    calls = usage.get("calls_made")
    maximum = usage.get("max_calls")
    if isinstance(calls, int) and isinstance(maximum, int) and maximum and calls > maximum:
        overruns += 1
    return overruns


def _stage_counts(usage: Mapping[str, Any]) -> dict[str, int]:
    """Per-stage candidate counters persisted inside the run usage payload."""

    raw = usage.get("counts")
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(key): int(value)
        for key, value in raw.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


_SECRET_MARKERS = ("ghp_", "gho_", "github_pat_", "sk-")


def _looks_like_secret(text: str) -> bool:
    return any(marker in text for marker in _SECRET_MARKERS)


def _load_yaml(text: str) -> Any:
    import yaml

    return yaml.safe_load(text)
