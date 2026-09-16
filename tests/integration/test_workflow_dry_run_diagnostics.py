from pathlib import Path


def test_dry_run_workflow_emits_persisted_run_diagnostics_after_discovery():
    workflow = Path(".github/workflows/daily_discovery.yml").read_text(encoding="utf-8")

    discovery_pos = workflow.index("      - name: Run discovery")
    diagnostics_pos = workflow.index("      - name: Emit dry-run diagnostics")
    integrity_pos = workflow.index("      - name: Verify database integrity")

    assert discovery_pos < diagnostics_pos < integrity_pos

    diagnostics = workflow[diagnostics_pos:integrity_pos]
    assert "if: ${{ steps.mode.outputs.dry_run == 'true' }}" in diagnostics
    assert 'sqlite3.connect("state/history.sqlite3")' in diagnostics
    assert "SELECT run_id, result, errors, usage FROM runs" in diagnostics
    assert "ORDER BY started_at DESC LIMIT 1" in diagnostics
    assert "DRY_RUN_DIAGNOSTICS_RUN_ID=" in diagnostics
    assert "DRY_RUN_DIAGNOSTICS_RESULT=" in diagnostics
    assert "DRY_RUN_DIAGNOSTICS_ERRORS=" in diagnostics
    assert "LLM_CALLS_MADE=" in diagnostics
    assert "LLM_INPUT_TOKENS=" in diagnostics
    assert "LLM_OUTPUT_TOKENS=" in diagnostics
    assert "LLM_COST=" in diagnostics
    assert "LLM_CACHE_HITS=" in diagnostics
    assert "LLM_FAILURES=" in diagnostics
    assert "LLM_REASONS=" in diagnostics
    assert "DEEPSEEK_API_KEY" not in diagnostics
