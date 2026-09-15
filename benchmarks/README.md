# Benchmarks

Measurement tools for the parts of Digr whose quality is a **number** rather
than a behaviour. Nothing in `src/digr` imports this directory, and it is not
part of the distributed package.

## Why this is committed

Tempo detection is the one component that can silently get worse. The ordinary
unit tests assert that a specific fixture detects a specific tempo, so a change
that fixes one file and breaks nine still passes green. Only a fixed corpus
measured as a whole can see that.

For the corpus to be worth anything it has to be **versioned**. Comparing a
"before" and "after" number only means something if both were measured against
the same input — an uncommitted corpus can drift, and then a moved number no
longer tells you whether the detector changed or the test did.

## Contents

| file | what it is |
|---|---|
| `tempo_corpus.py` | 105 synthetic drum loops — 63 **binary** (21 tempos × 3 band-routed patterns on a power-of-two 16th grid) plus 42 **ternary** (2 non-power-of-two patterns applied to all 21 tempos), spread across hip-hop, house, techno, garage, dubstep, footwork, jungle, DnB and hardcore. Deterministic: every loop is generated from a fixed seed. |
| `run_tempo_benchmark.py` | Runs the corpus through the detector and prints the per-band table. |

`tests/test_tempo_benchmark.py` uses the same corpus as a CI guard.

## Binary and ternary subsets

The corpus is two subsets, generated and guarded separately.

**Binary (63)** is the original corpus: 5 patterns on a power-of-two 16th
grid, routed to each tempo by musical fit (`patterns_for`). It is untouched by
the ternary addition below — new patterns use seeds `i*10+3` and `i*10+4`,
existing ones use `i*10+j` for `j in {0,1,2}`, so the two can never collide.
That bit-identical guarantee is pinned by a test, not just asserted in a
comment: `tests/test_tempo_benchmark.py` checks the binary subset still scores
the exact 41/63 it scored before this subset existed.

**Ternary (42)** is `shuffle` and `dotted`, applied to *every* tempo rather
than routed by band. They exist because the binary corpus has no onset period
that isn't a power-of-two subdivision, so it cannot generate the 2/3 and 4/3
tempo-ratio errors behind 28% of real-world error (see "Real audio" below).
Band-routing was tried and measured, not assumed, and rejected: `dotted`'s 4/3
errors all occur below 128 BPM, so confining it to a fast band scores 4/3 ==
0 — routing destroys the exact class the subset exists to add.

`build_corpus()` and `score()` both take a `subset` argument (`"binary"` /
`"ternary"` / `"both"`, default `"both"`) so a caller can report any of the
three.

The two subsets carry different guards because a single one can't serve both.
A combined accuracy floor over all 105 loops would be a materially weaker
regression guard than the binary-only floor it would replace — the
discriminating margin between the shipped detector and a known-bad variant
falls from +19.0 points to +8.6, because ternary material is hard for *every*
variant, including broken ones. So `MINIMUM_EXACT_PCT` and
`MAX_THIRD_RATIO_ERRORS` stay scoped to the binary 63 and do not move. The
ternary 42 instead gets a minimum count of 2/3 + 4/3 ratio errors: on that
subset a known-bad variant (no common-tempo snap) actually outscores the
shipped detector (52.4% vs 45.2%), so an accuracy floor there would pass for
the wrong detector.

## Running it

```bash
pip install -e ".[audio,dev]"

python benchmarks/run_tempo_benchmark.py             # summary + per-band table
python benchmarks/run_tempo_benchmark.py --verbose   # every file and its verdict
```

## Reading the result

**Always report per band.** A single overall figure hides the failure that
actually matters: detection is strong below 150 BPM and collapses above it,
because autocorrelation cannot separate a tempo from half that tempo — a
signal that repeats every beat also repeats every two beats, so the half-tempo
peak is always at least as strong as the true one. A change that lifts the
overall number while flattening the fast band is not an improvement.

The verdict for each file distinguishes *how* a detection is wrong, not just
whether. An `half` or `double` verdict means the detector found the right pulse
and the wrong frame, which is a different (and more recoverable) failure than
`other`.

## Real audio

The synthetic corpus is deliberately genre-spread and reproducible, but it is
still synthetic. Measured separately on **8 September 2026**, n=500, against
"a private local library of commercial sample packs (not committed — that is
the point: real, messy, at scale)": raw `detect_tempo` scored **39% exact**.

**Method:** ground truth came from strict filename tempo labels, keeping only
files whose duration is a whole bar-count at that label (this drops one-shots
and pads that merely inherited a pack tempo rather than stating their own).
Scored with raw `detect_tempo`, never `detect_tempo_with_hint` — the label is
the ground truth being scored against, so it must never leak into the
detector's answer.

| class | real audio (n=500) | corpus (105) |
|---|---|---|
| 2/3 | 15.2% | 11.4% |
| 4/3 | 13.0% | 5.7% |
| half | 9.4% | 23.8% |
| double | 3.6% | 1.9% |
| unrelated | 15.8% | 0% |
| declined (returned 0.0) | 0% | 0% |

The ternary subset moves the corpus toward this profile — it did not exist to
close the gap in one pass, and it doesn't: the corpus still has no analogue of
`unrelated` (real material the detector locks onto a plausible but wrong
tempo for reasons a synthetic loop doesn't reproduce), and `half` is
over-represented relative to real audio precisely because the binary corpus
is built to stress it. Treat 39% as the number that matters when judging
whether the detector is good enough, and the corpus figures as the number
that matters when judging whether a change to the detector is a regression.

## Relationship to `benchmark_audio.py`

The `benchmark_audio.py` script at the repository root does a complementary
job — comparing this engine against librosa on **real** samples from a local
drive. It needs a path argument, needs librosa installed alongside, and depends
on whatever files happen to be on that drive, so it cannot run in CI and is not
tracked. Use it to sanity-check against real material; use this directory to
measure change over time.
