"""Tests for the self-update download source.

The commercial rule under test: "all v1.x updates" means customers receive
RELEASED versions. When a GitHub release exists, --update must download that
exact tag — never main, which may hold unreleased (or future paid-2.0) code.
"""

from digr.updater import GITHUB_ZIP_URL, _download_url


def test_download_url_pins_to_release_tag():
    assert _download_url("1.0.2") == (
        "https://github.com/sentinel-protocol-lab/digr/archive/refs/tags/v1.0.2.zip"
    )


def test_download_url_falls_back_to_main_only_without_a_release():
    assert _download_url(None) == GITHUB_ZIP_URL
    assert "refs/heads/main" in GITHUB_ZIP_URL
