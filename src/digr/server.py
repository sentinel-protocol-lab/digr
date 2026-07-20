"""FastMCP server definition with all tool registrations."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
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

# How long the warm-up task waits before it starts the heavy import, so the
# transport gets a clear head start on answering the client's `initialize`
# handshake first. See _audio_warmup_lifespan for the full reasoning.
_HANDSHAKE_HEAD_START_SECONDS = 0.5


@asynccontextmanager
async def _audio_warmup_lifespan(_app: FastMCP) -> AsyncIterator[dict]:
    """Warm the audio stack AFTER the transport starts, not before it.

    Entering this context manager must NOT wait for the import: it schedules
    the warm-up as a task in its own task group and yields immediately, so
    the caller (the MCP server's request loop) starts reading stdio and can
    answer `initialize` right away. If we blocked here instead, a slow cold
    import would delay `initialize` itself -- and a real customer hit
    exactly that: on a from-scratch venv on old/slow hardware the import ran
    past Claude Desktop's own connect-handshake timeout (~60s) and Claude
    gave up before the server ever answered, showing "could not attach to
    MCP server" with no obvious recovery step.

    The warm-up still runs on the MAIN thread (no daemon thread, no GIL
    contention with the idle event loop -- that was the earlier, separately
    diagnosed and fixed bug: a background thread starves for the GIL while
    the loop is parked and can stall for minutes). It's the same single
    event-loop thread that answers `initialize`; the short head-start sleep
    just gives the request loop a turn to run first. Once the import starts
    it does monopolize that thread until it finishes (it has no internal
    await points), so any request arriving mid-import queues briefly --
    `initialize` is what has a tight client-side timeout, so getting that
    one out first is what matters. Pro tool calls that land before the
    import is done still hit the existing audio_warming_message() gate.
    """
    async with anyio.create_task_group() as tg:
        tg.start_soon(_warm_up_after_handshake)
        yield {}


async def _warm_up_after_handshake() -> None:
    await anyio.sleep(_HANDSHAKE_HEAD_START_SECONDS)
    warm_audio_stack()


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

    mcp = FastMCP(
        "digr",
        lifespan=_audio_warmup_lifespan,
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
