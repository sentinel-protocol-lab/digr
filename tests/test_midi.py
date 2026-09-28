"""Tests for read_midi's tempo reporting.

read_midi has no broader test suite yet -- this file exists to cover the
tempo-fallback-labelling fix (a file with no set_tempo message reported
"Tempo: 120.0 BPM" indistinguishably from a real reading).
"""

import mido
import pytest

from digr.tools.analyze import read_midi


def _build_midi(path, tempo_bpm=None, time_sig=None):
    mid = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    mid.tracks.append(track)
    if tempo_bpm is not None:
        track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo_bpm), time=0))
    if time_sig is not None:
        num, den = time_sig
        track.append(mido.MetaMessage("time_signature", numerator=num, denominator=den, time=0))
    track.append(mido.Message("note_on", note=60, velocity=100, time=0))
    track.append(mido.Message("note_off", note=60, velocity=0, time=480))
    mid.save(str(path))
    return path


@pytest.mark.asyncio
async def test_missing_tempo_is_labelled_not_read_from_file(tmp_path):
    path = _build_midi(tmp_path / "no_tempo.mid")

    result = await read_midi(str(path), track_index=-1)

    assert "not set in file" in result
    assert "Tempo: 120.0 BPM\n" not in result


@pytest.mark.asyncio
async def test_missing_tempo_is_labelled_on_the_notes_path_too(tmp_path):
    """track_index=-1 and a real track index print the tempo line separately --
    both call sites must carry the fix, not just the one for listing tracks."""
    path = _build_midi(tmp_path / "no_tempo.mid")

    result = await read_midi(str(path), track_index=0)

    assert "not set in file" in result


@pytest.mark.asyncio
async def test_real_tempo_is_reported_plainly(tmp_path):
    path = _build_midi(tmp_path / "has_tempo.mid", tempo_bpm=140.0, time_sig=(4, 4))

    result = await read_midi(str(path), track_index=-1)

    assert "Tempo: 140.0 BPM\n" in result
    assert "Tempo: not set in file" not in result


@pytest.mark.asyncio
async def test_missing_time_signature_is_labelled_not_read_from_file(tmp_path):
    path = _build_midi(tmp_path / "no_timesig.mid")

    result = await read_midi(str(path), track_index=-1)

    assert "Time Signature: not set in file (MIDI default of 4/4)" in result
    assert "Time Signature: 4/4\n" not in result


@pytest.mark.asyncio
async def test_missing_time_signature_is_labelled_on_the_notes_path_too(tmp_path):
    path = _build_midi(tmp_path / "no_timesig.mid")

    result = await read_midi(str(path), track_index=0)

    assert "Time Signature: not set in file (MIDI default of 4/4)" in result


@pytest.mark.asyncio
async def test_real_time_signature_is_reported_plainly(tmp_path):
    path = _build_midi(tmp_path / "has_timesig.mid", tempo_bpm=140.0, time_sig=(3, 4))

    result = await read_midi(str(path), track_index=-1)

    assert "Time Signature: 3/4\n" in result
    assert "Time Signature: not set in file" not in result
