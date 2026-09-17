"""Tests for analyze_sample's handling of Ableton's undecodable AIFF codec.

analyze_sample has no broader unit test suite yet -- this file exists only to
cover the codec-detection behaviour added alongside the rest of the AIFF fix.
"""

import pytest

from digr.tools.analyze import analyze_sample


@pytest.mark.asyncio
async def test_analyze_names_the_codec_instead_of_leaking_a_decode_error(
    pro_license, tmp_path, write_ableton_aifc
):
    """The old behaviour let libsndfile's raw string through as
    'ERROR analyzing loop.aif: File contains data in an unimplemented
    format.' -- internal, unexplained, no actionable cause."""
    path = write_ableton_aifc(tmp_path / "loop.aif")

    result = await analyze_sample(str(path))

    assert "loop.aif" in result
    assert "Ableton" in result
    assert "unimplemented format" not in result
    assert "ERROR analyzing" not in result


@pytest.mark.asyncio
async def test_analyze_still_works_on_a_decodable_aifc_file(
    pro_license, tmp_path, write_ableton_aifc
):
    """Sanity check the other side of the gate: a merely-AIFC (not
    able-coded) file must not be caught by the same check and blocked."""
    import numpy as np
    import soundfile as sf

    path = tmp_path / "tone.aif"
    sr = 22050
    t = np.linspace(0, 1.0, sr, endpoint=False)
    sf.write(
        str(path),
        (0.5 * np.sin(2 * np.pi * 440 * t)).astype("float32"),
        sr,
        format="AIFF",
    )

    result = await analyze_sample(str(path))

    assert "Ableton" not in result
    assert "BPM" in result
