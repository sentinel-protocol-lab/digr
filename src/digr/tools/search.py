"""Search tools: search_samples, search_samples_by_bpm."""

import time
from pathlib import Path
from typing import NamedTuple

from ._query import (
    BPM_MAX,
    BPM_MIN,
    SOURCE_DETECTED,
    SOURCE_LABEL_CONFIRMED,
    SOURCE_LABEL_HARMONIC,
    SOURCE_LABEL_ONLY,
    BpmTarget,
    file_tokens,
    parse_query,
)
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
# wording, matching detect_tempo_with_hint's own harmonic tolerance. Also
# used as the octave-tie-break tolerance for unlabelled detection (below).
BPM_LABEL_TOLERANCE = 0.08

# --- Detection-discovery of unlabelled files (Phase 2 #3b) ---
#
# Bounded two ways: a file-count budget (the deterministic, testable
# behaviour) and a wall-clock deadline (a guard against a cold external
# drive approaching Claude's 240s tool-call timeout -- decode cost measured
# locally at ~12ms/file is not a safe basis for the budget on its own, since
# real libraries live on external drives where I/O dominates by orders of
# magnitude). Provisional; calibrate against real drives (digr-STATUS.md).
DETECTION_BUDGET_FILES = 40
DETECTION_DEADLINE_SECONDS = 25.0

# How many combined labelled + unlabelled matches the walk gathers when a
# tempo range is in play. Most word-matching files carry no tempo label at
# all, so the per-library cap must not fill with them before enough LABELLED
# (certain) hits are counted. Deliberately far above max_results, which still
# bounds what's DISPLAYED and DECODED, not what's considered.
CANDIDATE_POOL_SIZE = 300


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


def _format_bpm_line(
    tempo: float,
    duration: float,
    label: float | None,
    source: str = SOURCE_DETECTED,
    detected: float | None = None,
) -> str:
    """Compose the BPM line for one match: one-shot honesty first, then
    labelled-primary/detected-confirmation when a range filter applied.

    ``source`` decides whether confirmation may be CLAIMED at all. When a
    filename carries an explicit BPM tag the engine can return that tag as the
    tempo, in which case comparing it against the label is comparing the label
    against itself -- it always agrees, and saying "confirmed by detection"
    asserts an independent check that never happened. Only a genuinely
    measured tempo can confirm anything.

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
    found = "" if detected is None else f" (found {detected:.1f})"
    if label is not None:
        if source == SOURCE_LABEL_CONFIRMED:
            # Detection agreed, so confirmation may be claimed -- but the
            # number shown as the confirmation must be the MEASURED one.
            # ``tempo`` is the label here, and comparing a label against
            # itself always agrees; printing it as its own confirmation is
            # the exact falsehood the rest of this function exists to avoid.
            if detected is None:
                return f"{label:.0f} (confirmed by detection)"
            return f"{label:.0f} (confirmed by detection: {detected:.1f})"
        if source == SOURCE_LABEL_HARMONIC:
            return (
                f"{label:.0f} (labelled) — detection found a harmonic of it"
                f"{found}, not an independent confirmation"
            )
        if source == SOURCE_LABEL_ONLY:
            return f"{label:.0f} (labelled) — detection could not confirm it{found}"
        if abs(tempo - label) <= label * BPM_LABEL_TOLERANCE:
            return f"{label:.0f} (confirmed by detection: {tempo:.1f})"
        return f"{label:.0f} (labelled) — detected {tempo:.1f}, trusting the label"
    if source == SOURCE_LABEL_CONFIRMED:
        # Same "no label to show it against" case as below, but detection did
        # agree here, so "not detected" would understate what happened.
        found_here = "" if detected is None else f": {detected:.1f}"
        return f"{tempo:.0f} — from the filename, confirmed by detection{found_here}"
    if source != SOURCE_DETECTED:
        # No range filter ran, so there is no label to present this against --
        # but the number still came off the filename, and the surrounding
        # output promises analysis. Say which it was.
        return f"{tempo:.0f} — read from the filename, not detected"
    return f"{tempo:.1f}"


def _bar_grid_fits(
    duration: float, target: BpmTarget, max_bars: int = 64
) -> list[tuple[int, float]]:
    """Tempos in ``target`` that make ``duration`` a whole number of 4/4 bars.

    Loops are almost always a whole number of bars, and duration is readable
    from the file HEADER with no decode -- so this orders the unlabelled
    detection queue before any expensive work happens (Phase 2 #3b). It is
    informative only when fewer than one whole bar-count fits inside the
    range (measured: ~14% of random durations admit a fit at an 8-BPM-wide
    range under 8s, vs ~96% over 20s, where the test says nothing) -- above
    that threshold it is skipped rather than pretending. NEVER a hard gate: a
    file with a fit is decoded first, but a loop with a reverb tail past the
    bar line still gets its turn if detection budget remains.
    """
    if duration <= 0:
        return []
    span = target.high - target.low
    if duration * span / 240.0 >= 1.0:
        return []
    fits: list[tuple[int, float]] = []
    for bars in range(1, max_bars + 1):
        tempo = 240.0 * bars / duration
        if tempo > target.high:
            break  # tempo rises monotonically with bar count
        if tempo >= target.low:
            fits.append((bars, round(tempo, 1)))
    return fits


def _admit_unlabelled(detected: float, target: BpmTarget) -> tuple[float, float] | None:
    """Accept a raw detection if it, its double, or its half lands in range.

    Half/double is a genuine disagreement between producers about how to
    describe ONE piece of music -- trap is labelled 140 or 70 by different
    packs, and the same goes for dubstep, footwork, and halftime sections in
    any genre -- so accepting it recovers ambiguity that exists in the music
    itself. 3/2 and 2/3 are deliberately NOT accepted: nobody calls a 124
    house loop "82" -- that ratio exists only in the autocorrelation, and
    accepting it would import the detector's own failure mode into the
    results dressed as musical meaning. Returns (admitted_tempo, factor), or
    None if nothing in {1x, 2x, 0.5x} lands in range.
    """
    for factor in (1.0, 2.0, 0.5):
        candidate = detected * factor
        if target.contains(candidate):
            return candidate, factor
    return None


def _format_detected_line(
    detected: float,
    admitted: float,
    factor: float,
    fit: tuple[int, float] | None,
) -> str:
    """Compose the candidate line for one unlabelled detection.

    Never asserts a tempo -- always hedged ("~", "detected", "no BPM in the
    name") -- because confidence cannot distinguish a real loop from a
    one-shot (a one-shot measured at 1.00 confidence, the maximum) and
    sustained tonal content can still reach here after the duration guard.
    Kept separate from the search loop for the same reason _format_bpm_line
    is: the trickiest logic in the change, unit-testable with plain numbers.
    """
    if factor == 2.0:
        octave_note = " at double time"
    elif factor == 0.5:
        octave_note = " at half time"
    else:
        octave_note = ""
    line = f"~{admitted:.0f} (detected {detected:.1f}{octave_note}"
    if fit is not None:
        bars, _ = fit
        line += f"; length fits {bars} bar{'s' if bars != 1 else ''} at {admitted:.0f}"
    line += ") — no BPM in the name"
    return line


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


def _decode_and_detect(audio, path: str, filename: str):
    """Load and detect once -- returns (tempo, duration, source, detected).

    Shared by the labelled-confirmation pass and the unlabelled-detection pass
    so both go through identical decode logic; raises on decode failure, which
    callers handle.

    ``source`` and ``detected`` are carried out because ``tempo`` is not
    always a measurement: when the filename holds an explicit BPM tag the
    engine may return that tag verbatim. A caller that presents such a value
    as detected would be comparing the label against itself.
    """
    y, sr = audio.load_audio(path, duration=15)
    duration = len(y) / sr
    result = audio.detect_tempo_with_hint(y, sr=sr, filename=filename)
    return result.tempo, duration, result.source, result.detected


class _ResultRow(NamedTuple):
    """One displayed match, either a confirmed label or a detected candidate."""

    path: str
    library_name: str
    filename: str
    folder: str
    bpm_line: str


def _render_row(index: int, row: _ResultRow) -> str:
    return (
        f"{index}. {row.filename}\n"
        f"   BPM: {row.bpm_line}\n"
        f"   Library: {row.library_name}\n"
        f"   Folder: {row.folder}\n"
        f"   Path: {row.path}\n\n"
    )


def _confirm_labelled(
    audio, path: str, library_name: str, label: float
) -> _ResultRow:
    """Stage 2 (#3a): detect a labelled-in-range match only to confirm it."""
    filename = Path(path).name
    folder = Path(path).parent.name
    try:
        tempo, duration, source, detected = _decode_and_detect(audio, path, filename)
        bpm_line = _format_bpm_line(tempo, duration, label, source, detected)
    except Exception as e:
        bpm_line = f"Unable to detect ({e})"
    return _ResultRow(path, library_name, filename, folder, bpm_line)


def _discover_unlabelled(
    audio, candidates: list[tuple[str, str]], target: BpmTarget
) -> tuple[list[_ResultRow], int]:
    """Stages 4-6 (#3b): order by bar-grid fit (header only, no decode), then
    decode within budget, admitting an octave-aware in-range reading.

    Returns (admitted rows, considered_count). ``considered_count`` is how
    many of ``candidates`` were actually looked at -- decoded OR rejected via
    the duration guard or an unreadable header -- before the budget or
    deadline stopped the pass. The caller compares it against
    ``len(candidates)`` to report truncation honestly: a file rejected by the
    (near-free) duration guard was still "checked", so it must not be
    reported as lost to the (expensive) decode budget.
    """
    staged: list[tuple[str, str, float, list[tuple[int, float]]]] = []
    for path, library_name in candidates:
        try:
            duration = audio.get_native_duration(path)
        except Exception:
            # Unreadable header -- folds into the duration guard below rather
            # than a separate error path, so it is honestly "considered",
            # not silently dropped from the count.
            duration = 0.0
        fits = _bar_grid_fits(duration, target) if duration > 0 else []
        staged.append((path, library_name, duration, fits))
    # Bar-grid-fit-first; a stable sort keeps each group's existing order
    # (`candidates` arrives already ranked by the search engine's own score).
    staged.sort(key=lambda c: 0 if c[3] else 1)

    rows: list[_ResultRow] = []
    decoded_count = 0
    considered_count = 0
    deadline = time.monotonic() + DETECTION_DEADLINE_SECONDS
    for path, library_name, duration, fits in staged:
        if decoded_count >= DETECTION_BUDGET_FILES or time.monotonic() >= deadline:
            break
        considered_count += 1
        if duration < ONE_SHOT_MAX_DURATION:
            # Rejected before spending any decode budget -- confidence cannot
            # do this job (a one-shot measures as the MOST confident thing in
            # the library), so duration is the only defence that works.
            continue
        filename = Path(path).name
        try:
            tempo, _, _, _ = _decode_and_detect(audio, path, filename)
        except Exception:
            decoded_count += 1
            continue
        decoded_count += 1
        if tempo == 0.0:
            continue
        admission = _admit_unlabelled(tempo, target)
        if admission is None:
            continue
        admitted, factor = admission
        fit = min(
            (f for f in fits if abs(f[1] - admitted) <= admitted * BPM_LABEL_TOLERANCE),
            key=lambda f: abs(f[1] - admitted),
            default=None,
        )
        if fit is not None:
            admitted = fit[1]
        line = _format_detected_line(tempo, admitted, factor, fit)
        rows.append(
            _ResultRow(path, library_name, filename, Path(path).parent.name, line)
        )
    return rows, considered_count


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


async def _search_by_bpm_no_range(keyword: str, max_results: int, audio) -> str:
    """No tempo range in play -- unchanged since before Phase 2 #3 existed."""
    matches = search_all_libraries(keyword, max_results)

    if not matches:
        set_last_search_results([])
        return f"No samples found matching '{keyword}' across all libraries"

    set_last_search_results(matches)

    result = f"Found {len(matches)} samples matching '{keyword}':\n"
    result += "Analyzing BPM (this may take a moment)...\n\n"

    for i, (path, library_name) in enumerate(matches, 1):
        filename = Path(path).name
        folder = Path(path).parent.name

        try:
            tempo, duration, source, _ = _decode_and_detect(audio, path, filename)
            bpm_line = _format_bpm_line(tempo, duration, None, source)

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


async def _search_by_bpm_ranged(
    keyword: str,
    target: BpmTarget,
    range_note: str,
    max_results: int,
    audio,
) -> str:
    """A tempo range is in play. Two families of match: files whose own
    filename/folder label puts them in range (free, trustworthy -- #3a), and
    files with NO tempo label at all, run through detection and offered only
    if an octave-aware reading lands in range (Phase 2 #3b -- the real Pro
    differentiator, since free search can only ever find a labelled range).
    """
    pool = search_all_libraries(
        keyword, CANDIDATE_POOL_SIZE, bpm_filter=target, allow_unlabelled=True
    )
    if not pool:
        set_last_search_results([])
        return f"No samples found matching '{keyword}'{range_note} across all libraries"

    labelled_pool: list[tuple[str, str, float]] = []
    unlabelled_pool: list[tuple[str, str]] = []
    for path, library_name in pool:
        label = _label_bpm(path, library_name, target)
        if label is not None:
            labelled_pool.append((path, library_name, label))
        else:
            unlabelled_pool.append((path, library_name))

    labelled_rows = [
        _confirm_labelled(audio, path, library_name, label)
        for path, library_name, label in labelled_pool[:max_results]
    ]

    total_candidates = len(unlabelled_pool)
    unlabelled_rows, considered_count = _discover_unlabelled(
        audio, unlabelled_pool, target
    )

    # Both sections in DISPLAYED order -- collect_search_results indexes into
    # this cache, so a mismatch here would copy the wrong file.
    set_last_search_results(
        [(r.path, r.library_name) for r in labelled_rows + unlabelled_rows]
    )

    if not labelled_rows and not unlabelled_rows:
        if total_candidates > 0:
            return (
                f"No confirmed matches for '{keyword}'{range_note}. Checked "
                f"{considered_count} of {total_candidates} unlabelled candidates, "
                f"none confirmed a tempo in range."
            )
        return f"No samples found matching '{keyword}'{range_note} across all libraries"

    result = (
        f"Found {len(labelled_rows) + len(unlabelled_rows)} samples "
        f"matching '{keyword}'{range_note}:\n"
        "Analyzing BPM (this may take a moment)...\n\n"
    )

    # Only split into headed sections once the unlabelled section actually
    # has something to show -- the common labelled-only case keeps the exact
    # #3a layout.
    show_headers = bool(labelled_rows) and bool(unlabelled_rows)
    i = 0
    if labelled_rows:
        if show_headers:
            result += f"Labelled{range_note} ({len(labelled_rows)} files)\n"
        for row in labelled_rows:
            i += 1
            result += _render_row(i, row)
    if unlabelled_rows:
        if show_headers:
            result += (
                f"Detected, not labelled — worth auditioning "
                f"({len(unlabelled_rows)} files)\n"
            )
        for row in unlabelled_rows:
            i += 1
            result += _render_row(i, row)

    if total_candidates > 0:
        truncated = considered_count < total_candidates
        result += (
            f"Checked {considered_count} of {total_candidates} unlabelled "
            f"candidates{' (detection budget reached)' if truncated else ''}.\n\n"
        )

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
    and detects each one only to confirm it. It ALSO runs detection on
    matching files that carry NO tempo label at all, offering any whose
    detected tempo (allowing an exact half/double reading) lands in range as
    a candidate worth auditioning -- clearly separated from the confirmed,
    labelled matches and never asserted as certain. That's the real Pro
    value: free search can only ever find a labelled range.

    Without a range, every match is detected and shown as before. Recommended
    5-20 results for speed. Results are balanced across all configured
    libraries. Pro feature.
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

    if effective_range is None:
        return await _search_by_bpm_no_range(keyword, max_results, audio)

    low, high = int(effective_range.low), int(effective_range.high)
    range_note = (
        f" ({low}-{high} BPM)" if effective_range.is_range else f" ({low} BPM)"
    )
    return await _search_by_bpm_ranged(
        keyword, effective_range, range_note, max_results, audio
    )
