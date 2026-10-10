"""Adversarial contracts for the isolated, non-executing policy combiner."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from itertools import permutations, product

import pytest

from hidden_gems.experimental.policy_monotonic import (
    MAX_RULES,
    PolicyDecision,
    PolicyRule,
    Verdict,
    evaluate_policy,
    most_restrictive,
)


VALUES = (Verdict.ALLOW, Verdict.ASK, Verdict.DENY)
RANK = {Verdict.ALLOW: 0, Verdict.ASK: 1, Verdict.DENY: 2}


def checked(*rules: PolicyRule, state: dict | None = None, seed: Verdict = Verdict.ALLOW):
    return evaluate_policy(
        rules,
        required_rules=tuple(rule.name for rule in rules),
        state=state,
        seed=seed,
    )


@pytest.mark.parametrize("left,right", list(product(VALUES, repeat=2)))
def test_join_is_monotonic_commutative_and_idempotent(left, right):
    outcome = most_restrictive(left, right)
    assert RANK[outcome] >= max(RANK[left], RANK[right])
    assert most_restrictive(right, left) is outcome
    assert most_restrictive(left, left) is left


@pytest.mark.parametrize("a,b,c", list(product(VALUES, repeat=3)))
def test_join_is_associative_and_evaluation_never_weakens(a, b, c):
    assert most_restrictive(most_restrictive(a, b), c) is most_restrictive(
        a, most_restrictive(b, c)
    )
    decision = checked(PolicyRule("one", a), PolicyRule("two", b), PolicyRule("three", c))
    assert RANK[decision.verdict] >= max(RANK[a], RANK[b], RANK[c])


def test_missing_manifest_or_empty_manifest_denies():
    assert evaluate_policy(()).verdict is Verdict.DENY
    assert evaluate_policy((), required_rules=()).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("rule", Verdict.ALLOW)]).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("rule", Verdict.ALLOW)], required_rules=()).verdict is Verdict.DENY


def test_full_manifest_required_and_extraneous_rules_refused():
    rules = (PolicyRule("auth", Verdict.ALLOW), PolicyRule("budget", Verdict.ALLOW))
    assert evaluate_policy(rules, required_rules=("auth",)).verdict is Verdict.DENY
    assert evaluate_policy(rules, required_rules=("auth", "budget", "unknown")).verdict is Verdict.DENY
    assert evaluate_policy(rules, required_rules=("auth", "auth")).verdict is Verdict.DENY
    assert evaluate_policy(rules, required_rules=["auth", "budget"]).verdict is Verdict.DENY
    assert evaluate_policy(rules, required_rules=("auth", "budget")).verdict is Verdict.ALLOW


def test_terminal_seed_deny_does_not_iterate():
    class Exploding:
        def __iter__(self):
            raise AssertionError("an external iterator executed")
    assert evaluate_policy(Exploding(), seed=Verdict.DENY) == PolicyDecision(
        Verdict.DENY, (), "terminal_seed_deny"
    )


def test_hostile_iterable_denied_before_any_iterator_call():
    class Hostile:
        calls = 0
        def __iter__(self):
            self.calls += 1
            raise AssertionError("external code executed")
    foreign = Hostile()
    result = evaluate_policy(foreign, required_rules=("a",))
    assert result.verdict is Verdict.DENY
    assert result.reason == "non_inert_rule_container"
    assert foreign.calls == 0


def test_terminal_rule_deny_skips_later_rules():
    decision = checked(
        PolicyRule("first", Verdict.ALLOW),
        PolicyRule("refused", Verdict.DENY),
        PolicyRule("later", Verdict.ALLOW),
    )
    assert decision == PolicyDecision(Verdict.DENY, ("first", "refused"), "terminal_rule_deny")


def test_state_requires_explicit_named_key_and_values():
    good = PolicyRule("budget", Verdict.ASK, requires_state=True, required_state_key="budget")
    assert checked(good).verdict is Verdict.DENY
    assert checked(good, state={}).verdict is Verdict.DENY
    assert checked(good, state={"budget": None}).verdict is Verdict.DENY
    assert checked(good, state={"budget": 1}).verdict is Verdict.ASK
    assert checked(good, state={"budget": 3.0}).verdict is Verdict.ASK
    assert checked(PolicyRule("budget", Verdict.ALLOW, requires_state=True), state={}).verdict is Verdict.DENY
    assert checked(PolicyRule("budget", Verdict.ALLOW, required_state_key="budget"), state={"budget": 1}).verdict is Verdict.DENY


@pytest.mark.parametrize("value", [None, {}, [], object(), float("nan"), float("inf"), float("-inf"), "", "  "])
def test_invalid_state_values_deny(value):
    p = PolicyRule("budget", Verdict.ALLOW, True, "budget")
    assert checked(p, state={"budget": value}).verdict is Verdict.DENY


def test_executable_mapping_is_rejected_without_visiting_keys():
    class HostileMap(dict):
        def __contains__(self, key):
            raise AssertionError("malicious state mapping invoked")
        def items(self):
            raise AssertionError("malicious state mapper invoked")
    r = PolicyRule("state", Verdict.ALLOW, True, "state")
    assert checked(r, state=HostileMap({"state": 1})).verdict is Verdict.DENY


@pytest.mark.parametrize("bad", [None, "ALLOW", "deny", 1, True])
def test_invalid_seed_or_rule_verdict_denies(bad):
    assert evaluate_policy((), seed=bad).verdict is Verdict.DENY
    assert evaluate_policy(
        (PolicyRule("unknown", bad),), required_rules=("unknown",)
    ).verdict is Verdict.DENY
    with pytest.raises(TypeError):
        most_restrictive(Verdict.ALLOW, bad)


def test_invalid_rules_fail_closed():
    assert evaluate_policy([object()], required_rules=("a",)).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("", Verdict.ALLOW)], required_rules=("",)).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("x", Verdict.ALLOW), PolicyRule("x", Verdict.ALLOW)], required_rules=("x",)).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("bad", Verdict.ALLOW, requires_state="true")], required_rules=("bad",)).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("a", Verdict.ALLOW)], required_rules=("a",) * (MAX_RULES + 1)).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("a", Verdict.ALLOW)], required_rules=("a",), state={"x": object()}).verdict is Verdict.DENY


def test_deny_cannot_be_revoked_by_reordering_or_replay():
    rules = (
        PolicyRule("perm", Verdict.ALLOW),
        PolicyRule("budget", Verdict.ASK, True, "budget"),
        PolicyRule("restricted", Verdict.DENY),
    )
    for arrangement in permutations(rules):
        a = evaluate_policy(arrangement, required_rules=("perm", "budget", "restricted"), state={"budget": 10})
        b = evaluate_policy(arrangement, required_rules=("perm", "budget", "restricted"), state={"budget": 10})
        assert a == b
        assert a.verdict is Verdict.DENY


def test_result_immutable_without_execution_surface():
    decision = checked(PolicyRule("confirmation", Verdict.ASK))
    assert decision.verdict is Verdict.ASK
    assert not hasattr(decision, "execute")
    assert not hasattr(decision, "commit")
    assert not hasattr(decision, "allow_tool")
    with pytest.raises(FrozenInstanceError):
        decision.verdict = Verdict.ALLOW
    assert json.dumps({"verdict": decision.verdict.value, "reason": decision.reason}, sort_keys=True) == (
        '{"reason": "composed", "verdict": "ASK"}'
    )
