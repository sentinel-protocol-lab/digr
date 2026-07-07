"""Tests for browse tools."""

import pytest

from digr.tools.browse import (
    add_library,
    count_samples_in_folder,
    list_all_samples_in_folder,
    list_folders,
    list_libraries,
)


@pytest.mark.asyncio
async def test_list_libraries(mock_libraries):
    result = await list_libraries()
    assert "Test Library" in result
    assert "Second Library" in result
    assert "Available" in result


@pytest.mark.asyncio
async def test_list_libraries_empty():
    from digr.tools._shared import set_libraries

    set_libraries({})
    result = await list_libraries()
    assert "No sample libraries configured" in result


@pytest.mark.asyncio
async def test_list_folders(mock_libraries):
    result = await list_folders()
    assert "Drums" in result
    assert "Bass" in result
    assert "MIDI" in result


@pytest.mark.asyncio
async def test_count_samples_in_folder(mock_libraries):
    result = await count_samples_in_folder("Drums")
    assert "WAV files:" in result
    assert "AIF/AIFF files:" in result


@pytest.mark.asyncio
async def test_count_includes_mp3_in_grand_total(mock_libraries, sample_dir):
    """MP3/FLAC/OGG files must appear in the totals, not just per-library counts."""
    loops = sample_dir / "Loops"
    loops.mkdir()
    (loops / "loop_a.mp3").write_bytes(b"\x00" * 40)
    (loops / "loop_b.flac").write_bytes(b"\x00" * 40)
    (loops / "loop_c.wav").write_bytes(b"RIFF" + b"\x00" * 40)

    result = await count_samples_in_folder("Loops")
    assert "MP3/FLAC/OGG files: 2" in result
    assert "Grand Total: 3 files" in result


@pytest.mark.asyncio
async def test_count_nonexistent_folder(mock_libraries):
    result = await count_samples_in_folder("NonexistentFolder")
    assert "not found" in result


@pytest.mark.asyncio
async def test_list_all_samples(mock_libraries):
    result = await list_all_samples_in_folder("Drums", max_results=50)
    assert "kick_808.wav" in result
    assert "snare_tight.wav" in result


@pytest.mark.asyncio
async def test_list_all_samples_respects_max(mock_libraries):
    result = await list_all_samples_in_folder("Drums", max_results=2)
    lines = [
        line for line in result.split("\n")
        if line.strip() and line.strip()[0].isdigit() and ". " in line
    ]
    assert len(lines) <= 2


@pytest.mark.asyncio
async def test_list_folders_excludes_macosx(macos_junk_library):
    result = await list_folders()
    assert "Bass Loops" in result
    assert "__MACOSX" not in result


@pytest.mark.asyncio
async def test_list_all_samples_excludes_macos_junk(macos_junk_library):
    result = await list_all_samples_in_folder("Bass Loops", max_results=50)
    assert "Bass Loop 01.wav" in result
    assert "._Bass Loop 01.wav" not in result


@pytest.mark.asyncio
async def test_count_excludes_macos_junk(macos_junk_library):
    # Bass Loops holds one real .wav and its ._ sidecar — only the real one counts.
    result = await count_samples_in_folder("Bass Loops")
    assert "WAV files: 1" in result


@pytest.mark.asyncio
async def test_add_library_count_excludes_macos_junk(tmp_path):
    loops = tmp_path / "Bass Loops"
    loops.mkdir(parents=True)
    (loops / "Bass Loop 01.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    (loops / "._Bass Loop 01.wav").write_bytes(b"\x00\x05\x16\x07")
    macosx = tmp_path / "__MACOSX"
    macosx.mkdir()
    (macosx / "._junk.wav").write_bytes(b"\x00\x05\x16\x07")

    result = await add_library("Junk", str(tmp_path))
    assert "Audio files found: 1" in result
