"""Self-update mechanism: download latest release from GitHub and overwrite local files."""

import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

GITHUB_REPO = "sentinel-protocol-lab/sample-library-manager"
GITHUB_ZIP_URL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.zip"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Directories and files to never overwrite (local state / user config)
SKIP_DIRS = {".git", ".venv", "venv", ".claude", "__pycache__", ".pytest_cache", ".ruff_cache"}
SKIP_FILES = {".env", ".DS_Store", "Thumbs.db"}
SKIP_EXTENSIONS = {".key"}


def _get_current_version() -> str:
    """Read the current installed version."""
    try:
        from . import __version__
        return __version__
    except ImportError:
        return "unknown"


def _get_latest_version() -> str | None:
    """Check GitHub for the latest release version. Returns None if no releases or on error."""
    try:
        req = urllib.request.Request(GITHUB_API_URL, headers={"Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            tag = data.get("tag_name", "")
            # Strip leading 'v' if present (e.g., 'v1.1.0' -> '1.1.0')
            return tag.lstrip("v") if tag else None
    except Exception:
        return None


def _should_skip(relative_path: Path) -> bool:
    """Check if a path should be skipped during update."""
    parts = relative_path.parts

    # Skip if any directory component is in SKIP_DIRS
    for part in parts[:-1]:
        if part in SKIP_DIRS:
            return True

    # Skip specific files
    if relative_path.name in SKIP_FILES:
        return True

    # Skip by extension
    if relative_path.suffix in SKIP_EXTENSIONS:
        return True

    return False


def run_update(install_dir: Path) -> None:
    """Download the latest version from GitHub and overwrite local files.

    Args:
        install_dir: The project root directory (contains pyproject.toml).
    """
    # Sanity check
    if not (install_dir / "pyproject.toml").exists():
        print(f"ERROR: Could not find pyproject.toml in {install_dir}")
        print("Are you running this from the correct directory?")
        sys.exit(1)

    current = _get_current_version()
    print(f"Current version: {current}")

    # Check latest version (informational — update proceeds regardless)
    latest = _get_latest_version()
    if latest:
        print(f"Latest version:  {latest}")
        if latest == current:
            print("\nAlready up to date.")
            return
    else:
        print("Could not check latest version (no releases yet or GitHub unreachable).")
        print("Downloading from main branch...\n")

    # Download the zip
    print("Downloading update...")
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "update.zip"

            urllib.request.urlretrieve(GITHUB_ZIP_URL, str(zip_path))
            print("Download complete.")

            # Extract
            print("Extracting files...")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)

            # Find the extracted directory (GitHub zips have one top-level folder)
            extracted_dirs = [
                d for d in Path(tmp_dir).iterdir()
                if d.is_dir() and d.name != "__MACOSX"
            ]
            if len(extracted_dirs) != 1:
                print("ERROR: Unexpected zip structure.")
                sys.exit(1)

            source_dir = extracted_dirs[0]

            # Walk the extracted files and overwrite
            updated = 0
            skipped = 0
            for src_file in source_dir.rglob("*"):
                if src_file.is_dir():
                    continue

                relative = src_file.relative_to(source_dir)

                if _should_skip(relative):
                    skipped += 1
                    continue

                dest_file = install_dir / relative
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src_file), str(dest_file))
                updated += 1

            print(f"Updated {updated} files ({skipped} local files preserved).")

            # Remove .venv so uv rebuilds it with new dependencies on next launch
            venv_dir = install_dir / ".venv"
            if venv_dir.exists():
                print("Removing .venv (will be rebuilt on next launch)...")
                try:
                    shutil.rmtree(venv_dir)
                except OSError:
                    print("  Could not fully remove .venv — please delete it manually.")

            print(f"\nUpdate complete! Restart Sample Library Manager to use the new version.")

    except urllib.error.URLError as e:
        print(f"ERROR: Could not download update — {e}")
        print("Check your internet connection and try again.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Update failed — {e}")
        sys.exit(1)
