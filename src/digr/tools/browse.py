"""Browse tools: list_folders, list_libraries, add_library, remove_library, count_samples_in_folder, list_all_samples_in_folder."""

from pathlib import Path

from ._shared import add_library_entry, get_libraries, remove_library_entry


async def list_libraries() -> str:
    """Show all configured sample library locations and whether they are accessible."""
    libraries = get_libraries()
    if not libraries:
        return (
            "No sample libraries configured.\n\n"
            "Use the add_library tool to add a sample folder. "
            "Just provide a name and the folder path.\n\n"
            "Example: add_library(name='My Samples', path='~/Music/Samples')"
        )

    result = "Configured Sample Libraries:\n\n"
    for i, (name, library) in enumerate(libraries.items(), 1):
        status = "Available" if library.exists() else "Not Found"
        result += f"{i}. [{status}] {name}\n"
        result += f"   Path: {library}\n\n"

    return result


async def add_library(name: str, path: str) -> str:
    """Add a sample library folder so all tools can access it. Saves to config and takes effect immediately.

    Args:
        name: A friendly name for this library (e.g. 'Music Samples', 'Drum Kits').
        path: The full folder path on disk (e.g. '~/Music/Samples' or 'D:/Samples').
    """
    folder = Path(path).expanduser().resolve()

    if not folder.exists():
        return (
            f"Folder not found: {folder}\n\n"
            f"Please check the path and try again. "
            f"Tip: drag the folder from Finder into the chat to paste the exact path."
        )

    if not folder.is_dir():
        return f"'{folder}' is a file, not a folder. Please provide a folder path."

    add_library_entry(name, folder)

    # Quick count of audio files for confirmation
    audio_count = 0
    for ext in ["*.wav", "*.aif", "*.aiff", "*.mp3", "*.flac", "*.ogg"]:
        audio_count += len(list(folder.rglob(ext)))

    midi_count = len(list(folder.rglob("*.mid"))) + len(list(folder.rglob("*.midi")))

    return (
        f"Library '{name}' added successfully!\n\n"
        f"  Path: {folder}\n"
        f"  Audio files found: {audio_count}\n"
        f"  MIDI files found: {midi_count}\n\n"
        f"You can now search, browse, and analyze samples in this library."
    )


async def remove_library(name: str) -> str:
    """Remove a sample library from the configuration. Does not delete any files on disk.

    Args:
        name: The name of the library to remove (as shown by list_libraries).
    """
    if remove_library_entry(name):
        return f"Library '{name}' removed from configuration. No files were deleted."
    else:
        libraries = get_libraries()
        if libraries:
            available = ", ".join(f"'{n}'" for n in libraries)
            return f"Library '{name}' not found. Available libraries: {available}"
        return f"Library '{name}' not found. No libraries are currently configured."


async def list_folders() -> str:
    """List all top-level folders across all configured sample libraries."""
    libraries = get_libraries()
    all_folders = []

    for library_name, library in libraries.items():
        if not library.exists():
            continue

        try:
            folders = [
                f for f in library.iterdir() if f.is_dir() and not f.name.startswith(".")
            ]
            for folder in folders:
                all_folders.append((library_name, folder.name))
        except (PermissionError, OSError):
            continue

    if not all_folders:
        return "No accessible folders found in any library"

    result = f"Found {len(all_folders)} folders across all libraries:\n\n"

    current_library = None
    for library_name, folder_name in sorted(all_folders):
        if current_library != library_name:
            current_library = library_name
            result += f"\n{library_name}:\n"
        result += f"   - {folder_name}\n"

    return result


async def count_samples_in_folder(folder_name: str) -> str:
    """Count how many audio samples and MIDI files are in a specific folder across all libraries."""
    libraries = get_libraries()

    total_wav = 0
    total_aif = 0
    total_mid = 0
    found_in = []

    for library_name, library in libraries.items():
        if not library.exists():
            continue

        folder_path = library / folder_name

        if folder_path.exists():
            try:
                wav_count = len(list(folder_path.rglob("*.wav")))
                aif_count = len(list(folder_path.rglob("*.aif"))) + len(
                    list(folder_path.rglob("*.aiff"))
                )
                mp3_count = (
                    len(list(folder_path.rglob("*.mp3")))
                    + len(list(folder_path.rglob("*.flac")))
                    + len(list(folder_path.rglob("*.ogg")))
                )
                mid_count = len(list(folder_path.rglob("*.mid"))) + len(
                    list(folder_path.rglob("*.midi"))
                )

                total_files = wav_count + aif_count + mp3_count + mid_count
                if total_files > 0:
                    total_wav += wav_count
                    total_aif += aif_count
                    total_mid += mid_count
                    found_in.append(f"{library_name}: {total_files} files")
            except (PermissionError, OSError):
                continue

    if not found_in:
        return f"Folder '{folder_name}' not found in any library"

    result = f"Sample count for '{folder_name}':\n\n"
    for location in found_in:
        result += f"  {location}\n"
    result += f"\nTotal across all libraries:\n"
    result += f"WAV files: {total_wav}\n"
    result += f"AIF/AIFF files: {total_aif}\n"
    result += f"MIDI files: {total_mid}\n"
    result += f"Grand Total: {total_wav + total_aif + total_mid} files\n"

    return result


async def list_all_samples_in_folder(folder_name: str, max_results: int = 100) -> str:
    """List all audio samples and MIDI files in a specific folder across all libraries."""
    libraries = get_libraries()
    samples = []

    for library_name, library in libraries.items():
        if not library.exists():
            continue

        folder_path = library / folder_name

        if not folder_path.exists():
            continue

        try:
            for extension in [
                "*.wav", "*.aif", "*.aiff", "*.mp3", "*.flac", "*.ogg",
                "*.mid", "*.midi",
            ]:
                for file_path in folder_path.rglob(extension):
                    samples.append((str(file_path), library_name))
                    if len(samples) >= max_results:
                        break
                if len(samples) >= max_results:
                    break
        except (PermissionError, OSError):
            continue

        if len(samples) >= max_results:
            break

    if not samples:
        return f"No samples found in folder '{folder_name}' across any library"

    result = f"Listing samples in '{folder_name}' (showing {len(samples)}):\n\n"

    for i, (path, library_name) in enumerate(samples, 1):
        filename = Path(path).name
        subfolder = Path(path).parent.name
        result += f"{i}. {filename}\n"
        result += f"   Library: {library_name}\n"
        if subfolder != folder_name:
            result += f"   Subfolder: {subfolder}\n"
        result += f"   Path: {path}\n\n"

    if len(samples) >= max_results:
        result += f"\n(Showing first {max_results} results. Increase max_results to see more.)"

    return result
