"""Layered configuration system.

Priority (highest wins): CLI args > env vars > config file > auto-detection
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .platform_detect import auto_detect_libraries, default_config_dir, default_config_path


@dataclass
class Config:
    """Server configuration."""

    libraries: dict[str, Path] = field(default_factory=dict)
    license_key: str | None = None


def load_config(
    config_path: str | None = None,
    cli_libraries: list[str] | None = None,
) -> Config:
    """Load config with layered overrides.

    Priority: auto-detect -> config file -> env vars -> CLI args (highest)
    """
    config = Config()

    # 1. Auto-detect common locations for this OS
    config.libraries = auto_detect_libraries()

    # 2. Merge config file (if exists)
    file_path = Path(config_path) if config_path else default_config_path()
    if file_path.exists():
        file_libs = _load_config_file(file_path)
        config.libraries.update(file_libs)

    # 3. Merge env vars
    env_libs = os.environ.get("DIGR_LIBRARIES")
    if env_libs:
        try:
            parsed = json.loads(env_libs)
            if isinstance(parsed, dict):
                config.libraries.update(
                    {k: Path(v) for k, v in parsed.items()}
                )
        except (json.JSONDecodeError, ValueError):
            pass

    # Also support individual env vars: DIGR_LIBRARY_1, DIGR_LIBRARY_1_NAME
    for i in range(1, 21):
        path_env = os.environ.get(f"DIGR_LIBRARY_{i}")
        name_env = os.environ.get(f"DIGR_LIBRARY_{i}_NAME", f"Library {i}")
        if path_env:
            config.libraries[name_env] = Path(path_env)

    # 4. Merge CLI args (highest priority)
    if cli_libraries:
        for lib in cli_libraries:
            if "=" in lib:
                name, path = lib.split("=", 1)
                config.libraries[name.strip()] = Path(path.strip())
            else:
                # If no name given, use the folder name
                p = Path(lib.strip())
                config.libraries[p.name] = p

    # 5. Load license key (env var > file)
    license_key = os.environ.get("DIGR_LICENSE_KEY")
    if not license_key:
        license_file = default_config_dir() / "license.key"
        if license_file.exists():
            try:
                license_key = license_file.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError):
                license_key = None
    config.license_key = license_key or None

    return config


def _load_config_file(path: Path) -> dict[str, Path]:
    """Load library paths from a YAML or JSON config file."""
    try:
        import yaml
    except ImportError:
        yaml = None

    content = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        if yaml is None:
            return {}
        data = yaml.safe_load(content)
    elif suffix == ".json":
        data = json.loads(content)
    else:
        # Try YAML first, then JSON
        if yaml is not None:
            try:
                data = yaml.safe_load(content)
            except Exception:
                data = json.loads(content)
        else:
            data = json.loads(content)

    if not isinstance(data, dict):
        return {}

    libs = data.get("libraries", {})
    if not isinstance(libs, dict):
        return {}

    return {name: Path(path_str) for name, path_str in libs.items()}
