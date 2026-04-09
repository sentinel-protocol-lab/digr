"""Audio analysis engine: BPM detection, key detection, audio loading.

Replaces the librosa dependency with numpy + scipy + soundfile for universal
cross-platform compatibility. The algorithms are ported from librosa's approach
(mel-spectrogram onset strength, autocorrelation tempogram, STFT chromagram)
to maintain equivalent accuracy without the numba/llvmlite dependency chain.
"""

import re
from math import gcd

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly, stft as scipy_stft


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

    onset_env = _onset_strength(y, sr)

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

    # Multipliers to check: covers octave (2×), half (0.5×), and
    # third-harmonic relationships (3/2× maps 112→168 ≈ 170 BPM)
    for multiplier in [2.0, 1.5, 0.5, 2.0 / 3.0]:
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
    common_tempos = [85, 90, 100, 110, 120, 128, 140, 150, 160, 170, 174, 180]

    def _musical_distance(bpm: float) -> float:
        return min(abs(bpm - ct) for ct in common_tempos)

    tempo = min(candidate_tempos, key=_musical_distance)

    return round(tempo, 1)


def detect_tempo_with_hint(
    y: np.ndarray,
    sr: int = 22050,
    filename: str = "",
) -> tuple[float, float]:
    """Detect BPM with optional filename hint cross-reference.

    Returns (tempo, confidence) where confidence is 0.0-1.0.

    If the filename contains a BPM hint (e.g. "117 BPM"), the detected
    tempo is compared against it. If detection lands on a harmonic of
    the hint (half, double, 2/3, 3/2), the hint is preferred. This
    corrects for autocorrelation's tendency to lock onto sub-harmonics
    in vocals and other non-percussive content.
    """
    detected = detect_tempo(y, sr)

    # --- Onset confidence ---
    # Coefficient of variation of the onset envelope: high for percussive
    # content (clear rhythmic pulses), low for smooth/tonal content.
    onset_env = _onset_strength(y, sr)
    if len(onset_env) > 0 and np.mean(onset_env) > 1e-10:
        cv = float(np.std(onset_env) / np.mean(onset_env))
    else:
        cv = 0.0

    # Map CV to a 0-1 confidence. Empirically:
    #   CV > 1.5 → strong percussive onsets → high confidence
    #   CV < 0.5 → smooth/tonal → low confidence
    tempo_confidence = min(1.0, max(0.0, (cv - 0.3) / 1.2))

    if detected == 0.0:
        return 0.0, tempo_confidence

    # --- Filename hint cross-reference ---
    hint_bpm = extract_bpm_from_filename(filename)
    if hint_bpm is not None and hint_bpm > 0:
        # Check if detected is a harmonic of the hint
        ratio = detected / hint_bpm
        harmonic_ratios = [0.5, 2.0 / 3.0, 1.0, 1.5, 2.0]
        for hr in harmonic_ratios:
            if abs(ratio - hr) < 0.08:  # within ~8% tolerance
                if abs(hr - 1.0) > 0.01:
                    # Detected is a harmonic — prefer the filename hint
                    return hint_bpm, tempo_confidence
                else:
                    # Detected matches hint directly — boost confidence
                    tempo_confidence = min(1.0, tempo_confidence + 0.3)
                    return detected, tempo_confidence

        # Detection disagrees entirely with the filename hint (not a
        # recognisable harmonic). Producers don't mislabel BPM, so trust
        # the explicit tag — but flag low confidence since the algorithm
        # couldn't confirm it independently.
        if 30.0 <= hint_bpm <= 300.0:
            return hint_bpm, min(tempo_confidence, 0.25)

    return detected, tempo_confidence


def extract_bpm_from_filename(filename: str) -> float | None:
    """Extract BPM value from a filename if present.

    Matches patterns like "170 bpm", "117BPM", "170_bpm", "bpm_170",
    "BPM 117", and leading-number formats like "120-BreakName".
    Returns None if no BPM pattern is found.
    """
    if not filename:
        return None

    # Strip extension for cleaner matching
    name = re.sub(r'\.[^.]+$', '', filename)

    # Pattern 1: number followed by "bpm" (with optional separator)
    match = re.search(r'(\d{2,3})\s*[-_]?\s*bpm', name, re.IGNORECASE)
    if match:
        return float(match.group(1))

    # Pattern 2: "bpm" followed by number
    match = re.search(r'bpm\s*[-_]?\s*(\d{2,3})', name, re.IGNORECASE)
    if match:
        return float(match.group(1))

    # Pattern 3: leading number followed by separator then text
    # e.g. "120-GitterBreak", "140_HouseLoop", "170 DnB Roller"
    # Only match if the number is in plausible BPM range (60-300)
    match = re.match(r'^(\d{2,3})[-_\s]', name)
    if match:
        bpm = float(match.group(1))
        if 60 <= bpm <= 300:
            return bpm

    return None


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
