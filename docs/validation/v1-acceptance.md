# GitHub Hidden Gems V1 — acceptance report (Task 18)

This report is generated from persisted SQLite evidence only. Regenerate it
after every real daily cycle:

```
hidden-gems validation-status \
  --root . \
  --db state/history.sqlite3 \
  --gradings docs/validation/gradings.yml \
  --markdown docs/validation/v1-acceptance.md
```

The gate never invents cycles. Fewer than seven consecutive real daily runs, an
ungraded notification, or a dry-run-only window keep the report pending instead
of accepted. A single hard-safety violation fails the gate.

## Criteria from persisted history

| Criterion | Status | Evidence |
|---|---|---|
| `seven_consecutive_daily_cycles` | PENDING | 0 consecutive daily cycles out of the required 7 |
| `sqlite_integrity` | PENDING | no evaluated cycles yet; integrity check unproven |
| `no_duplicate_issues` | PENDING | no evaluated cycles yet; duplicate Issues unproven |
| `no_budget_overruns` | PENDING | no evaluated cycles yet; budget overruns unproven |
| `no_concurrent_state_conflicts` | PENDING | no evaluated cycles yet; concurrent state conflicts unproven |
| `no_secret_exposures` | PENDING | no evaluated cycles yet; exposed secrets unproven |
| `silent_day_behaviour` | PENDING | no evaluated cycles yet; silent days unproven |
| `useful_discovery_rate` | PENDING | no graded notifications yet |
| `exceptional_calibration` | PENDING | no evaluated cycles yet; calibration unproven |
| `production_publication_cycles` | PENDING | no cycles evaluated yet; live publication unproven |

## Metrics

| Metric | Value |
|---|---|
| `cycles_observed` | 0 |
| `consecutive_cycles` | 0 |
| `notified_repositories` | 0 |
| `useful_notifications` | 0 |
| `useful_discovery_rate` | n/a |
| `issues_created` | 0 |
| `dry_run_cycles` | 0 |
| `ungraded_notifications` | 0 |

## Why the report is not accepted

- No scheduled production cycle has run yet: the state branch history is empty
  in this implementation environment.
- Controlled publication and email delivery are
  `PENDING_USER_VALIDATION` (creating real GitHub Issues was prohibited in this
  run; see `docs/validation/controlled-live-20260915.md`).
- The product DeepSeek credential is not available to the application, so live
  semantic enrichment is unvalidated. The pipeline is fully exercised with the
  LLM disabled and with mocked providers.

## Requirements before `V1_ACCEPTED` can appear

1. Run the production workflow seven consecutive days (no manually filled
   gaps). Each day must end with an explicit run result persisted in SQLite.
2. Zero SQLite corruption, zero exposed secrets, zero duplicate Issues, zero
   concurrent state conflicts and zero budget overruns across those seven days.
3. Every notified repository graded `GOOD` / `MAYBE` / `BAD` in
   `docs/validation/gradings.yml`; Useful Discovery Rate must be at least 70%
   `GOOD + MAYBE`.
4. Every finding at or above 85 points reviewed individually; an obviously
   mediocre exceptional finding blocks acceptance pending recalibration.
5. Days with no qualifying candidate must end as `SUCCESS_NO_FINDINGS` with no
   Issue.
6. Re-run the acceptance gate and commit the regenerated report.

## Per-cycle execution log (fill in from the real runs)

| Date (UTC) | RUN_ID | Result | Issue | Notified | Graded GOOD/MAYBE/BAD | Notes |
|---|---|---|---|---|---|---|
| _pending_ | | | | | | |

Seven real daily cycles have not happened yet, so this table is intentionally
empty: fabricating rows would invalidate the acceptance gate.

STATUS=PENDING_MULTI_DAY_VALIDATION
