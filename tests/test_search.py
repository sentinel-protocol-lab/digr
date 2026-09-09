"""Tests for search tools."""

from pathlib import Path

import pytest

from digr.tools._audio_analysis import TempoResult
from digr.tools._query import (
    SOURCE_DETECTED,
    SOURCE_LABEL_CONFIRMED,
    SOURCE_LABEL_HARMONIC,
    SOURCE_LABEL_ONLY,
    BpmTarget,
)
from digr.tools.search import (
    DETECTION_BUDGET_FILES,
    ONE_SHOT_MAX_DURATION,
    _admit_unlabelled,
    _bar_grid_fits,
    _discover_unlabelled,
    _format_bpm_line,
    _format_detected_line,
    search_samples,
    search_samples_by_bpm,
)
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


# ---------------------------------------------------------------------------
# search_samples_by_bpm -- tempo-range filtering (Phase 2 #3a)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bpm_range_explicit_params_filter(bpm_range_library, pro_license):
    """min_bpm/max_bpm must reach the shakers labelled only by a bare number
    ("_172_", no literal "bpm" word) and exclude the one outside the range."""
    result = await search_samples_by_bpm("shaker", min_bpm=170, max_bpm=178)
    assert "TSP_NOISIA_172_drum_loop_shakerloopedit.wav" in result
    assert "TSP_NOISIA_174_shaker_hats.wav" in result
    assert "TSP_NOISIA_200_shaker.wav" not in result


@pytest.mark.asyncio
async def test_bpm_range_keyword_filter_matches_explicit_params(
    bpm_range_library, pro_license
):
    """A range typed straight into the keyword must filter identically to
    passing the same range as min_bpm/max_bpm."""
    result = await search_samples_by_bpm("shaker 170-178")
    assert "TSP_NOISIA_172_drum_loop_shakerloopedit.wav" in result
    assert "TSP_NOISIA_200_shaker.wav" not in result


@pytest.mark.asyncio
async def test_bpm_range_min_only(bpm_range_library, pro_license):
    result = await search_samples_by_bpm("shaker", min_bpm=180)
    assert "TSP_NOISIA_200_shaker.wav" in result
    assert "TSP_NOISIA_172_drum_loop_shakerloopedit.wav" not in result


@pytest.mark.asyncio
async def test_bpm_range_max_only(bpm_range_library, pro_license):
    result = await search_samples_by_bpm("shaker", max_bpm=175)
    assert "TSP_NOISIA_172_drum_loop_shakerloopedit.wav" in result
    assert "TSP_NOISIA_174_shaker_hats.wav" in result
    assert "TSP_NOISIA_200_shaker.wav" not in result


@pytest.mark.asyncio
async def test_bpm_range_shown_in_header(bpm_range_library, pro_license):
    result = await search_samples_by_bpm("shaker", min_bpm=170, max_bpm=178)
    assert "170-178 BPM" in result


@pytest.mark.asyncio
async def test_bpm_no_range_header_unchanged(mock_libraries, pro_license):
    """Without any range (params or keyword), the header carries no range
    note -- existing callers see no behaviour change."""
    result = await search_samples_by_bpm("kick", max_results=10)
    first_line = result.split("\n")[0]
    assert "BPM)" not in first_line


@pytest.mark.asyncio
async def test_bpm_range_no_matches_names_the_range(bpm_range_library, pro_license):
    result = await search_samples_by_bpm("shaker", min_bpm=250, max_bpm=260)
    assert "170-178" not in result  # sanity: not just echoing an old range
    assert "250-260 BPM" in result
    assert "No samples found" in result


@pytest.mark.asyncio
async def test_bpm_range_one_shot_real_audio(tmp_path, pro_license):
    """End-to-end with REAL decoded audio: a short in-range-labelled sample
    must filter in, decode, and be reported honestly as a one-shot rather
    than given a junk tempo. Closes the wiring gap the fake-bytes tests can't
    reach (they fail to decode and hit the exception branch instead)."""
    import numpy as np
    import soundfile as sf

    from digr.tools._shared import set_libraries

    lib = tmp_path / "OneShots"
    lib.mkdir()
    # ~1s of quiet noise, named with a bare in-range number and no "bpm" word.
    sr = 22050
    audio = (np.random.default_rng(0).standard_normal(sr) * 0.01).astype("float32")
    sf.write(str(lib / "shaker_172.wav"), audio, sr)

    set_libraries({"One Shots": tmp_path})

    result = await search_samples_by_bpm("shaker", min_bpm=170, max_bpm=178)

    assert "shaker_172.wav" in result
    assert "labelled 172 — one-shot, no tempo detected" in result


class TestFormatBpmLine:
    """The one-shot-honesty / labelled-primary decision, in isolation --
    no audio decoding needed since this is pure display logic."""

    def test_one_shot_no_label(self):
        assert _format_bpm_line(tempo=287.0, duration=0.8, label=None) == (
            "one-shot — no tempo"
        )

    def test_one_shot_with_label(self):
        assert _format_bpm_line(tempo=287.0, duration=0.8, label=172.0) == (
            "labelled 172 — one-shot, no tempo detected"
        )

    def test_silence_treated_as_one_shot_even_if_long(self):
        """tempo == 0.0 means detect_tempo found no rhythm at all, regardless
        of how long the file is."""
        assert _format_bpm_line(tempo=0.0, duration=30.0, label=None) == (
            "one-shot — no tempo"
        )

    def test_label_confirmed_by_close_detection(self):
        assert _format_bpm_line(tempo=172.3, duration=8.0, label=172.0) == (
            "172 (confirmed by detection: 172.3)"
        )

    def test_label_trusted_over_disagreeing_detection(self):
        """Producers don't mislabel BPM -- a detection that lands far from
        the label is flagged, but the label still wins."""
        assert _format_bpm_line(tempo=156.6, duration=8.0, label=172.0) == (
            "172 (labelled) — detected 156.6, trusting the label"
        )

    def test_no_label_falls_back_to_raw_detection(self):
        """No-range mode: behaves exactly as before this feature existed."""
        assert _format_bpm_line(tempo=117.5, duration=8.0, label=None) == "117.5"

    def test_label_sourced_tempo_never_claims_confirmation(self):
        """The tempo IS the label here -- the engine read it off the filename
        rather than measuring it. Comparing it against the label would always
        agree, so claiming confirmation asserts a check that never ran."""
        line = _format_bpm_line(
            tempo=172.0,
            duration=8.0,
            label=172.0,
            source=SOURCE_LABEL_ONLY,
            detected=86.1,
        )
        assert "confirmed by detection" not in line
        assert line == "172 (labelled) — detection could not confirm it (found 86.1)"

    def test_harmonic_label_reports_partial_corroboration(self):
        """Detection found the right pulse and the wrong frame. That is more
        than nothing and less than agreement, so it says which."""
        line = _format_bpm_line(
            tempo=172.0,
            duration=8.0,
            label=172.0,
            source=SOURCE_LABEL_HARMONIC,
            detected=86.1,
        )
        assert "confirmed by detection" not in line
        assert "harmonic" in line
        assert "86.1" in line

    def test_unlabelled_but_filename_sourced_tempo_says_so(self):
        """No range filter ran, so there is no label to show it against -- but
        the number still came off the name and must not read as analysis."""
        line = _format_bpm_line(
            tempo=128.0, duration=8.0, label=None, source=SOURCE_LABEL_ONLY
        )
        assert line == "128 — read from the filename, not detected"

    def test_a_confirmed_label_shows_the_measurement_not_itself(self):
        """Once the engine returns the LABEL as the tempo, ``tempo == label``
        for this branch, so the generic tolerance check below it is trivially
        true and would print the label as its own confirmation -- reviving the
        exact bug this wording was written to kill. The number shown as
        evidence has to be the measured one."""
        line = _format_bpm_line(
            tempo=145.0,
            duration=8.0,
            label=145.0,
            source=SOURCE_LABEL_CONFIRMED,
            detected=144.2,
        )
        assert line == "145 (confirmed by detection: 144.2)"
        assert "145.0" not in line

    def test_a_genuine_detection_still_confirms_a_label(self):
        """The honest case is unchanged: this is what the wording is FOR."""
        assert _format_bpm_line(
            tempo=172.3,
            duration=8.0,
            label=172.0,
            source=SOURCE_DETECTED,
            detected=172.3,
        ) == "172 (confirmed by detection: 172.3)"


# ---------------------------------------------------------------------------
# Detection-discovery of unlabelled files (Phase 2 #3b)
# ---------------------------------------------------------------------------


class TestBarGridFits:
    """Duration-only, pre-decode ordering: a loop is almost always a whole
    number of 4/4 bars, and duration is readable from the file header."""

    def test_exact_bar_length_admits_true_tempo(self):
        duration = 4 * 4 * 60.0 / 174.0  # 4 bars at 174 BPM
        fits = _bar_grid_fits(duration, BpmTarget(170.0, 178.0))
        assert (4, 174.0) in fits

    def test_wrong_tempo_length_is_not_admitted(self):
        duration = 2 * 4 * 60.0 / 124.0  # 2 bars at 124 BPM
        assert _bar_grid_fits(duration, BpmTarget(170.0, 178.0)) == []

    def test_power_rule_skips_long_files(self):
        """Above roughly one whole bar-count fitting inside the range, the
        test is uninformative and must say nothing rather than pretend."""
        assert _bar_grid_fits(30.0, BpmTarget(170.0, 178.0)) == []

    def test_power_rule_skips_wide_ranges(self):
        assert _bar_grid_fits(5.0, BpmTarget(120.0, 180.0)) == []


class TestAdmitUnlabelled:
    """Octave-aware admission: accept ambiguities that exist in the music
    (half/double), reject artefacts that exist only in the algorithm."""

    def test_direct_match(self):
        assert _admit_unlabelled(172.0, BpmTarget(170.0, 178.0)) == (172.0, 1.0)

    def test_double_time_rescues_a_halved_detection(self):
        """The measured collapse: an unlabelled 172 loop often detects at
        86.1 (exact half) -- must be admitted as 172 at double time."""
        admitted, factor = _admit_unlabelled(86.1, BpmTarget(170.0, 178.0))
        assert admitted == pytest.approx(172.2)
        assert factor == 2.0

    def test_half_time_admits_an_overdetected_tempo(self):
        admitted, factor = _admit_unlabelled(344.0, BpmTarget(170.0, 178.0))
        assert admitted == pytest.approx(172.0)
        assert factor == 0.5

    def test_three_halves_ratio_is_not_admitted(self):
        """3/2 is the detector's own failure mode, not a musical ambiguity
        (decision B1) -- 82 * 1.5 = 123 falls inside the range but must NOT
        be accepted."""
        assert _admit_unlabelled(82.0, BpmTarget(120.0, 128.0)) is None

    def test_out_of_range_at_every_octave_is_rejected(self):
        assert _admit_unlabelled(100.0, BpmTarget(170.0, 178.0)) is None


class TestFormatDetectedLine:
    """The unlabelled-candidate wording, in isolation -- never asserts a
    bare tempo, since confidence alone cannot separate a real loop from a
    one-shot (a one-shot measured 1.00, the maximum)."""

    def test_direct_match_has_no_octave_note(self):
        line = _format_detected_line(detected=172.3, admitted=172.3, factor=1.0, fit=None)
        assert line == "~172 (detected 172.3) — no BPM in the name"

    def test_double_time_note(self):
        line = _format_detected_line(detected=86.1, admitted=172.2, factor=2.0, fit=None)
        assert line == "~172 (detected 86.1 at double time) — no BPM in the name"

    def test_half_time_note(self):
        line = _format_detected_line(detected=344.0, admitted=172.0, factor=0.5, fit=None)
        assert "at half time" in line

    def test_bar_grid_corroboration_is_mentioned(self):
        line = _format_detected_line(
            detected=86.1, admitted=172.0, factor=2.0, fit=(4, 172.0)
        )
        assert "length fits 4 bars at 172" in line

    def test_never_asserts_a_bare_tempo(self):
        line = _format_detected_line(detected=172.0, admitted=172.0, factor=1.0, fit=None)
        assert line.startswith("~")
        assert "no BPM in the name" in line


class _FakeAudio:
    """Deterministic stand-in for the audio module -- unit-tests the
    duration-guard/budget/ordering LOGIC in _discover_unlabelled without
    decoding real files."""

    def __init__(self, durations: dict, tempos: dict):
        self._durations = durations
        self._tempos = tempos

    def get_native_duration(self, path):
        return self._durations[path]

    def load_audio(self, path, duration=15):
        return [0.0], 22050

    def detect_tempo_with_hint(self, y, sr=22050, filename=""):
        # Unlabelled candidates carry no filename BPM by definition, so the
        # engine always reports a genuine detection for them.
        tempo = self._tempos[filename]
        return TempoResult(tempo, 1.0, SOURCE_DETECTED, tempo)


class TestDiscoverUnlabelled:
    """Stages 4-6 end-to-end at the pure-function level."""

    def test_one_shot_is_never_admitted_regardless_of_detected_tempo(self):
        """Regression for the confidence finding: a one-shot must be
        rejected on duration ALONE, before admission logic ever runs --
        even when its "detected" tempo would otherwise land in range."""
        candidates = [("/lib/shaker_oneshot.wav", "Lib")]
        audio = _FakeAudio(
            durations={"/lib/shaker_oneshot.wav": ONE_SHOT_MAX_DURATION - 0.1},
            tempos={"shaker_oneshot.wav": 258.4},  # would pass admission if reached
        )
        rows, considered = _discover_unlabelled(audio, candidates, BpmTarget(170.0, 178.0))
        assert rows == []
        assert considered == 1  # rejected, but still honestly "considered"

    def test_budget_caps_the_number_of_decodes(self):
        """More unlabelled candidates than the budget: exactly
        DETECTION_BUDGET_FILES are considered, and the remainder is
        reportable as truncated rather than silently dropped."""
        n = DETECTION_BUDGET_FILES + 10
        candidates = [(f"/lib/loop_{i}.wav", "Lib") for i in range(n)]
        audio = _FakeAudio(
            durations={p: 10.0 for p, _ in candidates},
            tempos={f"loop_{i}.wav": 172.0 for i in range(n)},
        )
        rows, considered = _discover_unlabelled(audio, candidates, BpmTarget(170.0, 178.0))
        assert considered == DETECTION_BUDGET_FILES
        assert len(rows) == DETECTION_BUDGET_FILES

    def test_bar_grid_fit_is_decoded_before_a_non_fitting_candidate(self):
        """Stage 4: ordering, not gating -- the fitting candidate is decoded
        first, but a non-fitting one still gets its turn within budget."""
        no_fit_duration = 30.0  # power-rule-uninformative length either way
        fit_duration = 4 * 4 * 60.0 / 172.0  # exact 4 bars at 172
        candidates = [("/lib/no_fit.wav", "Lib"), ("/lib/has_fit.wav", "Lib")]
        audio = _FakeAudio(
            durations={"/lib/no_fit.wav": no_fit_duration, "/lib/has_fit.wav": fit_duration},
            tempos={"no_fit.wav": 172.0, "has_fit.wav": 86.1},
        )
        rows, considered = _discover_unlabelled(audio, candidates, BpmTarget(170.0, 178.0))
        assert considered == 2
        assert rows[0].filename == "has_fit.wav"  # the bar-grid fit went first
        assert "length fits 4 bars at 172" in rows[0].bpm_line


class TestOptInSafety:
    """allow_unlabelled must never reach the organise tools by default --
    collect_samples/sort_samples share this engine but copy/move files, and
    a silent tempo filter there would touch files nobody asked for."""

    def test_search_all_libraries_defaults_to_no_unlabelled_matching(self):
        import inspect

        from digr.tools._shared import search_all_libraries

        sig = inspect.signature(search_all_libraries)
        assert sig.parameters["allow_unlabelled"].default is False

    def test_organize_never_passes_bpm_filter_or_allow_unlabelled(self):
        import inspect

        from digr.tools import organize

        source = inspect.getsource(organize)
        assert "bpm_filter" not in source
        assert "allow_unlabelled" not in source


def _synth_break_loop(bpm: float, bars: int, sr: int = 22050, seed: int = 0):
    """A deterministic (seeded), REAL, decodable break-style loop: kick/snare
    /ghost-hat pattern with enough syncopation for the detector to lock onto
    the true tempo rather than a further sub-harmonic, trimmed to an EXACT
    whole number of 4/4 bars. Mirrors the design-pass benchmark that measured
    the double-time collapse this feature corrects for."""
    import numpy as np

    rng = np.random.default_rng(seed)
    spb = 60.0 / bpm
    step = spb / 4
    n = int(spb * 4 * bars * sr) + sr
    y = np.zeros(n, dtype=np.float32)

    def hit(t, freq, dur, amp, noise=0.0):
        i = int(t * sr)
        length = int(dur * sr)
        if i + length > n:
            return
        env = np.exp(-np.linspace(0, 12, length))
        tone = np.sin(2 * np.pi * freq * np.arange(length) / sr)
        sig = tone * (1 - noise) + rng.standard_normal(length) * noise
        y[i : i + length] += (sig * env * amp).astype(np.float32)

    kick, snare = {0, 10}, {4, 13}
    for s in range(16 * bars):
        t = s * step
        pos = s % 16
        if pos in kick:
            hit(t, 55, 0.22, 0.95)
        if pos in snare:
            hit(t, 210, 0.18, 0.8, noise=0.75)
        if pos % 2 == 1:
            hit(t, 9000, 0.03, 0.25, noise=0.95)

    return y[: int(bars * 4 * spb * sr)]  # trim to an exact whole-bar length


@pytest.mark.asyncio
async def test_bpm_range_unlabelled_loop_discovered_via_double_time(tmp_path, pro_license):
    """End-to-end with REAL decoded audio: a 4-bar 172 loop with NO number in
    its filename must be found by detection-discovery, admitted via the
    double-time octave reading (the measured collapse -- an unlabelled fast
    loop detects at half its true tempo, e.g. 86.1 for a real 172), and
    corroborated by its bar-exact length. Closes the wiring gap the
    fake-bytes tests can't reach (they fail to decode and hit the exception
    branch instead)."""
    import soundfile as sf

    from digr.tools._shared import set_libraries

    y = _synth_break_loop(bpm=172.0, bars=4)

    lib = tmp_path / "Loops"
    lib.mkdir()
    sf.write(str(lib / "amen_chop_alpha.wav"), y, 22050)
    set_libraries({"Loops": tmp_path})

    result = await search_samples_by_bpm("", min_bpm=170, max_bpm=178)

    assert "amen_chop_alpha.wav" in result
    assert "at double time" in result
    assert "no BPM in the name" in result
    assert "length fits 4 bars at 172" in result


@pytest.mark.asyncio
async def test_bpm_range_shows_both_sections_and_caches_in_displayed_order(
    bpm_range_library, pro_license
):
    """When a labelled hit and an admitted unlabelled candidate both exist,
    the response splits into headed 'Labelled' / 'Detected, not labelled'
    sections with CONTINUOUS numbering, and the results cache must list
    every match in that exact displayed order -- collect_search_results
    indexes into it, so a mismatch across the section break would copy the
    wrong file."""
    import soundfile as sf

    y = _synth_break_loop(bpm=172.0, bars=4, seed=1)
    # Same library as the fixture's labelled shakers, no number in the name.
    sf.write(str(bpm_range_library / "amen_chop_beta.wav"), y, 22050)

    result = await search_samples_by_bpm("", min_bpm=170, max_bpm=178)

    assert "Labelled (170-178 BPM) (2 files)" in result
    assert "Detected, not labelled — worth auditioning (1 files)" in result
    # Both labelled hits (same score tier) precede the unlabelled candidate,
    # numbered continuously across the section break; their relative order
    # is the engine's existing tie-break (shorter path first) -- unrelated
    # to #3b and not what this test is pinning down.
    assert result.index("1. TSP_NOISIA_") < result.index("2. TSP_NOISIA_")
    assert result.index("2. TSP_NOISIA_") < result.index("3. amen_chop_beta.wav")

    cached = get_last_search_results()
    cached_names = [Path(p).name for p, _ in cached]
    assert cached_names[:2] == [
        "TSP_NOISIA_174_shaker_hats.wav",
        "TSP_NOISIA_172_drum_loop_shakerloopedit.wav",
    ]
    assert cached_names[2] == "amen_chop_beta.wav"


@pytest.mark.asyncio
async def test_mislabelled_file_is_never_reported_as_confirmed(tmp_path, pro_license):
    """End-to-end with REAL decoded audio, for the circular-confirmation bug.

    A genuine 172 loop carrying an explicit and WRONG "100bpm" tag. Because the
    tag is explicit, the engine returns 100 as the tempo -- so comparing it
    against the label 100 always agrees, and the display used to announce
    "100 (confirmed by detection: 100.0)". Nothing confirmed anything: the
    label was compared against itself.

    Only real audio reaches this. The fake-bytes tests fail to decode and take
    the exception branch, which is exactly why the bug shipped.
    """
    import soundfile as sf

    from digr.tools._shared import set_libraries

    y = _synth_break_loop(bpm=172.0, bars=4)

    lib = tmp_path / "Loops"
    lib.mkdir()
    sf.write(str(lib / "amen_chop_100bpm.wav"), y, 22050)
    set_libraries({"Loops": tmp_path})

    result = await search_samples_by_bpm("", min_bpm=95, max_bpm=105)

    assert "amen_chop_100bpm.wav" in result
    assert "confirmed by detection" not in result, (
        "a tempo read off the filename was presented as an independent "
        f"detection:\n{result}"
    )
    assert "could not confirm" in result


# ---------------------------------------------------------------------------
# Ranking the whole library, not the first cap-worth of it
# ---------------------------------------------------------------------------
#
# The gap that let the truncation defect ship: every search test above uses a
# fixture SMALLER than the per-library cap, so the cap never fires and ranking
# always looks perfect. Everything below deliberately overflows it.


@pytest.fixture
def oversized_library(tmp_path_factory):
    """More matching files than the cap, with the best ones NOT first.

    Fifty decoys carry "kick" only in the FOLDER name; five winners carry it
    in the FILENAME, which scores higher and also earns the
    all-terms-in-filename bonus.

    All fifty-five sit in ONE directory ON PURPOSE. Split across two folders
    the test is at the mercy of which folder the filesystem hands over first
    -- and it passed against the unfixed code for exactly that reason, since
    the winners' folder happened to come first and filled the cap with them.
    In a single directory, the old "keep the first five" rule can only return
    the five winners if the filesystem volunteers all five ahead of fifty
    others, which is not a coincidence worth planning around.
    """
    from digr.tools._shared import set_libraries

    lib = tmp_path_factory.mktemp("oversized_library")
    pack = lib / "Kick Pack"
    pack.mkdir()

    for i in range(50):
        (pack / f"pack_{i:02d}.wav").write_bytes(b"RIFF" + b"\x00" * 40)

    expected = set()
    for i in range(5):
        path = pack / f"kick_{i:02d}.wav"
        path.write_bytes(b"RIFF" + b"\x00" * 40)
        expected.add(str(path))

    set_libraries({"Oversized Library": lib})
    return expected


def test_cap_keeps_the_best_matches_not_the_first_ones(oversized_library):
    """The regression test for the whole defect.

    Fails before the rewrite: the walk stopped as soon as the cap was full, so
    the answer was five arbitrary files in traversal order and the five best
    were never even read.
    """
    from digr.tools._shared import search_libraries

    outcome = search_libraries("kick", max_results=100, per_library_cap=5)

    assert {path for path, _ in outcome.matches} == oversized_library


def test_midi_is_reachable_when_audio_alone_exceeds_the_cap(tmp_path):
    """Symptom B: MIDI starvation, fixed structurally rather than by tuning.

    The old walk globbed six audio extensions before ``*.mid``, so on a
    library where the audio matches alone fill the cap the walk broke out
    before MIDI was ever globbed -- which is why "midi" returned ZERO MIDI
    files on a real library that is half MIDI. One traversal leaves no
    extension with that privilege.
    """
    from digr.tools._shared import search_libraries, set_libraries

    loops = tmp_path / "Loops"
    loops.mkdir()
    for i in range(60):
        (loops / f"loop_number_{i:04d}.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    midi = loops / "loop.mid"
    midi.write_bytes(b"MThd" + b"\x00" * 40)
    set_libraries({"Loops": tmp_path})

    outcome = search_libraries("loop", max_results=100, per_library_cap=10)
    paths = [path for path, _ in outcome.matches]

    assert len(paths) == 10
    assert str(midi) in paths


def test_extensions_match_case_insensitively(tmp_path):
    """``rglob("*.wav")`` was case-SENSITIVE, so an upper-cased extension was

    invisible to search -- 83 files on one real 351k-file library. Widening is
    the safe direction: it can only add files Digr already knows how to read.
    """
    from digr.tools._shared import search_libraries, set_libraries

    loops = tmp_path / "Loops"
    loops.mkdir()
    shouty = loops / "KICK_HARD.WAV"
    shouty.write_bytes(b"RIFF" + b"\x00" * 40)
    set_libraries({"Loops": tmp_path})

    outcome = search_libraries("kick", max_results=10)

    assert [path for path, _ in outcome.matches] == [str(shouty)]


def test_one_unreadable_folder_does_not_cost_the_whole_library(tmp_path):
    """The old ``except (PermissionError, OSError): continue`` wrapped a
    per-extension loop. With one traversal an escaping error would abandon the
    entire library, so an unreadable subtree has to stay local to itself.
    """
    import os
    import stat

    from digr.tools._shared import search_libraries, set_libraries

    readable = tmp_path / "Open"
    readable.mkdir()
    kept = readable / "kick_open.wav"
    kept.write_bytes(b"RIFF" + b"\x00" * 40)

    locked = tmp_path / "Locked"
    locked.mkdir()
    (locked / "kick_locked.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    os.chmod(locked, 0o000)
    set_libraries({"Loops": tmp_path})

    try:
        outcome = search_libraries("kick", max_results=10)
    finally:
        os.chmod(locked, stat.S_IRWXU)

    assert str(kept) in [path for path, _ in outcome.matches]


@pytest.mark.asyncio
async def test_deadline_returns_ranked_results_and_says_it_was_cut_short(
    tmp_path, monkeypatch
):
    """Degrading honestly beats degrading silently.

    The deadline is checked AFTER each file rather than before it, so a
    ceiling that has already passed still yields what was gathered instead of
    an empty answer that reads like "nothing matched".
    """
    from digr.tools import _shared
    from digr.tools._shared import set_libraries
    from digr.tools.search import TRUNCATION_NOTE

    loops = tmp_path / "Loops"
    loops.mkdir()
    for i in range(20):
        (loops / f"loop_{i:02d}.wav").write_bytes(b"RIFF" + b"\x00" * 40)
    set_libraries({"Loops": tmp_path})

    monkeypatch.setattr(_shared, "SEARCH_DEADLINE_SECONDS", 0.0)
    result = await search_samples("loop")

    assert "loop_" in result
    assert TRUNCATION_NOTE in result


# ---------------------------------------------------------------------------
# Prefilter equivalence -- the load-bearing one
# ---------------------------------------------------------------------------


@pytest.fixture
def prefilter_library(tmp_path_factory):
    """Named to exercise every way the prefilter could wrongly say "no"."""
    from digr.tools._shared import set_libraries

    lib = tmp_path_factory.mktemp("prefilter_library")
    files = [
        # The compound join: "B-D" tokenises to b + d, which join to "bd",
        # which the alias map maps to "kick". A prefilter tested on the RAW
        # path never sees "bd" -- a hyphen sits between the letters.
        "Niko Kotoulas/Niko_Kotoulas_MelodicTrap_Bassline_1_C#m-A-B-D.mid",
        "Niko Kotoulas/Chords_G#m-E-B-D#m7.mid",
        # Kicks reached without any join, one of them via the BD abbreviation.
        "Drums/Kicks/kick_808.wav",
        "MusicRadar/E808_Loop_BD_01.wav",
        # -ies stemming in the direction that breaks a naive probe: the query
        # "melody" stems to "melody", which is NOT inside "melodies".
        "Melodic/melodies_bright.wav",
        "Melodic/melody_lead.wav",
        # Plurals, multi-term queries, and the pack folder "loop" must miss.
        "Loopmasters/Drum Hits/TSP_NOISIA_174_dnb_break.wav",
        "Breaks/Old Skool/amen_break.wav",
        "Breaks/dark_break_01.wav",
        "Loops/dusty_loop.wav",
        "Snares/snare_909_tight.wav",
        "Snares/909_snr.wav",
        "Drums/HiHats/hi-hat_closed_01.wav",
        # Noise that must be filtered out and stay out.
        "Pads/Seabed_pad.wav",
        "FX/Abduction_FX.wav",
        "Vocals/vox_wet_01.aiff",
    ]
    for relative in files:
        path = lib / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"RIFF" + b"\x00" * 40)

    set_libraries({"Prefilter Library": lib})
    return lib


@pytest.mark.parametrize(
    "query",
    [
        "kick",  # reachable only via a separator-spanning compound join
        "loop",
        "breaks",
        "snare 909",
        "dark break",
        "melody",  # -ies stemming, the direction a naive probe loses
        "melodies",
        "hi-hat",
        "808",
        "break 174",  # a tempo term the prefilter cannot test at all
    ],
)
def test_prefilter_never_drops_a_file_the_matcher_would_have_kept(
    query, prefilter_library, monkeypatch
):
    """The prefilter must be a NECESSARY condition, never an equivalent one.

    Identical SETS, not merely equal counts -- the 11% loss the naive
    raw-path version caused on a real library was a swap, not a shortfall.
    Re-run this whenever the tokeniser changes; the equivalence is a property
    of ``stem``/``compound_join``, not of the prefilter alone.
    """
    from digr.tools import _shared
    from digr.tools._shared import search_libraries

    filtered = search_libraries(query, 500, per_library_cap=500)

    # Admit every file, so match_query alone decides.
    monkeypatch.setattr(
        _shared, "prefilter_hits", lambda groups, stripped: len(groups)
    )
    unfiltered = search_libraries(query, 500, per_library_cap=500)

    assert {p for p, _ in filtered.matches} == {p for p, _ in unfiltered.matches}
    assert filtered.partial == unfiltered.partial
    assert filtered.matched_terms == unfiltered.matched_terms
    assert filtered.missing_terms == unfiltered.missing_terms


def test_the_naive_raw_path_prefilter_is_the_thing_being_avoided():
    """Pins WHY the strip exists, so nobody optimises it away.

    The joined token the alias map needs is absent from the raw filename and
    present once the separators go.
    """
    from digr.tools._query import strip_separators

    name = "Niko_Kotoulas_MelodicTrap_Bassline_1_C#m-A-B-D.mid"

    assert "bd" not in name.lower()
    assert "bd" in strip_separators(name)
