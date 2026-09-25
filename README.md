# GitHub Hidden Gems V1

Low-cost, GitHub-native discovery system that finds, scores, remembers
and reports **low-visibility but valuable** public repositories in four equally
weighted areas: AI/agents, automation, data extraction/analysis, and trading.
The guiding rule is **precision over recall**: no padding, no noise.

The frozen design (`SPEC_V1`) and the implementation plan live under
`docs/superpowers/`; the module contract is in
`docs/superpowers/contracts/v1-module-interfaces.md` and day-to-day operation is
documented in [docs/operations.md](docs/operations.md).

## How it works

```
GitHub Actions (daily)
  → Discovery Engine (new / recently active / topic / intersection / 1-hop related)
  → Hard Filter (structured rejection codes, conservative about innovation)
  → Light Analyzer (README, tree, manifests, releases, activity — static reads only)
  → Relationship Explorer (exactly one hop)
  → Deep Analyzer (bounded static file selection, untrusted content)
  → optional DeepSeek enrichment (strict schema, cached, budgeted)
  → Hidden Gem Scorer (HIDDEN_GEM_SCORE_V1, 0-100)
  → SQLite history (canonical) → GitHub Issue (user-facing archive)
  → GitHub Notifications / email
```

External repository code is **never** cloned, installed, imported, built,
tested or executed. LLM analysis is optional: `LLM_ENABLED=false` keeps the
whole pipeline working.

## Scoring

| Dimension | Max |
|---|---:|
| Thematic relevance | 20 |
| Technical quality / documentation | 20 |
| Recent activity | 20 |
| Low visibility | 15 |
| Novelty | 10 |
| Originality / usefulness | 10 |
| Thematic intersection | 5 |

Notification threshold `70` (`INTERESTING`), `85` (`EXCEPTIONAL`). Repositories
with 500–2,000 stars need `80`; above 2,000 stars they are not notifiable in
V1. Re-notification requires `+10` over the last notified score. At most one
Issue per run, up to 5 entries normally and 10 in absolute terms (positions 6–10
only when the score is at least 85).

## Quick start (offline)

```bash
python -m pip install -e ".[dev]"
hidden-gems validate-config --root .     # RESULT=CONFIG_VALID
hidden-gems migrate --root . --db state/history.sqlite3
hidden-gems db-check --root . --db state/history.sqlite3
python -m pytest -m "not live"
```

## Live operation

See [docs/operations.md](docs/operations.md) for secrets
(`GITHUB_TOKEN`, `DEEPSEEK_API_KEY`), the `Watch → Custom → Issues` email
setting, `NOTIFICATION_GITHUB_LOGIN`, dry-run/live modes, budget zones and
recovery procedures.

## Validation gates

```bash
# controlled-live gate: forced dry run with reduced limits (30/10/3 seen-light-deep, 2 LLM calls)
hidden-gems run --root . --db state/history.sqlite3 --controlled-live

# seven-cycle acceptance gate (read-only; needs human gradings)
hidden-gems validation-status --root . --db state/history.sqlite3 \
  --gradings docs/validation/gradings.yml \
  --markdown docs/validation/v1-acceptance.md
```

The acceptance gate never fabricates cycles: it stays
`PENDING_MULTI_DAY_VALIDATION` until seven consecutive real daily runs exist and
every notified repository has been graded `GOOD`/`MAYBE`/`BAD`, with a Useful
Discovery Rate of at least 70%. Evidence so far is recorded in
[docs/validation/](docs/validation/).

Implementation is developed in an isolated worktree/branch and is validated
before any merge or push.
