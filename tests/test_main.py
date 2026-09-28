"""Tests for the CLI entry point's argument handling.

Covers the removal of the old `digr --update` self-updater (Ibi, 27 Sept
2026): the update route is now "download the new release from GitHub and
install it again," so the flag and the module behind it are gone rather than
silently doing nothing.
"""

import pytest

from digr.__main__ import main


def test_update_flag_no_longer_recognized(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["digr", "--update"])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --update" in capsys.readouterr().err


def test_updater_module_removed():
    with pytest.raises(ModuleNotFoundError):
        import digr.updater  # noqa: F401
