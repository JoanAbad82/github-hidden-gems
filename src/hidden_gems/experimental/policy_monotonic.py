"""Experimental, side-effect-free composition of synthetic agent verdicts.

No execution or authorisation boundary. Requires an *externally trusted*
complete rule manifest to avoid an empty or incomplete rule set permitting
actions. Runtime callers MUST independently authenticate policies and state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    ASK = "ASK"
    DENY = "DENY"


_RANK = {Verdict.ALLOW: 0, Verdict.ASK: 1, Verdict.DENY: 2}
MAX_RULES = 128
MAX_STATE_KEYS = 128


@dataclass(frozen=True, slots=True)
class PolicyRule:
    """A declarative, already-evaluated rule; never a callback."""

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
    """Associative, commutative, idempotent join. DENY is terminal."""

    if type(left) is not Verdict or type(right) is not Verdict:
        raise TypeError("invalid verdict; caller must fail closed")
    return left if _RANK[left] >= _RANK[right] else right


def _inert_state(state: object) -> bool:
    """Only exact inert built-ins: never execute custom Mapping methods."""

    if type(state) is not dict or len(state) > MAX_STATE_KEYS:
        return False
    for key, value in state.items():
        if type(key) is not str or not key.strip():
            return False
        if type(value) is str and value.strip():
            continue
        if type(value) is bool:
            continue
        if type(value) is int:
            continue
        if type(value) is float and math.isfinite(value):
            continue
        return False
    return True


def evaluate_policy(
    rules: tuple[PolicyRule, ...] | list[PolicyRule],
    *,
    required_rules: tuple[str, ...] | None = None,
    seed: Verdict = Verdict.ALLOW,
    state: dict[str, object] | None = None,
) -> PolicyDecision:
    """Pure evaluation; never use this output to authorize an action.

    A complete, externally trusted rule manifest must be supplied. Empty
    manifests, omissions, duplicates, invalid objects and missing state deny.
    The caller is responsible for authenticating required_rules and freshness
    of state. This module does not evaluate budget sufficiency or permission
    provenance and cannot act as an executor's permission gate.
    """

    deny = lambda reason: PolicyDecision(Verdict.DENY, (), reason)
    if type(seed) is not Verdict:
        return deny("invalid_seed")
    if seed is Verdict.DENY:
        return deny("terminal_seed_deny")
    if type(required_rules) is not tuple or not (1 <= len(required_rules) <= MAX_RULES):
        return deny("missing_or_invalid_rule_manifest")
    if any(type(name) is not str or not name.strip() for name in required_rules):
        return deny("invalid_rule_manifest_name")
    if len(set(required_rules)) != len(required_rules):
        return deny("duplicate_rule_manifest_name")
    if type(rules) is not tuple and type(rules) is not list:
        return deny("non_inert_rule_container")
    if not (1 <= len(rules) <= MAX_RULES):
        return deny("empty_or_oversized_rules")

    ordered = tuple(rules)
    names: set[str] = set()
    for rule in ordered:
        if type(rule) is not PolicyRule:
            return deny("invalid_rule")
        if type(rule.name) is not str or not rule.name.strip() or rule.name in names:
            return deny("invalid_or_duplicate_rule_name")
        names.add(rule.name)
        if type(rule.verdict) is not Verdict:
            return deny("invalid_rule_verdict")
        if type(rule.requires_state) is not bool:
            return deny("invalid_state_requirement")
        if rule.required_state_key is not None and (
            type(rule.required_state_key) is not str or not rule.required_state_key.strip()
        ):
            return deny("invalid_state_key")
        if rule.requires_state != (rule.required_state_key is not None):
            return deny("unbounded_or_undeclared_state_dependency")
    if names != set(required_rules):
        return deny("incomplete_or_extra_rule_set")

    if state is not None and not _inert_state(state):
        return deny("invalid_or_executable_state")
    for rule in ordered:
        if rule.requires_state:
            if state is None:
                return deny("required_state_missing")
            if rule.required_state_key not in state:
                return deny("required_state_key_missing")
            # _inert_state rejected None, NaN, nested, and custom instances.
            # Value-specific constraints (budgets, policy authenticity, age)
            # are NOT checked here and must be proven by an external system.

    verdict = seed
    evaluated: list[str] = []
    for rule in ordered:
        verdict = most_restrictive(verdict, rule.verdict)
        evaluated.append(rule.name)
        if verdict is Verdict.DENY:
            return PolicyDecision(verdict, tuple(evaluated), "terminal_rule_deny")
    return PolicyDecision(verdict, tuple(evaluated), "composed")
