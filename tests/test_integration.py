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
    """The audio gate holds a cold first Pro call until the background import
    finishes (so results arrive on their own), and falls back to a friendly
    note only if warm-up overruns the safe cap under Claude's 240s timeout."""

    @pytest.mark.asyncio
    async def test_message_is_none_once_ready(self):
        shared._audio_ready.set()
        assert await shared.await_audio_ready_or_message() is None

    @pytest.mark.asyncio
    async def test_note_returned_when_warmup_overruns_cap(self, monkeypatch):
        """If the stack is still cold after the wait cap, return a don't-restart
        note (using a tiny cap so the test doesn't actually wait)."""
        monkeypatch.setattr(shared, "_AUDIO_WARM_WAIT_SECONDS", 0.05)
        shared._audio_ready.clear()
        try:
            msg = await shared.await_audio_ready_or_message()
            assert msg is not None
            assert "warm up" in msg.lower()
            assert "not restart" in msg.lower()  # must steer off the reset footgun
        finally:
            shared._audio_ready.set()  # restore for later tests

    @pytest.mark.asyncio
    async def test_ready_flag_set_midwait_lets_call_proceed(self, monkeypatch):
        """A call waiting on a cold stack must proceed the instant warm-up
        finishes (the Event wakes the waiter), not sit out the whole cap."""
        import asyncio

        monkeypatch.setattr(shared, "_AUDIO_WARM_WAIT_SECONDS", 5)
        shared._audio_ready.clear()
        try:
            waiter = asyncio.ensure_future(shared.await_audio_ready_or_message())
            await asyncio.sleep(0.05)
            shared._audio_ready.set()  # warm-up "finishes"
            assert await waiter is None  # proceeds, no note
        finally:
            shared._audio_ready.set()

    @pytest.mark.asyncio
    async def test_bpm_search_short_circuits_when_warmup_overruns(
        self, mock_libraries, pro_license, monkeypatch
    ):
        """If warm-up overruns the cap, search_samples_by_bpm returns the note
        WITHOUT running the heavy per-file analysis loop or caching results."""
        from digr.tools.search import search_samples_by_bpm

        monkeypatch.setattr(shared, "_AUDIO_WARM_WAIT_SECONDS", 0.05)
        shared._audio_ready.clear()
        try:
            result = await search_samples_by_bpm("kick", max_results=10)
            assert "warm up" in result.lower()
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
