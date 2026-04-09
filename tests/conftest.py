"""Shared test fixtures."""

import pytest
from pathlib import Path

from digr.config import Config
from digr.tools._shared import set_libraries


@pytest.fixture
def sample_dir(tmp_path):
    """Create a temporary sample library with test files."""
    # Create drum samples
    kicks = tmp_path / "Drums" / "Kicks"
    kicks.mkdir(parents=True)
    (kicks / "kick_808.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    (kicks / "kick_acoustic.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    (kicks / "kick_909.wav").write_bytes(b"RIFF" + b"\x00" * 40)

    snares = tmp_path / "Drums" / "Snares"
    snares.mkdir(parents=True)
    (snares / "snare_tight.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    (snares / "snare_crack.aif").write_bytes(b"FORM" + b"\x00" * 40)

    hihats = tmp_path / "Drums" / "HiHats"
    hihats.mkdir(parents=True)
    (hihats / "hihat_closed.wav").write_bytes(b"RIFF" + b"\x00" * 40)

    # Create bass samples
    bass = tmp_path / "Bass"
    bass.mkdir(parents=True)
    (bass / "bass_808_sub.wav").write_bytes(b"RIFF" + b"\x00" * 40)

    # Create a MIDI file directory
    midi = tmp_path / "MIDI"
    midi.mkdir(parents=True)

    return tmp_path


@pytest.fixture
def second_library(tmp_path_factory):
    """Create a second temporary library for multi-library tests."""
    lib2 = tmp_path_factory.mktemp("library2")
    kicks = lib2 / "Kicks"
    kicks.mkdir(parents=True)
    (kicks / "kick_vinyl.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    (kicks / "kick_808_hard.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    return lib2


@pytest.fixture
def mock_libraries(sample_dir, second_library):
    """Set up mock libraries and return the config."""
    libraries = {
        "Test Library": sample_dir,
        "Second Library": second_library,
    }
    set_libraries(libraries)
    return Config(libraries=libraries)


@pytest.fixture(autouse=True)
def reset_search_cache():
    """Clear search cache before each test."""
    from digr.tools._shared import set_last_search_results

    set_last_search_results([])
    yield
    set_last_search_results([])


@pytest.fixture(autouse=True)
def reset_license():
    """Reset license state before each test to ensure isolation."""
    from digr.tools._shared import set_license_key

    set_license_key(None)
    yield
    set_license_key(None)
