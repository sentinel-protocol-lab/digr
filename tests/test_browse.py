"""Tests for browse tools."""

import pytest

from digr.tools.browse import (
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
    lines = [l for l in result.split("\n") if l.strip() and l.strip()[0].isdigit() and ". " in l]
    assert len(lines) <= 2
