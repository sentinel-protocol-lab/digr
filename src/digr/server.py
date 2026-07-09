"""FastMCP server definition with all tool registrations."""

from mcp.server.fastmcp import FastMCP

from .config import Config
from .tools._shared import set_libraries, set_license_key, warm_audio_stack
from .tools.analyze import analyze_sample, read_midi
from .tools.browse import (
    add_library,
    count_samples_in_folder,
    list_all_samples_in_folder,
    list_folders,
    list_libraries,
    remove_library,
)
from .tools.license import activate_license
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

    # Set libraries and license key for all tools to use
    set_libraries(config.libraries)
    set_license_key(config.license_key)

    # Warm the heavy audio stack (numpy/scipy/soundfile) NOW, synchronously, on
    # the MAIN thread -- before mcp.run() (in __main__) starts the asyncio event
    # loop. This blocks server creation for the few seconds the import takes,
    # which is deliberate: on the main thread the cold import is fast, but on a
    # background daemon thread it starves for the GIL against the idle stdio
    # event loop and can stall for MINUTES (observed on Windows: a 56-minute
    # idle stall that only finished once tool-call traffic woke the loop).
    # Paying it up front keeps it off the 240s tool-call path, so the customer's
    # first Pro call is instant. warm_audio_stack swallows an ImportError
    # (free-tier, no [audio] extras) and just flags ready, so this never blocks
    # or breaks a free install.
    warm_audio_stack()

    mcp = FastMCP(
        "digr",
        instructions=(
            "MCP server for searching, analyzing, and organizing audio sample libraries.\n\n"
            "SETUP:\n"
            "- If no libraries are configured, use add_library to add one first\n"
            "- The user can say a folder name and path, and you call add_library\n\n"
            "TOOL SEQUENCING:\n"
            "- Start with search_samples to find samples by keyword\n"
            "- Use collect_search_results AFTER search_samples (reads cached results)\n"
            "- Use analyze_sample for BPM/key detection on a specific file path\n"
            "- All organize tools (collect_samples, copy_samples, sort_samples, "
            "rename_with_metadata) use two-phase confirm: first call previews, "
            "second call with confirm=true executes\n"
            "- Use read_midi with track_index=-1 to list MIDI tracks before reading notes\n\n"
            "FILEPATHS: Pass as JSON array of strings for reliability.\n\n"
            "PRO TOOLS (require license key): analyze_sample, search_samples_by_bpm, "
            "read_midi, sort_samples, rename_with_metadata.\n\n"
            "ACTIVATION: If the user has a Pro license key (or pastes one when a Pro "
            "tool is blocked), call activate_license with that key. It saves the key "
            "and unlocks Pro immediately — no restart needed.\n\n"
            "KEYWORDS: Use simple terms (e.g., 'kick', 'snare 909'). "
            "Multiple words are AND-matched against the full file path."
        ),
    )

    # --- Search tools ---
    mcp.tool()(search_samples)
    mcp.tool()(search_samples_by_bpm)

    # --- Browse tools ---
    mcp.tool()(list_libraries)
    mcp.tool()(add_library)
    mcp.tool()(remove_library)
    mcp.tool()(list_folders)
    mcp.tool()(count_samples_in_folder)
    mcp.tool()(list_all_samples_in_folder)

    # --- License tools ---
    mcp.tool()(activate_license)

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
