# Changelog

All notable changes to Digr are documented here.

## [1.3.0] - 2026-09-25

### Changed
- Digr is now completely free. BPM and key detection, MIDI reading, auto-sort and rename-with-metadata no longer need a licence key.

### Removed
- The `activate_license` tool. There is nothing to activate any more, so the tool count is now 16. A licence key file left on disk from an earlier version is simply ignored.

## [1.2.0] - 2026-09-17

### Added
- Natural-language search: understands plurals, common abbreviations (hi-hat/hh, perc/percussion), and shows near-miss results labelled with the word they were missing, instead of just "no results."
- `search_samples_by_bpm` can now filter by a BPM range, and finds in-range samples even when they carry no BPM label.
- Every `rename_with_metadata` batch can now be undone with `undo_rename`.
- `analyze_sample` now reports native sample rate and duration.

### Fixed
- Your filename's BPM and key labels are now trusted over automatic detection, instead of being contradicted or silently overwritten.
- Search now ranks results across your whole library, not just the first batch of files it finds.
- An Ableton Pack's own internal preview clips no longer surface in search results as if they were real samples.
- Fixed a crash analyzing very short audio files.
- Ableton's compressed AIFF format now reports a clear message instead of a raw decode error.
- Improved tempo-detection accuracy for octave-related misreads.

### Changed
- Upgraded the underlying MCP SDK to the current major version (mcp 2.x).
