"""Guards tempo-detection accuracy against a fixed synthetic corpus.

Digr's detector is the one component whose quality is a number rather than a
behaviour, and the ordinary unit tests cannot see it: they assert that a
specific fixture detects a specific tempo, so a change that fixes one file and
breaks nine still passes. This measures the whole corpus at once.

The corpus has two subsets. The BINARY 63 (5 patterns on a power-of-two 16th
grid, band-routed by ``patterns_for``) is the original committed corpus,
unchanged by anything below. The TERNARY 42 (``shuffle`` and ``dotted``,
applied to all 21 tempos) exists because the binary corpus cannot generate the
2/3 and 4/3 errors that make up 28% of real-world error -- see
``benchmarks/README.md``. The two subsets are guarded separately rather than
as one combined floor: ternary material is hard for every detector variant, so
a combined floor would sit close enough to a genuinely broken detector to be
an alarm in name only. If you find yourself moving MINIMUM_EXACT_PCT or
MAX_THIRD_RATIO_ERRORS, the scoping has gone wrong -- they are meant to stay
put.

The binary assertions are a FLOOR WITH MARGIN, never the exact current figure.
Accuracy can move a point or two between platforms as numpy and scipy versions
differ across the CI matrix, and a test that fails on that noise would be
abandoned long before it ever caught a real regression. The floor sits below
the current result but comfortably above the worst measured regressions
(removing the common-tempo snap scores 46%, trusting raw autocorrelation
strength scores 29%), so a genuine break still trips it.

For the full per-band table on a passing run, use the standalone runner:
``python benchmarks/run_tempo_benchmark.py --verbose``.
"""

import pytest

from digr.tools._audio_analysis import detect_tempo

from tempo_corpus import classify, score

# Below the measured result by enough to absorb cross-platform numeric drift,
# above the known-bad variants by enough to still catch them. Scoped to the
# BINARY subset -- see the module docstring.
MINIMUM_EXACT_PCT = 58.0

# The detector considers harmonics of its best autocorrelation peak. It accepts
# only the octave (half and double), because half/double is a real disagreement
# between producers about one piece of music, while 3/2 and 2/3 exist only in
# the autocorrelation -- nobody calls a 124 house loop "82". Re-admitting those
# ratios roughly doubles this count, so it is a direct guard on that rule.
# Scoped to the BINARY subset -- see the module docstring.
MAX_THIRD_RATIO_ERRORS = 4

# The ternary subset exists specifically to generate 2/3 and 4/3 ratio errors.
# Too few means the patterns have stopped stressing the detector the way they
# were designed to. No accuracy floor is set here: on this subset a known-bad
# detector variant (no common-tempo snap) OUTSCORES the shipped one (52.4% vs
# 45.2%), so an accuracy floor would pass for the wrong detector -- a
# ratio-error count is the only guard that means anything.
TERNARY_MIN_RATIO_ERRORS = 10

# The corpus is fixed, so its size is too. A change here means the corpus
# itself moved, which invalidates comparison against every recorded figure.
EXPECTED_CORPUS_SIZE = 105
EXPECTED_BINARY_SIZE = 63


def _table(result) -> str:
    """The full result, rendered for an assertion message -- CI runs pytest -q,
    which hides stdout from passing tests, so a failure message is the only
    place a table reliably reaches the log."""
    lines = [
        "",
        f"corpus: {result['total']} loops",
        f"overall exact: {result['exact']}/{result['total']} ({result['exact_pct']:.1f}%)",
        "by band:",
    ]
    for name, (hit, total, pct) in result["bands"].items():
        lines.append(f"  {name:<14} {hit:>3}/{total:<3} ({pct:>5.1f}%)")
    lines.append("error breakdown:")
    for verdict, count in sorted(result["breakdown"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {verdict:<8} {count:>3}")
    lines.append("")
    lines.append("Reproduce: python benchmarks/run_tempo_benchmark.py --verbose")
    return "\n".join(lines)


@pytest.fixture(scope="module")
def binary_result():
    """The original 63-loop corpus. Once per module, not once per assertion."""
    return score(detect_tempo, subset="binary")


@pytest.fixture(scope="module")
def ternary_result():
    """The 42-loop non-power-of-two corpus (shuffle, dotted x 21 tempos)."""
    return score(detect_tempo, subset="ternary")


@pytest.fixture(scope="module")
def combined_result():
    """Both subsets together -- the honest representative figure. Reported,
    not asserted on: see TERNARY_MIN_RATIO_ERRORS for why."""
    return score(detect_tempo, subset="both")


def test_corpus_is_the_expected_size(combined_result, binary_result):
    """A moved corpus makes every recorded accuracy figure incomparable."""
    assert combined_result["total"] == EXPECTED_CORPUS_SIZE, (
        f"corpus size changed ({combined_result['total']} != {EXPECTED_CORPUS_SIZE}); "
        "recorded accuracy figures are no longer comparable"
    )
    assert binary_result["total"] == EXPECTED_BINARY_SIZE, (
        f"binary subset size changed ({binary_result['total']} != {EXPECTED_BINARY_SIZE}); "
        "the ADD decision assumes this subset never grows or shrinks"
    )


def test_binary_subset_is_unchanged_by_the_ternary_addition(binary_result):
    """The ADD decision (over SUBSTITUTE) rests on the 63 committed loops
    being bit-identical to what they were before the ternary patterns existed.
    This is the number that proves it: if any existing loop's audio moved,
    this count moves with it."""
    assert binary_result["exact"] == 41, (
        f"binary subset scored {binary_result['exact']}/63 exact, not the "
        f"committed 41/63 -- an existing loop's audio changed.{_table(binary_result)}"
    )


def test_tempo_detection_accuracy_has_not_regressed(binary_result):
    assert binary_result["exact_pct"] >= MINIMUM_EXACT_PCT, (
        f"tempo detection fell to {binary_result['exact_pct']:.1f}%, below the "
        f"{MINIMUM_EXACT_PCT}% floor.{_table(binary_result)}"
    )


def test_three_halves_ratios_are_not_reported(binary_result):
    """Guards the octave-only rule where tempos are produced, matching the
    rule the search layer already applies when admitting an unlabelled file."""
    third_ratio = binary_result["breakdown"].get("3/2", 0) + binary_result["breakdown"].get("2/3", 0)
    assert third_ratio <= MAX_THIRD_RATIO_ERRORS, (
        f"{third_ratio} results landed on a 3/2 or 2/3 ratio, above the "
        f"{MAX_THIRD_RATIO_ERRORS} allowed.{_table(binary_result)}"
    )


def test_four_thirds_ratio_is_classified():
    """classify() gained a 4/3 bucket alongside the existing 3/2 -- a plain
    1.333 ratio used to fall through to "other", which made 13% of the real
    error profile unnameable by the benchmark."""
    assert classify(120, 160.0) == "4/3"


def test_ternary_subset_produces_enough_ratio_errors(ternary_result):
    """The ternary patterns exist to generate 2/3 and 4/3 errors -- too few
    means they have stopped stressing the detector the way they were added
    to. Breaks if dotted's hats regress from five to a straight-8th grid."""
    ratio_errors = (
        ternary_result["breakdown"].get("2/3", 0) + ternary_result["breakdown"].get("4/3", 0)
    )
    assert ratio_errors >= TERNARY_MIN_RATIO_ERRORS, (
        f"ternary subset produced only {ratio_errors} 2/3 or 4/3 errors, below "
        f"the {TERNARY_MIN_RATIO_ERRORS} expected.{_table(ternary_result)}"
    )


def test_detection_never_returns_an_absurd_tempo(combined_result):
    """A tempo outside the engine's own search range means the detector
    returned something its own lag bounds should have made impossible."""
    bad = [(bpm, pattern, got) for bpm, _, pattern, got, _ in combined_result["rows"]
           if got != 0.0 and not (30.0 <= got <= 300.0)]
    assert not bad, f"tempo outside 30-300 BPM: {bad}"
