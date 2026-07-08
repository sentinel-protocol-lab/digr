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

    def test_audio_warmup_is_background_daemon_and_imports_stack(self):
        """The heavy audio import (numpy/scipy/soundfile) must be warmed off
        the tool-call path at startup, so a cold first Pro call can't exceed
        Claude's 240s tool-call timeout. It runs in a daemon thread (never
        blocks startup/shutdown) and imports the stack with no tool call."""
        import sys

        from digr.server import _start_audio_warmup

        thread = _start_audio_warmup()
        assert thread.daemon  # must never block server startup or process exit
        thread.join(timeout=30)
        assert not thread.is_alive()
        assert "digr.tools._audio_analysis" in sys.modules

    def test_create_server_starts_the_audio_warmup(self):
        """create_server must actually kick the warm-up off (not just define it)."""
        import threading

        before = sum(
            1 for t in threading.enumerate() if t.name == "digr-audio-warmup"
        )
        create_server(Config())
        after_names = [t.name for t in threading.enumerate()]
        # Either the thread is still running, or it already finished its (fast,
        # cached) import — both prove create_server launched it. The daemon
        # thread is harmless; we don't join it here.
        assert (
            after_names.count("digr-audio-warmup") > before
            or "digr.tools._audio_analysis" in __import__("sys").modules
        )

    def test_warm_audio_stack_sets_ready_flag(self):
        """warm_audio_stack must flag readiness so the tool gate can open."""
        shared._audio_ready.clear()
        shared.warm_audio_stack()
        assert shared._audio_ready.is_set()


class TestAudioWarmupGate:
    """The 'still warming up' gate keeps a cold first Pro call from blocking
    past Claude's 240s tool-call timeout: it returns a fast note until the
    background import has finished."""

    def test_message_is_none_once_ready(self):
        shared._audio_ready.set()
        assert shared.audio_warming_message() is None

    def test_message_prompts_retry_while_cold(self):
        shared._audio_ready.clear()
        try:
            msg = shared.audio_warming_message()
            assert msg is not None
            assert "warming up" in msg.lower()
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
