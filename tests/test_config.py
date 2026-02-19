"""Tests for configuration system."""

import json
import os
import pytest
from pathlib import Path

from sample_library_manager.config import Config, load_config


def test_config_from_yaml_file(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        'libraries:\n'
        '  "Test Lib": "/tmp/test-samples"\n'
    )
    config = load_config(config_path=str(config_file))
    assert "Test Lib" in config.libraries
    assert config.libraries["Test Lib"] == Path("/tmp/test-samples")


def test_config_from_json_file(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "libraries": {
            "JSON Lib": "/tmp/json-samples"
        }
    }))
    config = load_config(config_path=str(config_file))
    assert "JSON Lib" in config.libraries


def test_config_env_var_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SLM_LIBRARIES", '{"Env Lib": "/tmp/env-samples"}')
    # Use a non-existent config file path to skip file loading
    config = load_config(config_path=str(tmp_path / "nonexistent.yaml"))
    assert "Env Lib" in config.libraries


def test_config_individual_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("SLM_LIBRARY_1", "/tmp/lib1")
    monkeypatch.setenv("SLM_LIBRARY_1_NAME", "First Library")
    config = load_config(config_path=str(tmp_path / "nonexistent.yaml"))
    assert "First Library" in config.libraries
    assert config.libraries["First Library"] == Path("/tmp/lib1")


def test_config_cli_override(tmp_path):
    config = load_config(
        config_path=str(tmp_path / "nonexistent.yaml"),
        cli_libraries=["CLI Lib=/tmp/cli-samples"],
    )
    assert "CLI Lib" in config.libraries
    assert config.libraries["CLI Lib"] == Path("/tmp/cli-samples")


def test_cli_overrides_env(tmp_path, monkeypatch):
    """CLI should win over env vars for the same library name."""
    monkeypatch.setenv("SLM_LIBRARIES", '{"Shared": "/env/path"}')
    config = load_config(
        config_path=str(tmp_path / "nonexistent.yaml"),
        cli_libraries=["Shared=/cli/path"],
    )
    assert config.libraries["Shared"] == Path("/cli/path")
