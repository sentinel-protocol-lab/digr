# Digr

MCP server for searching, analyzing, and organizing audio sample libraries for music production.

## Architecture

- **Framework**: FastMCP (`mcp.server.fastmcp`) — auto-generates tool schemas from Python type hints
- **Transports**: `stdio` (default, for Claude Desktop/Code) and `streamable-http` (for VS Code, Cursor, remote)
- **Config**: Layered — auto-detect > config file > env vars > CLI args (highest priority)
- **Structure**: `src/digr/` with `tools/` subpackage (search, browse, analyze, organize, _shared)
- **State**: Library paths and search result cache stored in `tools/_shared.py` module-level variables

## Tool Sequencing Rules

### Search Before Collect
`collect_search_results` reads from a cache populated by `search_samples`. Always call `search_samples` first:
```
search_samples(keyword="kick") → collect_search_results(result_numbers="1,3", destination="/path")
```

### Two-Phase Confirm Pattern
All destructive organize tools use preview-then-execute:
1. First call with `confirm=False` (default) → returns PREVIEW text
2. Second call with `confirm=True` → executes the operation

Tools using this pattern: `collect_samples`, `copy_samples`, `collect_search_results`, `rename_with_metadata`, `sort_samples`, `undo_rename`

### MIDI File Reading
Use `read_midi(filepath, track_index=-1)` first to list available tracks, then call again with the specific track index to get notes.

### Filepath Parameters
Pass filepaths as a JSON array of strings for maximum reliability:
```json
["/path/to/file1.wav", "/path/to/file2.wav"]
```
The server also accepts pipe-delimited, newline-delimited, and single path strings, but JSON arrays work best across all LLM clients.

## Tool Categories

### Free Tools (always available)
- `search_samples` — keyword search across all libraries
- `list_libraries` — show configured libraries and mount status
- `list_folders` — top-level folders across all libraries
- `count_samples_in_folder` — file counts by type
- `list_all_samples_in_folder` — browse folder contents
- `collect_samples` — copy/move by keyword (with preview)
- `copy_samples` — copy/move specific files by path (with preview)
- `collect_search_results` — copy/move from last search by result number (with preview)
- `undo_rename` — reverse the most recent `rename_with_metadata` batch (with preview). **Free by design** — undoing damage must never sit behind a licence, since a lapsed key would strand a user mid-rename
- `activate_license` — save a pasted Pro key and unlock Pro in-session (no restart)

### Pro Tools (require license key)
- `analyze_sample` — BPM and key detection (requires `[audio]` extras)
- `search_samples_by_bpm` — search + BPM detection (requires `[audio]` extras)
- `read_midi` — parse MIDI files to bar|beat format
- `sort_samples` — categorize into subfolders (Kicks, Snares, etc.)
- `rename_with_metadata` — append BPM/key to filenames (prefix-only renaming is free; BPM/key detection requires Pro). `include_bpm` and `include_key` both default to **False** and must be asked for explicitly

## Common Workflows

### Find and Copy Samples
```
search_samples(keyword="snare 909") → review results → collect_search_results(result_numbers="1,3,7", destination="/dest")
```

### Analyze and Organize a Collection
```
search_samples(keyword="drum loop") → sort_samples(source_keyword="drum loop", destination="/sorted", confirm=False) → review preview → sort_samples(..., confirm=True)
```

### Load Sample into Ableton (with Producer Pal)
```
search_samples(keyword="reverse cymbal") → analyze_sample(filepath="...") → [Producer Pal] ppal-create-track(type="audio") → ppal-create-clip(sampleFile="...", view="arrangement")
```

## Known Gotchas

- **A filename's BPM label always wins over detection** — the label is the producer's statement about their own file; detection is an estimate. When they agree the estimate adds confidence, not precision, so it never overwrites the label. `TempoResult.source` says which of the four cases applied (`detected`, `label_confirmed`, `label_harmonic`, `label_only`) and `TempoResult.detected` always carries what was measured — display code must show `detected`, never `tempo`, when reporting what confirmed a label
- **`rename_with_metadata` never appends a tag the filename already carries** — including across notations, so a stem ending `D#m` blocks an appended `Ds`
- **Every rename is logged and reversible** — batches append to `<config dir>/rename_history.jsonl` (capped at the most recent 50), reversed by `undo_rename`. Prefix-only renames are logged too. Undo skips and reports rather than guessing: a file moved since, or an original name now occupied, is left alone and **kept in the history so a later `undo_rename` can retry it**
- **BPM detection halves/doubles on short samples** — autocorrelation limitation, not a bug
- **One-shots return 0.0 BPM** — expected behavior for non-rhythmic content
- **Cannot load samples into Simpler/Sampler via MCP** — use `ppal-create-clip` with `sampleFile` for audio clips instead
- **Audio analysis uses numpy+scipy+soundfile** — no librosa/numba/llvmlite dependency (replaced for cross-platform compatibility)
- **Search matches full path, not just filename** — "kick" matches both `/Drums/Kicks/808.wav` and `/kick_heavy.wav`
- **Original librosa-based code** is backed up in `_librosa_backup/` with restore instructions

## Development

```bash
# Install for development (with audio analysis and test dependencies)
pip install -e ".[audio,dev]"

# Run tests
pytest

# Lint
ruff check src/

# Run server locally
digr                                    # stdio transport
digr --transport streamable-http        # HTTP on port 8000
```

## License Key Setup

Pro features require a license key. Three ways to set it:
- **`activate_license` tool (easiest)**: the user pastes their key in chat; the tool writes `license.key` for them and unlocks Pro in the same session (no restart). This is the frictionless path the gate message points customers to.
- **File**: `~/.config/digr/license.key` (just the key string, no whitespace; read with `utf-8-sig` so a Notepad BOM is tolerated)
- **Environment**: `DIGR_LICENSE_KEY=your-key-here` (takes priority over the file)

The key is read at startup (file/env) OR set live by `activate_license`. Activation verifies against Gumroad once, then writes a signed offline token (`license.token`) so later runs work offline; it re-checks every 14 days (`RECHECK_DAYS`).
