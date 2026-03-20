#!/usr/bin/env python3
"""Build script: packages sample-library-manager as a distributable .mcpb bundle.

An MCPB file is a zip archive that Claude Desktop can open directly to install
an MCP server — no Terminal or JSON editing required by the end user.

Usage:
    python build_mcpb.py

Output:
    dist/sample-library-manager-{version}.mcpb
"""

import fnmatch
import re
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
DIST_DIR = PROJECT_ROOT / "dist"
MCPBIGNORE = PROJECT_ROOT / ".mcpbignore"


def load_ignore_patterns() -> list[str]:
    """Parse .mcpbignore into a list of raw patterns."""
    if not MCPBIGNORE.exists():
        return []
    patterns = []
    for line in MCPBIGNORE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    return patterns


def is_ignored(path: Path, patterns: list[str]) -> bool:
    """Return True if path should be excluded from the bundle.

    Directory patterns (trailing /) are matched against directory components
    of the path. File patterns are matched against the filename only.
    """
    rel = path.relative_to(PROJECT_ROOT)
    parts = rel.parts          # e.g. ('src', 'sample_library_manager', 'server.py')
    dir_parts = parts[:-1]    # directory components only
    filename = parts[-1]

    for pattern in patterns:
        is_dir_pattern = pattern.endswith("/")
        clean = pattern.rstrip("/")

        if is_dir_pattern:
            # Match against any directory component in the path
            for part in dir_parts:
                if fnmatch.fnmatch(part, clean):
                    return True
        else:
            # Match against filename (handles *.pyc, .DS_Store, Dockerfile, etc.)
            if fnmatch.fnmatch(filename, clean):
                return True
            # Also match the full relative path for exact names at any depth
            if fnmatch.fnmatch(str(rel), clean):
                return True

    return False


def get_version() -> str:
    """Read version string from pyproject.toml using regex (no deps, any Python)."""
    text = (PROJECT_ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise RuntimeError("Could not find version in pyproject.toml")
    return match.group(1)


def build_mcpb() -> Path:
    DIST_DIR.mkdir(exist_ok=True)

    version = get_version()
    output_path = DIST_DIR / f"sample-library-manager-{version}.mcpb"

    patterns = load_ignore_patterns()

    included: list[Path] = []
    skipped: list[Path] = []

    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if is_ignored(path, patterns):
            skipped.append(path)
        else:
            included.append(path)

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in included:
            arcname = path.relative_to(PROJECT_ROOT)
            zf.write(path, arcname)

    size_kb = output_path.stat().st_size / 1024
    print(f"Built:   {output_path.name}")
    print(f"Size:    {size_kb:.1f} KB")
    print(f"Files:   {len(included)} included, {len(skipped)} excluded")
    print()
    print(f"Install: open dist/{output_path.name} with Claude Desktop")
    return output_path


if __name__ == "__main__":
    try:
        build_mcpb()
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
