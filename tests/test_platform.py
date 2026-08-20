"""Tests for platform auto-detection."""

from pathlib import Path
from unittest.mock import patch

from digr.platform_detect import (
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


@patch("digr.platform_detect.platform.system", return_value="Darwin")
def test_macos_detection(mock_system):
    result = auto_detect_libraries()
    # Should not crash, may or may not find libraries depending on system
    assert isinstance(result, dict)


@patch("digr.platform_detect.platform.system", return_value="Windows")
def test_windows_detection(mock_system):
    result = auto_detect_libraries()
    assert isinstance(result, dict)


@patch("digr.platform_detect.platform.system", return_value="Linux")
def test_linux_detection(mock_system):
    result = auto_detect_libraries()
    assert isinstance(result, dict)


def test_default_config_dir(monkeypatch):
    # Opt out of the autouse DIGR_CONFIG_DIR test override so the real
    # platform-derived default path is exercised here.
    monkeypatch.delenv("DIGR_CONFIG_DIR", raising=False)
    result = default_config_dir()
    assert isinstance(result, Path)
    assert "digr" in str(result)


def test_default_config_path(monkeypatch):
    monkeypatch.delenv("DIGR_CONFIG_DIR", raising=False)
    result = default_config_path()
    assert isinstance(result, Path)
    assert result.name == "config.yaml"


def test_config_dir_override_wins(monkeypatch, tmp_path):
    """DIGR_CONFIG_DIR overrides the platform default on every OS."""
    monkeypatch.setenv("DIGR_CONFIG_DIR", str(tmp_path))
    assert default_config_dir() == tmp_path
    assert default_config_path() == tmp_path / "config.yaml"


@patch("digr.platform_detect.platform.system", return_value="Windows")
def test_config_dir_windows_uses_appdata(mock_system, monkeypatch):
    """On Windows the config dir lives under %APPDATA%, not ~/.config.

    This forces the Windows branch on any host OS so the path logic is checked
    in CI on macOS/Linux too. The real backslash filesystem behaviour is only
    exercised on the actual Windows CI runner.
    """
    monkeypatch.delenv("DIGR_CONFIG_DIR", raising=False)
    appdata = r"C:\Users\Test\AppData\Roaming"
    monkeypatch.setenv("APPDATA", appdata)
    result = default_config_dir()
    assert result == Path(appdata) / "digr"


@patch("digr.platform_detect.platform.system", return_value="Darwin")
def test_config_dir_macos_uses_dot_config(mock_system, monkeypatch):
    """On macOS the config dir lives under ~/.config/digr."""
    monkeypatch.delenv("DIGR_CONFIG_DIR", raising=False)
    result = default_config_dir()
    assert result == Path.home() / ".config" / "digr"
