"""Cross-platform detection of common sample library locations."""

import os
import platform
from pathlib import Path


def auto_detect_libraries() -> dict[str, Path]:
    """Auto-detect common sample library locations for the current OS.

    Returns a dict mapping library names to Path objects for directories that exist.
    """
    system = platform.system()
    candidates: dict[str, Path] = {}
    libraries: dict[str, Path] = {}

    if system == "Darwin":  # macOS
        candidates = {
            "Core Library (Suite)": Path(
                "/Applications/Ableton Live 12 Suite.app"
                "/Contents/App-Resources/Core Library/Samples"
            ),
            "Core Library (Standard)": Path(
                "/Applications/Ableton Live 12 Standard.app"
                "/Contents/App-Resources/Core Library/Samples"
            ),
            "User Library": Path.home() / "Music" / "Ableton" / "User Library",
            "Splice Samples": Path.home() / "Splice" / "sounds",
            "LANDR Samples": Path.home() / "LANDR" / "samples",
        }
        # Check external volumes for sample folders
        volumes = Path("/Volumes")
        if volumes.exists():
            try:
                for vol in volumes.iterdir():
                    if not vol.is_dir() or vol.name == "Macintosh HD":
                        continue
                    for sub in [
                        "Samples",
                        "Audio Samples",
                        "Sample Library",
                        "Samples, Loops & Midi's",
                    ]:
                        p = vol / sub
                        if p.exists():
                            libraries[f"{vol.name}/{sub}"] = p
                    # Check for Ableton User Library on external volumes
                    for ableton_dir in ["Ableton", "Ableton "]:
                        user_lib = vol / ableton_dir / "Ableton" / "User Library"
                        if user_lib.exists():
                            libraries[f"{vol.name}/User Library"] = user_lib
                        packs = vol / ableton_dir / "Ableton Packs"
                        if packs.exists():
                            libraries[f"{vol.name}/Ableton Packs"] = packs
            except (PermissionError, OSError):
                pass

    elif system == "Windows":
        program_files = os.environ.get("PROGRAMFILES", "C:/Program Files")
        candidates = {
            "Core Library (Suite)": (
                Path(program_files)
                / "Ableton"
                / "Live 12 Suite"
                / "Resources"
                / "Core Library"
                / "Samples"
            ),
            "Core Library (Standard)": (
                Path(program_files)
                / "Ableton"
                / "Live 12 Standard"
                / "Resources"
                / "Core Library"
                / "Samples"
            ),
            "User Library": (
                Path.home() / "Documents" / "Ableton" / "User Library"
            ),
            "Splice Samples": Path.home() / "Splice" / "sounds",
        }
        # Check common drives for sample folders
        for drive_letter in "DEFGH":
            drive = f"{drive_letter}:"
            if not Path(drive + "/").exists():
                continue
            for sub in ["Samples", "Audio Samples", "Sample Library"]:
                p = Path(drive) / sub
                if p.exists():
                    libraries[f"{drive}/{sub}"] = p
            # Check for Ableton libraries on other drives
            user_lib = Path(drive) / "Ableton" / "User Library"
            if user_lib.exists():
                libraries[f"{drive}/User Library"] = user_lib
            packs = Path(drive) / "Ableton Packs"
            if packs.exists():
                libraries[f"{drive}/Ableton Packs"] = packs

    elif system == "Linux":
        candidates = {
            "User Library": Path.home() / "Ableton" / "User Library",
            "Splice Samples": Path.home() / "Splice" / "sounds",
        }
        # Check /mnt and /media for mounted drives
        username = os.environ.get("USER", "")
        mount_roots = [Path("/mnt")]
        if username:
            mount_roots.append(Path("/media") / username)

        for mount_root in mount_roots:
            if not mount_root.exists():
                continue
            try:
                for vol in mount_root.iterdir():
                    if not vol.is_dir():
                        continue
                    for sub in ["Samples", "Audio Samples", "Sample Library"]:
                        p = vol / sub
                        if p.exists():
                            libraries[f"{vol.name}/{sub}"] = p
            except (PermissionError, OSError):
                continue

    # Add candidates that actually exist on disk
    for name, path in candidates.items():
        if path.exists():
            libraries[name] = path

    return libraries


def default_config_dir() -> Path:
    """Return the default config directory for the current OS."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / ".config"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "sample-library-manager"


def default_config_path() -> Path:
    """Return the default config file path."""
    return default_config_dir() / "config.yaml"
