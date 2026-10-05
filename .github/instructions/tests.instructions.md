---
applyTo: "tests/**/*.py"
---

When editing tests:
- prefer minimal deterministic fixtures;
- test invariants and failure boundaries rather than implementation accidents;
- include adversarial cases for ambiguous or unverifiable evidence;
- avoid network access and external repository execution;
- do not reduce assertions merely to satisfy a failing implementation;
- preserve the repository's fail-closed semantics.
