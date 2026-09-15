"""The committed validation documents must not overstate their evidence."""

from __future__ import annotations

from pathlib import Path


def test_acceptance_report_has_exactly_one_status_line(repo_root: Path):
    text = (repo_root / "docs" / "validation" / "v1-acceptance.md").read_text(encoding="utf-8")
    assert text.count("STATUS=") == 1
    assert text.rstrip().endswith("STATUS=PENDING_MULTI_DAY_VALIDATION")
    assert "PENDING_USER_VALIDATION" in text


def test_controlled_live_evidence_keeps_publication_pending(repo_root: Path):
    text = (
        repo_root / "docs" / "validation" / "controlled-live-20260915.md"
    ).read_text(encoding="utf-8")
    assert "LIVE_READ_ONLY_PROBE=PASS" in text
    assert "ISSUES_CREATED=0" in text
    assert "CONTROLLED_PUBLICATION=PENDING_USER_VALIDATION" in text
    assert "EMAIL_DELIVERY=PENDING_USER_VALIDATION" in text
    assert "ISSUES_CREATED=1" not in text


def test_gradings_template_is_empty_and_explains_the_scale(repo_root: Path):
    text = (repo_root / "docs" / "validation" / "gradings.yml").read_text(encoding="utf-8")
    from hidden_gems.validation.acceptance import load_gradings

    assert load_gradings(repo_root / "docs" / "validation" / "gradings.yml") == {}
    for grade in ("GOOD", "MAYBE", "BAD"):
        assert grade in text
