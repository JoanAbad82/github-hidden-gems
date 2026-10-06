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
- preserves previous schemas/prompts; the current semantic contract is `KNOWLEDGE_ANALYSIS_V1R2` / `KNOWLEDGE_PACKET_V1R2` with `KNOWLEDGE_HARVEST_PROMPT_V1R2`.

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
