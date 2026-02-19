# Sample Library Manager

MCP server for searching, analyzing, and organizing audio sample libraries. Works with any MCP-compatible client (Claude Desktop, Claude Code, Cursor, VS Code Copilot, OpenAI Codex, and more).

## Install

### PyPI (pip / uvx)

```bash
# Basic (search, browse, organize, MIDI reading)
pip install sample-library-manager

# Full (adds BPM/key detection via librosa)
pip install sample-library-manager[audio]

# Or run directly with uvx
uvx sample-library-manager
uvx --with 'sample-library-manager[audio]' sample-library-manager
```

### MCPB Bundle (one-click)

Download `sample-library-manager.mcpb` from [Releases](https://github.com/sample-library-manager/sample-library-manager/releases) and open it with Claude Desktop.

### Docker

```bash
docker run -p 8000:8000 \
  -v /path/to/samples:/samples:ro \
  -e SLM_LIBRARIES='{"Samples": "/samples"}' \
  sample-library-manager \
  --transport streamable-http --host 0.0.0.0
```

## Client Configuration

### Claude Desktop / Claude Code (stdio)

```json
{
  "mcpServers": {
    "sample-library-manager": {
      "command": "uvx",
      "args": ["--with", "sample-library-manager[audio]", "sample-library-manager"]
    }
  }
}
```

### With config file

```json
{
  "mcpServers": {
    "sample-library-manager": {
      "command": "uvx",
      "args": [
        "--with", "sample-library-manager[audio]",
        "sample-library-manager",
        "--config", "/path/to/config.yaml"
      ]
    }
  }
}
```

### Cursor / VS Code / OpenAI Codex (Streamable HTTP)

Start the server:
```bash
sample-library-manager --transport streamable-http --port 8000
```

Connect in your client:
```json
{
  "mcpServers": {
    "sample-library-manager": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

## Configuration

Libraries are configured via a layered system (highest priority wins):

### 1. CLI Arguments

```bash
sample-library-manager --library "My Samples=/path/to/samples" --library "Packs=/path/to/packs"
```

### 2. Environment Variables

```bash
# JSON object
export SLM_LIBRARIES='{"My Samples": "/path/to/samples", "Packs": "/path/to/packs"}'

# Or individual paths
export SLM_LIBRARY_1="/path/to/samples"
export SLM_LIBRARY_1_NAME="My Samples"
```

### 3. Config File

Default location: `~/.config/sample-library-manager/config.yaml`

```yaml
libraries:
  "My Samples": "/path/to/samples"
  "Ableton Packs": "/path/to/packs"
  "Core Library": "/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/Core Library/Samples"
```

### 4. Auto-Detection

If no config is provided, the server auto-detects common sample locations:
- **macOS**: Ableton Core Library, ~/Music/Ableton/User Library, Splice, external volumes
- **Windows**: Program Files/Ableton, Documents/Ableton, Splice, D:/E:/F: drives
- **Linux**: ~/Ableton, Splice, /mnt/*/Samples, /media/*/Samples

## Tools

| Tool | Description |
|------|-------------|
| `search_samples` | Search for audio samples and MIDI files across all libraries |
| `search_samples_by_bpm` | Search and auto-detect BPM for each result |
| `list_libraries` | Show configured library locations and status |
| `list_folders` | List top-level folders across all libraries |
| `count_samples_in_folder` | Count samples in a specific folder |
| `list_all_samples_in_folder` | List all samples in a folder |
| `analyze_sample` | Detect BPM and musical key (requires `[audio]`) |
| `read_midi` | Read MIDI file notes in bar\|beat format |
| `collect_samples` | Copy/move samples by keyword |
| `copy_samples` | Copy/move specific files by path |
| `collect_search_results` | Copy/move from last search results |
| `rename_with_metadata` | Rename with BPM/key appended (requires `[audio]`) |
| `sort_samples` | Sort into categorized subfolders |

## Development

```bash
git clone https://github.com/sample-library-manager/sample-library-manager
cd sample-library-manager
pip install -e ".[audio,dev]"
pytest
```

## License

MIT
