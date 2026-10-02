# Post-light semantic filter v1

Date: 2026-10-02

## Trigger

`multilingual-tutorial-detection-v1` proved that the real repository
`AidenBJ/java-multi-agent-lab` (`repo_id=1379423359`) is:

- PASS when the hard filter only has discovery metadata;
- REJECT_TUTORIAL when README + tree evidence is available;
- substantial rather than minimal (187 source paths in the real characterization).

Static inspection then showed that production only called
`evaluate_candidate()` before `LightAnalyzer`, despite the hard-filter module
already documenting a two-stage contract.

## Scope

This change does **not** modify filtering rules.

Its only purpose is to connect the existing semantic filter to the
post-light production path before ranking, deep analysis and DeepSeek.

## Design

### Ephemeral README excerpt

`LightAnalysis` now has an optional `readme_excerpt` field.

`LightAnalyzer` populates it from the README it already fetched, bounded to
the existing `max_readme_chars_for_hash` limit (60,000 characters in current
configuration).

The excerpt:
- does not require an additional GitHub request;
- is not inserted into `LightAnalysis.evidence`;
- is therefore not persisted as observation evidence;
- is not consumed by DeepAnalyzer/LLM prompts.

### Minimal FilterEvidence reconstruction

The orchestrator converts the completed light result into:

- bounded README excerpt;
- already-read tree paths;
- already-read manifest names;
- repository size metadata.

No repository content is re-read for this filter pass.

### Second semantic decision

Immediately after a successful light analysis, and before:
- relationship ranking,
- preliminary scoring,
- deep analysis,
- LLM enrichment,

the orchestrator calls the existing `evaluate_candidate()` again.

Every second decision is persisted in `filter_decisions` with:

`stage:post_light`

prepended to its evidence.

A rejection is excluded from the downstream `lights` collection.

The same gate is applied to candidates found through relationship expansion.

## Integration proof

A pipeline integration test uses:

- repo_id: `1379423359`
- explicit Chinese tutorial wording in the description;
- independent tutorial wording in the README;
- a substantial synthetic implementation tree;
- real SQLite HistoryStore;
- CountingLLM.

Expected and observed after the fix:

- pre-light filter: PASS;
- LightAnalyzer completes;
- post-light filter: REJECT_TUTORIAL;
- persisted evidence includes:
  - `stage:post_light`
  - `description:tutorial_wording`
  - `readme:tutorial_wording`
- deep_analyzed: 0;
- CountingLLM.calls: 0.

A normal production-style control still remains eligible for LLM analysis.

## README bounding proof

An oversized README is tested.

Observed:
- `readme_excerpt` length is exactly the configured bound;
- `readme_excerpt` is absent from persisted/general analysis evidence.

## Validation

Focused tests:
- post-light gate + light analyzer: **9/9 PASS**

Integration + filtering:
- **124/124 PASS**

Full suite:
- frozen base: **483 PASS / 2 skipped**
- branch: **486 PASS / 2 skipped**
- delta: **+3 PASS / 0 new failures**

Additional:
- `CONFIG_VALID`
- `git diff --check`: clean

## Disposition

`READY_FOR_INTEGRATION_REVIEW`

Branch:
`fix/post-light-semantic-filter-v1`

No filtering-rule change.
No live publishing change.
No scoring change.


## Production-path closure

Integrated code commit:

`acd2f3a66585f493ae1fc181864f6a10747a0651`

### Real repository targeted pipeline proof

A local read-only diagnostic ran the real `run_pipeline` against the real GitHub
repository `AidenBJ/java-multi-agent-lab` while forcing discovery to contain
only that repository.

The diagnostic used:
- the production `LightAnalyzer`;
- the production post-light semantic gate;
- real GitHub README/tree data;
- real SQLite `HistoryStore`;
- a local sentinel LLM that records calls and would fail if invoked.

The Python import path was pinned explicitly to the current `main/src` to
avoid stale editable-install ambiguity.

Observed:

- repo_id: `1379423359`
- discovered: 1
- filtered_in: 1
- light_analyzed: 1
- rejected: 1
- deep_analyzed: 0
- scored: 0
- LLM calls: **0**
- result: `SUCCESS_NO_FINDINGS`

Persisted filter decisions:

1. pre-light:
   - PASS
   - `passed:no_rejection_rule_matched`

2. post-light:
   - `REJECT_TUTORIAL`
   - `stage:post_light`
   - `description:tutorial_wording`
   - `readme:tutorial_wording`

Therefore, when this repository enters the production pipeline, it cannot reach
DeepAnalyzer or consume an LLM call after the post-light gate.

### Full GitHub Actions dry-run

Run:
`37038564968`

SHA:
`acd2f3a66585f493ae1fc181864f6a10747a0651`

Result:
- workflow conclusion: `success`
- pipeline result: `SUCCESS`
- discovered: 383
- reported: 5
- LLM calls: 26
- LLM failures: 0
- LLM reasons: 25 PRIMARY + 1 RETRY
- database integrity: `DB_VALID`
- dry-run state persistence: skipped as designed

One unrelated repository (`repo_id=1373833056`) hit an output-token
truncation on PRIMARY and recovered successfully on RETRY. This did not produce
an LLM failure.

The target repository `1379423359` was not present in this run's discovery/log
surface, so its absence from `LLM_ATTEMPTS` is **not** used as evidence of
post-light rejection. The targeted real-repository pipeline proof above is the
closure evidence for that property.

### Baseline comparison

Immediately preceding full dry-run on the same 383-candidate discovery surface:
- discovered: 383
- reported: 5
- LLM calls: 26
- LLM failures: 0

Post-light-filter dry-run:
- discovered: 383
- reported: 5
- LLM calls: 26
- LLM failures: 0

No observed degradation in report count or LLM failure rate.

## Final disposition

`ACCEPTED / POST_LIGHT_SEMANTIC_GATE_CONNECTED`

The documented two-stage hard-filter contract is now implemented in the
production path.
