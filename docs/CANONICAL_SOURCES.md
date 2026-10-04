# Canonical sources

This document tells humans and agents how to resolve conflicts between implementation, contracts, plans, validation notes, and research material in GitHub Hidden Gems.

## Authority order

| Priority | Source | Role |
|---:|---|---|
| 1 | Current source code + tests | Executable behavior and enforced invariants |
| 2 | `docs/superpowers/contracts/v1-module-interfaces.md` | Current module boundaries/interfaces |
| 3 | `docs/operations.md` | Day-to-day operation, secrets, dry-run/live behavior, recovery |
| 4 | Current files under `docs/validation/` | Evidence about validation gates and observed acceptance state |
| 5 | `docs/superpowers/specs/2026-09-14-github-hidden-gems-design.md` | Frozen V1 architectural intent |
| 6 | `docs/superpowers/plans/` | Historical implementation planning; non-authoritative when implementation has moved on |
| 7 | `docs/research/` and Research Intake | Research context / external hypotheses; never production authority by themselves |

## Conflict resolution

If two sources disagree:

1. prefer enforced code/tests over prose;
2. prefer current contracts over implementation plans;
3. prefer current validation state over aspirational acceptance language;
4. treat historical plans and research notes as explanatory context, not as current behavior.

## Production / research boundary

Research Intake, MoltBook findings, and isolated experiments may propose hypotheses or falsifiers. They have **no automatic promotion path** into production. Any production change requires a separate reviewed change in this repository and must pass the relevant validation gates.

## LLM boundary

DeepSeek/LLM enrichment is optional, schema-bounded, cached, and budgeted. `LLM_ENABLED=false` must leave the core pipeline functional. LLM output is evidence-adjacent enrichment, not unrestricted authority.

## Acceptance status

Do not infer that V1 is accepted merely because implementation or dry-run evidence exists. Use the current validation documents—especially `docs/validation/v1-acceptance.md` and associated gradings—as the authoritative acceptance-state evidence.
