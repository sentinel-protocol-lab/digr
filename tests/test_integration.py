"""Integration tests: multi-tool workflows, server creation, Pro gating in context."""

import pytest

from digr.config import Config
from digr.server import create_server
import digr.tools._shared as shared
from digr.tools._shared import (
    get_last_search_results,
    set_license_key,
)
from digr.tools.organize import (
    collect_samples,
    collect_search_results,
    sort_samples,
)
from digr.tools.search import search_samples


class TestServerCreation:
    """Test that the server boots correctly with different configs."""

    def test_create_server_empty_config(self):
        mcp = create_server(Config())
        assert mcp is not None
        assert mcp.name == "digr"

    def test_create_server_with_libraries(self, sample_dir):
        config = Config(libraries={"Test": sample_dir})
        mcp = create_server(config)
        assert mcp is not None

    def test_create_server_with_license_key(self):
        # Verification is lazy, so server creation must not touch the network.
        config = Config(license_key="A1B2C3D4-E5F60718-9ABCDEF0-1234ABCD")
        mcp = create_server(config)
        assert mcp is not None

    def test_create_server_does_not_warm_audio_stack_itself(self):
        """create_server() must only WIRE UP the warm-up (via the FastMCP
        lifespan) -- it must not run the heavy numpy/scipy/soundfile import
        itself. Running it inline here would put us back to blocking the
        caller (and, in production, the MCP `initialize` handshake) on the
        cold import, which is the exact bug this design avoids: a customer
        on old/slow hardware hit a cold import slow enough that Claude
        Desktop's own connect timeout fired first, and Claude gave up before
        the server ever answered `initialize` ("could not attach to MCP
        server")."""
        shared._audio_ready.clear()

        create_server(Config())

        assert not shared._audio_ready.is_set()

    @pytest.mark.asyncio
    async def test_lifespan_warms_audio_stack_without_delaying_the_handshake(self):
        """_audio_warmup_lifespan must let its caller (the MCP request loop,
        which answers `initialize`) proceed immediately, THEN warm the audio
        stack -- on the MAIN thread, so no background-thread GIL contention
        with the idle event loop (the separately diagnosed and fixed cause of
        the earlier minutes-long stalls)."""
        from digr.server import _audio_warmup_lifespan

        shared._audio_ready.clear()
        mcp = create_server(Config())

        async with _audio_warmup_lifespan(mcp):
            # Entering must not itself wait for the import -- this is what
            # lets `initialize` get answered even if the import takes minutes.
            assert not shared._audio_ready.is_set()

        # Exiting waits for the scheduled warm-up task, so by here it's done.
        assert shared._audio_ready.is_set()

    def test_warm_audio_stack_sets_ready_flag(self):
        """warm_audio_stack must flag readiness so the tool gate can open."""
        shared._audio_ready.clear()
        shared.warm_audio_stack()
        assert shared._audio_ready.is_set()


class TestAudioWarmupGate:
    """The 'still warming up' gate keeps a cold first Pro call from blocking
    past Claude's 240s tool-call timeout: it returns a fast note until the
    background import has finished. It's a single instant check -- never a
    wait -- because an in-process wait can stall on the GIL while the warm-up
    thread is mid-import, silently degrading into the exact hang it prevents."""

    def test_message_is_none_once_ready(self):
        shared._audio_ready.set()
        assert shared.audio_warming_message() is None

    def test_message_prompts_retry_while_cold(self):
        shared._audio_ready.clear()
        try:
            msg = shared.audio_warming_message()
            assert msg is not None
            assert "warming up" in msg.lower()
            assert "do not" in msg.lower()  # must steer off the restart footgun
        finally:
            shared._audio_ready.set()  # restore for later tests

    @pytest.mark.asyncio
    async def test_bpm_search_short_circuits_while_cold(self, mock_libraries, pro_license):
        """While the audio stack is cold, search_samples_by_bpm returns the
        warming note WITHOUT running the heavy per-file analysis loop."""
        from digr.tools.search import search_samples_by_bpm

        shared._audio_ready.clear()
        try:
            result = await search_samples_by_bpm("kick", max_results=10)
            assert "warming up" in result.lower()
            # It bailed out before caching any results.
            assert get_last_search_results() == []
        finally:
            shared._audio_ready.set()  # restore for later tests


class TestSearchThenCollectWorkflow:
    """Integration: search_samples -> collect_search_results (most common workflow)."""

    @pytest.mark.asyncio
    async def test_search_populates_cache(self, mock_libraries):
        result = await search_samples("kick", max_results=10)
        assert "kick" in result.lower()
        cached = get_last_search_results()
        assert len(cached) > 0

    @pytest.mark.asyncio
    async def test_collect_without_search_shows_hint(self, mock_libraries):
        # Don't call search_samples first
        result = await collect_search_results("1", "/tmp/test_dest", confirm=False)
        assert "ERROR" in result
        assert "search_samples" in result
        assert "Hint" in result

    @pytest.mark.asyncio
    async def test_search_then_collect_preview(self, mock_libraries, tmp_path):
        await search_samples("kick", max_results=5)
        dest = str(tmp_path / "collected")
        result = await collect_search_results("1,2", dest, confirm=False)
        assert "PREVIEW" in result

    @pytest.mark.asyncio
    async def test_search_then_collect_execute(self, mock_libraries, tmp_path):
        await search_samples("kick", max_results=5)
        dest = str(tmp_path / "collected")
        result = await collect_search_results("1", dest, confirm=True)
        assert "Copied 1/1" in result
        assert (tmp_path / "collected").exists()

    @pytest.mark.asyncio
    async def test_search_no_results_shows_hint(self, mock_libraries):
        result = await search_samples("zzz_nonexistent_xyz")
        assert "Hint" in result
        assert "list_libraries" in result


class TestCollectSamplesWorkflow:
    """Integration: collect_samples preview -> execute."""

    @pytest.mark.asyncio
    async def test_collect_preview_then_execute(self, mock_libraries, tmp_path):
        dest = str(tmp_path / "dest")

        # Preview
        preview = await collect_samples("kick", dest, max_results=5, confirm=False)
        assert "PREVIEW" in preview
        assert not (tmp_path / "dest").exists()

        # Execute
        result = await collect_samples("kick", dest, max_results=5, confirm=True)
        assert "Copied" in result
        assert (tmp_path / "dest").exists()


class TestProGatingInWorkflow:
    """Integration: verify Pro tools are gated in realistic workflows."""

    @pytest.mark.asyncio
    async def test_sort_blocked_without_license(self, mock_libraries, tmp_path):
        original = shared.ENFORCE_LICENSE_GATE
        shared.ENFORCE_LICENSE_GATE = True
        try:
            set_license_key(None)
            dest = str(tmp_path / "sorted")
            result = await sort_samples("kick", dest, confirm=False)
            assert "Pro feature" in result
            assert "sort_samples" in result
            assert not (tmp_path / "sorted").exists()
        finally:
            shared.ENFORCE_LICENSE_GATE = original

    @pytest.mark.asyncio
    async def test_sort_works_with_license(self, mock_libraries, pro_license, tmp_path):
        dest = str(tmp_path / "sorted")
        result = await sort_samples("wav", dest, confirm=False)
        assert "PREVIEW" in result
        assert "Kicks" in result


class TestAnalyzeSampleReportsNativeMetadata:
    """analyze_sample must report the file's TRUE sample rate and duration,
    read from the header -- not the internal analysis buffer, which is always
    resampled to 22050 Hz and capped at the first 30 seconds. Regression guard
    for the bug where both fields reflected the analysis buffer, not the asset."""

    @pytest.mark.asyncio
    async def test_reports_native_rate_and_duration_not_analysis_buffer(self, tmp_path, pro_license):
        import numpy as np
        import soundfile as sf

        from digr.tools.analyze import analyze_sample

        # 48 kHz AND longer than the 30s cap, so BOTH fields would be wrong
        # (22050 Hz / 30.0s) if they were read from the analysis buffer.
        wav = tmp_path / "native_48k_32s.wav"
        sr_native = 48000
        seconds = 32.0
        t = np.linspace(0, seconds, int(sr_native * seconds), endpoint=False)
        tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        sf.write(str(wav), tone, sr_native)

        result = await analyze_sample(str(wav))

        assert "Sample Rate: 48000 Hz" in result # true rate, not 22050
        assert "22050 Hz" not in result          # the old, wrong value
        assert "Duration: 32.0 seconds" in result # true length, not capped at 30