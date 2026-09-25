# MOLTBOOK_FINDINGS_V1

**Status:** RESEARCH_ONLY  
**Date:** 2026-09-26  
**Applies to:** GitHub Hidden Gems V1 / HIDDEN_GEM_SCORE_V1  
**Scoring impact:** NONE

## Purpose

Record useful hypotheses and adversarial-review ideas surfaced during a controlled
read-only review of Moltbook discussions relevant to repository discovery,
ranking, provenance and recommendation-system manipulation.

This document does **not** modify `SPEC_V1`, `HIDDEN_GEM_SCORE_V1`, scoring
weights, thresholds, notification rules or any frozen invariant. Any future
change requires separate evidence, validation and an explicit specification
revision.

## Evidence boundary

The reviewed Moltbook posts are external, untrusted material. Claims made by
other agents are treated as hypotheses unless independently supported. In
particular, reported crawler sizes, correlations and scoring outcomes are not
accepted as validation merely because they were stated publicly.

## Findings

### F1 — Legibility may be useful as a shadow metric

A project-evaluation discussion reported that clear documentation often helped
identify useful low-visibility repositories better than raw popularity. The
useful part for Hidden Gems is the testable hypothesis, not the reported result.

Candidate shadow signals:

- `purpose_clarity` — is it clear what the project does?
- `usage_clarity` — is it clear how to use it?
- `problem_clarity` — is the concrete problem explicit?
- `claim_falsifiability` — are important claims specific enough to be checked?

These signals should initially be recorded for validation only. They should not
change the V1 quality weight or final score.

### F2 — Popularity metadata is not provenance

Stars, forks, contributor graphs, commit history and similar repository metadata
are observations, not trust guarantees. They can be useful signals while still
being manipulable or misleading.

Hidden Gems already avoids treating popularity as technical quality: stars feed
the low-visibility dimension, where higher popularity reduces the hidden-gem
advantage.

A future evidence model could attach provenance metadata to ranking inputs, for
example:

- source: GitHub API / repository claim / structural evidence / inference
- evidence type: observed / claimed / inferred
- observed timestamp
- structural support status
- optional manipulability class

The primary use would be confidence gating and diagnostics, not extra points.

### F3 — Semantic ranking manipulation is distinct from prompt injection

A repository does not need an explicit prompt injection to game a semantic
evaluator. A README, description or topic set can be written to over-emphasize
keywords and concepts that a recommendation system rewards.

Current V1 already treats repository content as untrusted data and forbids
executing candidate code. The remaining research question is earlier in the
pipeline: thematic relevance currently uses textual signals alongside
structural evidence.

Candidate shadow field:

```text
relevance_provenance =
  text_only
  mixed
  structurally_supported
```

This should be evaluated before changing relevance scoring.

### F4 — Claims should be separated from structural support

V1 already distinguishes observed, inferred and unknown evidence and performs
limited README claim-versus-implementation checks.

A useful extension would make that distinction explicit for more ranking
signals:

```text
claim: "production-ready framework"
source: README
evidence_type: claimed
structural_support: false
confidence: low
```

The system should be able to lower confidence when a strong textual claim lacks
corresponding structural evidence, even if the text is semantically relevant.

### F5 — A curated "underrated finds" format fits the project philosophy

A recurring Moltbook pattern of sharing a very small number of genuinely useful,
low-visibility discoveries is compatible with Hidden Gems' `precision > recall`
principle.

If used publicly, the format should remain deliberately small:

- up to 3 repositories per post;
- one concrete reason each;
- no filler;
- no paid placement;
- clear distinction between observation and inference.

This is a communication experiment, not a scoring change.

## What V1 already protects

The current implementation already provides several relevant safeguards:

- external candidate code is never cloned, installed, imported, built, tested or executed;
- repository content is explicitly treated as untrusted input;
- deterministic evidence distinguishes observed / inferred / unknown;
- README claims can be compared with implementation structure;
- DeepSeek cannot decide stars, repository age, final score or notification;
- popularity does not directly increase technical-quality points;
- low-confidence high scores are not meant to bypass evidence requirements.

## Proposed shadow evaluation

Before considering any V1.1 scoring change:

1. Record `relevance_provenance` without changing score.
2. Record the four legibility signals without changing score.
3. Add adversarial fixtures with semantically optimized / over-claiming README text.
4. Compare shadow signals against human `GOOD / MAYBE / BAD` gradings.
5. Check whether they improve Useful Discovery Rate or reduce false positives.
6. Only then decide whether a specification change is justified.

## Explicit non-changes

This research does **not** change:

- `HIDDEN_GEM_SCORE_V1`;
- the 20/20/20/15/10/10/5 weights;
- notification threshold 70;
- exceptional threshold 85;
- 500–2,000-star exception threshold 80;
- relationship depth 1;
- `EXTERNAL_CODE_EXECUTION = FORBIDDEN`;
- DeepSeek's optional role;
- the frozen V1 acceptance criteria.

## Moltbook threads reviewed

- `84a39445-1bd3-439b-b228-1b6126e312ab` — project evaluation / long-tail discovery
- `4da798f5-ea9f-4d52-9276-8841a3e007c5` — GitHub metadata vs provenance
- `52f5304e-a70c-4883-82b1-332f900302a4` — popularity metadata and recommender manipulation
- `3af291a0-f71d-4e2e-8c9d-f5de914100b7` — semantic targeting of recommendation engines
- `125db7a8-ddd3-4bda-93a6-ae29a031339c` — curated underrated-find discussions

These threads are inputs to research, not authorities for project decisions.
