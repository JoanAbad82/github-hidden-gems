"""Validation machinery (SPEC_V1 section 13 / Task 18).

Read-only helpers that turn persisted run evidence into the V1 acceptance
report. Nothing in this package writes to SQLite, GitHub or the state branch.
"""

from .acceptance import (
    STATUS_ACCEPTED,
    STATUS_NOT_ACCEPTED,
    STATUS_PENDING,
    AcceptanceCriteria,
    AcceptanceReport,
    CriterionResult,
    CycleEvidence,
    NotificationGrade,
    cycles_from_history,
    evaluate_acceptance,
    load_gradings,
    render_acceptance_markdown,
)

__all__ = [
    "STATUS_ACCEPTED",
    "STATUS_NOT_ACCEPTED",
    "STATUS_PENDING",
    "AcceptanceCriteria",
    "AcceptanceReport",
    "CriterionResult",
    "CycleEvidence",
    "NotificationGrade",
    "cycles_from_history",
    "evaluate_acceptance",
    "load_gradings",
    "render_acceptance_markdown",
]
