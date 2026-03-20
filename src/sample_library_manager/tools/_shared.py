"""Shared utilities for all tools: search engine, file helpers, state cache, license gating."""

import json
import os
import shutil
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
# Set to True when payment infrastructure is live and Gumroad license keys are available.
# See GTM plan Step 7.
ENFORCE_LICENSE_GATE = False

# --- License key state ---
_license_key: str | None = None
_license_valid: bool = False
_VALID_KEY_PREFIX = "SLM-PRO-"


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
    """Set and validate the license key. Called at server startup."""
    global _license_key, _license_valid
    _license_key = key
    _license_valid = _validate_key(key) if key else False


def is_pro_licensed() -> bool:
    """Check if the current session has a valid Pro license."""
    return _license_valid


def _validate_key(key: str) -> bool:
    """Validate a license key format.

    Format: SLM-PRO-<segment>-<payload> (minimum 4 dash-separated parts).
    In production, replace this with cryptographic signature verification.
    """
    if not key or not key.startswith(_VALID_KEY_PREFIX):
        return False
    parts = key.split("-")
    # Minimum structure: SLM-PRO-SEGMENT-PAYLOAD
    return len(parts) >= 4


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
    if _license_valid:
        return None
    return (
        f"'{tool_name}' is a Pro feature.\n"
        f"Get a license key at https://samplelibrary.pro\n\n"
        f"Set your key via:\n"
        f"  - File: ~/.config/sample-library-manager/license.key\n"
        f"  - Environment: SLM_LICENSE_KEY=your-key-here\n\n"
        f"Free tools available: search_samples, list_libraries, list_folders, "
        f"count_samples_in_folder, list_all_samples_in_folder, collect_samples, "
        f"copy_samples, collect_search_results"
    )


def match_keywords(path_str: str, keywords: list[str]) -> bool:
    """Check if all keywords appear anywhere in the path (case-insensitive)."""
    path_lower = path_str.lower()
    return all(kw in path_lower for kw in keywords)


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
