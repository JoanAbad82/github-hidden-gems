# GitHub Hidden Gems V1 — acceptance report

Generated at: 2026-10-14T22:02:23Z

## Historical source and scope

This report is a **snapshot of persisted historical evidence**, not proof of
seven consecutive live days as of the generation timestamp. The evidence comes
from the private `state` Git branch:

- Source commit: `c490e27717f2a5015740fadadc7ba7c36654ea92`
- SQLite SHA-256: `a0d0fdbbf1f92ddb136eec667c610345a803f8d444e60e0cd9dc20efc244cae1`
- SQLite integrity: `PRAGMA integrity_check = ok`
- Run history: 2026-09-15 dry-run, 2026-09-15 live, 2026-09-16 live
- Historical notifications: 6, all human-graded; 4 GOOD/MAYBE, 2 BAD
- Rate 4/6 = 66.67%: **provisional**, not V1 acceptance
- GitHub scheduled dry-runs in October are not stored as new live
  publication cycles in the canonical `state` branch.

The preceding controlled-live *dry-run* exercise separately recorded
`CONTROLLED_PUBLICATION=PENDING_USER_VALIDATION` and
`EMAIL_DELIVERY=PENDING_USER_VALIDATION`
([controlled-live-20260915.md](controlled-live-20260915.md)).
Those labels apply to **that specific preflight**, not to the subsequent
historical live notifications; actual end-to-end email delivery has not been
independently demonstrated here.

**Accounting limitation:** the stored `llm_cost` and `projected_monthly_llm_cost` fields are historical **internal counters**, not an authenticated DeepSeek invoice or a provider-enforced spending ceiling. A recorded zero must not be interpreted as proof of zero charges. The `production_publication_cycles` individual criterion concerns only the two observed live rows and does not satisfy the seven-day gate.

**Reproduction:** after checking out the exact `state` commit, regenerate
this report using `hidden-gems validation-status` with the canonical
`docs/validation/gradings.yml`. Do not treat a local scratch database or
an unstaged synthetic run as additional production history.

## Criteria

| Criterion | Status | Evidence |
|---|---|---|
| `seven_consecutive_daily_cycles` | PENDING | 2 consecutive daily cycles out of the required 7 |
| `unique_live_cycle_per_day` | PASS | at most one live run per UTC day |
| `sqlite_integrity` | PASS | 0 cycles with a failed integrity check across 2 cycles |
| `no_duplicate_issues` | PASS | 0 duplicate Issues across 2 cycles |
| `no_budget_overruns` | PASS | 0 budget overruns across 2 cycles |
| `no_concurrent_state_conflicts` | PASS | 0 concurrent state conflicts across 2 cycles |
| `no_secret_exposures` | PASS | 0 exposed secrets across 2 cycles |
| `silent_day_behaviour` | PASS | 0 silent day(s) ended as SUCCESS_NO_FINDINGS with no Issue |
| `useful_discovery_rate` | PENDING | provisional useful discovery rate 66.67% GOOD+MAYBE over 6 notified repositories; requires 7 distinct live days without duplicates before comparison to 70% |
| `exceptional_calibration` | PASS | no BAD finding at or above 85 points |
| `production_publication_cycles` | PASS | 2 non-dry-run cycle(s) |

## Metrics

| Metric | Value |
|---|---|
| `candidates_deep_analyzed` | 50 |
| `candidates_discovered` | 805 |
| `candidates_light_analyzed` | 400 |
| `candidates_reported` | 6 |
| `consecutive_cycles` | 2 |
| `cycles_observed` | 3 |
| `dry_run_cycles` | 0 |
| `issues_created` | 2 |
| `llm_cache_hits` | 0 |
| `llm_calls` | 28 |
| `llm_cost` | 0.0 |
| `notified_repositories` | 6 |
| `projected_monthly_llm_cost` | 0.0 |
| `ungraded_notifications` | 0 |
| `useful_discovery_rate` | 0.6666666666666666 |
| `useful_notifications` | 4 |
| `window_cycles` | 2 |
| `window_end` | 2026-09-16 |
| `window_run_records` | 2 |
| `window_start` | 2026-09-15 |

## Blocking / pending reasons

- 2 consecutive daily cycles out of the required 7
- provisional useful discovery rate 66.67% GOOD+MAYBE over 6 notified repositories; requires 7 distinct live days without duplicates before comparison to 70%

## Status

The status below is derived only from persisted run evidence; seven real
consecutive daily cycles (plus human grading of every notified repository)
are required before `V1_ACCEPTED` can appear.

STATUS=PENDING_MULTI_DAY_VALIDATION
