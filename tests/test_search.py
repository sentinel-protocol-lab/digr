"""Tests for search tools."""

from pathlib import Path

import pytest

from digr.tools._query import BpmTarget
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
        return self._tempos[filename], 1.0


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
