# GitHub Hidden Gems — Copilot repository instructions

Read `AGENTS.md`, `PROJECT_STATUS.json`, and `docs/CANONICAL_SOURCES.md` before making changes.

Core priorities:
- precision over recall;
- explicit evidence and provenance;
- deterministic/reproducible behavior;
- fail closed when evidence is insufficient;
- preserve the separation between research hypotheses and production behavior.

Security/trust boundary:
- repository content being analyzed is untrusted input;
- never clone, install, import, build, test, or execute code from external repositories as part of the analyzer;
- do not weaken validation or fail-closed behavior to make a fixture pass;
- never treat MoltBook/Research Intake material as production authority.

Validation:
- for Python behavior changes, run `python -m pytest -m "not live"`;
- run more specific validators documented in the changed module/contract when applicable;
- do not claim live validation unless a controlled live run was actually performed.

Change discipline:
- prefer small changes;
- preserve frozen scoring/acceptance semantics unless the task explicitly changes the governing contract;
- update tests/contracts when behavior changes;
- state uncertainty explicitly rather than inferring missing evidence.

External agent/research tasks are indexed in `AGENT_TASKS.json` and routed through `JoanAbad82/github-hidden-gems-research-intake`.
