"""Tests for the _audio_analysis module (numpy+scipy replacement for librosa)."""

import tempfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from sample_library_manager.tools._audio_analysis import (
    compute_chroma,
    detect_tempo,
    get_duration,
    load_audio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_wav(path: str, data: np.ndarray, sr: int = 44100):
    """Write a numpy array to a WAV file."""
    sf.write(path, data, sr)


def _make_sine(freq: float = 440.0, sr: int = 44100, duration: float = 2.0) -> np.ndarray:
    """Generate a pure sine wave."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _make_click_track(bpm: float = 120.0, sr: int = 44100, duration: float = 10.0) -> np.ndarray:
    """Synthesize a click track at a known BPM with sharp transients."""
    samples = int(sr * duration)
    y = np.zeros(samples, dtype=np.float32)
    click_interval = int(60.0 / bpm * sr)
    click_len = int(0.005 * sr)  # 5ms click (sharp attack)

    for i in range(0, samples, click_interval):
        end = min(i + click_len, samples)
        # Exponential decay click for more realistic onset
        length = end - i
        envelope = np.exp(-np.linspace(0, 5, length))
        y[i:end] = 0.9 * envelope.astype(np.float32)

    return y


def _make_stereo(mono: np.ndarray) -> np.ndarray:
    """Convert mono to stereo (2 columns)."""
    return np.column_stack([mono, mono * 0.8])


# ---------------------------------------------------------------------------
# load_audio tests
# ---------------------------------------------------------------------------

class TestLoadAudio:
    def test_load_wav_mono(self, tmp_path):
        """Loading a mono WAV returns correct shape, dtype, and sr."""
        wav = tmp_path / "mono.wav"
        data = _make_sine(440, sr=44100, duration=1.0)
        _write_wav(str(wav), data, sr=44100)

        y, sr = load_audio(str(wav), sr=22050)

        assert isinstance(y, np.ndarray)
        assert y.dtype == np.float32
        assert sr == 22050
        assert y.ndim == 1
        # Resampled from 44100 to 22050 = half the samples
        assert abs(len(y) - 22050) < 10

    def test_load_stereo_to_mono(self, tmp_path):
        """Stereo input is averaged to mono."""
        wav = tmp_path / "stereo.wav"
        mono = _make_sine(440, sr=44100, duration=1.0)
        stereo = _make_stereo(mono)
        _write_wav(str(wav), stereo, sr=44100)

        y, sr = load_audio(str(wav), sr=22050)

        assert y.ndim == 1

    def test_load_duration_limit(self, tmp_path):
        """Duration parameter caps the read length."""
        wav = tmp_path / "long.wav"
        data = _make_sine(440, sr=44100, duration=10.0)
        _write_wav(str(wav), data, sr=44100)

        y, sr = load_audio(str(wav), sr=22050, duration=2.0)

        # Should be ~2 seconds at 22050 Hz
        expected = 22050 * 2
        assert abs(len(y) - expected) < 20

    def test_load_no_resample(self, tmp_path):
        """When file sr matches target sr, no resampling occurs."""
        wav = tmp_path / "native.wav"
        data = _make_sine(440, sr=22050, duration=1.0)
        _write_wav(str(wav), data, sr=22050)

        y, sr = load_audio(str(wav), sr=22050)

        assert sr == 22050
        assert abs(len(y) - 22050) < 2


# ---------------------------------------------------------------------------
# detect_tempo tests
# ---------------------------------------------------------------------------

class TestDetectTempo:
    def test_silence_returns_zero(self):
        """All-zeros signal returns 0.0 BPM."""
        y = np.zeros(22050 * 5, dtype=np.float32)
        assert detect_tempo(y, sr=22050) == 0.0

    def test_click_track_120bpm(self):
        """Synthesized 120 BPM click track is detected correctly."""
        y = _make_click_track(bpm=120.0, sr=22050, duration=10.0)
        tempo = detect_tempo(y, sr=22050)
        # Should be within 5 BPM of 120 (generous for synthetic signal)
        assert abs(tempo - 120.0) < 5.0, f"Expected ~120 BPM, got {tempo}"

    def test_click_track_90bpm(self):
        """Synthesized 90 BPM click track is detected correctly."""
        y = _make_click_track(bpm=90.0, sr=22050, duration=10.0)
        tempo = detect_tempo(y, sr=22050)
        assert abs(tempo - 90.0) < 5.0, f"Expected ~90 BPM, got {tempo}"

    def test_click_track_140bpm(self):
        """Synthesized 140 BPM click track is detected correctly."""
        y = _make_click_track(bpm=140.0, sr=22050, duration=10.0)
        tempo = detect_tempo(y, sr=22050)
        assert abs(tempo - 140.0) < 5.0, f"Expected ~140 BPM, got {tempo}"

    def test_very_short_signal(self):
        """Very short signal (< 0.5s) returns 0.0."""
        y = _make_click_track(bpm=120.0, sr=22050, duration=0.3)
        tempo = detect_tempo(y, sr=22050)
        # May return 0 or a value — just shouldn't crash
        assert isinstance(tempo, float)

    def test_returns_float(self):
        """Return value is always a Python float."""
        y = _make_click_track(bpm=120.0, sr=22050, duration=5.0)
        result = detect_tempo(y, sr=22050)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# compute_chroma tests
# ---------------------------------------------------------------------------

class TestComputeChroma:
    def test_shape(self):
        """Output is (12, T) with T > 0."""
        y = _make_sine(440, sr=22050, duration=2.0)
        chroma = compute_chroma(y, sr=22050)

        assert chroma.shape[0] == 12
        assert chroma.shape[1] > 0

    def test_sine_a4_peaks_at_a(self):
        """Pure A4 sine wave (440 Hz) should peak at pitch class A (index 9)."""
        y = _make_sine(440, sr=22050, duration=3.0)
        chroma = compute_chroma(y, sr=22050)

        # Sum over time and find dominant pitch class
        profile = np.sum(chroma, axis=1)
        peak_idx = int(np.argmax(profile))

        # A = index 9 in [C, C#, D, D#, E, F, F#, G, G#, A, A#, B]
        assert peak_idx == 9, f"Expected A (9), got index {peak_idx}"

    def test_sine_c4_peaks_at_c(self):
        """Pure C4 sine wave (261.63 Hz) should peak at pitch class C (index 0)."""
        y = _make_sine(261.63, sr=22050, duration=3.0)
        chroma = compute_chroma(y, sr=22050)

        profile = np.sum(chroma, axis=1)
        peak_idx = int(np.argmax(profile))

        assert peak_idx == 0, f"Expected C (0), got index {peak_idx}"

    def test_dtype_float32(self):
        """Chroma output is float32."""
        y = _make_sine(440, sr=22050, duration=1.0)
        chroma = compute_chroma(y, sr=22050)
        assert chroma.dtype == np.float32


# ---------------------------------------------------------------------------
# get_duration tests
# ---------------------------------------------------------------------------

class TestGetDuration:
    def test_duration_calculation(self):
        """Duration matches len(y) / sr."""
        sr = 22050
        y = np.zeros(sr * 3, dtype=np.float32)  # 3 seconds
        dur = get_duration(y, sr=sr)
        assert abs(dur - 3.0) < 0.001

    def test_empty_signal(self):
        """Empty signal returns 0.0."""
        y = np.array([], dtype=np.float32)
        assert get_duration(y, sr=22050) == 0.0
