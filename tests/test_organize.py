"""Tests for organize tools."""

import numpy as np
import pytest
import soundfile as sf

from digr.tools.organize import (
    collect_samples,
    collect_search_results,
    copy_samples,
    rename_with_metadata,
    sort_samples,
)
from digr.tools.search import search_samples


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
    assert "search_samples" in result


@pytest.mark.asyncio
async def test_collect_search_results_preview(mock_libraries, tmp_path):
    # First, run a search to populate cache
    await search_samples("kick", max_results=5)
    dest = str(tmp_path / "collected")
    result = await collect_search_results("1,2", dest, confirm=False)
    assert "PREVIEW" in result


@pytest.mark.asyncio
async def test_sort_samples_preview(mock_libraries, pro_license, tmp_path):
    dest = str(tmp_path / "sorted")
    result = await sort_samples("wav", dest, max_results=20, confirm=False)
    # Should categorize some files
    assert "PREVIEW" in result


@pytest.mark.asyncio
async def test_sort_samples_execute(mock_libraries, pro_license, tmp_path):
    dest = str(tmp_path / "sorted")
    result = await sort_samples(
        "kick", dest, categories="Kicks,Other", max_results=10, confirm=True
    )
    assert "Copied" in result
    assert (tmp_path / "sorted").exists()


# ---------------------------------------------------------------------------
# rename_with_metadata -- the producer's label wins
# ---------------------------------------------------------------------------
#
# This tool renames the user's files IN PLACE with no undo, and had no
# behaviour tests until now -- only licence-gate references. The defect that
# prompted these was found on a real drive, not by this suite: a file the
# producer had labelled 117 BPM was permanently renamed to 123bpm, because
# detection landed inside the old +/-8% agreement window and its estimate was
# preferred to the label.
#
# These use REAL generated audio through the REAL detector rather than a stub.
# The bug lived in the seam between what detection returned and what was
# written to disk, so a stubbed detector would have reported success.


def _click_track(bpm: float, sr: int = 22050, duration: float = 10.0) -> np.ndarray:
    """A loop at a known tempo, with attacks sharp enough to be detectable."""
    samples = int(sr * duration)
    y = np.zeros(samples, dtype=np.float32)
    interval = int(60.0 / bpm * sr)
    click_len = int(0.005 * sr)
    for i in range(0, samples, interval):
        end = min(i + click_len, samples)
        envelope = np.exp(-np.linspace(0, 5, end - i))
        y[i:end] = 0.9 * envelope.astype(np.float32)
    return y


def _write_loop(directory, name: str, bpm: float):
    path = directory / name
    sf.write(str(path), _click_track(bpm), 22050)
    return path


@pytest.mark.asyncio
async def test_rename_keeps_a_labelled_files_own_tempo(pro_license, tmp_path):
    """The real-drive defect. The file says 117 and measures ~123; the rename
    must not put 123 on it. A filename BPM is the producer's statement about
    their own file, and detection is an estimate -- the estimate must never
    overwrite the statement."""
    path = _write_loop(tmp_path, "Aisha - The Creator 117 BPM.wav", 123.0)

    preview = await rename_with_metadata(str(path), include_bpm=True, confirm=False)

    assert "123bpm" not in preview
    assert "117" in preview


@pytest.mark.asyncio
async def test_rename_does_not_append_a_label_to_itself(pro_license, tmp_path):
    """A file already labelled 112 gains no second tag."""
    path = _write_loop(tmp_path, "voice-fx-spooky-scream_112bpm.wav", 112.0)

    preview = await rename_with_metadata(str(path), include_bpm=True, confirm=False)

    assert "112bpm_112bpm" not in preview
    assert "already labelled" in preview
    assert "(SKIPPED)" in preview


@pytest.mark.asyncio
async def test_rename_dedup_sees_through_case_and_spacing(pro_license, tmp_path):
    """Real packs write "145BPM", "145 bpm" and "145_bpm" for the same thing,
    and the dedup has to read all of them as already stated."""
    path = _write_loop(tmp_path, "FPV_Kit_Drop_145BPM.wav", 145.0)

    preview = await rename_with_metadata(str(path), include_bpm=True, confirm=False)

    assert "already labelled" in preview
    assert "(SKIPPED)" in preview  # nothing left to append, so no rename
    assert "->" not in preview


@pytest.mark.asyncio
async def test_rename_still_appends_to_an_unlabelled_file(pro_license, tmp_path):
    """The feature still works: with no label to defer to, the measurement is
    what the tool has to offer and it is appended."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)

    preview = await rename_with_metadata(str(path), include_bpm=True, confirm=False)

    assert "-> untitled_loop_1" in preview  # a 1xx bpm tag was appended
    assert "bpm" in preview


@pytest.mark.asyncio
async def test_rename_metadata_flags_are_both_off_by_default(pro_license, tmp_path):
    """Both flags write a permanent change on the strength of an estimate, so
    neither may happen unless asked for. Key detection in particular has never
    had its accuracy measured."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)

    result = await rename_with_metadata(str(path))

    # Nothing was requested, so there is nothing to do -- and in particular no
    # tempo or key was appended by assumption.
    assert "ERROR: Nothing to do" in result


@pytest.mark.asyncio
async def test_rename_prefix_only_still_works(tmp_path):
    """Prefix-only renaming is the free path and is unaffected by any of this
    -- note this test deliberately takes no pro_license fixture."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)

    preview = await rename_with_metadata(str(path), prefix="DNB")

    assert "DNB_untitled_loop.wav" in preview
    assert "bpm" not in preview.lower()


@pytest.mark.asyncio
async def test_rename_preview_leaves_the_file_untouched(tmp_path):
    """The two-phase confirm is the only thing standing between a wrong rename
    and a manual repair job, so the preview must be inert."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)
    before = sorted(p.name for p in tmp_path.iterdir())

    await rename_with_metadata(str(path), prefix="DNB", confirm=False)

    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert path.exists()


@pytest.mark.asyncio
async def test_rename_confirm_actually_renames(tmp_path):
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)

    await rename_with_metadata(str(path), prefix="DNB", confirm=True)

    assert not path.exists()
    assert (tmp_path / "DNB_untitled_loop.wav").exists()
