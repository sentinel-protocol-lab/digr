"""Unit tests for the plain-English query engine, one class per stage."""

from pathlib import Path

from digr.tools._query import (
    BpmTarget,
    compound_join,
    expansions,
    extract_bpm_from_filename,
    file_tokens,
    match_query,
    parse_query,
    rank_key,
    stem,
    tokenize,
    weak_expansions,
)


# ---------------------------------------------------------------------------
# Stage 1 -- normalisation & tokenisation
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_splits_on_pack_punctuation(self):
        tokens = tokenize("TSP_NOISIA-174 (dnb).break[01]")
        assert "tsp" in tokens
        assert "noisia" in tokens
        assert "dnb" in tokens
        assert "break" in tokens

    def test_splits_letter_digit_boundaries(self):
        assert tokenize("174dnb") == ["174", "dnb"]
        assert tokenize("kick808") == ["kick", "808"]

    def test_splits_camel_case(self):
        assert tokenize("DarkReese") == ["dark", "reese"]

    def test_acronym_before_word(self):
        assert tokenize("MIDIFile") == ["midi", "file"]

    def test_extension_is_kept_as_a_token(self):
        """Type search ('wav', 'mid') depends on it, and it is not what let
        '.mid' match a '...MiDi...' folder -- the camel split is."""
        assert "wav" in tokenize("break.wav")

    def test_midi_folder_does_not_produce_a_mid_token(self):
        """The real reported false positive, killed by tokenisation alone."""
        tokens = tokenize("Ghosthack.Platinum.Bundle.2019.WAV.MiDi.SERUM.PRESETS")
        assert "mid" not in tokens
        assert "mi" in tokens and "di" in tokens

    def test_windows_separator(self):
        assert tokenize(r"Drums\Kicks") == ["drums", "kicks"]

    def test_compound_join_pairs_neighbours(self):
        assert compound_join(["hi", "hat"]) == ["hihat"]
        assert compound_join(["a", "b", "c"]) == ["ab", "bc"]


# ---------------------------------------------------------------------------
# Stage 3 -- stemming
# ---------------------------------------------------------------------------


class TestStem:
    def test_simple_plural(self):
        assert stem("breaks") == "break"
        assert stem("pads") == "pad"
        assert stem("snares") == "snare"

    def test_double_s_is_protected(self):
        assert stem("bass") == "bass"
        assert stem("brass") == "brass"

    def test_es_endings(self):
        assert stem("crashes") == "crash"
        assert stem("punches") == "punch"

    def test_ies_ending(self):
        assert stem("bodies") == "body"

    def test_short_and_non_alpha_untouched(self):
        assert stem("fx") == "fx"
        assert stem("sub") == "sub"
        assert stem("808") == "808"

    def test_does_not_handle_tense(self):
        """Deliberately out of scope -- no -ing/-ed handling."""
        assert stem("rolling") == "rolling"


# ---------------------------------------------------------------------------
# Stage 2 / 2b -- alias expansion
# ---------------------------------------------------------------------------


class TestExpansions:
    def test_hihat_family(self):
        assert "hihat" in expansions("hat")
        assert "hat" in expansions("hihat")
        assert "hihat" in expansions("hats")

    def test_percussion(self):
        assert "percussion" in expansions("perc")
        assert "perc" in expansions("percussion")

    def test_vocal(self):
        assert "vocal" in expansions("vox")
        assert "vox" in expansions("vocals")

    def test_sub_and_808(self):
        assert "808" in expansions("sub")
        assert "sub" in expansions("808")

    def test_drum_machine_abbreviations(self):
        assert "kick" in expansions("bd")
        assert "bd" in expansions("kick")
        assert "snare" in expansions("sd")
        assert "clap" in expansions("cp")
        assert "rimshot" in expansions("rs")
        assert "cymbal" in expansions("cy")
        assert "hihat" in expansions("hh")

    def test_sets_overlap_rather_than_partition(self):
        """hihat belongs to the hi-hat group AND the hh abbreviation group."""
        hihat = expansions("hihat")
        assert {"hat", "hh"} <= hihat

    def test_cb_collision_is_weak_and_carries_both_senses(self):
        """cb is cowbell AND contrabass -- exactly what equivalence groups
        cannot represent, and why the weak tier exists."""
        weak = weak_expansions("cb")
        assert {"cowbell", "contrabass"} <= weak
        # Not promoted into the strong tier.
        assert "cowbell" not in expansions("cb")

    def test_cl_collision(self):
        weak = weak_expansions("cl")
        assert {"clave", "clarinet"} <= weak

    def test_weak_is_empty_for_ordinary_words(self):
        assert weak_expansions("kick") == frozenset()

    def test_expansion_includes_itself(self):
        assert "reese" in expansions("reese")
        assert "reece" in expansions("reese")


# ---------------------------------------------------------------------------
# Stages 4 & 7 -- query parsing, BPM targets, stopwords
# ---------------------------------------------------------------------------


def _texts(spec):
    return [term.text for term in spec.terms]


class TestParseQuery:
    def test_plain_terms(self):
        assert _texts(parse_query("dark reese")) == ["dark", "reese"]

    def test_stopwords_dropped(self):
        assert _texts(parse_query("find me some snares")) == ["snares"]

    def test_letter_a_is_kept_because_it_is_a_key(self):
        assert "a" in _texts(parse_query("bass a minor"))

    def test_bare_integer_is_target_and_token(self):
        spec = parse_query("174 break")
        assert "174" in _texts(spec)
        assert BpmTarget(174.0, 174.0) in spec.bpm_targets

    def test_808_is_not_a_tempo(self):
        """808 sits above the band, so 'kick 808' keeps working as before."""
        spec = parse_query("kick 808")
        assert _texts(spec) == ["kick", "808"]
        assert spec.bpm_targets == ()

    def test_bpm_suffix_forms(self):
        for query in ("174bpm", "174 bpm", "174-bpm", "bpm 174"):
            spec = parse_query(query)
            assert BpmTarget(174.0, 174.0) in spec.bpm_targets, query
            assert "bpm" not in _texts(spec), query

    def test_range_forms(self):
        for query in ("170-178", "170 to 178"):
            spec = parse_query(query)
            assert BpmTarget(170.0, 178.0) in spec.bpm_targets, query

    def test_range_does_not_become_two_and_terms(self):
        """Keeping 170 and 178 as separate required terms would match nothing."""
        spec = parse_query("170-178 breaks")
        assert _texts(spec) == ["breaks", "170-178"]

    def test_out_of_band_numbers_are_not_a_range(self):
        spec = parse_query("909-808")
        assert spec.bpm_targets == ()
        assert "909" in _texts(spec)

    def test_known_compound_is_fused(self):
        """'hi hat' is one thing, not two requirements."""
        assert _texts(parse_query("hi-hat")) == ["hihat"]
        assert _texts(parse_query("hi hat")) == ["hihat"]

    def test_unknown_compound_is_left_alone(self):
        assert _texts(parse_query("dark reese")) == ["dark", "reese"]

    def test_duplicate_terms_collapse(self):
        assert _texts(parse_query("kick kick")) == ["kick"]

    def test_empty_query(self):
        assert parse_query("   ").terms == ()


class TestExtractBpmFromFilename:
    def test_patterns(self):
        assert extract_bpm_from_filename("Break_170bpm.wav") == 170.0
        assert extract_bpm_from_filename("Aisha 117BPM.wav") == 117.0
        assert extract_bpm_from_filename("loop_bpm_170.wav") == 170.0
        assert extract_bpm_from_filename("120-GitterBreak.wav") == 120.0

    def test_no_bpm(self):
        assert extract_bpm_from_filename("kick_808.wav") is None
        assert extract_bpm_from_filename("") is None


# ---------------------------------------------------------------------------
# File side -- tokenising a path
# ---------------------------------------------------------------------------


class TestFileTokens:
    def test_name_and_folder_buckets_are_separate(self):
        bag = file_tokens("/lib/Drums/Kicks/kick_808.wav", root=Path("/lib"))
        assert "kick" in bag.name
        assert "808" in bag.name
        assert "kicks" in bag.folder
        assert "kick" not in bag.folder

    def test_folders_are_relative_to_the_library(self):
        """The machine's own path must not contribute searchable tokens."""
        bag = file_tokens("/Users/someone/Developer/lib/Kicks/k.wav", root=Path("/Users/someone/Developer/lib"))
        assert "developer" not in bag.folder
        assert "someone" not in bag.folder
        assert "kicks" in bag.folder

    def test_compound_tokens_on_the_file_side(self):
        bag = file_tokens("/lib/hi-hat_closed.wav", root=Path("/lib"))
        assert "hihat" in bag.name

    def test_stems_are_precomputed(self):
        bag = file_tokens("/lib/Breaks/amen_break.wav", root=Path("/lib"))
        assert "break" in bag.folder_stems
        assert "break" in bag.name_stems

    def test_numbers_collected(self):
        bag = file_tokens("/lib/loop_172_shaker.wav", root=Path("/lib"))
        assert 172 in bag.numbers

    def test_bpm_hint(self):
        bag = file_tokens("/lib/Break_174bpm.wav", root=Path("/lib"))
        assert bag.bpm_hint == 174.0

    def test_extension_is_searchable(self):
        bag = file_tokens("/lib/kick.wav", root=Path("/lib"))
        assert "wav" in bag.name


# ---------------------------------------------------------------------------
# Stages 5 & 6 -- matching and ranking
# ---------------------------------------------------------------------------


def _match(query: str, path: str, root: str = "/lib"):
    return match_query(parse_query(query), file_tokens(path, root=Path(root)))


class TestMatching:
    def test_filename_exact(self):
        assert _match("kick", "/lib/Drums/kick_808.wav").matched

    def test_folder_exact(self):
        assert _match("drums", "/lib/Drums/kick_808.wav").matched

    def test_all_terms_required(self):
        assert not _match("kick snare", "/lib/Drums/kick_808.wav").matched

    def test_plural_matches_singular(self):
        assert _match("breaks", "/lib/amen_break.wav").matched

    def test_singular_matches_plural(self):
        assert _match("break", "/lib/Breaks/amen.wav").matched

    def test_alias_matches(self):
        assert _match("hihat", "/lib/hi-hat_closed.wav").matched
        assert _match("hat", "/lib/hihat_open.wav").matched
        assert _match("percussion", "/lib/perc_rattle.wav").matched

    def test_bd_abbreviation_finds_kick(self):
        assert _match("kick", "/lib/E808_Loop_BD_01.wav").matched

    def test_abbreviation_false_positives_are_dead(self):
        """The two files the 9 Jul substring ruling was worried about."""
        assert not _match("kick", "/lib/Abduction_FX.wav").matched
        assert not _match("kick", "/lib/Seabed_pad.wav").matched

    def test_substring_fallback_inside_a_filename_token(self):
        assert _match("verb", "/lib/Big_Reverb_Tail.wav").matched

    def test_substring_fallback_is_filename_only(self):
        """'loop' must not match the Loopmasters pack folder."""
        assert not _match("loop", "/lib/Loopmasters/Drum Hits/TSP_174_break.wav").matched
        assert _match("loop", "/lib/Loopmasters/E808_Loop_BD.wav").matched

    def test_substring_needs_four_characters(self):
        assert not _match("808", "/lib/kick_1808x.wav").matched

    def test_substring_never_applies_to_an_alias(self):
        """kick -> bd -> substring would resurrect 'Seabed'. It must not."""
        assert not _match("kick", "/lib/Seabed_and_Abduction.wav").matched

    def test_bpm_token_matches_either_way(self):
        assert _match("174", "/lib/TSP_174_break.wav").matched
        assert _match("174bpm", "/lib/TSP_174_break.wav").matched
        assert _match("174", "/lib/TSP_break_174bpm.wav").matched

    def test_range_matches_a_number_in_the_filename(self):
        assert _match("170-178", "/lib/TSP_172_shaker.wav").matched
        assert not _match("170-178", "/lib/TSP_140_shaker.wav").matched

    def test_matched_terms_reports_the_near_miss(self):
        result = _match("dark 174 break", "/lib/TSP_174_break.wav")
        assert not result.matched
        assert result.matched_terms == frozenset({1, 2})


class TestRanking:
    def test_filename_beats_folder(self):
        in_name = _match("break", "/lib/amen_break.wav").score
        in_folder = _match("break", "/lib/Breaks/dusty.wav").score
        assert in_name > in_folder

    def test_exact_beats_alias(self):
        exact = _match("hihat", "/lib/hihat_closed.wav").score
        alias = _match("hihat", "/lib/hh_closed.wav").score
        assert exact > alias

    def test_alias_beats_weak_alias(self):
        alias = _match("hihat", "/lib/hh_closed.wav").score
        weak = _match("hihat", "/lib/oh_closed.wav").score
        assert alias > weak

    def test_weak_alias_beats_substring(self):
        weak = _match("hihat", "/lib/oh_closed.wav").score
        substring = _match("verb", "/lib/reverb.wav").score
        assert weak > substring

    def test_bpm_hint_bonus(self):
        with_hint = _match("174", "/lib/break_174bpm.wav").score
        without_hint = _match("174", "/lib/break_174_x.wav").score
        assert with_hint > without_hint

    def test_all_in_filename_bonus(self):
        both_in_name = _match("kick 808", "/lib/Drums/kick_808.wav").score
        split = _match("kick 808", "/lib/808/kick_hard.wav").score
        assert both_in_name > split

    def test_rank_key_orders_by_score_then_length_then_alphabetically(self):
        rows = [(1.0, "bbb"), (5.0, "zzzzzz"), (5.0, "aaa"), (5.0, "aab")]
        ordered = [path for _, path in sorted(rows, key=lambda r: rank_key(*r))]
        assert ordered == ["aaa", "aab", "zzzzzz", "bbb"]
