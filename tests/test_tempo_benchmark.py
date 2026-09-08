"""Guards tempo-detection accuracy against a fixed synthetic corpus.

Digr's detector is the one component whose quality is a number rather than a
behaviour, and the ordinary unit tests cannot see it: they assert that a
specific fixture detects a specific tempo, so a change that fixes one file and
breaks nine still passes. This measures the whole corpus at once.

The assertion is a FLOOR WITH MARGIN, never the exact current figure. Accuracy
can move a point or two between platforms as numpy and scipy versions differ
across the CI matrix, and a test that fails on that noise would be abandoned
long before it ever caught a real regression. The floor sits below the current
result but comfortably above the worst measured regressions (removing the
common-tempo snap scores 46%, trusting raw autocorrelation strength scores
29%), so a genuine break still trips it.

For the full per-band table on a passing run, use the standalone runner:
``python benchmarks/run_tempo_benchmark.py --verbose``.
"""

import pytest

from digr.tools._audio_analysis import detect_tempo

from tempo_corpus import score

# Below the measured result by enough to absorb cross-platform numeric drift,
# above the known-bad variants by enough to still catch them.
MINIMUM_EXACT_PCT = 52.0

# The corpus is fixed, so its size is too. A change here means the corpus
# itself moved, which invalidates comparison against every recorded figure.
EXPECTED_CORPUS_SIZE = 63


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
def result():
    """Scoring the corpus decodes nothing but does run detection 63 times.
    Once per module, not once per assertion."""
    return score(detect_tempo)


def test_corpus_is_the_expected_size(result):
    """A moved corpus makes every recorded accuracy figure incomparable."""
    assert result["total"] == EXPECTED_CORPUS_SIZE, (
        f"corpus size changed ({result['total']} != {EXPECTED_CORPUS_SIZE}); "
        "recorded accuracy figures are no longer comparable"
    )


def test_tempo_detection_accuracy_has_not_regressed(result):
    assert result["exact_pct"] >= MINIMUM_EXACT_PCT, (
        f"tempo detection fell to {result['exact_pct']:.1f}%, below the "
        f"{MINIMUM_EXACT_PCT}% floor.{_table(result)}"
    )


def test_detection_never_returns_an_absurd_tempo(result):
    """A tempo outside the engine's own search range means the detector
    returned something its own lag bounds should have made impossible."""
    bad = [(bpm, pattern, got) for bpm, _, pattern, got, _ in result["rows"]
           if got != 0.0 and not (30.0 <= got <= 300.0)]
    assert not bad, f"tempo outside 30-300 BPM: {bad}"
