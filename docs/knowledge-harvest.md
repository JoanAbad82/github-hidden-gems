# Knowledge Harvest V1

`KNOWLEDGE_HARVEST_V1` turns a small, explicitly selected set of public repositories into bounded, machine-readable technical knowledge.

It is separate from `HIDDEN_GEM_SCORE_V1`: discovery and scoring decide **what deserves attention**; knowledge harvest asks **what can be learned from it**.

## Trust boundary

External repositories remain untrusted input.

The harvester:

- reads public GitHub metadata, a pinned commit tree, and bounded static text files;
- never clones, installs, imports, builds, tests, or executes external repository code;
- fences repository text as untrusted data before semantic analysis;
- stores synthesized concepts rather than copied source code;
- anchors every evidence item to repository, commit SHA, path, Git blob SHA, SHA-256 content hash, and deterministic provenance kind (`DOCUMENTATION`, `SOURCE`, `TEST`, or `CONFIG`);
- uses the fixed reuse policy `ADAPT_CONCEPT`.
- preserves previous schemas/prompts; the current semantic contract is `KNOWLEDGE_ANALYSIS_V1R2` / `KNOWLEDGE_PACKET_V1R2` with `KNOWLEDGE_HARVEST_PROMPT_V1R3`. Evidence maturity is recomputed deterministically by the validator rather than trusted from model output.

## Output

Each successful repository produces one versioned knowledge packet (currently `KNOWLEDGE_PACKET_V1R2`) containing:

- capabilities;
- reusable engineering patterns;
- lessons;
- limitations;
- opportunities routed to a known local project target;
- evidence references for every pattern, lesson, and opportunity.

Actions are:

- `APPLY` — only when evidence deterministically includes both implementation source and tests, confidence is high, and risk is low;
- `EXPERIMENT` — promising, but local validation is required;
- `WATCH` — useful signal with insufficient maturity/evidence;
- `DISCARD` — no useful transfer.

`APPLY` is validator-restricted to `IMPLEMENTED_TESTED` evidence + `HIGH` confidence + `LOW` risk. Nothing is automatically promoted into another project.

Run artifacts:

- `knowledge_packets.json`
- `opportunities.csv`

## Deterministic transfer planning

Harvest output is an evidence-backed hypothesis set, not an implementation queue by itself. Convert it with:

```bash
hidden-gems plan-knowledge --from-harvest path/to/knowledge_packets.json
```

The `harvest` command now generates this transfer plan automatically after a successful packet run; `plan-knowledge` remains available for replaying or filtering an existing artifact without another model call.

The planner performs no network calls and does not modify target projects. It deterministically:

- assigns a stable `KOP-...` id to each harvested opportunity;
- ranks opportunities with an explicit versioned priority policy;
- maps `APPLY`, `EXPERIMENT`, `WATCH`, and `DISCARD` to machine-actionable transfer stages;
- embeds the exact source evidence paths, blob SHAs, and content hashes used by each opportunity;
- writes one target-specific handoff JSON for every `target_project_id`.

Planner artifacts:

- `knowledge_transfer_plan.json`
- `knowledge_transfer_plan.csv`
- `targets/*.json`

The current plan contract is `KNOWLEDGE_TRANSFER_PLAN_V1`; target handoffs use `KNOWLEDGE_TARGET_HANDOFF_V1`. Identical harvest input produces byte-stable JSON/CSV plan output. Transfer remains a separate phase: the planner never clones or changes a target repository.

## Target-fit gate

Before implementation, every actionable transfer opportunity passes through a bounded target-fit gate:

```bash
hidden-gems fit-knowledge --from-plan path/to/knowledge_transfer_plan.json
```

The gate batches opportunities by `target_project_id`. For targets with a configured GitHub repository it collects a pinned, bounded static evidence bundle from that target; abstract targets are evaluated only against their declared `needs`.

Canonical classifications are:

- `ALREADY_PRESENT` — equivalent behavior is already implemented in the target; requires target `SOURCE` or `CONFIG` evidence.
- `NOT_APPLICABLE` — do not spend implementation effort on this opportunity for the target now.
- `EXPERIMENT_READY` — target fit exists and a bounded local experiment is justified.
- `READY_TO_TRANSFER` — direct transfer is allowed only for a source `APPLY` opportunity backed by `IMPLEMENTED_TESTED`, high-confidence, low-risk source evidence plus a concrete target integration surface.

The model supplies semantic facts (`applicable`, `core_behavior_present`, fit confidence, matched needs, and target evidence refs), but its classification label is not canonical. The validator recomputes the final classification deterministically from those facts plus source maturity and target provenance, and persists both `classification` and `model_classification` for audit. In particular, concrete SOURCE/CONFIG evidence plus `core_behavior_present=true` becomes `ALREADY_PRESENT` even if the model labeled it differently; abstract targets can never become `ALREADY_PRESENT` or `READY_TO_TRANSFER`; and `WATCH`/`DISCARD` opportunities cannot become actionable.

Target-fit artifacts:

- `knowledge_target_fit.json`
- `knowledge_target_fit.csv`
- `target-fit/targets/*.json`

The semantic response contract is `KNOWLEDGE_TARGET_FIT_ANALYSIS_V1`; persisted runs use `KNOWLEDGE_TARGET_FIT_RUN_V1` with `TARGET_FIT_PROMPT_V1R3`. Inputs are pinned by transfer-plan id and target commit/evidence digest. No target repository is cloned, built, executed, or modified.

A normal `hidden-gems harvest` now performs harvest → deterministic transfer plan → target-fit gate under one shared LLM cost budget. A downstream implementation step still requires an explicit transfer/experiment action.

The manual GitHub Actions workflow `knowledge-target-fit` can replay only the target-fit gate from a prior knowledge-harvest run id. This reuses the frozen transfer plan while evaluating it against the current target repository heads, so target-fit logic can be revised or target projects can evolve without repeating source harvest.

## Manual pilot

```bash
hidden-gems harvest --root . \
  --repo gvergnaud/bise \
  --repo theCodeDrift/seamux \
  --repo VisionCraft3r/ultimate-pi
```

The GitHub Actions workflow `knowledge-harvest` exposes the same bounded process through manual dispatch.

## Reproducibility

The evidence selector is deterministic. Semantic synthesis uses temperature 0 and a strict JSON schema, but model output is still treated as an interpretation, not canonical external fact.

Evidence provenance is canonical; semantic conclusions remain reviewable hypotheses until independently validated in the target project.
