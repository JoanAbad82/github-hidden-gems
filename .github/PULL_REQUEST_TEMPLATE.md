## Summary

Describe the change and the concrete problem it solves.

## Evidence

Provide the failing case, fixture, measurement, issue, or other evidence that
motivates this change.

## Validation

- [ ] Relevant tests were added or updated.
- [ ] `python -m pytest -m "not live"` passes, or the reason it cannot be run is documented.
- [ ] Configuration/schema/migration checks were run when applicable.
- [ ] No secrets, credentials, personal data, or generated local state are included.
- [ ] The change does not execute untrusted external repository code.
- [ ] Scoring, discovery semantics, trust boundaries, and provenance behavior are unchanged, or their impact is explicitly documented below.

## Behavioral / operational impact

Describe any effect on scoring, discovery, evidence interpretation, schemas,
migrations, CI, notifications, budgets, or runtime behavior.

## Research boundary

If this started as a speculative hypothesis or adversarial case, link the
corresponding Research Intake material and explain what evidence justified
promotion into a production change.
