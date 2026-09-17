"""Shared test fixtures."""

from pathlib import Path

import pytest

from digr.config import Config
from digr.tools import _shared
from digr.tools._shared import set_libraries


@pytest.fixture(autouse=True)
def _isolate_config_dir(tmp_path_factory, monkeypatch):
    """Redirect every config/license write into a throwaway temp dir.

    Digr persists libraries to ``~/.config/digr/config.yaml`` (and the licence
    key/token alongside). Without isolation, any test that calls ``add_library``
    writes to the developer's REAL config and clobbers their live library list
    (this actually happened — see fix-test-config-isolation). ``DIGR_CONFIG_DIR``
    overrides the config dir on all platforms, so pointing it at a fresh temp
    dir guarantees no test can ever touch the real one.
    """
    cfg = tmp_path_factory.mktemp("digr_config")
    monkeypatch.setenv("DIGR_CONFIG_DIR", str(cfg))
    yield


@pytest.fixture(autouse=True)
def _reset_libraries():
    """Clear the in-memory library store around each test.

    The store is a module-level dict; without a reset it leaks between tests, so
    a save triggered by one test would persist libraries a previous test left
    behind. Combined with _isolate_config_dir, this keeps every test hermetic.
    """
    set_libraries({})
    yield
    set_libraries({})


@pytest.fixture(autouse=True)
def _audio_stack_ready():
    """Treat the audio stack as warmed by default so Pro audio tools run their
    real logic in tests.

    The background warm-up (and the "still warming up" gate it feeds) only runs
    in a live server; in tests numpy/scipy are already importable, so we mark it
    ready before each test. Tests that exercise the cold-window gate clear this
    themselves.
    """
    _shared._audio_ready.set()
    yield


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
def ableton_pack_library(tmp_path_factory):
    """A library with a real sample alongside an Ableton Pack's own preview clips.

    Mirrors an installed Ableton Pack: real content in its normal folders, plus
    the pack's ``Ableton Folder Info`` housekeeping directory, whose ``Previews``
    tree holds Live's own preset-preview clips -- never something a producer
    would want returned as a sample. The subfolder names under ``Previews`` vary
    per pack (Drums, Sounds, MIDI Clips, ...), so the fixture uses one of many
    real ones to make clear the filter can't key on that.
    """
    lib = tmp_path_factory.mktemp("ableton_pack_library")
    kits = lib / "Clubber Kit" / "Samples"
    kits.mkdir(parents=True)
    (kits / "Clap 01.wav").write_bytes(b"RIFF" + b"\x00" * 40)

    previews = lib / "Clubber Kit" / "Ableton Folder Info" / "Previews" / "Drums"
    previews.mkdir(parents=True)
    (previews / "Clubber Kit.adg.ogg").write_bytes(b"OggS" + b"\x00" * 40)

    set_libraries({"Ableton Pack Library": lib})
    return lib


@pytest.fixture
def vocabulary_library(tmp_path_factory):
    """A library named the way real packs are named.

    Every file here exists to pin one behaviour of the plain-English engine,
    and several are lifted straight from real reports: the Loopmasters pack
    folder that "loop" used to match, the MusicRadar kick labelled BD, and the
    two files ("Abduction", "Seabed") that a substring bd->kick rule would
    wrongly resurrect.
    """
    lib = tmp_path_factory.mktemp("vocabulary_library")

    files = [
        # Pack folder that must NOT be matched by "loop"...
        "Loopmasters/Drum Hits/TSP_NOISIA_174_dnb_break.wav",
        # ...while a file with "Loop" in its NAME still is. Also the
        # MusicRadar-style kick labelled BD.
        "MusicRadar/E808_Loop_BD_01.wav",
        # Plural/singular, and folder-only vs filename ranking.
        "Breaks/Old Skool/amen_break.wav",
        "Breaks/dusty_hit.wav",
        # Spelling variants of the same instrument.
        "Drums/HiHats/hi-hat_closed_01.wav",
        # Abbreviation in the filename, full word in the folder.
        "Drums/Percussion/shaker_soft.wav",
        "Drums/Loose/perc_rattle_01.wav",
        # These two must never come back for "kick".
        "FX/Abduction_FX.wav",
        "Pads/Seabed_pad.wav",
        # Substring fallback inside a filename token.
        "FX/Big_Reverb_Tail.wav",
        # The reported '.mid returns .wav files' pack folder, alongside a real
        # MIDI file that a type search should still find.
        "Ghosthack.Platinum.Bundle.2019.WAV.MiDi.SERUM.PRESETS/DSS_Bass_38_Am.wav",
        "Midi Files/Drum Breaks/DnB Break 04.mid",
    ]
    for relative in files:
        path = lib / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF" + b"\x00" * 40)

    set_libraries({"Vocabulary Library": lib})
    return lib


@pytest.fixture
def symptom_c_library(tmp_path_factory):
    """One incidental full-AND match alongside a much larger near-miss set.

    Modelled on the real drive, where "dark 174 break" returns a single genuine
    hit and hides 58 better near-misses. The full match is deliberately scored
    LOWER than the near-misses (its terms land on folders, theirs on filenames)
    so that ranking on raw score alone would put a file that ignores "dark"
    above one that honours it.
    """
    lib = tmp_path_factory.mktemp("symptom_c_library")

    files = [
        # The single full match: "dark" and "174" land on FOLDERS, so it scores
        # 2 + 2 + 3 = 7 with no all-in-filename bonus.
        "Dark/174/break_hit.wav",
        # Near-misses: both terms in the FILENAME, so 3 + 3 + 2 = 8 -- higher
        # than the full match above.
        "Loops/174_break_loop.wav",
    ]
    files += [f"Loops/amen_174_break_{i:02}.wav" for i in range(1, 11)]

    for relative in files:
        path = lib / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF" + b"\x00" * 40)

    set_libraries({"Symptom C Library": lib})
    return lib


@pytest.fixture
def partial_overflow_library(tmp_path_factory):
    """More near-misses than the old first-N partial pool cap would hold.

    No fixture anywhere overflowed a cap AND exercised the partial path at
    the same time, which left the two-bar prefilter resting on two tests
    written for something else. This is that fixture.

    Every file is in ONE directory: split across folders, the filesystem can
    hand over a convenient order and let a first-N cap look correct by luck.
    """
    lib = tmp_path_factory.mktemp("partial_overflow_library")
    folder = lib / "Breaks"
    folder.mkdir(parents=True, exist_ok=True)

    # 2,500 near-misses -- comfortably past the 2,000 first-N cap.
    for i in range(2500):
        (folder / f"amen_174_break_{i:04}.wav").write_bytes(b"RIFF" + b"\x00" * 40)

    set_libraries({"Partial Overflow Library": lib})
    return lib


@pytest.fixture
def bpm_range_library(tmp_path_factory):
    """Shakers labelled only by a bare number in their filename, like
    "..._172_...", with no literal "bpm" word alongside it -- exactly what
    the engine's loose number-token path exists to catch, and what a strict
    BPM-in-filename check would miss.
    """
    lib = tmp_path_factory.mktemp("bpm_range_library")
    files = [
        "Shakers/TSP_NOISIA_172_drum_loop_shakerloopedit.wav",
        "Shakers/TSP_NOISIA_174_shaker_hats.wav",
        "Shakers/TSP_NOISIA_200_shaker.wav",
    ]
    for relative in files:
        path = lib / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF" + b"\x00" * 40)

    set_libraries({"BPM Range Library": lib})
    return lib


@pytest.fixture
def singular_filenames_library(tmp_path_factory):
    """Real packs overwhelmingly name files with the SINGULAR instrument word
    ("kick.wav", not "kicks.wav"), dumped in a flat folder with no
    "Kicks"/"Snares"/"HiHats" path component to save a raw plural-substring
    match. This exact shape used to send 54 of 63 real files to Other.
    """
    lib = tmp_path_factory.mktemp("singular_library")
    folder = lib / "Downloads"
    folder.mkdir(parents=True)
    for name in ("kick.wav", "MTIA_snare.wav", "hat_1.wav"):
        (folder / name).write_bytes(b"RIFF" + b"\x00" * 40)

    set_libraries({"Singular Library": lib})
    return lib


@pytest.fixture
def write_ableton_aifc():
    """Factory: writes a minimal, valid AIFF-C file with a given compression
    type -- by default Ableton's own 'able' codec, which libsndfile (and
    CoreAudio, and ffmpeg) cannot open at all. This is what every compressed
    AIFF inside a real Ableton Pack looks like on disk; used to test that
    Digr recognises and skips this codec instead of attempting a decode that
    can only ever fail.
    """

    def _write(path, compression: bytes = b"able", extra_chunks: bytes = b""):
        comm_data = (
            b"\x00\x01"  # numChannels = 1
            + (1000).to_bytes(4, "big")  # numSampleFrames
            + b"\x00\x10"  # sampleSize = 16
            + b"\x40\x0e\xac\x44\x00\x00\x00\x00\x00\x00"  # sampleRate (80-bit float)
            + compression  # 4-byte compressionType FourCC
            + b"\x00"  # compressionName: zero-length Pascal string
        )
        comm_chunk = b"COMM" + len(comm_data).to_bytes(4, "big") + comm_data
        body = b"AIFC" + extra_chunks + comm_chunk
        data = b"FORM" + len(body).to_bytes(4, "big") + body
        Path(path).write_bytes(data)
        return Path(path)

    return _write


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
