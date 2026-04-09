"""Tests for search tools."""

import pytest

from digr.tools.search import search_samples
from digr.tools._shared import get_last_search_results


@pytest.mark.asyncio
async def test_search_finds_samples(mock_libraries):
    result = await search_samples("kick", max_results=10)
    assert "kick_808.wav" in result
    assert "kick_acoustic.wav" in result
    assert "kick_909.wav" in result


@pytest.mark.asyncio
async def test_search_multi_keyword(mock_libraries):
    result = await search_samples("kick 808", max_results=10)
    assert "kick_808" in result
    # Should NOT match kick_acoustic (no "808" in path)
    assert "kick_acoustic" not in result


@pytest.mark.asyncio
async def test_search_no_results(mock_libraries):
    result = await search_samples("nonexistent_xyzzy", max_results=10)
    assert "No samples found" in result


@pytest.mark.asyncio
async def test_search_caches_results(mock_libraries):
    await search_samples("kick", max_results=10)
    cached = get_last_search_results()
    assert len(cached) > 0
    assert any("kick" in path.lower() for path, _ in cached)


@pytest.mark.asyncio
async def test_search_balanced_across_libraries(mock_libraries):
    """Results should include samples from both libraries."""
    result = await search_samples("kick 808", max_results=10)
    assert "Test Library" in result
    assert "Second Library" in result


@pytest.mark.asyncio
async def test_search_respects_max_results(mock_libraries):
    result = await search_samples("kick", max_results=2)
    # Count numbered results (lines starting with a digit followed by .)
    lines = [l for l in result.split("\n") if l.strip() and l.strip()[0].isdigit() and ". " in l]
    assert len(lines) <= 2


@pytest.mark.asyncio
async def test_search_matches_folder_names(mock_libraries):
    """Keywords should match against folder names, not just filenames."""
    result = await search_samples("Snares", max_results=10)
    assert "snare_tight.wav" in result
