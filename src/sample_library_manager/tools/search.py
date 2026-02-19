"""Search tools: search_samples, search_samples_by_bpm."""

from pathlib import Path

from ._shared import (
    search_all_libraries,
    set_last_search_results,
)


def _require_librosa():
    """Import librosa and numpy, raising a clear error if not installed."""
    try:
        import librosa
        import numpy as np

        return librosa, np
    except ImportError:
        raise RuntimeError(
            "Audio analysis requires the 'audio' extras. "
            "Install with: pip install sample-library-manager[audio]"
        )


async def search_samples(keyword: str, max_results: int = 100) -> str:
    """Search for audio samples and MIDI files across all configured sample libraries.

    Matches keywords against the full file path including folder names.
    Multiple keywords are matched independently (all must appear).
    Results are balanced across libraries.
    """
    matches = search_all_libraries(keyword, max_results)

    if not matches:
        set_last_search_results([])
        return f"No samples found matching '{keyword}' across all libraries"

    # Cache results for collect_search_results
    set_last_search_results(matches)

    result = f"Found samples matching '{keyword}' (showing {len(matches)}):\n\n"
    for i, (path, library_name) in enumerate(matches, 1):
        filename = Path(path).name
        folder = Path(path).parent.name
        result += f"{i}. {filename}\n"
        result += f"   Library: {library_name}\n"
        result += f"   Folder: {folder}\n"
        result += f"   Path: {path}\n\n"

    result += "Use collect_search_results with the result numbers above to copy/move files to a folder."

    return result


async def search_samples_by_bpm(keyword: str, max_results: int = 20) -> str:
    """Search for samples by keyword and automatically detect BPM for each result.

    Useful for finding samples at specific tempos. Recommended 5-20 results for speed.
    Results are balanced across all configured libraries.
    """
    librosa, np = _require_librosa()

    matches = search_all_libraries(keyword, max_results)

    if not matches:
        return f"No samples found matching '{keyword}' across all libraries"

    result = f"Found {len(matches)} samples matching '{keyword}':\n"
    result += "Analyzing BPM (this may take a moment)...\n\n"

    for i, (path, library_name) in enumerate(matches, 1):
        filename = Path(path).name
        folder = Path(path).parent.name

        try:
            y, sr = librosa.load(path, duration=15)
            tempo_raw, _ = librosa.beat.beat_track(y=y, sr=sr)
            tempo = float(np.asarray(tempo_raw).item())

            result += f"{i}. {filename}\n"
            result += f"   BPM: {tempo:.1f}\n"
            result += f"   Library: {library_name}\n"
            result += f"   Folder: {folder}\n"
            result += f"   Path: {path}\n\n"

        except Exception as e:
            result += f"{i}. {filename}\n"
            result += f"   BPM: Unable to detect ({e})\n"
            result += f"   Library: {library_name}\n"
            result += f"   Folder: {folder}\n"
            result += f"   Path: {path}\n\n"

    return result
