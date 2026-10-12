# Hidden Gems V1 — B1–B4 live-safety hardening (pre-production)

Scope: **isolated pull request**. This is not authorization to enable live production. Neither `HIDDEN_GEM_SCORE_V1` nor its thresholds are changed.

## B1 — LLM budget estimates

Previously `cost_per_1k_input_tokens=0` and `cost_per_1k_output_tokens=0`, causing false zero-dollar reports. The pricing ceilings in `config/limits.yml` are conservative **USD per 1,000 tokens** derived from the highest published DeepSeek V4 Pro peak cache-miss input ($1.32 per million) and output ($3.96 per million) as viewed 2026-10-12: https://api-docs.deepseek.com/quick_start/pricing/

- Actual charge is *not* returned as dollars in the currently consumed API response, so recorded cost remains an **estimate/upper bound**, not an invoice.
- A billable response with token usage is accounted at these positive ceiling rates, regardless of cache discounts.
- Before each call the provider reserves a conservative one-call upper estimate based on UTF-8 prompt bytes, plus max generated tokens. The run call limit (30) also remains.
- Prices may change; before any real run, verify the configured `deepseek-chat` model alias/rate from the provider account and billing. Set an external account spend limit. A changed rate or unverified alias means **NO-GO**. Do not equate an estimated cap with a provider-side spending limit.

## B2 — fail-closed persistence
- An exception while recording `finish_run` now raises `StateIntegrityError` and surfaces a nonzero `FAILED_INTEGRITY` result.
- Manifest write failure on a real run now returns `FAILED_INTEGRITY` instead of warning then success.
- Existing dry-run results remain unchanged.

## B3 — recoverable backups
- `live_state_guard stage-live` copies the **previous verified state** into a gzip backup, embeds its SHA-256 in the archive name, independently restores and integrity-checks it, and stages the new run.
- Up to three backups remain; the manifest indexes the backups. References, archive content, checksum, and restored SQLite integrity are checked on each preflight.
- `restore_backup` refuses to overwrite any destination. Restore rehearsals run only on temporary data.

## B4 — consistency gates
- Checkout of the `state` branch no longer has `continue-on-error`.
- Preflight checks SQLite against manifest hash, bytes, run id and result, plus any referenced backups.
- A live run must have completed SQLite history and a corresponding manifest before staging or pushing.
- Git push is checked against the remote `state` SHA; concurrent writers are serialized with the existing Actions concurrency group.

## Evidence and limit of the test
- Unit/integration tests (offline) exercise price, malformed manifest, corrupted backups, restored history, state mismatch, and persistence failures.
- Read-only preflight against an authenticated snapshot of the existing 2026-09-16 `state` branch returned `STATE_VALID`.
- No integration with the provider's actual billing page or a live production publish was attempted.

**Release gate:** review this PR, verify CI and signing, then separately authorize a single manual live pilot with `HIDDEN_GEMS_SCHEDULED_LIVE=false`. Seven production cycles require another explicit authorization and an automatic stop plan.
