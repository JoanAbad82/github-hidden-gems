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

1. Bounded reads, strict UTF-8, duplicate-key rejection (all nesting), non-finite JSON values, malformed/truncated JSON, and valid Draft 2020-12 schema. The canonical schema bytes must first match the hardcoded SHA-256 `2521ed1a6154aabc8dd8f93c75707b55cee5602fdc0bff5633eec54317cc82b8`; mismatch fails before `jsonschema` validation or reference resolution. As defense in depth, `$ref`, `$dynamicRef`, and `$recursiveRef` are recursively restricted to current, existing `#/$defs/...` entries. External and nonfragment references are rejected without network access.
2. Internal semantic consistency: candidate count, unique repository IDs, selected flags, unique/contiguous report ranks, reported count.
3. Original CSV rendered **byte-for-byte** from the JSON via the already existing `_CSV_FIELDS` and `_csv_row` functions. No migration, hashing-format change or alternate exporter.
4. Optional **externally expected** SHA-256 digests for the two source files. They are all-or-nothing: supplying only JSON or only CSV fails closed. `RunPairAudit.validated=True` means only that schema, semantic, and JSON/CSV replay **consistency** checks passed. `RunPairAudit.matched_expected_digests=True` is set only when both expected digests were supplied and matched. **Without independently obtained expected digests, coordinated tampering of both JSON and CSV—including changes to `run.errors`, which CSV does not represent—cannot be detected cryptographically.** Digests copied from the artifacts being checked are not a trust anchor.

Expected-digest matching is not provenance verification. The caller must acquire both expected values independently, outside the artifact pair and its storage/transport trust boundary. Even a `matched_expected_digests=True` result attests only that the bytes match those caller-provided values; it is neither a signature nor proof of who produced or transported them.

Independent read-only replay of archived *production-generated* dry-run snapshots (not production modifications):

| UTC run ID | JSON SHA-256 | CSV SHA-256 | JSON candidates / reported |
| --- | --- | --- | --- |
| `RUN-20261009T132200Z` | `2f49c9b05cabb073137a8c84c304be3ce0b3938f91e7b9cc0da00ebde5ca0afa` | `aa9a816b76b021260fa6eded6855c019002c01d7e288ff0125af495abefa9381` | 25 / 5 |
| `RUN-20261010T123637Z` | `02ea231177f8d0a3693b500e13ddfb7eb2790acc8fd5f3cc6d9002481a7cc47a` | `9e2457eec20111975fd5a12ea4e3af8cfeae1ca2fce415bd3f852a9cb1f54dcb` | 25 / 5 |

Both snapshots independently passed schema, semantic, exact CSV, and external SHA-256 checks. The artifacts were never rewritten.

**Limitations:** This is neither a signature verifier nor an acquisition-provenance attestation. The replay formatter calls private functions of the existing writer. SHA-pinned golden tests for the original V1 empty-run and Unicode JSON/CSV bytes detect accidental format drift even if writer and checker change together; any future writer change therefore requires an explicit, reviewed golden update. It is deliberately not connected to `daily-discovery`.

## B. Monotonic policy: ORCA-POLICY-MONOTONIC-V1

`hidden_gems.experimental.policy_monotonic` is an isolated, side-effect-free decision model, **not an executor or authorization system**. Verdicts are ordered `ALLOW < ASK < DENY`; the join is associative, commutative, idempotent and monotonic. A `DENY` seed is terminal.

After the security audit, its `evaluate_policy` entrypoint now **denies by default when there is no explicit, nonempty required-rule manifest**. The manifest must match the declared rules exactly, with no missing or extra names. It accepts only inert builtin tuple/list containers holding exact frozen `PolicyRule` objects, and plain dictionaries holding safely typed scalar state. Arbitrary iterables, user-supplied Mapping subclasses, missing required keys, invalid values (including `None` and nonfinite floats), and unnamed state dependencies **fail closed**. The previous cases `evaluate_policy(())` -> ALLOW and `requires_state=True, state={}` -> ALLOW are eliminated.

**Important residual trust boundary:** The caller must **independently authenticate the rule manifest**, determine whether the rule outputs are correct, verify freshness and authority of state, and enforce actual permissions. The module does not know whether a claimed budget is sufficient, signed or atomic. It cannot authorize GitHub/Codex/Desktop Commander operations; no executor integration exists and none is approved. All tests use synthetic rules and data. Never connect this module to a real agent without a separate security design and explicit owner approval.
## Quality gates

- Tests: `python -m pytest -q tests/unit/experimental`, plus full offline regression (`python -m pytest -q -m "not live"`) and whitespace/static contract checks.
- Negative tests exercise tampering, invalid numbers, missing state, seed denial, invalid rules, associative/commutative joins, and no-execution surface.
- Git scope: *only new* `src/hidden_gems/experimental/*`, `tests/unit/experimental/*`, and this documentation. Existing tracked files must remain byte-identical to base main.
- Experimental branch/PR only; **no automated merge, deployment, application changes, credential use, or change to `main`.** Future adoption requires separate security and compatibility reviews.
