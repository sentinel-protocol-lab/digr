"""Tests for configuration system."""

import json
import os
import pytest
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


# --- License key file loading (Windows text-encoding edge cases) ---

TEST_LICENSE_KEY = "A1B2C3D4-E5F60718-9ABCDEF0-1234ABCD"


def test_license_key_file_loaded(tmp_path, monkeypatch):
    """A plain license.key file is read and assigned to the config."""
    monkeypatch.delenv("DIGR_LICENSE_KEY", raising=False)
    monkeypatch.setattr("digr.config.default_config_dir", lambda: tmp_path)
    (tmp_path / "license.key").write_text(TEST_LICENSE_KEY, encoding="utf-8")
    config = load_config(config_path=str(tmp_path / "nonexistent.yaml"))
    assert config.license_key == TEST_LICENSE_KEY


def test_license_key_file_with_bom_is_stripped(tmp_path, monkeypatch):
    """Windows Notepad saves UTF-8 with a leading BOM; it must not corrupt the key.

    Writing with encoding="utf-8-sig" prepends the BOM, mimicking Notepad. The
    loaded key must come back clean — a stray BOM would make Gumroad reject the
    key and would break the offline-token fingerprint.
    """
    monkeypatch.delenv("DIGR_LICENSE_KEY", raising=False)
    monkeypatch.setattr("digr.config.default_config_dir", lambda: tmp_path)
    (tmp_path / "license.key").write_text(TEST_LICENSE_KEY, encoding="utf-8-sig")
    config = load_config(config_path=str(tmp_path / "nonexistent.yaml"))
    assert config.license_key == TEST_LICENSE_KEY
    assert not config.license_key.startswith("﻿")


def test_license_key_file_with_windows_line_ending(tmp_path, monkeypatch):
    """A trailing CRLF (Windows newline) must be stripped from the key."""
    monkeypatch.delenv("DIGR_LICENSE_KEY", raising=False)
    monkeypatch.setattr("digr.config.default_config_dir", lambda: tmp_path)
    (tmp_path / "license.key").write_bytes((TEST_LICENSE_KEY + "\r\n").encode("utf-8"))
    config = load_config(config_path=str(tmp_path / "nonexistent.yaml"))
    assert config.license_key == TEST_LICENSE_KEY
