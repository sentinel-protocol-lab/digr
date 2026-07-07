"""Shared test fixtures."""

import pytest

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
def macos_junk_library(tmp_path_factory):
    """A library with real samples alongside macOS metadata junk.

    Mirrors a Mac-zipped sample pack unpacked on Windows: an AppleDouble
    sidecar (._Name.wav) next to a real file, plus a __MACOSX folder whose
    contents (dotfile or not) are all junk.
    """
    lib = tmp_path_factory.mktemp("junk_library")
    loops = lib / "Bass Loops"
    loops.mkdir(parents=True)
    (loops / "Bass Loop 01.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    (loops / "._Bass Loop 01.wav").write_bytes(b"\x00\x05\x16\x07")  # AppleDouble

    macosx = lib / "__MACOSX" / "Bass Loops"
    macosx.mkdir(parents=True)
    (macosx / "._Bass Loop 01.wav").write_bytes(b"\x00\x05\x16\x07")
    (macosx / "Bass Loop 99.wav").write_bytes(b"\x00\x05\x16\x07")  # non-dotfile, still junk

    set_libraries({"Junk Library": lib})
    return lib


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
def reset_license(monkeypatch):
    """Reset license state before each test to ensure isolation.

    Also blanks the product ID (env var AND baked-in constant) so no test can
    accidentally reach the real Gumroad API; tests that need a product ID set
    DIGR_GUMROAD_PRODUCT_ID explicitly, which takes priority.
    """
    import digr.licensing as licensing
    from digr.tools._shared import set_license_key

    monkeypatch.delenv("DIGR_GUMROAD_PRODUCT_ID", raising=False)
    monkeypatch.setattr(licensing, "GUMROAD_PRODUCT_ID", None)
    set_license_key(None)
    yield
    set_license_key(None)


@pytest.fixture
def pro_license(monkeypatch):
    """Unlock Pro tools by stubbing license activation (no network, no token files)."""
    import digr.licensing as licensing
    from digr.tools._shared import set_license_key

    monkeypatch.setattr(licensing, "activate_or_check", lambda key: (True, None))
    set_license_key("TEST0000-TEST0000-TEST0000-TEST0000")
    yield
    set_license_key(None)
