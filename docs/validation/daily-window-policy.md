# V1 acceptance — UTC daily observation and provisional evidence policy

**Date of correction:** 2026-10-14. **Scope:** acceptance read-only evaluator, historical human gradings and regression tests. No scoring changes, live operations or schema migrations.

## Measurement unit and selection protocol

- The observation unit for seven consecutive cycles is a **distinct UTC calendar day** with exactly one verifiable live run. An individual SQLite row does not count as a new day.
- For each UTC date, if there is a live run, prefer it over any dry-run rows from that date. A dry-run must never shadow a real publication, and dry-runs do not earn acceptance credit.
- If a date has **multiple live runs**, retain all their evidence and their notification denominators; fail the explicit `unique_live_cycle_per_day` criterion rather than silently selecting one outcome. This prevents result-dependent cherry-picking.
- If there are only dry-runs on a date, choose one deterministic representative for continuity display, marked as dry-run. The production criterion remains PENDING.
- Find the trailing consecutive set of **distinct dates**, not contiguous SQLite rows. Restrict the evaluation window to the last seven such dates, retaining all live rows for any anomalous duplicate day.
- An incomplete seven-live-day observation window can report its observed GOOD+MAYBE numerator and all-notification denominator, but the discovery-rate gate is **PENDING (provisional)** regardless of whether the preliminary ratio is above or below 70%. Security failures can still produce FAIL immediately.
- Once seven distinct consecutive live days exist, with no ambiguous duplicate live dates and all notifications human graded, compute UDR with all recorded notifications and compare it against the frozen 70% floor. Preserve the grade labels, scores and thresholds unchanged.

## Falsifying example from the historical state snapshot

SQLite state snapshot SHA-256: `a0d0fdbbf1f92ddb136eec667c610345a803f8d444e60e0cd9dc20efc244cae1`.

| Date UTC | Run ID | Mode | Notifications |
|---|---|---|---:|
| 2026-09-15 | `RUN-20260915T152056Z` | dry-run | 0 |
| 2026-09-15 | `RUN-20260915T202610Z` | live | 5 |
| 2026-09-16 | `RUN-20260916T114014Z` | live | 1 |

The previous gate selected the dry-run + Sep16 live run, showing **1/1 = 100%** and excluding five reviewed notifications. The corrected daily-window protocol selects both live rows and **4/6 = 66.67% (provisional)**, preserving the `PENDING_MULTI_DAY_VALIDATION` status.

## Provenance of the six ratified historical gradings

Source from 2026-10-12: `HIDDEN_GEMS_ACTA_RATIFICADA_RESUMEN_2026-10-12.md` and `HIDDEN_GEMS_GRADINGS_RATIFICADOS_STAGING_2026-10-12.yml` in the owner's local historical evidence folder. They were approved by the project owner and are copied **without altering their labels, scores or notes** to `docs/validation/gradings.yml` in this isolated PR only.

Ratified grades are 2 GOOD, 2 MAYBE, 2 BAD. They are not a statistically independent random draw, and the 66.67% historical cohort must not be mistaken for population-level model precision or the V1 acceptance-window success rate. They do not fabricate new run rows.

## Regression contract

- Six permutations of the three authentic run IDs must select **both** live days with denominator 6; result provisional PENDING.
- Two distinct live records on one UTC day must be explicitly FAIL and their evidence must remain in the denominator.
- Extra dry-run rows on the same day cannot replace a live result or fabricate additional days.
- Fewer than seven live dates must never trigger acceptance or definitive performance rejection solely from the interim UDR.
- Existing hard-safety failures (integrity, duplicate Issues, budget overrun, state conflict, secrets) remain fail-closed, including on incomplete windows.
- The old test suite and read-only production-state reproduction must remain PASS; no GitHub, SQLite or scoring writes occur during evaluation.

**Deployment boundary:** this policy is prepared for a signed isolated PR. It does not authorize merge, GitHub Actions variable changes, a live pilot, Issue publication or seven consecutive live cycles.
