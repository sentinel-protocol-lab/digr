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
| `tempo_corpus.py` | 63 synthetic drum loops — 21 tempos (70–180 BPM) × 3 patterns each, spread across hip-hop, house, techno, garage, dubstep, footwork, jungle, DnB and hardcore. Deterministic: every loop is generated from a fixed seed. |
| `run_tempo_benchmark.py` | Runs the corpus through the detector and prints the per-band table. |

`tests/test_tempo_benchmark.py` uses the same corpus as a CI guard.

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

## Relationship to `benchmark_audio.py`

The `benchmark_audio.py` script at the repository root does a complementary
job — comparing this engine against librosa on **real** samples from a local
drive. It needs a path argument, needs librosa installed alongside, and depends
on whatever files happen to be on that drive, so it cannot run in CI and is not
tracked. Use it to sanity-check against real material; use this directory to
measure change over time.
