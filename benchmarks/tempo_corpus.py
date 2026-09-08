"""A deterministic, synthetic drum-loop corpus for measuring tempo detection.

Tempo detection is the one part of Digr whose quality is a NUMBER rather than
a behaviour, so it needs a fixed corpus to measure against. Two properties
matter more than realism:

* **Deterministic.** Every loop is generated from a fixed seed, so a change in
  the reported accuracy is always a change in the detector, never in the input.
* **Genre-spread.** Digr is a general-purpose tool, so the corpus spans the
  tempo space real sample libraries occupy -- hip-hop through hardcore -- and
  is deliberately NOT weighted toward any one genre. Reasoning about the
  detector from a corpus centred on one tempo band is how a detector acquires
  a bias toward that band.

Each loop is an exact whole number of 4/4 bars at a known tempo, which is what
lets a caller classify an error as "octave" (half or double) rather than merely
"wrong" -- the distinction the detector's real failure mode lives in.

Deliberately synthetic and self-contained: it runs identically on every CI
runner with no audio files, no network and no drives attached. The separate
(gitignored) ``benchmark_audio.py`` at the repo root does the complementary
job -- comparing engines on REAL samples from a local drive -- and cannot run
in CI for exactly the reasons this module avoids.
"""

import numpy as np

SR = 22050

# Patterns are 16th-note step positions within one 4/4 bar (16 steps).
# Three shapes, chosen because they stress the detector differently: a dense
# grid where every subdivision is filled, a backbeat where the strong onsets
# are sparse, and a halftime feel whose snare genuinely suggests half the
# tempo -- the ambiguity that is real in the music rather than in the maths.
PATTERNS = {
    "fourfloor": {"k": [0, 4, 8, 12], "s": [4, 12], "h": [2, 6, 10, 14]},
    "backbeat": {"k": [0, 6, 10], "s": [4, 12], "h": [0, 2, 4, 6, 8, 10, 12, 14]},
    "breaks": {"k": [0, 10], "s": [4, 7, 12, 14], "h": [2, 6, 8, 14]},
    "halftime": {"k": [0, 11], "s": [8], "h": [0, 4, 8, 12]},
    "sparse": {"k": [0, 8], "s": [4, 12], "h": []},
}

# (bpm, genre) across the span a general-purpose library actually contains.
TEMPOS = [
    (70, "downtempo"),
    (85, "hip-hop"),
    (90, "hip-hop"),
    (95, "trip-hop"),
    (100, "boom-bap"),
    (110, "breaks"),
    (118, "disco"),
    (124, "house"),
    (128, "house/techno"),
    (132, "techno"),
    (135, "uk-garage"),
    (140, "dubstep/trap"),
    (145, "techno"),
    (150, "hardgroove"),
    (160, "footwork"),
    (165, "jungle"),
    (170, "dnb"),
    (172, "dnb"),
    (174, "dnb"),
    (176, "dnb"),
    (180, "hardcore"),
]


def _kick(sr: int, dur: float = 0.18) -> np.ndarray:
    """A pitch-dropping sine with a fast decay -- the strongest onset there is."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    freq = 120.0 * np.exp(-t * 28.0) + 45.0
    return np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-t * 18.0)


def _snare(sr: int, dur: float = 0.16) -> np.ndarray:
    """Filtered noise plus a short tone, seeded so every snare is identical."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    noise = np.random.default_rng(7).standard_normal(n)
    tone = np.sin(2 * np.pi * 190.0 * t) * np.exp(-t * 40.0)
    return (noise * 0.7 + tone * 0.5) * np.exp(-t * 30.0)


def _hat(sr: int, dur: float = 0.05) -> np.ndarray:
    """Quiet, very short noise. Marks subdivisions, not beats -- which is why
    a detector that weights all onsets equally can mistake a hat grid for the
    beat grid and report double the true tempo."""
    n = int(sr * dur)
    t = np.arange(n) / sr
    return np.random.default_rng(13).standard_normal(n) * np.exp(-t * 120.0) * 0.35


def _place(buf: np.ndarray, hit: np.ndarray, start: float) -> None:
    i = int(start)
    if i >= len(buf):
        return
    j = min(len(buf), i + len(hit))
    buf[i:j] += hit[: j - i]


def make_loop(
    bpm: float, pattern: str = "fourfloor", bars: int = 4, sr: int = SR, seed: int = 0
) -> np.ndarray:
    """One loop of exactly ``bars`` whole 4/4 bars at ``bpm``.

    Hit velocities vary slightly from a seeded generator so the onset envelope
    isn't perfectly uniform (a perfectly uniform one is easier to analyse than
    any real recording), while staying reproducible.
    """
    if pattern not in PATTERNS:
        raise KeyError(f"unknown pattern {pattern!r}; have {sorted(PATTERNS)}")
    seconds_per_beat = 60.0 / bpm
    step = seconds_per_beat / 4.0
    buf = np.zeros(int(sr * seconds_per_beat * 4 * bars))
    steps = PATTERNS[pattern]
    rng = np.random.default_rng(seed)
    for bar in range(bars):
        base = bar * 4 * seconds_per_beat
        for name, sound, lo in (("k", _kick, 0.85), ("s", _snare, 0.8), ("h", _hat, 0.7)):
            for s in steps[name]:
                _place(buf, sound(sr) * rng.uniform(lo, 1.0), (base + s * step) * sr)
    buf += rng.standard_normal(len(buf)) * 0.0015  # light floor, never silent
    peak = float(np.max(np.abs(buf)))
    if peak > 0:
        buf = buf / peak * 0.9
    return buf.astype(np.float32)


def patterns_for(bpm: float) -> list[str]:
    """Patterns that make musical sense at ``bpm``.

    A four-on-the-floor kick at 174 or a jungle break at 70 would measure the
    detector against material no library contains.
    """
    if bpm < 105:
        return ["backbeat", "sparse", "halftime"]
    if bpm < 150:
        return ["fourfloor", "backbeat", "sparse"]
    return ["breaks", "fourfloor", "halftime"]


def build_corpus(bars: int = 4) -> list[tuple[int, str, str, np.ndarray]]:
    """The full corpus as (bpm, genre, pattern, audio) -- 3 patterns per tempo."""
    corpus = []
    for i, (bpm, genre) in enumerate(TEMPOS):
        for j, pattern in enumerate(patterns_for(bpm)):
            corpus.append(
                (bpm, genre, pattern, make_loop(bpm, pattern, bars=bars, seed=i * 10 + j))
            )
    return corpus


# Bands are reported separately because overall accuracy hides the failure that
# actually matters: detection is strong below 150 BPM and collapses above it.
BANDS = [(0, 105, "slow <105"), (105, 150, "mid 105-149"), (150, 400, "fast >=150")]


def classify(true_bpm: float, detected: float) -> str:
    """How a detection is wrong, not merely whether.

    Octave errors (half/double) are a different kind of failure from the rest:
    they mean the detector found the right pulse and the wrong frame, and they
    are the dominant error mode above 150 BPM.
    """
    if detected == 0.0:
        return "zero"
    ratio = detected / true_bpm
    for name, target, tol in (
        ("exact", 1.0, 0.04),
        ("double", 2.0, 0.08),
        ("half", 0.5, 0.02),
        ("3/2", 1.5, 0.06),
        ("2/3", 2.0 / 3.0, 0.03),
    ):
        if abs(ratio - target) < tol:
            return name
    return "other"


def score(detect, bars: int = 4) -> dict:
    """Run ``detect(audio, sr)`` over the corpus and summarise.

    Returns overall/per-band exact-match rates plus the error breakdown, and
    the raw rows so a caller can print or diff individual files.
    """
    rows = []
    for bpm, genre, pattern, audio in build_corpus(bars=bars):
        detected = float(detect(audio, SR))
        rows.append((bpm, genre, pattern, detected, classify(bpm, detected)))

    total = len(rows)
    exact = sum(1 for r in rows if r[4] == "exact")
    breakdown: dict[str, int] = {}
    for row in rows:
        breakdown[row[4]] = breakdown.get(row[4], 0) + 1

    bands = {}
    for low, high, name in BANDS:
        sub = [r for r in rows if low <= r[0] < high]
        if sub:
            hit = sum(1 for r in sub if r[4] == "exact")
            bands[name] = (hit, len(sub), 100.0 * hit / len(sub))

    return {
        "rows": rows,
        "total": total,
        "exact": exact,
        "exact_pct": 100.0 * exact / total if total else 0.0,
        "breakdown": breakdown,
        "bands": bands,
    }
