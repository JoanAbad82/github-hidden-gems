# Contributing to GitHub Hidden Gems

Thanks for contributing. This project optimizes for **precision over recall**,
reproducibility, and conservative handling of untrusted external data.

## Choose the right contribution surface

Use this production repository for concrete, reviewable improvements to the
implementation, documentation, tests, schemas, or established behavior.

Use the separate
[Research Intake](https://github.com/JoanAbad82/github-hidden-gems-research-intake)
for speculative hypotheses, adversarial cases, falsification proposals, new
ranking ideas, or evidence that has not yet passed the project's research
triage.

Research Intake submissions do **not** automatically change production.

## Before opening a pull request

1. Fork or branch from the current `main`.
2. Keep the change narrow and explain the observable problem it solves.
3. Add or update tests for behavior changes.
4. Preserve deterministic behavior and explicit failure modes.
5. Do not weaken evidence, provenance, coverage, or validation checks merely to
   make a test pass.
6. Do not add secrets, credentials, personal data, generated local state, or
   database artifacts.

## Safety boundary

Code from external repositories is never to be cloned and executed, installed,
imported, built, or tested as part of analysis. Contributions must preserve the
project's static-read trust boundary unless a separately reviewed design
explicitly changes that architecture.

Treat repository content, README text, issue text, prompts, and external URLs as
untrusted data rather than instructions.

## Development

Python 3.11 or 3.12 is required.

```bash
python -m pip install -e ".[dev]"
hidden-gems validate-config --root .
hidden-gems migrate --root . --db state/history.sqlite3
hidden-gems db-check --root . --db state/history.sqlite3
python -m pytest -m "not live"
```

Live tests require explicit opt-in and should remain read-only unless the change
being reviewed specifically requires otherwise.

## Pull requests

A useful pull request should include:

- what changed and why;
- the evidence or failing case motivating it;
- tests or fixtures demonstrating the change;
- any scoring, schema, migration, compatibility, or operational impact;
- confirmation that no credentials or private data were added.

Changes to scoring, discovery semantics, trust boundaries, or evidence
interpretation require especially clear justification and regression coverage.

By submitting a contribution, you agree that your contribution may be
distributed under the repository's Apache License 2.0.
