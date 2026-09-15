"""Contract tests for the GitHub Actions workflows (Task 15)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def load_workflow(name: str) -> dict:
    payload = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def trigger_block(workflow: dict) -> dict:
    # PyYAML parses the bare `on` key as the boolean True (YAML 1.1).
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow must declare triggers"
    if isinstance(triggers, str):
        return {triggers: None}
    return triggers


@pytest.fixture(scope="module")
def tests_workflow() -> dict:
    return load_workflow("tests.yml")


@pytest.fixture(scope="module")
def discovery_workflow() -> dict:
    return load_workflow("daily_discovery.yml")


def test_all_workflow_files_parse():
    files = sorted(path.name for path in WORKFLOWS.glob("*.yml"))
    assert files == ["daily_discovery.yml", "tests.yml"]


def test_no_pull_request_target_anywhere():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "pull_request_target" not in text


def test_production_triggers_are_schedule_and_manual_only(discovery_workflow: dict):
    triggers = trigger_block(discovery_workflow)
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    schedule = triggers["schedule"]
    assert isinstance(schedule, list) and len(schedule) == 1
    cron = schedule[0]["cron"]
    fields = cron.split()
    assert len(fields) == 5, f"invalid cron expression: {cron}"
    minute, hour, day_of_month, month, day_of_week = fields
    assert minute.isdigit() and int(minute) % 5 != 0, f"schedule must avoid round minutes: {cron}"
    assert (day_of_month, month, day_of_week) == ("*", "*", "*"), f"initial schedule is daily: {cron}"


def test_manual_dispatch_defaults_to_dry_run(discovery_workflow: dict):
    triggers = trigger_block(discovery_workflow)
    dry_run = triggers["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry_run["type"] == "boolean"
    assert dry_run["default"] is True


def test_production_has_single_concurrency_group(discovery_workflow: dict):
    concurrency = discovery_workflow["concurrency"]
    assert concurrency["group"] == "hidden-gems-state-writer"
    assert concurrency["cancel-in-progress"] is False


def test_default_permissions_are_read_only(discovery_workflow: dict, tests_workflow: dict):
    assert discovery_workflow["permissions"] == {"contents": "read"}
    assert tests_workflow["permissions"] == {"contents": "read"}


def test_only_publishing_job_requests_write_permissions(discovery_workflow: dict):
    write_jobs = {}
    for name, job in discovery_workflow["jobs"].items():
        permissions = job.get("permissions", {})
        writes = {key: value for key, value in permissions.items() if value == "write"}
        if writes:
            write_jobs[name] = writes
    assert set(write_jobs) == {"discover"}
    assert set(write_jobs["discover"]) <= {"contents", "issues"}
    for job in discovery_workflow["jobs"].values():
        assert "permissions" in job, "each job must declare its own permissions"


def test_test_workflow_never_references_production_secrets(tests_workflow: dict):
    text = yaml.safe_dump(tests_workflow, width=10000)
    assert "DEEPSEEK_API_KEY" not in text
    assert "secrets." not in text


def test_no_personal_access_token_secret_is_referenced():
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "secrets.PAT" not in text
        assert "secrets.GH_PAT" not in text
        assert "PAT_TOKEN" not in text
        assert "${{ secrets.GITHUB_TOKEN }}" in text or path.name == "tests.yml"


def test_production_workflow_runs_pipeline_and_persists_state():
    text = (WORKFLOWS / "daily_discovery.yml").read_text(encoding="utf-8")
    assert "hidden-gems validate-config" in text
    assert "hidden-gems migrate" in text
    assert "hidden-gems db-check" in text
    assert "hidden-gems run" in text
    assert "ref: main" in text
    assert "ref: state" in text
    assert "git push origin HEAD:state" in text


def test_production_workflow_has_timeout(discovery_workflow: dict):
    for job in discovery_workflow["jobs"].values():
        assert int(job["timeout-minutes"]) > 0


def test_test_workflow_runs_config_unit_and_integration():
    text = (WORKFLOWS / "tests.yml").read_text(encoding="utf-8")
    assert "hidden-gems validate-config" in text
    assert "tests/unit" in text
    assert "tests/integration" in text
    assert "-m \"not live\"" in text
