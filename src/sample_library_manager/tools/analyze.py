"""Analyze tools: analyze_sample, read_midi."""

from pathlib import Path

import mido

from ._shared import identify_library

_MIDI_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _require_librosa():
    """Import librosa and numpy, raising a clear error if not installed."""
    try:
        import librosa
        import numpy as np

        return librosa, np
    except ImportError:
        raise RuntimeError(
            "Audio analysis requires the 'audio' extras. "
            "Install with: pip install sample-library-manager[audio]"
        )


def _midi_num_to_name(note_num: int) -> str:
    """Convert MIDI note number to note name (e.g., 60 -> C3)."""
    octave = (note_num // 12) - 2
    return f"{_MIDI_NOTE_NAMES[note_num % 12]}{octave}"


def _ticks_to_bar_beat(ticks: int, ticks_per_beat: int, beats_per_bar: int = 4) -> str:
    """Convert absolute ticks to 1-indexed bar|beat notation."""
    total_beats = ticks / ticks_per_beat
    bar = int(total_beats // beats_per_bar) + 1
    beat_in_bar = (total_beats % beats_per_bar) + 1
    return f"{bar}|{beat_in_bar:.4g}"


async def analyze_sample(filepath: str) -> str:
    """Detect BPM and musical key of an audio sample.

    Returns tempo, estimated key, duration, and sample rate.
    Requires the [audio] extras (librosa).
    """
    librosa, np = _require_librosa()

    file_path = Path(filepath)

    if not file_path.exists():
        return f"ERROR: File not found at {filepath}"

    try:
        # Load audio file (analyze first 30 seconds for speed)
        y, sr = librosa.load(str(file_path), duration=30)

        # Detect BPM (librosa 0.11+ returns an array, extract the scalar)
        tempo_raw, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo = float(np.asarray(tempo_raw).item())

        # Detect key using chromagram analysis
        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        key_idx = int(np.argmax(np.sum(chroma, axis=1)))
        keys = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        detected_key = keys[key_idx]

        # Get duration
        duration = librosa.get_duration(y=y, sr=sr)

        # Determine which library this sample is from
        library_name = identify_library(file_path)

        result = f"Analysis of: {file_path.name}\n\n"
        result += f"BPM: {tempo:.1f}\n"
        result += f"Key: {detected_key} (estimated)\n"
        result += f"Duration: {duration:.1f} seconds\n"
        result += f"Sample Rate: {sr} Hz\n"
        result += f"Library: {library_name}\n"
        result += f"Path: {filepath}\n"

        return result

    except Exception as e:
        return f"ERROR analyzing {file_path.name}: {e}"


async def read_midi(filepath: str, track_index: int = 0) -> str:
    """Read a MIDI file and return its notes in bar|beat format.

    Returns file metadata (tempo, time signature, track names, total notes).
    Use track_index=-1 to list all tracks without reading notes.
    """
    file_path = Path(filepath)
    if not file_path.exists():
        return f"ERROR: File not found at {filepath}"

    if file_path.suffix.lower() not in (".mid", ".midi"):
        return f"ERROR: Not a MIDI file: {file_path.name}"

    try:
        mid = mido.MidiFile(str(file_path))
    except Exception as e:
        return f"ERROR reading MIDI file: {e}"

    tpb = mid.ticks_per_beat

    # Extract tempo and time signature from all tracks
    tempo_bpm = 120.0  # default
    time_sig_num = 4
    time_sig_den = 4
    for track in mid.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                tempo_bpm = mido.tempo2bpm(msg.tempo)
            elif msg.type == "time_signature":
                time_sig_num = msg.numerator
                time_sig_den = msg.denominator

    # If track_index == -1, just list tracks
    if track_index == -1:
        result = f"MIDI File: {file_path.name}\n"
        result += f"Tempo: {tempo_bpm:.1f} BPM\n"
        result += f"Time Signature: {time_sig_num}/{time_sig_den}\n"
        result += f"Ticks per beat: {tpb}\n"
        result += f"Length: {mid.length:.2f} seconds\n"
        result += f"Tracks: {len(mid.tracks)}\n\n"

        for i, track in enumerate(mid.tracks):
            note_count = sum(
                1 for m in track if m.type == "note_on" and m.velocity > 0
            )
            name = track.name or "(unnamed)"
            result += f"  Track {i}: {name} -- {note_count} notes\n"

        return result

    # Validate track index
    if track_index < 0 or track_index >= len(mid.tracks):
        return (
            f"ERROR: Track index {track_index} out of range. "
            f"File has {len(mid.tracks)} track(s) (0-{len(mid.tracks) - 1})."
        )

    track = mid.tracks[track_index]
    track_name = track.name or "(unnamed)"

    # Collect notes with absolute timing
    notes: list[tuple[int, int, int, int]] = []  # (start_tick, note_num, velocity, dur_ticks)
    abs_time = 0
    pending: dict[int, tuple[int, int]] = {}  # note_num -> (start_tick, velocity)

    for msg in track:
        abs_time += msg.time
        if msg.type == "note_on" and msg.velocity > 0:
            pending[msg.note] = (abs_time, msg.velocity)
        elif msg.type in ("note_off", "note_on") and (
            msg.type == "note_off" or msg.velocity == 0
        ):
            if msg.note in pending:
                start, vel = pending.pop(msg.note)
                dur = abs_time - start
                notes.append((start, msg.note, vel, dur))

    notes.sort(key=lambda x: (x[0], x[1]))

    # Build output
    result = f"MIDI File: {file_path.name}\n"
    result += f"Tempo: {tempo_bpm:.1f} BPM\n"
    result += f"Time Signature: {time_sig_num}/{time_sig_den}\n"
    result += f"Track {track_index}: {track_name} -- {len(notes)} notes\n"
    result += f"Length: {mid.length:.2f} seconds\n\n"

    if not notes:
        result += "No notes found in this track.\n"
        return result

    # Calculate clip length (next full bar after last note end)
    last_note_end = max(s + d for s, _, _, d in notes)
    total_beats = last_note_end / tpb
    total_bars = int(total_beats // time_sig_num) + (
        1 if total_beats % time_sig_num > 0 else 0
    )
    clip_length = f"{total_bars}:0.0"

    # Convert to bar|beat format
    ppal_notes = []
    for start_tick, note_num, vel, dur_ticks in notes:
        bar_beat = _ticks_to_bar_beat(start_tick, tpb, time_sig_num)
        dur_beats = dur_ticks / tpb
        note_name = _midi_num_to_name(note_num)
        ppal_notes.append(f"{bar_beat} v{vel} t{dur_beats:.4g} {note_name}")

    notes_str = "\n".join(ppal_notes)

    result += f"Suggested clip length: {clip_length}\n\n"
    result += f"Notes (bar|beat format):\n\n"
    result += notes_str
    result += "\n"

    return result
