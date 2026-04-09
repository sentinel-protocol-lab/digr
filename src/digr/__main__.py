"""CLI entry point for Digr."""

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Digr - MCP server for audio sample libraries",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  # Run with stdio transport (default, for Claude Desktop / Claude Code)
  digr

  # Run with Streamable HTTP transport (for Cursor, VS Code, remote access)
  digr --transport streamable-http --port 8000

  # Use a specific config file
  digr --config /path/to/config.yaml

  # Add libraries via CLI
  digr --library "My Samples=/path/to/samples"

  # Combine options
  digr --transport streamable-http --library "Drums=/mnt/drums"
""",
    )

    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host for HTTP transport (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for HTTP transport (default: 8000)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config file (YAML or JSON)",
    )
    parser.add_argument(
        "--library",
        action="append",
        default=None,
        help="Add a library as 'Name=/path' (can be repeated)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Update to the latest version from GitHub",
    )

    args = parser.parse_args()

    # Handle update before anything else
    if args.update:
        from .updater import run_update

        install_dir = Path(__file__).resolve().parent.parent.parent
        run_update(install_dir)
        sys.exit(0)

    # Load config with layered overrides
    from .config import load_config

    config = load_config(
        config_path=args.config,
        cli_libraries=args.library,
    )

    # Create server
    from .server import create_server

    mcp = create_server(config)

    # Run with selected transport
    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


def _get_version() -> str:
    try:
        from . import __version__

        return __version__
    except ImportError:
        return "unknown"


if __name__ == "__main__":
    main()
