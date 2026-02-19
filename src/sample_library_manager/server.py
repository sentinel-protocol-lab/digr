"""FastMCP server definition with all tool registrations."""

from mcp.server.fastmcp import FastMCP

from .config import Config
from .tools._shared import set_libraries
from .tools.analyze import analyze_sample, read_midi
from .tools.browse import (
    count_samples_in_folder,
    list_all_samples_in_folder,
    list_folders,
    list_libraries,
)
from .tools.organize import (
    collect_samples,
    collect_search_results,
    copy_samples,
    rename_with_metadata,
    sort_samples,
)
from .tools.search import search_samples, search_samples_by_bpm


def create_server(config: Config | None = None) -> FastMCP:
    """Create and configure the FastMCP server with all tools.

    Args:
        config: Server configuration with library paths. If None, uses empty config.
    """
    if config is None:
        config = Config()

    # Set libraries for all tools to use
    set_libraries(config.libraries)

    mcp = FastMCP(
        "sample-library-manager",
        instructions=(
            "MCP server for searching, analyzing, and organizing audio sample libraries. "
            "Provides tools to search across multiple configured sample library locations, "
            "detect BPM and musical key, read MIDI files, and organize samples into folders."
        ),
    )

    # --- Search tools ---
    mcp.tool()(search_samples)
    mcp.tool()(search_samples_by_bpm)

    # --- Browse tools ---
    mcp.tool()(list_libraries)
    mcp.tool()(list_folders)
    mcp.tool()(count_samples_in_folder)
    mcp.tool()(list_all_samples_in_folder)

    # --- Analyze tools ---
    mcp.tool()(analyze_sample)
    mcp.tool()(read_midi)

    # --- Organize tools ---
    mcp.tool()(collect_samples)
    mcp.tool()(copy_samples)
    mcp.tool()(collect_search_results)
    mcp.tool()(rename_with_metadata)
    mcp.tool()(sort_samples)

    return mcp
