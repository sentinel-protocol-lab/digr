"""Tests for configuration system."""

import json
from pathlib import Path

from digr.config import Config, load_config


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
    monkeypatch.setenv("DIGR_LIBRARIES", '{"Env Lib": "/tmp/env-samples"}')
    # Use a non-existent config file path to skip file loading
    config = load_config(config_path=str(tmp_path / "nonexistent.yaml"))
    assert "Env Lib" in config.libraries


def test_config_individual_env_vars(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGR_LIBRARY_1", "/tmp/lib1")
    monkeypatch.setenv("DIGR_LIBRARY_1_NAME", "First Library")
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
    monkeypatch.setenv("DIGR_LIBRARIES", '{"Shared": "/env/path"}')
    config = load_config(
        config_path=str(tmp_path / "nonexistent.yaml"),
        cli_libraries=["Shared=/cli/path"],
    )
    assert config.libraries["Shared"] == Path("/cli/path")


def test_corrupt_yaml_config_does_not_crash(tmp_path, capsys):
    """A hand-edited, invalid config file must never stop the server starting.

    Regression: this used to raise straight out of load_config, which killed
    the MCP server at startup with a raw traceback in the client's log.
    """
    config_file = tmp_path / "config.yaml"
    config_file.write_text("libraries: [unclosed", encoding="utf-8")

    config = load_config(config_path=str(config_file))

    assert isinstance(config, Config)
    assert isinstance(config.libraries, dict)
    # The failure is reported on stderr (stdout carries the MCP protocol).
    assert "could not read config file" in capsys.readouterr().err
