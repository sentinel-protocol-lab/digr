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
        config = Config(license_key="DIGR-PRO-test1234-demo")
        mcp = create_server(config)
        assert mcp is not None


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
    async def test_sort_works_with_license(self, mock_libraries, tmp_path):
        set_license_key("DIGR-PRO-abcd1234-test")
        dest = str(tmp_path / "sorted")
        result = await sort_samples("wav", dest, confirm=False)
        assert "PREVIEW" in result
        assert "Kicks" in result
