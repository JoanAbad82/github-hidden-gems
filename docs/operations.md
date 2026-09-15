# GitHub Hidden Gems V1 — Operations Guide

This document describes how to run, validate, and operate the discovery
system. SPEC_V1 (`docs/superpowers/specs/2026-09-14-github-hidden-gems-design.md`)
is the binding authority; this guide only explains how to operate it.

## 1. Architecture in one paragraph

GitHub Actions (daily, `schedule` + `workflow_dispatch`) → Discovery Engine →
Hard Filter → Light Analyzer → Relationship Explorer (one hop) → Deep Analyzer →
optional DeepSeek enrichment → Hidden Gem Scorer → SQLite history → GitHub Issue.
SQLite is the canonical technical history; the GitHub Issue is the user-facing
archive and email is delivered through GitHub Notifications.

## 2. Command line

All commands print exactly one terminal `RESULT=<STATE>` line.

| Command | Meaning | Result states |
|---|---|---|
| `hidden-gems validate-config --root .` | Validate every configuration file and the frozen invariants before any network activity | `RESULT=CONFIG_VALID`, `RESULT=FAILED_CONFIGURATION` (exit 2) |
| `hidden-gems migrate --root . --db state/history.sqlite3` | Create/upgrade the SQLite schema | `RESULT=DB_MIGRATED`, `RESULT=FAILED_INTEGRITY` (exit 3) |
| `hidden-gems db-check --root . --db state/history.sqlite3` | Run `PRAGMA integrity_check` and schema validation | `RESULT=DB_VALID`, `RESULT=DB_INVALID` (exit 3) |
| `hidden-gems run --root . --db state/history.sqlite3` | One discovery run (dry-run by default; prints the run result) | `RESULT=SUCCESS`, `RESULT=SUCCESS_NO_FINDINGS`, `RESULT=PARTIAL_SUCCESS`, `RESULT=PARTIAL_SUCCESS_RATE_LIMIT`, `RESULT=FAILED_INTEGRITY`, `RESULT=FAILED_CONFIGURATION` |
| `hidden-gems run --root . --controlled-live` | Controlled-live gate: forced dry run with reduced limits (30 seen / 10 light / 3 deep / 2 LLM calls). Budget overrides may only lower a configured limit | same run results as `run`; never publishes an Issue |
| `hidden-gems validation-status --root . --db state/history.sqlite3 --gradings docs/validation/gradings.yml` | Read-only evaluation of the seven-cycle acceptance gate | `RESULT=VALIDATION_ACCEPTED` (exit 0), `RESULT=VALIDATION_NOT_ACCEPTED` (exit 1), `RESULT=VALIDATION_PENDING` (exit 2), `RESULT=FAILED_INTEGRITY` (exit 3) |

`--db` defaults to `<root>/state/history.sqlite3`.

## 3. Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | for live runs | Minimum-permission token used through the central GitHub client. No PAT in V1 unless a documented blocker exists. |
| `GITHUB_REPOSITORY` | for publication | `owner/repo` that owns the discovery Issue. |
| `NOTIFICATION_GITHUB_LOGIN` | optional | Assigns the Issue to the target account so GitHub sends the notification email. |
| `DRY_RUN` | optional | `true` (default) never creates or updates an Issue. `false` is only honoured together with `--live`. |
| `LLM_ENABLED` | optional | `false` (default) keeps the whole pipeline working without DeepSeek. |
| `DEEPSEEK_API_KEY` | only when LLM is enabled | Read from the environment by the provider; never logged, never stored in SQLite. |

Secrets belong in GitHub Actions Secrets (`DEEPSEEK_API_KEY`) and in the
automatic `GITHUB_TOKEN`. The DeepSeek key is never read from any other
configuration source.

## 4. Enabling the daily email notification

1. Open the repository that owns the discovery Issue.
2. `Watch` → `Custom` → enable `Issues` (this is what makes GitHub send the
   notification email to the watching account).
3. Set the repository variable `NOTIFICATION_GITHUB_LOGIN` to that account so
   the Issue is assigned to it when possible.
4. Optionally confirm your notification email under GitHub `Settings →
   Notifications → Email notification preferences`.

There is no external mail infrastructure: email delivery is GitHub's.

## 5. Running modes

- **Offline/unit**: `python -m pytest -m "not live"` — no network, no secrets.
- **Manual dry-run** (recommended for validation): in the Actions UI use
  `Run workflow` and keep `dry_run = true`.
- **Controlled live test**: `Workflow → daily-discovery → Run workflow` with
  `dry_run = false` after the deployment gate. Only one Issue per run is
  created, and only when at least one candidate reaches the notification
  threshold.
- **Scheduled production run**: happens only when the repository variable
  `HIDDEN_GEMS_SCHEDULED_LIVE=true`; otherwise scheduled runs stay in dry-run.

## 6. Budgets and cost protection

Budgets per run (`config/limits.yml`): 1,000 unique seen repositories, 200 light
analyses, 20 relationship seeds, 25 deep analyses. DeepSeek limits:
`MAX_LLM_CANDIDATES_PER_RUN`, `MAX_LLM_CALLS_PER_RUN`,
`MAX_INPUT_TOKENS_PER_REPO`, `MAX_OUTPUT_TOKENS_PER_REPO`,
`MAX_LLM_BUDGET_PER_RUN`.

GitHub API budget zones: GREEN keeps working; YELLOW stops non-essential work
(rotating and relationship-triggered searches); RED stops new GitHub work,
persists valid state and ends the run as `PARTIAL_SUCCESS_RATE_LIMIT`.

The bot never clones, installs, imports, builds, tests or runs candidate
repository code. Only static reads (README, tree, manifests, releases,
commits) are performed.

## 7. Recovery procedures

### Corrupted or suspicious SQLite

```bash
hidden-gems db-check --root . --db state/history.sqlite3   # expect RESULT=DB_VALID
```

If it reports `DB_INVALID`, restore the most recent file from the `state`
branch `backups/` directory (rotated, at most `state.max_backups` files) and
re-run `db-check`. A run that detects corruption ends as `FAILED_INTEGRITY`
and refuses to publish state.

### `PENDING_REPORT` state after a crash

The publish protocol is: generate `REPORT_FINGERPRINT` → persist
`PENDING_REPORT` and checkpoint → find or create the Issue by fingerprint →
register `REPORT_PUBLISHED` → integrity check → persist final state.

If a run crashes between creation and confirmation, simply re-run the same
workflow: the publisher looks up the existing Issue by fingerprint and adopts
it instead of creating a duplicate. Never hand-edit the state branch.

### Disabling the LLM

Set `LLM_ENABLED=false` (or unset `DEEPSEEK_API_KEY`). The pipeline continues
with deterministic scoring: relevance is capped by verified area evidence and
originality is limited to a conservative `0–4`.

### Rejected / noisy findings

Inspect `filter_decisions`, `scores`, `llm_analyses` and `notifications` in the
SQLite history. Every rejection carries a canonical reason code
(`REJECT_FORK`, `REJECT_ARCHIVED`, `REJECT_EMPTY`, `REJECT_TUTORIAL`,
`REJECT_TEMPLATE`, `REJECT_DEMO`, `REJECT_SPAM`, `REJECT_IRRELEVANT`,
`REJECT_LOW_MAX_SCORE`).

## 8. Validation stages

`UNIT → INTEGRATION → CONTROLLED LIVE → MULTI-DAY VALIDATION`.

Before `V1_ACCEPTED`, seven consecutive daily runs must show zero SQLite
corruption, zero exposed secrets, zero duplicate Issues, zero concurrent state
conflicts and zero budget overruns; notified repositories must reach a Useful
Discovery Rate of at least 70% `GOOD+MAYBE`.

### Controlled live gate (Task 17)

```bash
hidden-gems run --root . --db state/history.sqlite3 --controlled-live
```

`--controlled-live` lowers every budget below production, forces a dry run even
when `--live` is also present, and therefore can never create an Issue. Use it
for the first look at real GitHub data. `--max-light`, `--max-deep`,
`--max-raw-candidates` and `--max-llm-calls` accept individual reductions; a
value above the configured limit is rejected with `RESULT=FAILED_CONFIGURATION`.

### Acceptance gate (Task 18)

```bash
hidden-gems validation-status --root . --db state/history.sqlite3 \
  --gradings docs/validation/gradings.yml \
  --markdown docs/validation/v1-acceptance.md
```

The gate reads only persisted run/notification evidence and the human gradings
file. It returns `PENDING_MULTI_DAY_VALIDATION` until seven consecutive real
daily cycles exist and every notified repository is graded; an ungraded
notification, a dry-run-only window or a missing day keeps it pending, and any
hard-safety violation (corruption, duplicate Issue, budget overrun, concurrent
state conflict, exposed secret) fails it.
