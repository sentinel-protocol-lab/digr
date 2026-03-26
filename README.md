# Sample Library Manager

**Search your samples by describing what you want.**

"Find me some dark 170bpm drum breaks." "What key is this pad in?"
"Sort my downloads into kicks, snares, hats, and everything else."

Sample Library Manager connects your AI assistant to your audio files.
It searches across all your sample folders, detects BPM and key,
and helps you organise thousands of files without manual browsing.

Works with Claude Desktop, Claude Code, Cursor, VS Code, and any
MCP-compatible client. Mac and Windows. Any DAW or no DAW at all.

Free for personal use · [License (BSL 1.1)](LICENSE)

## Install

### Claude Desktop — MCPB (Recommended)

Download `sample-library-manager-1.0.0.mcpb` from [Releases](https://github.com/sentinel-protocol-lab/sample-library-manager/releases), then:

1. Open Claude Desktop → **Settings** → **Extensions**
2. Click **Install Extension** and select the `.mcpb` file
3. Done — Claude handles everything automatically

### Upgrading from a Previous Version

Claude Desktop installs extensions side-by-side — a new `.mcpb` does **not** overwrite the old one. To upgrade:

1. Open Claude Desktop → **Settings** → **Extensions**
2. Find "Sample Library Manager" → click **Remove**
3. Delete the leftover data folder:
   - **Mac**: `~/Library/Application Support/SampleLibraryManager/`
   - **Windows**: `%APPDATA%\SampleLibraryManager\`
4. Install the new `.mcpb` file as normal (step 2 above)

This ensures all old code and cached data is fully replaced.

### Windows — One-Click Installer

Download `install.bat` and `install.ps1` from [Releases](https://github.com/sentinel-protocol-lab/sample-library-manager/releases) into the same folder as the `.mcpb` file, then double-click `install.bat`.

Installs `uv`, registers the server in Claude Desktop, and restarts it automatically.

### Mac — One-Click Installer

Download `install-mac.command` from [Releases](https://github.com/sentinel-protocol-lab/sample-library-manager/releases) into the same folder as the `.mcpb` file, then double-click it.

> If macOS says it can't verify the file (web download only): right-click → **Open** → **Open**. This one-time step is not needed for USB installs.

Installs `uv`, registers the server in Claude Desktop, and restarts it automatically.

### PyPI (pip / uvx)

```bash
# Basic (search, browse, organize, MIDI reading)
pip install sample-library-manager

# Full (adds BPM/key detection)
pip install sample-library-manager[audio]

# Or run directly with uvx
uvx sample-library-manager
uvx --with 'sample-library-manager[audio]' sample-library-manager
```

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

| Tool | Description | Tier |
|------|-------------|------|
| `search_samples` | Search for audio samples and MIDI files across all libraries | Free |
| `list_libraries` | Show configured library locations and status | Free |
| `list_folders` | List top-level folders across all libraries | Free |
| `count_samples_in_folder` | Count samples in a specific folder | Free |
| `list_all_samples_in_folder` | List all samples in a folder | Free |
| `collect_samples` | Copy/move samples by keyword | Free |
| `copy_samples` | Copy/move specific files by path | Free |
| `collect_search_results` | Copy/move from last search results | Free |
| `add_library` | Add a sample library path at runtime | Free |
| `remove_library` | Remove a sample library by name | Free |
| `analyze_sample` | Detect BPM and musical key (requires `[audio]`) | Pro |
| `search_samples_by_bpm` | Search and auto-detect BPM for each result | Pro |
| `read_midi` | Read MIDI file notes in bar\|beat format | Pro |
| `rename_with_metadata` | Rename with BPM/key appended (requires `[audio]`) | Pro |
| `sort_samples` | Sort into categorized subfolders | Pro |

Pro tools require a license key. Set via either method:
- **File**: `~/.config/sample-library-manager/license.key`
- **Environment**: `SLM_LICENSE_KEY=your-key-here`

## Development

```bash
git clone https://github.com/sentinel-protocol-lab/sample-library-manager
cd sample-library-manager
pip install -e ".[audio,dev]"
pytest
```

## License

Business Source License 1.1 — see [LICENSE](LICENSE) for details.

Free for production use. You may not use this software to offer a competing commercial sample library management product or service. Converts to Apache 2.0 on 2029-03-19.
