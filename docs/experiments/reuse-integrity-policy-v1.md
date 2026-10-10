# Experimental reuse: evidence replay and monotonic policy (V1)

Status: **EXPERIMENTAL / NOT WIRED TO PRODUCTION / NOT AUTHORIZED TO MERGE**.

This laboratory branch was based on `JoanAbad82/github-hidden-gems` main SHA `4ecee86349c82f339ef5d8c0ff9e61876f6cec57`. Existing pipeline, API, hashing semantics, configuration, dependencies, schemas, CLI and workflows are unchanged. No user, service or tool permissions are altered.

## Source provenance and decision

- Slotvox: [`hawaiicoco/slotvox`](https://github.com/hawaiicoco/slotvox/tree/a66d2911f6185b52c841507d338b395fd4aaee96), MIT, read-only review of JSON/CSV replay and adversarial validation. Upstream pinned SHA `a66d2911f6185b52c841507d338b395fd4aaee96`. No source code copied.
- Orca Agent Engine: [`orca-ae/orca-agent-engine`](https://github.com/orca-ae/orca-agent-engine/tree/5176ec6dd0aac4fec9d3981f6a83379e8de0cd53), Apache-2.0, review of monotonic permission composition. Upstream pinned SHA `5176ec6dd0aac4fec9d3981f6a83379e8de0cd53`. No source code copied.
- Audit dossier: `AUDITORIA_ORCA_SLOTVOX_20261010.zip` (archived locally under `Documents/GITHUB_PARA_IA/INVESTIGACION/AUDITORIAS/2026-10-10_ORCA_SLOTVOX`).

Both implementations below are original and stand-alone; they preserve the invariants, not the libraries or runtime internals.

## A. Replay integrity: SLOTVOX-REPLAY-INTEGRITY-V1

Import `hidden_gems.experimental.replay_integrity.validate_run_pair` to *read* existing `RUN_CANDIDATES_V1` JSON/CSV files and the existing `schemas/run_candidates_v1.json` **without changing the exporter**. This checks:

1. Bounded reads, strict UTF-8, duplicate-key rejection (all nesting), non-finite JSON values, malformed/truncated JSON, valid Draft 2020-12 schema.
2. Internal semantic consistency: candidate count, unique repository IDs, selected flags, unique/contiguous report ranks, reported count.
3. Original CSV rendered **byte-for-byte** from the JSON via the already existing `_CSV_FIELDS` and `_csv_row` functions. No migration, hashing-format change or alternate exporter.
4. Optional **externally trusted** SHA-256 digests for each source file. **Without those trusted digests, coordinated tampering of both JSON and CSV cannot be detected cryptographically.** Hashes supplied only by the artifacts themselves are not trust anchors.

Independent read-only replay of archived *production-generated* dry-run snapshots (not production modifications):

| UTC run ID | JSON SHA-256 | CSV SHA-256 | JSON candidates / reported |
| --- | --- | --- | --- |
| `RUN-20261009T132200Z` | `2f49c9b05cabb073137a8c84c304be3ce0b3938f91e7b9cc0da00ebde5ca0afa` | `aa9a816b76b021260fa6eded6855c019002c01d7e288ff0125af495abefa9381` | 25 / 5 |
| `RUN-20261010T123637Z` | `02ea231177f8d0a3693b500e13ddfb7eb2790acc8fd5f3cc6d9002481a7cc47a` | `9e2457eec20111975fd5a12ea4e3af8cfeae1ca2fce415bd3f852a9cb1f54dcb` | 25 / 5 |

Both snapshots independently passed schema, semantic, exact CSV, and external SHA-256 checks. The artifacts were never rewritten.

**Limitations:** This is neither a signature verifier nor an acquisition-provenance attestation. The replay formatter calls private functions of the existing writer; future writer changes require deliberately updated tests. It is deliberately not connected to `daily-discovery`.

## B. Monotonic policy: ORCA-POLICY-MONOTONIC-V1

`hidden_gems.experimental.policy_monotonic` offers an **in-memory declarative decision function**, not an executor. Three outcomes are ordered `ALLOW < ASK < DENY`. Its join is associative, commutative, idempotent and monotonic. Existing DENY is terminal; absence of any rule's required state fails closed before evaluating rules; invalid inputs also fail closed. No callbacks, GitHub API, Codex, SSH, filesystem writes or remote action mechanisms are included.

**Limitations:** Merely evaluating a policy does not enforce it; actual authorization would require separately reviewed executor boundaries, trusted state snapshots, concurrency/atomic-budget semantics, replay defense, and explicit owner authorization. **Do not wire this experimental evaluator into agent execution without those controls.**

## Quality gates

- Tests: `python -m pytest -q tests/unit/experimental`, plus full offline regression (`python -m pytest -q -m "not live"`) and whitespace/static contract checks.
- Negative tests exercise tampering, invalid numbers, missing state, seed denial, invalid rules, associative/commutative joins, and no-execution surface.
- Git scope: *only new* `src/hidden_gems/experimental/*`, `tests/unit/experimental/*`, and this documentation. Existing tracked files must remain byte-identical to base main.
- Experimental branch/PR only; **no automated merge, deployment, application changes, credential use, or change to `main`.** Future adoption requires separate security and compatibility reviews.
