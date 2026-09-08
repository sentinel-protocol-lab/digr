"""Audio analysis engine: BPM detection, key detection, audio loading.

Replaces the librosa dependency with numpy + scipy + soundfile for universal
cross-platform compatibility. The algorithms are ported from librosa's approach
(mel-spectrogram onset strength, autocorrelation tempogram, STFT chromagram)
to maintain equivalent accuracy without the numba/llvmlite dependency chain.
"""

from math import gcd
from typing import NamedTuple

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, stft as scipy_stft

# extract_bpm_from_filename lives in _query because it is pure stdlib and the
# FREE search path needs it -- importing this module would drag in
# numpy/scipy/soundfile. The SOURCE_* constants live there for the same
# reason: the code that DISPLAYS a tempo has to name these cases without
# importing the optional audio engine. Re-exported here so existing callers
# are unaffected.
from ._query import (
    SOURCE_DETECTED,
    SOURCE_LABEL_CONFIRMED,
    SOURCE_LABEL_HARMONIC,
    SOURCE_LABEL_ONLY,
    extract_bpm_from_filename,
)

# How close detection must land to a filename label before the two count as
# agreeing. Deliberately tighter than the harmonic tolerance below it: this
# decides what Digr CLAIMS, and claiming agreement on an 8% disagreement is
# how "confirmed by detection" ended up meaning nothing. At 145 BPM, 8% is
# ±11.6 BPM.
AGREEMENT_TOLERANCE = 0.04


# ---------------------------------------------------------------------------
# Audio loading
# ---------------------------------------------------------------------------

def load_audio(
    path: str,
    sr: int = 22050,
    duration: float | None = None,
) -> tuple[np.ndarray, int]:
    """Load audio file, convert to mono float32, resample to target sr.

    Drop-in replacement for ``librosa.load(path, duration=N)``.

    Parameters
    ----------
    path : str
        Path to audio file (WAV, FLAC, AIFF, OGG, etc.)
    sr : int
        Target sample rate (default 22050, matching librosa).
    duration : float or None
        Maximum seconds to read. ``None`` reads the whole file.

    Returns
    -------
    (y, sr) : tuple[np.ndarray, int]
        Mono audio as float32 numpy array, and the sample rate.
    """
    # Determine how many frames to read
    info = sf.info(path)
    file_sr = info.samplerate

    if duration is not None:
        stop = min(int(duration * file_sr), info.frames)
    else:
        stop = info.frames

    # Read audio (always as float32, normalised to [-1, 1])
    data, file_sr = sf.read(path, dtype="float32", stop=stop, always_2d=True)

    # Convert to mono by averaging channels
    if data.shape[1] > 1:
        data = np.mean(data, axis=1)
    else:
        data = data[:, 0]

    # Resample to target sr if needed
    if file_sr != sr:
        g = gcd(sr, file_sr)
        up = sr // g
        down = file_sr // g
        data = resample_poly(data, up, down).astype(np.float32)

    return data, sr


def get_native_samplerate(path: str) -> int:
    """Read the file's true sample rate from its header, without decoding audio.
    
    Unlike load_audio (which resamples to a fixed analysis rate), this reports the sample rate the file actually recorded at - e.g. 44100 or 48000."""
    return int(sf.info(path).samplerate)

def get_native_duration(path: str) -> float:
    """Read the file"s true length in seconds from its header, without decoding.
    
    Load audio only reads the first 30s for speed, so the loaded audio understates long files. This reports the file's real duration."""
    return float(sf.info(path).duration)


# ---------------------------------------------------------------------------
# Mel filterbank (for onset strength computation)
# ---------------------------------------------------------------------------

def _hz_to_mel(f: float | np.ndarray) -> float | np.ndarray:
    """Convert Hz to Mel scale (HTK formula)."""
    return 2595.0 * np.log10(1.0 + np.asarray(f) / 700.0)


def _mel_to_hz(m: float | np.ndarray) -> float | np.ndarray:
    """Convert Mel scale to Hz."""
    return 700.0 * (10.0 ** (np.asarray(m) / 2595.0) - 1.0)


def _mel_filterbank(
    sr: int,
    n_fft: int,
    n_mels: int = 128,
    fmin: float = 0.0,
    fmax: float | None = None,
) -> np.ndarray:
    """Build a mel-scaled triangular filterbank with Slaney normalisation.

    Returns shape (n_mels, n_fft // 2 + 1).
    """
    if fmax is None:
        fmax = sr / 2.0

    n_freqs = n_fft // 2 + 1

    # Mel-spaced center frequencies
    mel_min = _hz_to_mel(fmin)
    mel_max = _hz_to_mel(fmax)
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = _mel_to_hz(mel_points)

    # FFT bin frequencies
    fft_freqs = np.linspace(0, sr / 2.0, n_freqs)

    # Build triangular filters
    filterbank = np.zeros((n_mels, n_freqs))
    for m in range(n_mels):
        f_left = hz_points[m]
        f_center = hz_points[m + 1]
        f_right = hz_points[m + 2]

        # Rising slope
        if f_center > f_left:
            rising = (fft_freqs - f_left) / (f_center - f_left)
            filterbank[m] += np.maximum(0, rising)

        # Falling slope
        if f_right > f_center:
            falling = (f_right - fft_freqs) / (f_right - f_center)
            filterbank[m] = np.minimum(filterbank[m], np.maximum(0, falling))

        # Slaney normalisation: divide by bandwidth in Hz
        bandwidth = hz_points[m + 2] - hz_points[m]
        if bandwidth > 0:
            filterbank[m] *= 2.0 / bandwidth

    return filterbank


# ---------------------------------------------------------------------------
# Onset strength envelope
# ---------------------------------------------------------------------------

def _onset_strength(
    y: np.ndarray,
    sr: int = 22050,
    n_fft: int = 2048,
    hop_length: int = 512,
    n_mels: int = 128,
) -> np.ndarray:
    """Compute onset strength envelope from audio signal.

    Uses mel-spectrogram spectral flux (positive first-order difference
    across mel bands, half-wave rectified, averaged) — matching librosa's
    ``onset.onset_strength`` default behaviour.
    """
    # Compute STFT via scipy
    _, _, Zxx = scipy_stft(
        y,
        fs=sr,
        nperseg=n_fft,
        noverlap=n_fft - hop_length,
        window="hann",
    )
    power = np.abs(Zxx) ** 2

    # Apply mel filterbank
    mel_fb = _mel_filterbank(sr, n_fft, n_mels)
    mel_spec = mel_fb @ power  # shape: (n_mels, T)

    # Convert to dB (log-power)
    mel_spec_db = 10.0 * np.log10(np.maximum(mel_spec, 1e-10))

    # Spectral flux: positive first-order difference, half-wave rectified
    onset = np.diff(mel_spec_db, axis=1)
    onset = np.maximum(0.0, onset)

    # Average across mel bands to get 1-D envelope
    onset_env = np.mean(onset, axis=0)

    return onset_env


# ---------------------------------------------------------------------------
# Tempo estimation
# ---------------------------------------------------------------------------

def _tempo_from_onset_env(onset_env: np.ndarray, sr: int = 22050) -> float:
    """Estimate BPM from an already-computed onset envelope.

    Split out from ``detect_tempo`` so that a caller needing both the tempo
    and something else derived from the envelope (``detect_tempo_with_hint``
    needs its variation, for confidence) can compute the envelope ONCE.
    Building it is the dominant cost of detection — roughly half the total —
    so computing it twice doubles the price of every analysed file.

    Returns 0.0 for signals with no detectable rhythm.
    """
    if len(onset_env) < 4:
        return 0.0

    # Check for meaningful rhythmic content
    if np.std(onset_env) < 1e-4:
        return 0.0

    # Onset envelope sample rate (frames per second)
    hop_length = 512
    osr = sr / hop_length

    # Lag range corresponding to 30-300 BPM
    min_bpm, max_bpm = 30.0, 300.0
    min_lag = max(1, int(np.ceil(60.0 * osr / max_bpm)))
    max_lag = int(np.floor(60.0 * osr / min_bpm))
    max_lag = min(max_lag, len(onset_env) - 1)

    if max_lag <= min_lag:
        return 0.0

    # Autocorrelation via FFT (fast)
    n = len(onset_env)
    fft_size = 1
    while fft_size < 2 * n:
        fft_size *= 2

    onset_fft = np.fft.rfft(onset_env, n=fft_size)
    acf = np.fft.irfft(onset_fft * np.conj(onset_fft))[:n]

    # Normalise
    if acf[0] > 0:
        acf = acf / acf[0]

    # Extract valid lag range
    acf_valid = acf[min_lag : max_lag + 1]
    lags = np.arange(min_lag, max_lag + 1)
    bpm_candidates = 60.0 * osr / lags

    # Apply log-normal tempo prior centered at 120 BPM
    # Sigma of 1.4 is wider than librosa's default (1.0) — this reduces
    # bias toward 120 so that faster genres (DnB, techno) aren't penalised
    # as heavily. The harmonic correction below handles the rest.
    log2_bpm = np.log2(bpm_candidates / 120.0)
    tempo_prior = np.exp(-0.5 * (log2_bpm / 1.4) ** 2)

    weighted_acf = acf_valid * tempo_prior

    # Peak picking
    best_idx = int(np.argmax(weighted_acf))
    tempo = float(bpm_candidates[best_idx])

    # --- Harmonic correction ---
    # The log-normal prior biases toward 120 BPM, which can suppress fast
    # tempos (DnB ~170, techno ~140+). Autocorrelation also produces peaks
    # at integer ratios of the true tempo (2×, 3/2×, etc.).
    # Check harmonically-related tempos and prefer one with strong raw ACF.
    raw_at_best = acf[lags[best_idx]]
    candidate_tempos = [tempo]

    # Octave only — double and half. The governing rule is to accept
    # ambiguities that exist in the MUSIC and reject artefacts that exist only
    # in the algorithm. Half/double is a real disagreement between producers
    # about one piece of music: the same trap loop is labelled 140 by one pack
    # and 70 by another, and the same goes for dubstep, footwork and any
    # halftime section. 3/2 and 2/3 are not that — nobody calls a 124 house
    # loop "82". That ratio appears only because autocorrelation picked a
    # three-against-two peak, so accepting it imports the detector's own
    # failure mode into the answer dressed as musical meaning. The search
    # layer already refuses these ratios when admitting an unlabelled file;
    # this is the same rule applied where the number is produced.
    for multiplier in [2.0, 0.5]:
        alt_tempo = tempo * multiplier
        if alt_tempo < min_bpm or alt_tempo > max_bpm:
            continue
        alt_lag = int(round(60.0 * osr / alt_tempo))
        if alt_lag < min_lag or alt_lag > max_lag:
            continue
        raw_at_alt = acf[alt_lag]
        # Accept the alternative if its raw ACF is at least 50% as strong —
        # meaning the prior was suppressing a legitimate peak.
        if raw_at_alt > 0.5 * raw_at_best:
            candidate_tempos.append(alt_tempo)

    # Among plausible candidates, prefer the one closest to a common
    # musical tempo (85, 90, 100, 110, 120, 128, 140, 150, 160, 170, 174, 180).
    #
    # LOAD-BEARING, despite looking like a cosmetic nicety, and measurably so:
    # removing it costs ~13 points of corpus accuracy and replacing it with
    # "strongest raw autocorrelation" costs ~30, because autocorrelation is
    # structurally biased toward half-time (a signal repeating every beat also
    # repeats every two beats, so the half-tempo peak is always at least as
    # strong) and this list is most of what currently counters that. It is a
    # crude instrument — the list carries genre assumptions a general-purpose
    # tool should not need — but do not remove it without a replacement that
    # holds the accuracy. Run benchmarks/run_tempo_benchmark.py before and
    # after any change here.
    common_tempos = [85, 90, 100, 110, 120, 128, 140, 150, 160, 170, 174, 180]

    def _musical_distance(bpm: float) -> float:
        return min(abs(bpm - ct) for ct in common_tempos)

    tempo = min(candidate_tempos, key=_musical_distance)

    return round(tempo, 1)


def detect_tempo(y: np.ndarray, sr: int = 22050) -> float:
    """Detect BPM from audio signal.

    Uses onset-strength autocorrelation with a log-normal tempo prior
    centered at 120 BPM — the same core approach as ``librosa.beat.beat_track``.

    Returns 0.0 for silence or signals with no detectable rhythm.
    """
    # Quick exit: silence check
    rms = float(np.sqrt(np.mean(y ** 2)))
    if rms < 1e-6:
        return 0.0

    return _tempo_from_onset_env(_onset_strength(y, sr), sr)


class TempoResult(NamedTuple):
    """A tempo, how much to trust it, and where it came from.

    ``source`` exists because ``tempo`` is not always a measurement. When the
    filename carries an explicit tag the label may be returned verbatim, and
    without this field a caller cannot tell that apart from an independent
    detection that happened to agree.
    """

    tempo: float
    confidence: float
    source: str
    # What the audio actually measured, before any label was substituted for
    # it. Equal to ``tempo`` when ``source`` is detected; when it is not, this
    # is the only way a caller can say WHAT detection found instead of merely
    # that it disagreed -- "the label says 172, detection found 86.1" is
    # useful to a producer, "detection did not confirm" is not.
    detected: float = 0.0


def detect_tempo_with_hint(
    y: np.ndarray,
    sr: int = 22050,
    filename: str = "",
) -> TempoResult:
    """Detect BPM, cross-referenced against a BPM tag in the filename.

    When the filename carries a hint (e.g. "117 BPM") that hint is what comes
    back, in all three of the cases below; ``source`` says how much detection
    had to say about it, and ``detected`` carries what was measured.

    ==================  ==========  ==========================================
    detection vs hint   ``source``  meaning
    ==================  ==========  ==========================================
    within 4%           confirmed   measured independently and agreed
    a harmonic of it    harmonic    found the right pulse, the wrong frame
    neither             label_only  could not corroborate the label at all
    no hint at all      detected    ``tempo`` is a measurement
    ==================  ==========  ==========================================

    Only the last row returns a number that was MEASURED; the rest return one
    that was READ. Callers must not describe a label-sourced tempo as
    detected, and must show ``detected`` — never ``tempo`` — when reporting
    what confirmed it, since ``tempo`` is by then the label itself.
    """
    # One envelope, used for both the tempo and the confidence below.
    # Detection is dominated by the cost of building this, so computing it
    # separately for each purpose doubles the price of every analysed file.
    onset_env = _onset_strength(y, sr)

    rms = float(np.sqrt(np.mean(y ** 2)))
    detected = 0.0 if rms < 1e-6 else _tempo_from_onset_env(onset_env, sr)

    # --- Onset confidence ---
    # Coefficient of variation of the onset envelope: high for percussive
    # content (clear rhythmic pulses), low for smooth/tonal content.
    if len(onset_env) > 0 and np.mean(onset_env) > 1e-10:
        cv = float(np.std(onset_env) / np.mean(onset_env))
    else:
        cv = 0.0

    # Map CV to a 0-1 confidence. Empirically:
    #   CV > 1.5 → strong percussive onsets → high confidence
    #   CV < 0.5 → smooth/tonal → low confidence
    #
    # Note this measures PERCUSSIVENESS, not correctness: a one-shot decaying
    # into silence scores the maximum while reporting a meaningless tempo. It
    # is not a quality gate and must not be used as one — duration is what
    # rejects one-shots.
    tempo_confidence = min(1.0, max(0.0, (cv - 0.3) / 1.2))

    if detected == 0.0:
        return TempoResult(0.0, tempo_confidence, SOURCE_DETECTED, 0.0)

    # --- Filename hint cross-reference ---
    #
    # Whenever a label exists the label is what gets returned. It is the
    # producer's statement about their own file; detection is an estimate.
    # When the two nearly agree the estimate adds CONFIDENCE, not PRECISION,
    # so it must not overwrite the statement — a 145 that measures 136 is a
    # file labelled 145, not a file at 136.
    #
    # Note the inversion this corrects. The harmonic branch already preferred
    # the label, in the case where detection was clearly wrong; the near-match
    # branch preferred the algorithm, in the case where detection was nearly
    # right. It trusted itself precisely where it was least justified.
    #
    # ``detected`` carries what was measured either way, so a caller that
    # wants to report the real number still can.
    hint_bpm = extract_bpm_from_filename(filename)
    if hint_bpm is not None and hint_bpm > 0:
        ratio = detected / hint_bpm

        # Agreement is decided first, and at a tighter tolerance than the
        # harmonic test. A tempo 4-8% off the label is neither agreement nor a
        # harmonic, so it falls through to "could not confirm" rather than
        # being claimed as either.
        if abs(ratio - 1.0) < AGREEMENT_TOLERANCE:
            return TempoResult(
                hint_bpm,
                min(1.0, tempo_confidence + 0.3),
                SOURCE_LABEL_CONFIRMED,
                detected,
            )

        # Detected is a harmonic — keep the filename hint. Detection did
        # independently find the right pulse and only got the frame wrong, so
        # this is partial corroboration; it is not the same claim as
        # agreement. The list stays permissive: a wider net here only keeps
        # the producer's label more often, which is the safe direction.
        harmonic_ratios = [0.5, 2.0 / 3.0, 1.5, 2.0]
        for hr in harmonic_ratios:
            if abs(ratio - hr) < 0.08:  # within ~8% tolerance
                return TempoResult(
                    hint_bpm, tempo_confidence, SOURCE_LABEL_HARMONIC, detected
                )

        # Detection disagrees entirely with the filename hint (not a
        # recognisable harmonic). Producers don't mislabel BPM, so trust
        # the explicit tag — but flag low confidence since the algorithm
        # couldn't confirm it independently.
        if 30.0 <= hint_bpm <= 300.0:
            return TempoResult(
                hint_bpm, min(tempo_confidence, 0.25), SOURCE_LABEL_ONLY, detected
            )

    return TempoResult(detected, tempo_confidence, SOURCE_DETECTED, detected)


# ---------------------------------------------------------------------------
# Chromagram (key detection)
# ---------------------------------------------------------------------------

def compute_chroma(
    y: np.ndarray,
    sr: int = 22050,
    n_fft: int = 4096,
    hop_length: int = 512,
) -> np.ndarray:
    """Compute 12-bin chromagram (pitch class energy distribution).

    Uses STFT with logarithmic frequency-to-chroma mapping. The larger
    ``n_fft`` (4096 vs 2048 for tempo) provides ~5.4 Hz resolution at
    sr=22050, adequate for distinguishing bass notes.

    Returns shape (12, T) matching ``librosa.feature.chroma_cqt``.
    """
    # Compute STFT power spectrum
    f, _, Zxx = scipy_stft(
        y,
        fs=sr,
        nperseg=n_fft,
        noverlap=n_fft - hop_length,
        window="hann",
    )
    power = np.abs(Zxx) ** 2

    # Build chroma filterbank: map each FFT bin to its pitch class
    n_bins = len(f)
    chroma_fb = np.zeros((12, n_bins))

    # Reference: C0 ~ 16.3516 Hz
    c0 = 16.3516
    min_freq = 32.0  # ignore below C1

    for i in range(n_bins):
        freq = f[i]
        if freq < min_freq:
            continue
        # Semitones above C0, mapped to pitch class 0-11
        semitones = 12.0 * np.log2(freq / c0)
        pitch_class = int(round(semitones)) % 12
        chroma_fb[pitch_class, i] += 1.0

    # Apply filterbank
    chroma = chroma_fb @ power  # shape: (12, T)

    # L2-normalise each time frame
    norms = np.sqrt(np.sum(chroma ** 2, axis=0, keepdims=True)) + 1e-10
    chroma = chroma / norms

    return chroma.astype(np.float32)


def key_confidence(chroma: np.ndarray) -> float:
    """Compute confidence ratio for key detection.

    Returns a value between 0.0 and 1.0 indicating how dominant the
    detected key is relative to other pitch classes.  A low value
    (< 0.6) suggests the detection may be unreliable — common with
    short transient-heavy samples or atonal content.

    The metric is: 1 - (second_best / best) of the summed chroma
    energy per pitch class.  A perfectly clear key yields ~1.0;
    uniformly distributed energy yields ~0.0.
    """
    energy = np.sum(chroma, axis=1)  # shape: (12,)
    if energy.max() < 1e-10:
        return 0.0
    sorted_energy = np.sort(energy)[::-1]
    if sorted_energy[0] < 1e-10:
        return 0.0
    return float(1.0 - sorted_energy[1] / sorted_energy[0])


# ---------------------------------------------------------------------------
# Duration (trivial)
# ---------------------------------------------------------------------------

def get_duration(y: np.ndarray, sr: int = 22050) -> float:
    """Get audio duration in seconds."""
    return len(y) / sr
