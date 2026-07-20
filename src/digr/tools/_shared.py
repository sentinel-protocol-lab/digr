"""Shared utilities for all tools: search engine, file helpers, state cache, license gating."""

import json
import shutil
import sys
import threading
import time
from pathlib import Path

# Supported audio and MIDI file extensions
AUDIO_EXTENSIONS = ["*.wav", "*.aif", "*.aiff", "*.mp3", "*.flac", "*.ogg"]
MIDI_EXTENSIONS = ["*.mid", "*.midi"]
ALL_EXTENSIONS = AUDIO_EXTENSIONS + MIDI_EXTENSIONS

# Cache for last search results so collect_search_results can reference them by index
_last_search_results: list[tuple[str, str]] = []  # [(path, library_name), ...]

# Libraries dict set at server startup from config
_libraries: dict[str, Path] = {}

# --- License gate configuration ---
# When True, Pro tools require a Gumroad-verified license (see digr/licensing.py).
ENFORCE_LICENSE_GATE = True

# --- License key state ---
_license_key: str | None = None
# Memoized (licensed, reason_if_not) from licensing.activate_or_check, so the
# network is consulted at most once per server run.
_license_status: tuple[bool, str | None] | None = None


# --- Audio stack warm-up state ---
# The Pro audio tools (analyze_sample, search_samples_by_bpm, rename_with_metadata)
# need numpy/scipy/soundfile. Importing that stack is only a few seconds on the
# MAIN thread -- but where and when the import happens matters enormously:
#   * lazily, on the first Pro call -> it sits on Claude Desktop's 240s tool-call
#     path and a slow cold load blows the timeout (first BPM search hangs);
#   * on a BACKGROUND daemon thread -> a C-extension import there starves for the
#     GIL against the idle asyncio/stdio loop and can stall for MINUTES (observed
#     on Windows: a 56-minute idle stall that only finished once tool-call
#     traffic woke the loop). This is the real cause of the "cold BPM hang" saga
#     -- NOT antivirus; the same import is ~seconds on the main thread.
#   * synchronously BEFORE the transport starts reading stdio -> a slow cold
#     import (old/cold hardware) delays the `initialize` reply past the
#     client's own connect-handshake timeout, and the client gives up before
#     the server ever answers -- observed for real on a customer Mac ("could
#     not attach to MCP server").
#
# So the import is done ONCE, SYNCHRONOUSLY, on the MAIN thread, but scheduled
# to start just AFTER the transport is already up -- see server.py's
# _audio_warmup_lifespan, which lets `initialize` get answered first and then
# runs warm_audio_stack() as a lifespan task. Two pieces live here:
#   1. warm_audio_stack() does the main-thread import, times it, and sets
#      _audio_ready.
#   2. audio_warming_message() is a belt-and-suspenders gate: if a Pro call
#      arrives before _audio_ready is set (the import is still running, or a
#      request queued up behind it) it returns a fast "still warming up" note
#      instead of blocking, so a Pro tool can never hang on a cold import.
_audio_ready = threading.Event()  # set once the warm-up import attempt completes


def _log_warmup(message: str) -> None:
    """Print a timestamped warm-up line to stderr.

    FastMCP/stdio forwards the server's stderr into the client's MCP log, so
    these lines are how we observe the real cold-import cost on a customer
    machine without attaching a debugger.
    """
    print(f"[digr audio-warmup] {message}", file=sys.stderr, flush=True)


def warm_audio_stack() -> None:
    """Import the heavy audio stack once, timing it, then flag it ready.

    Called SYNCHRONOUSLY on the MAIN thread, as a lifespan task scheduled
    from server.py's _audio_warmup_lifespan (after `initialize` has had a
    head start, not before it) -- never on a background thread, where a
    C-extension import starves for the GIL and can stall for minutes.
    Importing ``_audio_analysis`` pulls in numpy + scipy + soundfile, forcing
    their native code to load now. ``_audio_ready`` is set in a ``finally``
    so it fires on SUCCESS OR FAILURE: a free-tier install (no ``[audio]``
    extras) must not leave the tools stuck on "warming up" -- it falls
    through to ``_require_audio`` which raises the proper "install the
    extras" error, and the synchronous import fails fast so it never delays
    a free-tier startup.
    """
    start = time.monotonic()
    _log_warmup("starting cold import of numpy/scipy/soundfile...")
    try:
        from . import _audio_analysis  # noqa: F401  (the import IS the work)
        import numpy  # noqa: F401

        _log_warmup(f"ready after {time.monotonic() - start:.1f}s")
    except Exception as exc:  # free-tier (no extras) or a transient failure
        _log_warmup(f"import failed after {time.monotonic() - start:.1f}s: {exc!r}")
    finally:
        _audio_ready.set()


def audio_warming_message() -> str | None:
    """Return a friendly "still warming up" message if the audio stack isn't
    ready yet, else None so the caller proceeds immediately.

    This is a single instant check -- it never waits. That's deliberate: an
    in-process wait here can stall on Python's GIL while the warm-up thread is
    mid-import (numpy/scipy's C extensions hold it for long stretches), so a
    "bounded wait" can silently degrade into an unbounded one. Returning
    immediately guarantees the tool call itself is always fast; the cost is
    that the user must ask again once the engine is warm.
    """
    if _audio_ready.is_set():
        return None
    _log_warmup("a Pro audio tool was called before warm-up finished; asked to retry")
    return (
        "Digr's audio engine is still warming up -- a one-time background load "
        "of the BPM/key-detection libraries that runs when Digr starts. This is "
        "normal and it is loading correctly; it can take a while the first time "
        "on Windows (antivirus scans the libraries on first load). Do NOT "
        "restart Digr or Claude -- that would start the load over. Just wait a "
        "moment and ask me to try again; it will be instant once warm-up "
        "finishes."
    )


def set_libraries(libraries: dict[str, Path]) -> None:
    """Set the active sample libraries. Called once at server startup."""
    global _libraries
    _libraries = dict(libraries)


def get_libraries() -> dict[str, Path]:
    """Get the active sample libraries."""
    return _libraries


def add_library_entry(name: str, path: Path) -> None:
    """Add a library to the in-memory store AND persist it to config.yaml."""
    global _libraries
    _libraries[name] = path
    _save_libraries_to_config()


def remove_library_entry(name: str) -> bool:
    """Remove a library from the in-memory store AND persist the change. Returns True if found."""
    global _libraries
    if name not in _libraries:
        return False
    del _libraries[name]
    _save_libraries_to_config()
    return True


def _save_libraries_to_config() -> None:
    """Persist the current libraries dict to config.yaml."""
    from ..platform_detect import default_config_path

    try:
        import yaml
    except ImportError:
        yaml = None

    config_path = default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing config to preserve other settings
    existing: dict = {}
    if config_path.exists():
        content = config_path.read_text(encoding="utf-8")
        if yaml is not None:
            try:
                existing = yaml.safe_load(content) or {}
            except Exception:
                existing = {}

    # Update libraries section only
    existing["libraries"] = {name: str(p) for name, p in _libraries.items()}

    if yaml is not None:
        config_path.write_text(
            yaml.dump(existing, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    else:
        # Fallback: write as JSON if pyyaml not available
        import json

        config_path.with_suffix(".json").write_text(
            json.dumps(existing, indent=2), encoding="utf-8"
        )


def set_last_search_results(results: list[tuple[str, str]]) -> None:
    """Update the cached search results."""
    global _last_search_results
    _last_search_results = results


def get_last_search_results() -> list[tuple[str, str]]:
    """Get the cached search results."""
    return _last_search_results


# --- License key management ---


def set_license_key(key: str | None) -> None:
    """Store the license key from config. Called at server startup.

    Verification happens lazily on the first Pro tool call (see
    _license_check) so startup never waits on the network.
    """
    global _license_key, _license_status
    cleaned = key.strip() if isinstance(key, str) else None
    _license_key = cleaned or None
    _license_status = None


def _license_check() -> tuple[bool, str | None]:
    """Activate or re-check the license, memoizing the result for this run."""
    global _license_status
    if _license_status is None:
        from ..licensing import activate_or_check

        _license_status = activate_or_check(_license_key)
    return _license_status


def activate_license_key(key: str) -> tuple[bool, str | None]:
    """Verify a just-pasted key NOW and remember the result for the gate.

    set_license_key (used at startup) is lazy — it waits for the first Pro tool
    call to verify. This is the eager path used by the activate_license tool: it
    loads the key, clears the memoized status, and runs the check immediately so
    Pro is unlocked in the SAME session, with no Claude restart.

    Returns (licensed, reason_if_not).
    """
    set_license_key(key)
    return _license_check()


def is_pro_licensed() -> bool:
    """Check if the current session has a valid Pro license."""
    return _license_check()[0]


def require_pro(tool_name: str) -> str | None:
    """Check Pro license. Returns None if licensed, or an upgrade message if not.

    Usage in tool functions:
        gate = require_pro("analyze_sample")
        if gate:
            return gate
        # ... rest of tool logic
    """
    if not ENFORCE_LICENSE_GATE:
        return None
    licensed, reason = _license_check()
    if licensed:
        return None

    from ..platform_detect import default_config_dir

    key_file = default_config_dir() / "license.key"

    parts = [f"'{tool_name}' is a Pro feature."]
    if reason:
        parts.append(reason)
    else:
        parts.append("Get a license key at https://sentinelprotocol.co.uk/digr")
    parts.append(
        "Already purchased? Just paste your license key here and I'll activate "
        "it for you right away — Pro unlocks immediately, no restart needed.\n\n"
        "Prefer to set it up by hand? Put the key in a file or an env var:\n"
        f"  - File: {key_file}\n"
        "  - Environment: DIGR_LICENSE_KEY=your-key-here"
    )
    parts.append(
        "Free tools available: search_samples, list_libraries, list_folders, "
        "count_samples_in_folder, list_all_samples_in_folder, collect_samples, "
        "copy_samples, collect_search_results"
    )
    return "\n\n".join(parts)


def match_keywords(path_str: str, keywords: list[str]) -> bool:
    """Check if all keywords appear anywhere in the path (case-insensitive)."""
    path_lower = path_str.lower()
    return all(kw in path_lower for kw in keywords)


def is_junk_path(file_path: Path) -> bool:
    """True for macOS metadata litter that only looks like a sample.

    When audio is zipped or copied on a Mac and unpacked on another
    filesystem, two kinds of junk appear with audio-looking names:
    AppleDouble sidecar files (``._Track.wav``) and the ``__MACOSX``
    folder. They carry an audio extension but contain no audio, so they
    must never be searched, counted, analysed, or organised as samples.
    """
    if file_path.name.startswith("._"):
        return True
    return "__MACOSX" in file_path.parts


def search_all_libraries(
    keyword: str, max_results: int, per_library_cap: int | None = None
) -> list[tuple[str, str]]:
    """Search all libraries and return balanced results as (path, library_name) tuples."""
    keywords = keyword.lower().split()
    if per_library_cap is None:
        per_library_cap = max(max_results, 50)

    library_matches: dict[str, list[str]] = {}
    for library_name, library in _libraries.items():
        if not library.exists():
            continue

        lib_results: list[str] = []
        for extension in ALL_EXTENSIONS:
            try:
                for file_path in library.rglob(extension):
                    if is_junk_path(file_path):
                        continue
                    if match_keywords(str(file_path), keywords):
                        lib_results.append(str(file_path))
                        if len(lib_results) >= per_library_cap:
                            break
            except (PermissionError, OSError):
                continue
            if len(lib_results) >= per_library_cap:
                break

        if lib_results:
            library_matches[library_name] = lib_results

    if not library_matches:
        return []

    # Distribute results evenly across libraries, then fill remainder
    num_libs = len(library_matches)
    per_lib = max(1, max_results // num_libs)
    matches: list[tuple[str, str]] = []

    for lib_name, paths in library_matches.items():
        for path in paths[:per_lib]:
            matches.append((path, lib_name))

    remaining = max_results - len(matches)
    if remaining > 0:
        for lib_name, paths in library_matches.items():
            for path in paths[per_lib:]:
                if remaining <= 0:
                    break
                matches.append((path, lib_name))
                remaining -= 1

    return matches


def parse_filepaths(filepaths) -> list[str]:
    """Parse filepaths from various formats.

    Handles: JSON array, pipe-delimited string, newline-delimited, or single path.
    Robust against LLMs that send strings instead of arrays.
    """
    # Already a list
    if isinstance(filepaths, list):
        return [p.strip() for p in filepaths if isinstance(p, str) and p.strip()]

    # String input
    if isinstance(filepaths, str):
        s = filepaths.strip()

        # Try JSON array (e.g., '["path1", "path2"]')
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [
                        p.strip() for p in parsed if isinstance(p, str) and p.strip()
                    ]
            except (json.JSONDecodeError, ValueError):
                pass

        # Try pipe delimiter
        if "|" in s:
            return [p.strip() for p in s.split("|") if p.strip()]

        # Try newline delimiter
        if "\n" in s:
            return [p.strip() for p in s.split("\n") if p.strip()]

        # Single path
        if s:
            return [s]

    return []


def copy_or_move(src: Path, dest_dir: Path, move: bool = False) -> Path:
    """Copy or move a file to a destination directory, handling name collisions."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        i = 1
        while dest.exists():
            dest = dest_dir / f"{stem}_{i}{suffix}"
            i += 1
    if move:
        shutil.move(str(src), str(dest))
    else:
        shutil.copy2(str(src), str(dest))
    return dest


def parse_result_numbers(result_numbers: str) -> list[int]:
    """Parse result numbers from a string like '1,3,7' or '1-5' or '1,3-5,7'."""
    indices = []
    for part in result_numbers.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                indices.extend(range(int(start.strip()), int(end.strip()) + 1))
            except (ValueError, TypeError):
                continue
        else:
            try:
                indices.append(int(part))
            except (ValueError, TypeError):
                continue
    return indices


def identify_library(file_path: Path) -> str:
    """Determine which library a file belongs to."""
    for lib_name, lib_path in _libraries.items():
        try:
            if lib_path.exists() and file_path.is_relative_to(lib_path):
                return lib_name
        except (ValueError, OSError):
            continue
    return "External"
