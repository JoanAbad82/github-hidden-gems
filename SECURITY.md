# Security Policy

## Supported code

Security fixes are applied to the current `main` branch. This project is
research-oriented and does not currently promise maintenance of older snapshots
or unreleased branches.

## What to report

Please report vulnerabilities that could materially affect users or the
integrity of the system, including:

- credential or secret exposure;
- unsafe execution of untrusted repository content;
- command, path, prompt, or data injection crossing a trust boundary;
- authorization or GitHub token handling flaws;
- workflow or CI behavior that could write unexpectedly to external systems;
- evidence/provenance failures that create a security-relevant false claim.

## How to report privately

If GitHub's **Report a vulnerability** option is available under the repository
Security tab, use it and include reproduction steps, affected versions or
commits, impact, and a minimal proof of concept.

If private vulnerability reporting is not available, open a minimal public
issue requesting a private security contact channel. Do **not** include secrets,
working exploits, tokens, personal data, or sensitive reproduction details in
that public issue.

## Handling untrusted repositories

GitHub Hidden Gems is designed to inspect external repositories using static
reads. Their code should not be cloned for execution, installed, imported,
built, or tested by the analysis pipeline. A report showing that this boundary
can be crossed is considered security-relevant.

Please allow reasonable time for investigation before public disclosure.
