# Controlled live test — 2026-09-15 (GitHub Hidden Gems V1, Task 17)

**Gate result:** offline and read-only live evidence complete; controlled
publication and email delivery are `PENDING_USER_VALIDATION`.

## 1. Scope and rulings for this run

- Real GitHub Issue creation is prohibited in this implementation run, so
  Task 17 steps 5–6 (controlled publication and idempotent re-run) are prepared
  and documented but **not executed**.
- The product DeepSeek credential is not available to the application, so live
  semantic enrichment is pending. The provider, schema validation, cache,
  budgets and their tests are implemented; nothing was fabricated.
- No candidate repository code was cloned, installed, imported, built, tested
  or executed at any point.

## 2. Offline evidence (executed)

| Step | Command | Result |
|---|---|---|
| Offline suite | `.venv/Scripts/python.exe -m pytest -m "not live" -q` | `445 passed, 3 deselected` |
| Config validation | `hidden-gems validate-config --root .` | `RESULT=CONFIG_VALID` (exit 0) |
| Schema migration | `hidden-gems migrate --root . --db state/history.sqlite3` | `RESULT=DB_MIGRATED` (exit 0) |
| DB integrity | `hidden-gems db-check --root . --db state/history.sqlite3` | `RESULT=DB_VALID` (exit 0) |
| Acceptance gate | `hidden-gems validation-status --root . --db state/history.sqlite3` | `STATUS=PENDING_MULTI_DAY_VALIDATION` (exit 2) |
| Whitespace | `git diff --check aed6ef0..HEAD` | clean |
| Secret scan | `git grep -I -E "ghp_|gho_|github_pat_|sk-|AKIA|BEGIN .*PRIVATE KEY"` and the same over `git log -p --all` | no matches in tracked files or history |

Reference-corpus calibration (offline, deterministic, no LLM):

| Metric | Value |
|---|---|
| Cases | 21 (frozen GOOD/MAYBE/BAD labels) |
| Notified | 7 |
| Useful Discovery Rate | 100% GOOD+MAYBE |
| Exceptional false positives | 0 |

## 3. Live read-only probe (executed: no token, no writes)

Command (worktree root):

```
RUN_LIVE_TESTS=1 .venv/Scripts/python.exe -m pytest tests/live -q
```

Observed: `3 passed`. The two live contract tests exercised, unauthenticated
and read-only:

1. `GET /search/repositories` — `total_count=37430`, `items=50`, response
   parsing bounded and correct.
2. `GET /repos/python/cpython` — metadata parsing correct, `stargazers_count`
   returned as an integer.

Rate-limit headers were parsed from the real response by the central client:

```
ZONE=YELLOW
{"limit": 10, "remaining": 7, "reset_at": "2026-09-15T15:10:42+00:00", "resource": "search", "search_remaining": 7, "zone": "YELLOW"}
```

Findings from the probe:

- The unauthenticated search bucket is 10 requests/hour; a real daily run must
  use `GITHUB_TOKEN` (available in Actions as `secrets.GITHUB_TOKEN`), where the
  search bucket is 30/minute.
- The client's rate-zone logic correctly reported `YELLOW` from live headers,
  which is the SPEC_V1 behaviour for a low remaining search budget.
- Only `GET` requests were issued. No Issue was created, no repository was
  cloned, no candidate code ran and no LLM call was made.

## 4. Reduced-limit controlled-live dry run (executed, token-less)

The controlled-live gate lowers every budget and forces a dry run, so it cannot
publish an Issue even if `--live` is passed:

```
hidden-gems run --root . --db state/history.sqlite3 --controlled-live
```

Executed on 2026-09-15 with the limits lowered further (`--max-light 3
--max-deep 1`) to stay inside the unauthenticated GitHub budget. Observed
terminal line: `RESULT=SUCCESS_NO_FINDINGS` (exit 0). Persisted run row
`RUN-20260915T152056Z`:

| Field | Value |
|---|---|
| started_at | `2026-09-15T15:20:56Z` |
| dry_run | `1` (no Issue can be created) |
| issue_number | `None` — `ISSUES_CREATED=0` |
| discovered / rejected / admitted | 30 / 9 / 21 |
| light_analyzed / pruned (max score < 70) | 3 / 2 |
| deep_analyzed / scored / notifiable / reported | 1 / 1 / 0 / 0 |
| LLM calls / cache hits / cost | 0 / 0 / 0 |
| repositories / filter_decisions / notifications | 30 / 32 / 0 |

Every GitHub request in the run was a read-only `GET` (search, repository,
tree, contents): no clone, no install, no candidate code executed, no Issue
created, no LLM call. Repository content was read statically and the hard
filter rejected 9 of the 30 candidates.

Limits enforced by `--controlled-live` (all strictly below production):

| Budget | Production | Controlled live |
|---|---:|---:|
| unique repositories seen | 1000 | 30 |
| light analyses | 200 | 10 |
| deep analyses | 25 | 3 |
| LLM calls | 30 | 2 |

Expected: `RESULT=SUCCESS`, `RESULT=SUCCESS_NO_FINDINGS` or
`RESULT=PARTIAL_SUCCESS*`; zero Issues; no secret in the log output. This step
needs a real `GITHUB_TOKEN` and therefore remains user-run.

## 5. Controlled publication and email (PENDING_USER_VALIDATION)

To be executed by the user after the deployment gate is opened:

1. `workflow_dispatch` with `dry_run = false` on `daily-discovery` (or
   `hidden-gems run --live` with `GITHUB_REPOSITORY` set) once at least one real
   candidate reaches the notification threshold. The production score threshold
   is never lowered for the test.
2. Verify in the created Issue: `REPORT_FINGERPRINT`, labels
   (`discovery-report`, plus `exceptional-findings`/`has-updates` when
   applicable), assignee `NOTIFICATION_GITHUB_LOGIN`, the notification row in
   SQLite, and the notification email reached the watching account
   (`Watch → Custom → Issues`).
3. Re-run the same run state and confirm no duplicate Issue is created
   (adoption by fingerprint).
4. Record run IDs, API usage, LLM usage/cost, Issue number and the email
   verification result.

## 6. Defects found and fixed while preparing this gate

| Defect | Fix |
|---|---|
| `MAX_LLM_CANDIDATES_PER_RUN` was validated but not enforced at runtime, so more repositories than allowed could reach the provider | commit `75b62b5`, enforced per run with `candidate_cap_skipped`/`llm_candidates_used` usage counters |
| The default `--db` path did not match the documented `state/` layout | commit `32aad3d` |
| `LLM_ENABLED` was read from a non-documented variable name | commit `32aad3d` (`resolve_llm_enabled`) |
| `.gitignore` failed `git diff --check` | commit `f60aa3c` |

LIVE_READ_ONLY_PROBE=PASS
ISSUES_CREATED=0
EXTERNAL_CODE_EXECUTED=NO
CONTROLLED_PUBLICATION=PENDING_USER_VALIDATION
EMAIL_DELIVERY=PENDING_USER_VALIDATION
