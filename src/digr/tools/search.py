"""Search tools: search_samples, search_samples_by_bpm."""

from pathlib import Path

from ._query import BPM_MAX, BPM_MIN, BpmTarget, file_tokens, parse_query
from ._shared import (
    audio_warming_message,
    get_libraries,
    require_pro,
    search_all_libraries,
    search_libraries,
    set_last_search_results,
)

# Below this length, tempo detection is unreliable (one-shots have no
# rhythm to autocorrelate against) -- report "no tempo" rather than a number.
ONE_SHOT_MAX_DURATION = 3.0

# How far a detected tempo may drift from a filename/folder label before it
# is shown as a disagreement rather than a confirmation. Producers don't
# mislabel BPM, so a label is trusted either way -- this only changes the
# wording, matching detect_tempo_with_hint's own harmonic tolerance.
BPM_LABEL_TOLERANCE = 0.08


def _require_audio():
    """Import audio analysis module, raising a clear error if not installed."""
    try:
        from . import _audio_analysis as audio
        import numpy as np

        return audio, np
    except ImportError:
        raise RuntimeError(
            "Audio analysis requires the 'audio' extras. "
            "Install with: pip install digr[audio]"
        )


def _resolve_bpm_filter(
    min_bpm: float | None, max_bpm: float | None
) -> BpmTarget | None:
    """Turn explicit min/max params into a BpmTarget, or None if neither given.

    Swaps a reversed range and clamps to the engine's supported band
    (BPM_MIN-BPM_MAX) rather than erroring -- a typo'd range should still
    search something sensible.
    """
    if min_bpm is None and max_bpm is None:
        return None
    low = float(min_bpm) if min_bpm is not None else BPM_MIN
    high = float(max_bpm) if max_bpm is not None else BPM_MAX
    if low > high:
        low, high = high, low
    return BpmTarget(max(BPM_MIN, low), min(BPM_MAX, high))


def _format_bpm_line(tempo: float, duration: float, label: float | None) -> str:
    """Compose the BPM line for one match: one-shot honesty first, then
    labelled-primary/detected-confirmation when a range filter applied.

    Kept separate from the search loop (which does file I/O and exception
    handling) so this decision -- the actual tricky part -- can be tested
    directly with plain numbers, no audio decoding required.
    """
    is_one_shot = duration < ONE_SHOT_MAX_DURATION or tempo == 0.0
    if is_one_shot:
        return (
            f"labelled {label:.0f} — one-shot, no tempo detected"
            if label is not None
            else "one-shot — no tempo"
        )
    if label is not None:
        if abs(tempo - label) <= label * BPM_LABEL_TOLERANCE:
            return f"{label:.0f} (confirmed by detection: {tempo:.1f})"
        return f"{label:.0f} (labelled) — detected {tempo:.1f}, trusting the label"
    return f"{tempo:.1f}"


def _label_bpm(path: str, library_name: str, target: BpmTarget) -> float | None:
    """The in-range number that satisfied a tempo filter, for display.

    Re-running the strict ``extract_bpm_from_filename`` here would miss bare
    "_174_" labels (no literal "bpm" token) -- exactly the files the range
    filter exists to catch. So this reads the SAME loose hint/number tokens
    the matcher used: the filename BPM hint if it's in range, else any
    in-range number token from the filename or folder.
    """
    root = get_libraries().get(library_name)
    bag = file_tokens(path, root=root)
    if bag.bpm_hint is not None and target.contains(bag.bpm_hint):
        return bag.bpm_hint
    in_range = sorted(n for n in bag.numbers if target.contains(n))
    return float(in_range[0]) if in_range else None


async def search_samples(keyword: str, max_results: int = 100) -> str:
    """Search for audio samples and MIDI files across all configured sample libraries.

    Matches keywords against the full file path including folder names.
    Multiple keywords are matched independently (all must appear).
    Results are balanced across libraries.
    """
    outcome = search_libraries(keyword, max_results, allow_partial=True)
    matches = outcome.matches

    if not matches:
        set_last_search_results([])
        return (
            f"No samples found matching '{keyword}' across all libraries.\n"
            f"Hint: Check that libraries are mounted with list_libraries. "
            f"Try simpler keywords (e.g., 'kick' instead of 'dark punchy kick')."
        )

    # Cache results for collect_search_results
    set_last_search_results(matches)

    if outcome.partial:
        # Nothing satisfied every word. Say which words DID land and show
        # those files, rather than returning a dead end.
        matched = " + ".join(f"'{t}'" for t in outcome.matched_terms)
        missing = " or ".join(f"'{t}'" for t in outcome.missing_terms)
        count = outcome.partial_total
        noun = "file" if count == 1 else "files"
        result = (
            f"No exact match for '{keyword}'. "
            f"{count} {noun} matched {matched} but not {missing} "
            f"— showing those (top {len(matches)}):\n\n"
        )
    else:
        result = f"Found samples matching '{keyword}' (showing {len(matches)}):\n\n"

    for i, (path, library_name) in enumerate(matches, 1):
        filename = Path(path).name
        folder = Path(path).parent.name
        result += f"{i}. {filename}\n"
        result += f"   Library: {library_name}\n"
        result += f"   Folder: {folder}\n"
        result += f"   Path: {path}\n\n"

    result += "Use collect_search_results with the result numbers above to copy/move files to a folder."

    return result


async def search_samples_by_bpm(
    keyword: str,
    min_bpm: int | None = None,
    max_bpm: int | None = None,
    max_results: int = 20,
) -> str:
    """Search for samples by keyword and automatically detect BPM for each result.

    Pass min_bpm and/or max_bpm to search a tempo RANGE, e.g. min_bpm=170,
    max_bpm=178 for "shakers between 170 and 178 BPM". A range typed straight
    into the keyword also works ("shaker 170-178", "shaker around 174") --
    the params are the reliable way to trigger it, not the only way.

    With a range, results are already filtered to samples whose filename or
    folder carries an in-range tempo, so this shows that label as the BPM
    and detects each one only to confirm it -- the Pro value is trustworthy,
    range-filtered results, not raw detection. Without a range, every match
    is detected and shown as before. Recommended 5-20 results for speed.
    Results are balanced across all configured libraries. Pro feature.
    """
    gate = require_pro("search_samples_by_bpm")
    if gate:
        return gate

    bpm_filter = _resolve_bpm_filter(min_bpm, max_bpm)
    effective_range = bpm_filter
    if effective_range is None:
        keyword_targets = parse_query(keyword).bpm_targets
        effective_range = keyword_targets[0] if keyword_targets else None

    # If the heavy audio stack is still cold-loading in the background, return a
    # fast note instead of blocking past Claude's 240s tool-call timeout.
    warming = audio_warming_message()
    if warming:
        return warming

    audio, np = _require_audio()

    matches = search_all_libraries(keyword, max_results, bpm_filter=bpm_filter)

    range_note = ""
    if effective_range is not None:
        low, high = int(effective_range.low), int(effective_range.high)
        range_note = (
            f" ({low}-{high} BPM)" if effective_range.is_range else f" ({low} BPM)"
        )

    if not matches:
        set_last_search_results([])
        return f"No samples found matching '{keyword}'{range_note} across all libraries"

    # Cache results so collect_search_results works after a BPM search too,
    # instead of silently reading a stale cache from an earlier keyword search.
    set_last_search_results(matches)

    result = f"Found {len(matches)} samples matching '{keyword}'{range_note}:\n"
    result += "Analyzing BPM (this may take a moment)...\n\n"

    for i, (path, library_name) in enumerate(matches, 1):
        filename = Path(path).name
        folder = Path(path).parent.name

        try:
            y, sr = audio.load_audio(path, duration=15)
            duration = len(y) / sr
            tempo, _ = audio.detect_tempo_with_hint(y, sr=sr, filename=filename)

            label = (
                _label_bpm(path, library_name, effective_range)
                if effective_range is not None
                else None
            )
            bpm_line = _format_bpm_line(tempo, duration, label)

            result += f"{i}. {filename}\n"
            result += f"   BPM: {bpm_line}\n"
            result += f"   Library: {library_name}\n"
            result += f"   Folder: {folder}\n"
            result += f"   Path: {path}\n\n"

        except Exception as e:
            result += f"{i}. {filename}\n"
            result += f"   BPM: Unable to detect ({e})\n"
            result += f"   Library: {library_name}\n"
            result += f"   Folder: {folder}\n"
            result += f"   Path: {path}\n\n"

    result += "Use collect_search_results with the result numbers above to copy/move files to a folder."

    return result
