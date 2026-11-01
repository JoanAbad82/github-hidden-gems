# Hidden Gems: Shadow post-run validation (V1)

Status: EXPERIMENTAL / READ-ONLY / NO PRODUCTION WIRING.

This experimental module is a post-run observer of GitHub Actions daily-discovery artifacts. It does not trigger discovery, write to GitHub, score candidates, modify workflow conclusions, block publication, authorize agents or import the experimental policy module.

Inputs: completed public daily-discovery run metadata; matching nonexpired action artifact; pinned RUN_CANDIDATES_V1 schema from local PR #34 checkout.

Security constraints: only GET GitHub API calls through the existing authenticated gh CLI; ZIP data fetched as bytes, not executed. Exactly two allowed archive entries with one strict run directory, no traversal or symlinks, bounded size, then validate original JSON/CSV by schema and replay. All reports stored separately in the local research area. No upstream code, workflow, state or data modifications.

PASS_CONSISTENCY_ONLY means the JSON/CSV pair passes internal checks and byte-identical CSV replay; it is NOT integrity provenance. PASS_WITH_EXTERNAL_DIGEST_MATCH means both expected SHA-256 strings were supplied by an independent local index and matched. The origin and authenticity of those SHA values are NOT verified by the script. integrity_provenance_verified is always false in this V1. An attacker who can forge both files may still pass consistency.

Files:
- source: src/hidden_gems/experimental/shadow_run_audit.py
- tests: tests/unit/experimental/test_shadow_run_audit.py
- launcher: Documents/GITHUB_PARA_IA/INVESTIGACION/SHADOW/HIDDEN_GEMS/STAR_HERE.ps1
- results: Documents/GITHUB_PARA_IA/INVESTIGACION/SHADOW/HIDDEN_GEMS/run_reports
- summaries: SHADOW_SUMMARY.csv and SHADOW_LATEST.json
- scheduler: Windows task HiddenGems-Shadow-ReadOnly, daily 19:00 Europe/Madrid.

The Windows task only runs when the machine is available and the authorized user's interactive session is active; this is not a cloud scheduler. It checks the latest 15 runs and skips those already reported; expired or very old artifacts may require manual follow-up. An observed failure is stored as a local report, never as a failed discovery result.

Manually run the installed STAR_HERE.ps1 launcher to recheck. Local output is read-only with respect to production, though research reports are newly written. Github CLI authentication on this machine has broader permissions than the calls in the code; a limited GitHub App credential would be preferable for eventual persistent operation.

No merge, deployment, branch protection change, GitHub write, or activation of real agent authorization is approved.

Compatibility cutoff: deterministic RUN_CANDIDATES_V1 ZIP artifact upload is available in the completed discovery runs from 2026-10-07. The read-only runner skips earlier completed runs before fetching artifacts, to avoid misclassifying pre-V1 runs with no artifacts as corrupt. The initial exploratory 15-run backfill is preserved separately as archival evidence; operational reports include eligible V1 runs only.
