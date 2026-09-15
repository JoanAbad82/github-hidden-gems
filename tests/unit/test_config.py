from __future__ import annotations

from pathlib import Path

import pytest

from hidden_gems import cli
from hidden_gems.config import (
    AppConfig,
    ConfigError,
    load_config,
    resolve_llm_enabled,
    validate_config,
)


def test_canonical_scoring_weights_sum_to_100(app_config: AppConfig):
    assert sum(app_config.scoring.weights.values()) == 100


def test_unknown_config_key_is_fatal(tmp_path: Path, canonical_config_tree):
    canonical_config_tree(tmp_path, extra_limits={"max_lmm_calls": 3})
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(tmp_path)


def test_unknown_nested_key_is_fatal(tmp_path: Path, canonical_config_tree):
    tree = canonical_config_tree(tmp_path)
    path = tree / "config" / "limits.yml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("  per_page: 50", "  per_page: 50\n  unknown_knob: 1"), encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown key"):
        load_config(tree)


def test_v1_invariants_are_loaded(app_config: AppConfig):
    assert app_config.scoring.notification_threshold == 70
    assert app_config.scoring.exceptional_threshold == 85
    assert app_config.scoring.renotification_score_delta == 10
    assert app_config.discovery.relationship_depth == 1
    assert app_config.reporting.normal_max == 5
    assert app_config.reporting.absolute_max == 10


def test_four_equal_weight_areas_are_configured(app_config: AppConfig):
    assert app_config.topics.ids == ("ai_agents", "automation", "data", "trading")
    assert {area.weight for area in app_config.topics.areas} == {25}


def test_run_budgets_match_spec(app_config: AppConfig):
    assert app_config.limits.run_budgets == {
        "max_raw_candidates": 1000,
        "max_light_analysis": 200,
        "max_relationship_seeds": 20,
        "max_deep_analysis": 25,
    }
    assert app_config.discovery.max_relationship_seeds == 20


def test_llm_disabled_by_default(app_config: AppConfig):
    assert app_config.llm.enabled_default is False
    assert resolve_llm_enabled(app_config, env={}) is False
    assert resolve_llm_enabled(app_config, env={"LLM_ENABLED": "true"}) is True
    assert resolve_llm_enabled(app_config, env={"LLM_ENABLED": "0"}) is False
    with pytest.raises(ConfigError):
        resolve_llm_enabled(app_config, env={"LLM_ENABLED": "maybe"})


def test_relationship_depth_other_than_one_is_fatal(tmp_path: Path, canonical_config_tree):
    canonical_config_tree(tmp_path, extra_discovery={"relationship_depth": 2})
    with pytest.raises(ConfigError, match="relationship_depth"):
        load_config(tmp_path)


def test_absolute_max_above_ten_is_fatal(tmp_path: Path, canonical_config_tree):
    tree = canonical_config_tree(tmp_path)
    path = tree / "config" / "limits.yml"
    path.write_text(path.read_text(encoding="utf-8").replace("absolute_max: 10", "absolute_max: 11"), encoding="utf-8")
    with pytest.raises(ConfigError, match="absolute_max"):
        load_config(tree)


def test_weights_that_do_not_sum_to_100_are_fatal(tmp_path: Path, canonical_config_tree):
    tree = canonical_config_tree(tmp_path)
    path = tree / "config" / "scoring.yml"
    path.write_text(path.read_text(encoding="utf-8").replace("relevance: 20", "relevance: 19"), encoding="utf-8")
    with pytest.raises(ConfigError, match="100"):
        load_config(tree)


def test_missing_config_directory_is_fatal(tmp_path: Path):
    with pytest.raises(ConfigError, match="missing config directory"):
        load_config(tmp_path)


def test_missing_config_file_is_fatal(tmp_path: Path, canonical_config_tree):
    tree = canonical_config_tree(tmp_path)
    (tree / "config" / "scoring.yml").unlink()
    with pytest.raises(ConfigError, match="missing configuration file"):
        load_config(tree)


def test_validate_config_accepts_canonical_tree(app_config: AppConfig):
    validate_config(app_config)


def test_cli_validate_config_returns_zero(app_config: AppConfig, repo_root: Path, capsys):
    assert cli.main(["validate-config", "--root", str(repo_root)]) == 0
    assert "RESULT=CONFIG_VALID" in capsys.readouterr().out


def test_cli_validate_config_reports_failure(tmp_path: Path, canonical_config_tree, capsys):
    canonical_config_tree(tmp_path, extra_limits={"max_lmm_calls": 3})
    assert cli.main(["validate-config", "--root", str(tmp_path)]) == 2
    assert "RESULT=FAILED_CONFIGURATION" in capsys.readouterr().out


def test_configuration_validation_makes_no_network_calls(monkeypatch, app_config: AppConfig):
    import socket

    def _boom(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("configuration validation must not touch the network")

    monkeypatch.setattr(socket, "socket", _boom)
    validate_config(app_config)
