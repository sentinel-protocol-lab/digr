# Digr
**Natural-language search, analysis, and organization for your sample library.**

Search your samples by describing what you want.

"Find me some dark 170bpm drum breaks." "What key is this pad in?"
"Sort my downloads into kicks, snares, hats, and everything else."

Digr connects your AI assistant to your audio files.
It searches across all your sample folders, detects BPM and key,
and helps you organise thousands of files without manual browsing.

Everything runs locally: nothing is uploaded, and nothing is used to train AI.

Works with Claude Desktop and any MCP-compatible client.
Mac and Windows. Any DAW or no DAW at all.

## Model Recommendations

Digr works with any MCP-compatible AI model, but results
vary with model capability:

- **Claude Opus / Sonnet** — Recommended. Handles multi-step workflows
  (search → collect, preview → confirm) reliably with minimal guidance.
- **Claude Haiku / lighter models** — Functional, but may need more explicit
  instructions. If the model skips steps or misformats parameters, try
  breaking your request into smaller, single-step prompts.

## Install

### Claude Desktop — MCPB (Recommended)

Download the latest `.mcpb` file from [Releases](https://github.com/sentinel-protocol-lab/digr/releases), then:

1. Open Claude Desktop → **Settings** → **Extensions**
2. Click **Install Extension** and select the `.mcpb` file
3. Done — Claude handles everything automatically

### Windows — One-Click Installer

Download `install.bat` and `install.ps1` from [Releases](https://github.com/sentinel-protocol-lab/digr/releases) into the same folder as the `.mcpb` file, then double-click `install.bat`.

Installs `uv`, registers the server in Claude Desktop, and restarts it automatically.

### Mac — One-Click Installer

Download `install-mac.command` from [Releases](https://github.com/sentinel-protocol-lab/digr/releases) into the same folder as the `.mcpb` file, then double-click it.

> If macOS says it can't verify the file (web download only): right-click → **Open** → **Open**. This one-time step is not needed for USB installs.

Installs `uv`, registers the server in Claude Desktop, and restarts it automatically.

## Configuration

**Most people don't need to set anything up.** When Digr starts, it
automatically finds common sample locations — your Splice downloads, any Ableton
libraries, and folders named "Samples" on your external drives.

On a different DAW, or keep your samples elsewhere? Just add the folder (below) —
Digr works with any sample collection, whatever made it.

### Adding your own folders

To add a folder Digr didn't find, copy its location from Finder (Mac) or File
Explorer (Windows), paste it into the chat, and ask your assistant to add it:

> "Add my samples folder at /Users/me/Music/Samples"

Digr saves it, and it's available in every session from then on — no files to
edit. Remove one the same way: "remove the Packs library."

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
| `activate_license` | Save a Pro license key and unlock Pro instantly (no restart) | Free |
| `analyze_sample` | Detect BPM and musical key (requires `[audio]`) | Pro |
| `search_samples_by_bpm` | Search and auto-detect BPM for each result | Pro |
| `read_midi` | Read MIDI file notes in bar\|beat format | Pro |
| `rename_with_metadata` | Rename with BPM/key appended (requires `[audio]`) | Pro |
| `sort_samples` | Sort into categorized subfolders | Pro |

**Digr Pro** unlocks BPM & key detection, MIDI reading, and automatic sample sorting.
**[Get a Digr Pro license →](https://sentinelprotocol.co.uk/digr/pro)**

Once you have your key, activate it by **pasting it to your AI assistant** and
asking it to activate Digr Pro — the `activate_license` tool saves the key for
you and unlocks Pro immediately, with no restart.

### Notes

- **Digr loads its audio engine in the background when it starts.** This
  usually takes a few seconds — on Windows the installer pre-loads the engine
  during installation, so even the very first launch starts warm. On an older
  machine, or one busy with something heavy (an OS update installing, say), a
  load can occasionally take a few minutes, and requests sent during it may
  wait or time out. If that happens, wait a minute or two and ask again —
  don't restart Claude or Digr, as a restart begins the load over. Once
  loaded, everything is fast for the rest of the session.

## License

Business Source License 1.1 — see the [full terms](LICENSE) for details.

Free for production use. You may not use this software to offer a competing commercial sample library management product or service. Converts to Apache 2.0 on 2029-03-19.
