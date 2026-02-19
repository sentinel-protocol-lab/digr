"""Tests for platform auto-detection."""

import pytest
from pathlib import Path
from unittest.mock import patch

from sample_library_manager.platform_detect import (
    auto_detect_libraries,
    default_config_dir,
    default_config_path,
)


def test_auto_detect_returns_dict():
    result = auto_detect_libraries()
    assert isinstance(result, dict)
    # All values should be Path objects
    for name, path in result.items():
        assert isinstance(name, str)
        assert isinstance(path, Path)


def test_auto_detect_only_existing_paths():
    """All returned paths should exist on disk."""
    result = auto_detect_libraries()
    for name, path in result.items():
        assert path.exists(), f"Library '{name}' path does not exist: {path}"


@patch("sample_library_manager.platform_detect.platform.system", return_value="Darwin")
def test_macos_detection(mock_system):
    result = auto_detect_libraries()
    # Should not crash, may or may not find libraries depending on system
    assert isinstance(result, dict)


@patch("sample_library_manager.platform_detect.platform.system", return_value="Windows")
def test_windows_detection(mock_system):
    result = auto_detect_libraries()
    assert isinstance(result, dict)


@patch("sample_library_manager.platform_detect.platform.system", return_value="Linux")
def test_linux_detection(mock_system):
    result = auto_detect_libraries()
    assert isinstance(result, dict)


def test_default_config_dir():
    result = default_config_dir()
    assert isinstance(result, Path)
    assert "sample-library-manager" in str(result)


def test_default_config_path():
    result = default_config_path()
    assert isinstance(result, Path)
    assert result.name == "config.yaml"
