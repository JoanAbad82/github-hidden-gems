"""Contract tests for the isolated, declarative policy experiment."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from itertools import permutations, product
import json

import pytest

from hidden_gems.experimental.policy_monotonic import (
    PolicyDecision, PolicyRule, Verdict, evaluate_policy, most_restrictive,
)


VALUES = (Verdict.ALLOW, Verdict.ASK, Verdict.DENY)
RANK = {Verdict.ALLOW: 0, Verdict.ASK: 1, Verdict.DENY: 2}


@pytest.mark.parametrize("left,right", list(product(VALUES, repeat=2)))
def test_pairwise_monotonic_commutative_idempotent(left, right):
    outcome = most_restrictive(left, right)
    assert RANK[outcome] >= max(RANK[left], RANK[right])
    assert most_restrictive(right, left) is outcome
    assert most_restrictive(left, left) is left


@pytest.mark.parametrize("a,b,c", list(product(VALUES, repeat=3)))
def test_associative_and_composition_never_weakens(a, b, c):
    assert most_restrictive(most_restrictive(a, b), c) is most_restrictive(
        a, most_restrictive(b, c)
    )
    decision = evaluate_policy(
        [PolicyRule("one", a), PolicyRule("two", b), PolicyRule("three", c)]
    )
    assert RANK[decision.verdict] >= max(RANK[a], RANK[b], RANK[c])


def test_terminal_seed_deny_never_iterates_rules():
    class ExplodingRules:
        def __iter__(self):
            raise AssertionError("DENY seeded evaluation touched rules")
    assert evaluate_policy(ExplodingRules(), seed=Verdict.DENY) == PolicyDecision(
        Verdict.DENY, (), "terminal_seed_deny"
    )


def test_terminal_rule_deny_skips_later_rules():
    result = evaluate_policy([
        PolicyRule("allowed", Verdict.ALLOW),
        PolicyRule("refused", Verdict.DENY),
        PolicyRule("later", Verdict.ASK),
    ])
    assert result.verdict is Verdict.DENY
    assert result.evaluated_rules == ("allowed", "refused")


def test_stateful_requirement_fails_closed_before_evaluation():
    result = evaluate_policy([
        PolicyRule("first", Verdict.ALLOW),
        PolicyRule("budget", Verdict.ALLOW, requires_state=True, required_state_key="budget"),
    ])
    assert result == PolicyDecision(Verdict.DENY, (), "required_state_missing")
    assert evaluate_policy([
        PolicyRule("budget", Verdict.ALLOW, requires_state=True, required_state_key="budget")
    ], state={}) == PolicyDecision(Verdict.DENY, (), "required_state_key_missing")
    allowed = evaluate_policy([
        PolicyRule("budget", Verdict.ASK, requires_state=True, required_state_key="budget")
    ], state={"budget": 1})
    assert allowed.verdict is Verdict.ASK


@pytest.mark.parametrize("bad", [None, "ALLOW", "deny", 1, True])
def test_invalid_seed_and_verdict_fail_closed(bad):
    assert evaluate_policy([], seed=bad).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("unknown", bad)]).verdict is Verdict.DENY
    with pytest.raises(TypeError):
        most_restrictive(Verdict.ALLOW, bad)


def test_duplicate_or_malformed_rules_fail_closed():
    assert evaluate_policy([PolicyRule("x", Verdict.ALLOW), PolicyRule("x", Verdict.ALLOW)]).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("", Verdict.ALLOW)]).verdict is Verdict.DENY
    assert evaluate_policy([object()]).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("bad", Verdict.ALLOW, requires_state="true")]).verdict is Verdict.DENY
    assert evaluate_policy([PolicyRule("bad", Verdict.ALLOW, required_state_key="budget")]).verdict is Verdict.DENY


def test_denials_never_revoked_when_permuted_or_replayed():
    policies = [
        PolicyRule("permission", Verdict.ALLOW),
        PolicyRule("budget", Verdict.ASK, True, "budget"),
        PolicyRule("restricted", Verdict.DENY),
    ]
    for arrangement in permutations(policies):
        a = evaluate_policy(arrangement, state={"budget": 10})
        b = evaluate_policy(arrangement, state={"budget": 10})
        assert a == b
        assert a.verdict is Verdict.DENY


def test_immutable_result_and_no_execution_surface():
    result = evaluate_policy((PolicyRule("needs-confirmation", Verdict.ASK),))
    assert result.verdict is Verdict.ASK
    assert not hasattr(result, "execute")
    assert not hasattr(result, "commit")
    assert not hasattr(result, "allow_tool")
    with pytest.raises(FrozenInstanceError):
        result.verdict = Verdict.ALLOW
    assert json.dumps({"verdict": result.verdict.value, "reason": result.reason}, sort_keys=True) == (
        '{"reason": "composed", "verdict": "ASK"}'
    )
