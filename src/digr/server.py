"""FastMCP server definition with all tool registrations."""

import threading

from mcp.server.fastmcp import FastMCP

from .config import Config
from .tools._shared import set_libraries, set_license_key
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


def _start_audio_warmup() -> threading.Thread:
    """Import the heavy audio stack in a background thread at startup.

    numpy/scipy/soundfile are ~46 MB of native libraries that Pro tools load
    lazily on their first call (see ``_require_audio`` in tools/search.py and
    tools/analyze.py). On a fresh Windows process that first cold load can take
    MINUTES — antivirus scans each freshly-read DLL — which blows Claude
    Desktop's hard 240-second tool-call timeout on the customer's very first
    BPM search (confirmed against the MCP log: first call 4:12, retry 0.8s).

    Warming the import here moves that one-time cost off the timed tool-call
    path and into the idle window right after startup. Python's per-module
    import lock coordinates for us: if a Pro call arrives mid-warm-up it simply
    waits on the same import and pays only the remaining time — no double work.

    Daemon thread so it never blocks startup or process exit. If the audio
    extras aren't installed (free-tier), the import fails and we do nothing —
    the Pro gate already handles that at call time.
    """

    def _warm() -> None:
        try:
            from .tools import _audio_analysis  # noqa: F401  (import IS the work)
            import numpy  # noqa: F401
        except Exception:
            pass  # free-tier (no audio extras) or transient — safe to ignore

    thread = threading.Thread(target=_warm, name="digr-audio-warmup", daemon=True)
    thread.start()
    return thread


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

    # Kick off the heavy audio-stack import now, in the background, so a slow
    # cold load can't stall the customer's first Pro tool call past Claude's
    # 240s timeout. Started before FastMCP setup to maximise the head start.
    _start_audio_warmup()

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
