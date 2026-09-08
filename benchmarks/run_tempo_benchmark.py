#!/usr/bin/env python3
"""Report tempo-detection accuracy against the fixed corpus.

    python benchmarks/run_tempo_benchmark.py            # summary + per-band
    python benchmarks/run_tempo_benchmark.py --verbose  # every file

Requires the audio extras: ``pip install -e ".[audio,dev]"``.

The per-band table is the point. Overall accuracy alone hides the failure that
matters -- detection is strong below 150 BPM and collapses above it, because
autocorrelation cannot distinguish a tempo from half that tempo (a signal
repeating every beat also repeats every two beats). Any change to detection
should be reported per band, not as a single number.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tempo_corpus import score  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="print every file, not just totals"
    )
    args = parser.parse_args()

    try:
        from digr.tools._audio_analysis import detect_tempo
    except ImportError as exc:
        print(f"ERROR: audio extras not installed ({exc})")
        print('Install with:  pip install -e ".[audio,dev]"')
        return 1

    result = score(detect_tempo)

    if args.verbose:
        print(f"{'true':>5}  {'genre':<14} {'pattern':<10} {'detected':>9}  verdict")
        print("-" * 56)
        for bpm, genre, pattern, detected, verdict in result["rows"]:
            flag = "" if verdict == "exact" else "  <<<"
            print(f"{bpm:>5}  {genre:<14} {pattern:<10} {detected:>9.1f}  {verdict}{flag}")
        print()

    print(f"Corpus: {result['total']} loops")
    print(f"Overall exact: {result['exact']}/{result['total']} ({result['exact_pct']:.0f}%)")
    print("\nBy band:")
    for name, (hit, total, pct) in result["bands"].items():
        print(f"  {name:<14} {hit:>3}/{total:<3} ({pct:>3.0f}%)")
    print("\nError breakdown:")
    for verdict, count in sorted(result["breakdown"].items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:<8} {count:>3} ({100.0 * count / result['total']:>3.0f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
