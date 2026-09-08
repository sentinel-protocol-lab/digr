"""Tests for organize tools."""

import numpy as np
import pytest
import soundfile as sf

from digr.tools._rename_log import MAX_BATCHES, history_path, read_batches
from digr.tools.organize import (
    collect_samples,
    collect_search_results,
    copy_samples,
    rename_with_metadata,
    sort_samples,
    undo_rename,
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


# ---------------------------------------------------------------------------
# undo_rename -- every rename is reversible
# ---------------------------------------------------------------------------
#
# A rename that is wrong but undoable is a nuisance. A rename that is wrong and
# permanent is data loss, and every rename Digr made used to be the second
# kind. The history lives in the config dir, which conftest redirects into a
# temp dir per test, so these never touch a real user's log.


@pytest.mark.asyncio
async def test_undo_restores_a_prefix_rename(tmp_path):
    """Prefix-only renaming is the FREE path and involves no detection at all,
    but a typo applied to a whole library is still a manual repair job. It has
    to be logged and undoable like anything else -- note no pro_license here,
    for either the rename or the undo."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)
    await rename_with_metadata(str(path), prefix="DNB", confirm=True)
    assert (tmp_path / "DNB_untitled_loop.wav").exists()

    result = await undo_rename(confirm=True)

    assert (tmp_path / "untitled_loop.wav").exists()
    assert not (tmp_path / "DNB_untitled_loop.wav").exists()
    assert "1/1" in result


@pytest.mark.asyncio
async def test_undo_preview_restores_nothing(tmp_path):
    """Same two-phase confirm as every other destructive tool."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)
    await rename_with_metadata(str(path), prefix="DNB", confirm=True)

    result = await undo_rename(confirm=False)

    assert "PREVIEW" in result
    assert "DNB_untitled_loop.wav" in result
    assert (tmp_path / "DNB_untitled_loop.wav").exists()  # still renamed
    assert not (tmp_path / "untitled_loop.wav").exists()


@pytest.mark.asyncio
async def test_undo_with_no_history_says_so(tmp_path):
    result = await undo_rename(confirm=True)
    assert "ERROR" in result
    assert "No renames to undo" in result


@pytest.mark.asyncio
async def test_undo_reverses_the_most_recent_batch_only(tmp_path):
    """Batches are the unit of undo because they are the unit the user thinks
    in: put back what that last call did, not everything ever."""
    first = _write_loop(tmp_path, "one.wav", 120.0)
    await rename_with_metadata(str(first), prefix="A", confirm=True)
    second = _write_loop(tmp_path, "two.wav", 120.0)
    await rename_with_metadata(str(second), prefix="B", confirm=True)

    await undo_rename(confirm=True)

    assert (tmp_path / "two.wav").exists()  # newest batch reversed
    assert (tmp_path / "A_one.wav").exists()  # older batch untouched


@pytest.mark.asyncio
async def test_a_second_undo_walks_back_to_the_previous_batch(tmp_path):
    first = _write_loop(tmp_path, "one.wav", 120.0)
    await rename_with_metadata(str(first), prefix="A", confirm=True)
    second = _write_loop(tmp_path, "two.wav", 120.0)
    await rename_with_metadata(str(second), prefix="B", confirm=True)

    await undo_rename(confirm=True)
    await undo_rename(confirm=True)

    assert (tmp_path / "one.wav").exists()
    assert (tmp_path / "two.wav").exists()
    assert read_batches() == []


@pytest.mark.asyncio
async def test_undo_skips_a_file_that_moved_since(tmp_path):
    """Skip and report, never guess. Digr has no idea where the file went."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)
    await rename_with_metadata(str(path), prefix="DNB", confirm=True)
    (tmp_path / "DNB_untitled_loop.wav").unlink()

    result = await undo_rename(confirm=True)

    assert "0/1" in result
    assert "no longer there" in result


@pytest.mark.asyncio
async def test_undo_skips_when_the_original_name_is_taken(tmp_path):
    """Restoring would clobber whatever now holds that name, which is a second
    destructive act performed to reverse the first."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)
    await rename_with_metadata(str(path), prefix="DNB", confirm=True)
    _write_loop(tmp_path, "untitled_loop.wav", 90.0)  # something else claimed it

    result = await undo_rename(confirm=True)

    assert "already exists" in result
    assert (tmp_path / "DNB_untitled_loop.wav").exists()  # not clobbered


@pytest.mark.asyncio
async def test_an_unreversed_entry_stays_in_the_history_for_a_retry(tmp_path):
    """Dropping the whole batch would strand exactly the files that failed to
    restore -- the permanent-loss problem this log exists to remove."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)
    await rename_with_metadata(str(path), prefix="DNB", confirm=True)
    blocker = _write_loop(tmp_path, "untitled_loop.wav", 90.0)

    await undo_rename(confirm=True)
    assert len(read_batches()) == 1  # kept, not dropped

    blocker.unlink()  # obstruction cleared
    result = await undo_rename(confirm=True)

    assert "1/1" in result
    assert (tmp_path / "untitled_loop.wav").exists()


@pytest.mark.asyncio
async def test_only_successful_renames_are_logged(tmp_path):
    """The log must never claim a rename that did not happen."""
    real = _write_loop(tmp_path, "untitled_loop.wav", 120.0)
    await rename_with_metadata(
        [str(real), "/nonexistent/ghost.wav"], prefix="DNB", confirm=True
    )

    batches = read_batches()
    assert len(batches) == 1
    assert len(batches[0]["renames"]) == 1
    assert "untitled_loop" in batches[0]["renames"][0]["from"]


@pytest.mark.asyncio
async def test_history_is_capped(tmp_path):
    """An append-only file in the config dir has nothing else to prune it."""
    for i in range(MAX_BATCHES + 5):
        path = _write_loop(tmp_path, f"loop_{i}.wav", 120.0)
        await rename_with_metadata(str(path), prefix=f"P{i}", confirm=True)

    assert len(read_batches()) == MAX_BATCHES


@pytest.mark.asyncio
async def test_a_corrupt_line_does_not_block_the_rest_of_the_history(tmp_path):
    """This file is read when a user is trying to undo damage. A stray bad
    line must not be what stops them getting their history back."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)
    await rename_with_metadata(str(path), prefix="DNB", confirm=True)

    log = history_path()
    log.write_text("not json at all\n" + log.read_text(encoding="utf-8"), encoding="utf-8")

    result = await undo_rename(confirm=True)

    assert (tmp_path / "untitled_loop.wav").exists()
    assert "1/1" in result


@pytest.mark.asyncio
async def test_rename_points_the_user_at_undo(tmp_path):
    """The tool that does the damage should say how to reverse it."""
    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)

    result = await rename_with_metadata(str(path), prefix="DNB", confirm=True)

    assert "undo_rename" in result


@pytest.mark.asyncio
async def test_undo_is_free_and_works_with_no_licence(tmp_path):
    """Undoing damage must never sit behind a licence. A lapsed or unactivated
    key would strand a user mid-rename, which is exactly when they need this
    most. The gate is ON and no key is set here (see conftest's reset_license),
    so this test fails the moment undo_rename is made Pro."""
    from digr.tools import _shared
    from digr.tools._shared import is_pro_licensed

    assert _shared.ENFORCE_LICENSE_GATE  # the gate is live for this test
    assert not is_pro_licensed()  # and the user has no licence

    path = _write_loop(tmp_path, "untitled_loop.wav", 120.0)
    await rename_with_metadata(str(path), prefix="DNB", confirm=True)

    result = await undo_rename(confirm=True)

    assert "Pro" not in result
    assert (tmp_path / "untitled_loop.wav").exists()
