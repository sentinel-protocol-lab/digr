"""Tests for search tools."""

import pytest

from digr.tools.search import search_samples, search_samples_by_bpm
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
    lines = [
        line for line in result.split("\n")
        if line.strip() and line.strip()[0].isdigit() and ". " in line
    ]
    assert len(lines) <= 2


@pytest.mark.asyncio
async def test_search_matches_folder_names(mock_libraries):
    """Keywords should match against folder names, not just filenames."""
    result = await search_samples("Snares", max_results=10)
    assert "snare_tight.wav" in result


@pytest.mark.asyncio
async def test_bpm_search_caches_results(mock_libraries, pro_license):
    """collect_search_results must work after a BPM search, not read a stale cache."""
    await search_samples_by_bpm("kick", max_results=10)
    cached = get_last_search_results()
    assert len(cached) > 0
    assert all("kick" in path.lower() for path, _ in cached)


@pytest.mark.asyncio
async def test_bpm_search_replaces_stale_keyword_cache(mock_libraries, pro_license):
    """A BPM search after a keyword search must overwrite the older results —
    otherwise 'collect number 2' would silently copy a file from the old search."""
    await search_samples("snare", max_results=10)
    await search_samples_by_bpm("kick", max_results=10)
    cached = get_last_search_results()
    assert len(cached) > 0
    assert all("snare" not in path.lower() for path, _ in cached)


@pytest.mark.asyncio
async def test_search_plural_finds_singular(vocabulary_library):
    """'breaks' used to miss every file called '..._break.wav'."""
    result = await search_samples("breaks", max_results=20)
    assert "amen_break.wav" in result
    assert "TSP_NOISIA_174_dnb_break.wav" in result


@pytest.mark.asyncio
@pytest.mark.parametrize("spelling", ["hihat", "hi-hat", "hat", "hats", "hh"])
async def test_search_hihat_spellings(vocabulary_library, spelling):
    result = await search_samples(spelling, max_results=20)
    assert "hi-hat_closed_01.wav" in result


@pytest.mark.asyncio
async def test_search_perc_and_percussion_agree(vocabulary_library):
    """The abbreviation finds the folder; the full word finds the filename."""
    abbreviated = await search_samples("perc", max_results=20)
    spelled_out = await search_samples("percussion", max_results=20)
    assert "shaker_soft.wav" in abbreviated
    assert "perc_rattle_01.wav" in abbreviated
    assert "perc_rattle_01.wav" in spelled_out


@pytest.mark.asyncio
async def test_search_bpm_token_in_filename(vocabulary_library):
    """'174' has to find '_174_', which packs write far more often than
    '174bpm'."""
    result = await search_samples("174", max_results=20)
    assert "TSP_NOISIA_174_dnb_break.wav" in result


@pytest.mark.asyncio
async def test_search_bpm_word_is_grammar_not_a_requirement(vocabulary_library):
    """'174 bpm' must not exclude files that only write '_174_'."""
    result = await search_samples("174 bpm", max_results=20)
    assert "TSP_NOISIA_174_dnb_break.wav" in result


@pytest.mark.asyncio
async def test_search_loop_does_not_match_the_loopmasters_folder(vocabulary_library):
    """A pack folder must not answer for every file inside it."""
    result = await search_samples("loop", max_results=20)
    assert "E808_Loop_BD_01.wav" in result
    assert "TSP_NOISIA_174_dnb_break.wav" not in result


@pytest.mark.asyncio
async def test_search_kick_finds_bd_labelled_packs(vocabulary_library):
    """MusicRadar/SampleRadar label kicks 'BD' -- a real vocabulary gap."""
    result = await search_samples("kick", max_results=20)
    assert "E808_Loop_BD_01.wav" in result


@pytest.mark.asyncio
async def test_search_kick_does_not_resurrect_substring_false_positives(
    vocabulary_library,
):
    """The exact files the substring approach was rejected over."""
    result = await search_samples("kick", max_results=20)
    assert "Abduction_FX.wav" not in result
    assert "Seabed_pad.wav" not in result


@pytest.mark.asyncio
async def test_search_substring_fallback_inside_a_filename(vocabulary_library):
    result = await search_samples("verb", max_results=20)
    assert "Big_Reverb_Tail.wav" in result


@pytest.mark.asyncio
async def test_search_ranks_filename_hits_above_folder_hits(vocabulary_library):
    result = await search_samples("break", max_results=20)
    assert result.index("amen_break.wav") < result.index("dusty_hit.wav")


@pytest.mark.asyncio
async def test_search_mid_no_longer_returns_wav_files(vocabulary_library):
    """The reported bug: '.mid' matched a folder called '...WAV.MiDi.SERUM...'
    and returned .wav files. Type search itself still works."""
    result = await search_samples(".mid", max_results=20)
    assert "DnB Break 04.mid" in result
    assert "DSS_Bass_38_Am.wav" not in result


@pytest.mark.asyncio
async def test_search_partial_match_reports_what_it_dropped(vocabulary_library):
    """No file is named 'dark', so the query would have been a dead end."""
    result = await search_samples("dark 174 break", max_results=20)
    assert "No exact match" in result
    assert "'dark'" in result
    assert "TSP_NOISIA_174_dnb_break.wav" in result


@pytest.mark.asyncio
async def test_partial_match_results_are_collectable(vocabulary_library):
    """Partial results are shown numbered, so they must be cached like any
    other search or 'collect number 1' would act on a stale list."""
    await search_samples("dark 174 break", max_results=20)
    cached = get_last_search_results()
    assert any("dnb_break" in path for path, _ in cached)


@pytest.mark.asyncio
async def test_search_excludes_macos_junk(macos_junk_library):
    """AppleDouble sidecars and __MACOSX contents must never surface as samples."""
    result = await search_samples("bass loop", max_results=50)
    # The real sample still comes through.
    assert "Bass Loop 01.wav" in result
    # The ._ AppleDouble sidecar is filtered out.
    assert "._Bass Loop 01.wav" not in result
    # Nothing inside __MACOSX surfaces — even a non-dotfile.
    assert "__MACOSX" not in result
    assert "Bass Loop 99.wav" not in result
