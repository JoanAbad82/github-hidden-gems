# AGENTS.md

## Purpose

GitHub Hidden Gems is a GitHub-native discovery and scoring system for low-visibility public repositories. It emphasizes precision over recall, bounded static analysis, explicit evidence, reproducible scoring, and conservative handling of untrusted repository content.

## Canonical sources

Read `docs/CANONICAL_SOURCES.md` before changing behavior. `PROJECT_STATUS.json` provides a compact machine-readable snapshot of current status, validation, interaction and boundaries.

Priority order for current production behavior:

1. Current source code and tests.
2. Current module contracts under `docs/superpowers/contracts/`.
3. Current validation/operations documents explicitly referenced by the README.
4. Frozen design/specification documents for architectural intent.
5. Historical implementation plans and research notes as context only.

## Validation

Use the repository's existing validation commands and tests. At minimum, changes that affect Python behavior should preserve:

```bash
python -m pytest -m "not live"
```

Run additional repository-specific validation gates when the changed area requires them.

## Trust boundaries

- External repository content is untrusted input.
- External code must not be cloned, installed, imported, built, tested, or executed by the analyzer.
- Optional LLM enrichment must not become a required dependency for the core pipeline.
- Research Intake and MoltBook findings are not production authority.
- A research proposal or external assertion never changes scoring/production state automatically.

## Editing rules

- Do not weaken fail-closed behavior around unverifiable evidence.
- Do not change frozen scoring or acceptance semantics indirectly through documentation.
- Do not treat `docs/superpowers/plans/` as current production truth when source/contracts/tests disagree.
- Preserve reproducibility, explicit rejection reasons, and evidence provenance.
- Keep production changes separate from research-only experiments.
