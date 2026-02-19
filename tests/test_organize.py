"""Tests for organize tools."""

import pytest
from pathlib import Path

from sample_library_manager.tools.organize import (
    collect_samples,
    collect_search_results,
    copy_samples,
    sort_samples,
)
from sample_library_manager.tools.search import search_samples


@pytest.mark.asyncio
async def test_collect_samples_preview(mock_libraries, tmp_path):
    dest = str(tmp_path / "collected")
    result = await collect_samples("kick", dest, max_results=5, confirm=False)
    assert "PREVIEW" in result
    assert "kick" in result.lower()
    # Should NOT have actually created the directory
    assert not (tmp_path / "collected").exists()


@pytest.mark.asyncio
async def test_collect_samples_execute(mock_libraries, tmp_path):
    dest = str(tmp_path / "collected")
    result = await collect_samples("kick", dest, max_results=5, confirm=True)
    assert "copied" in result.lower() or "Copied" in result
    # Files should exist
    assert (tmp_path / "collected").exists()


@pytest.mark.asyncio
async def test_copy_samples_preview(mock_libraries, sample_dir, tmp_path):
    kick_path = str(sample_dir / "Drums" / "Kicks" / "kick_808.wav")
    dest = str(tmp_path / "copied")
    result = await copy_samples([kick_path], dest, confirm=False)
    assert "PREVIEW" in result
    assert "kick_808.wav" in result


@pytest.mark.asyncio
async def test_copy_samples_execute(mock_libraries, sample_dir, tmp_path):
    kick_path = str(sample_dir / "Drums" / "Kicks" / "kick_808.wav")
    dest = str(tmp_path / "copied")
    result = await copy_samples([kick_path], dest, confirm=True)
    assert "1/1" in result
    assert (tmp_path / "copied" / "kick_808.wav").exists()


@pytest.mark.asyncio
async def test_copy_samples_missing_file(mock_libraries, tmp_path):
    dest = str(tmp_path / "copied")
    result = await copy_samples(["/nonexistent/file.wav"], dest, confirm=False)
    assert "ERROR" in result or "not found" in result.lower()


@pytest.mark.asyncio
async def test_collect_search_results_no_cache(mock_libraries, tmp_path):
    dest = str(tmp_path / "collected")
    result = await collect_search_results("1,2", dest, confirm=False)
    assert "ERROR" in result
    assert "search_samples first" in result


@pytest.mark.asyncio
async def test_collect_search_results_preview(mock_libraries, tmp_path):
    # First, run a search to populate cache
    await search_samples("kick", max_results=5)
    dest = str(tmp_path / "collected")
    result = await collect_search_results("1,2", dest, confirm=False)
    assert "PREVIEW" in result


@pytest.mark.asyncio
async def test_sort_samples_preview(mock_libraries, tmp_path):
    dest = str(tmp_path / "sorted")
    result = await sort_samples("wav", dest, max_results=20, confirm=False)
    # Should categorize some files
    assert "PREVIEW" in result


@pytest.mark.asyncio
async def test_sort_samples_execute(mock_libraries, tmp_path):
    dest = str(tmp_path / "sorted")
    result = await sort_samples(
        "kick", dest, categories="Kicks,Other", max_results=10, confirm=True
    )
    assert (tmp_path / "sorted").exists()
