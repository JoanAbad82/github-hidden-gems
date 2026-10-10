"""Experimental, side-effect-free composition of agent permission verdicts.

Not connected to GitHub, Codex, Desktop Commander, or any executor.
The standalone policy is inspired by a general monotonic permission principle,
not a port of Orca's guardrail engine. A DENY decision can never be weakened.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


_RANK = {Verdict.ALLOW: 0, Verdict.ASK: 1, Verdict.DENY: 2}


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """A previously evaluated synthetic rule, with no executable callback."""

    name: str
    verdict: Verdict
    requires_state: bool = False
    required_state_key: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    verdict: Verdict
    evaluated_rules: tuple[str, ...]
    reason: str


def most_restrictive(left: Verdict, right: Verdict) -> Verdict:
    """Join two valid verdicts, never reducing restrictions."""

    if type(left) is not Verdict or type(right) is not Verdict:
        raise TypeError("unknown verdict; fail closed at evaluate_policy boundary")
    return left if _RANK[left] >= _RANK[right] else right


def evaluate_policy(
    rules: tuple[PolicyRule, ...] | list[PolicyRule],
    *,
    seed: Verdict = Verdict.ALLOW,
    state: Mapping[str, object] | None = None,
) -> PolicyDecision:
    """Pure decision only; cannot call tools or perform actions.

    A DENY seed terminates before accessing rules. Any state requirement
    without explicit state blocks the whole evaluation before processing
    even the earlier rules. Invalid policy data also fails closed.
    The caller must separately enforce the decision; this lab function
    is deliberately NOT an authorization or execution boundary.
    """

    if type(seed) is not Verdict:
        return PolicyDecision(Verdict.DENY, (), "invalid_seed")
    if seed is Verdict.DENY:
        return PolicyDecision(Verdict.DENY, (), "terminal_seed_deny")
    try:
        ordered = tuple(rules)
    except (TypeError, ValueError):
        return PolicyDecision(Verdict.DENY, (), "invalid_rules")
    names: set[str] = set()
    for item in ordered:
        if type(item) is not PolicyRule:
            return PolicyDecision(Verdict.DENY, (), "invalid_rule")
        if not isinstance(item.name, str) or not item.name.strip() or item.name in names:
            return PolicyDecision(Verdict.DENY, (), "invalid_or_duplicate_rule_name")
        names.add(item.name)
        if type(item.verdict) is not Verdict:
            return PolicyDecision(Verdict.DENY, (), "invalid_rule_verdict")
        if type(item.requires_state) is not bool:
            return PolicyDecision(Verdict.DENY, (), "invalid_state_requirement")
        if item.required_state_key is not None and (
            not isinstance(item.required_state_key, str) or not item.required_state_key
        ):
            return PolicyDecision(Verdict.DENY, (), "invalid_state_key")
        if item.required_state_key is not None and not item.requires_state:
            return PolicyDecision(Verdict.DENY, (), "undeclared_state_dependency")

    if state is not None and not isinstance(state, Mapping):
        return PolicyDecision(Verdict.DENY, (), "invalid_state")
    for item in ordered:
        if item.requires_state and state is None:
            return PolicyDecision(Verdict.DENY, (), "required_state_missing")
        if item.required_state_key is not None and item.required_state_key not in state:
            return PolicyDecision(Verdict.DENY, (), "required_state_key_missing")

    verdict = seed
    evaluated: list[str] = []
    for item in ordered:
        verdict = most_restrictive(verdict, item.verdict)
        evaluated.append(item.name)
        if verdict is Verdict.DENY:
            return PolicyDecision(verdict, tuple(evaluated), "terminal_rule_deny")
    return PolicyDecision(verdict, tuple(evaluated), "composed")
