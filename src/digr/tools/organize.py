"""Organize tools: collect_samples, copy_samples, collect_search_results, sort_samples, rename_with_metadata."""

from pathlib import Path
from typing import Union

from ._query import (
    SOURCE_DETECTED,
    extract_bpm_from_filename,
    extract_key_from_filename,
)
from ._rename_log import MAX_BATCHES, last_batch, record_batch, replace_last_batch
from ._shared import (
    audio_warming_message,
    copy_or_move,
    get_last_search_results,
    get_libraries,
    identify_library,
    parse_filepaths,
    parse_result_numbers,
    require_pro,
    search_all_libraries,
)


async def collect_samples(
    keyword: str,
    destination: str,
    max_results: int = 50,
    move: bool = False,
    flatten: bool = False,
    confirm: bool = False,
) -> str:
    """Copy or move samples matching a keyword into a destination folder.

    First call returns a PREVIEW. Call again with confirm=true to execute.
    """
    matches = search_all_libraries(keyword, max_results)
    if not matches:
        return f"No samples found matching '{keyword}' across all libraries"

    action = "MOVE" if move else "COPY"
    dest_path = Path(destination)

    if not confirm:
        result = f"PREVIEW -- {action} {len(matches)} samples to:\n"
        result += f"   {destination}\n"
        if flatten:
            result += "   (flatten: all files into one folder)\n"
        result += "\nFiles:\n"
        for i, (path, library_name) in enumerate(matches, 1):
            result += f"  {i}. {Path(path).name} ({library_name})\n"
        result += f"\nACTION REQUIRED: Call again with confirm=true to execute this {action.lower()}."
        if move:
            result += "\nWARNING: This will PERMANENTLY MOVE files -- originals will be deleted!"
        return result

    # Execute mode
    libraries = get_libraries()
    copied = 0
    errors = []
    for path, library_name in matches:
        src = Path(path)
        if flatten:
            target_dir = dest_path
        else:
            for lib_name, lib_path in libraries.items():
                if lib_name == library_name:
                    try:
                        rel = src.parent.relative_to(lib_path)
                        target_dir = dest_path / rel
                    except ValueError:
                        target_dir = dest_path
                    break
            else:
                target_dir = dest_path

        try:
            copy_or_move(src, target_dir, move=move)
            copied += 1
        except Exception as e:
            errors.append(f"{src.name}: {e}")

    action_past = "moved" if move else "copied"
    result = f"{action_past.capitalize()} {copied}/{len(matches)} samples to {destination}\n"
    if errors:
        result += f"\n{len(errors)} errors:\n"
        for err in errors:
            result += f"  - {err}\n"
    return result


async def copy_samples(
    filepaths: Union[list[str], str],
    destination: str,
    move: bool = False,
    confirm: bool = False,
) -> str:
    """Copy or move specific audio files by their exact file paths into a destination folder.

    First call returns a PREVIEW. Call again with confirm=true to execute.
    Accepts filepaths as a JSON array of strings.
    """
    paths = parse_filepaths(filepaths)
    if not paths:
        return "ERROR: No file paths provided"

    action = "MOVE" if move else "COPY"
    dest_path = Path(destination)

    # Validate all paths and identify their libraries
    file_info: list[tuple[Path, str]] = []
    missing: list[str] = []
    for filepath in paths:
        src = Path(filepath)
        if not src.exists():
            missing.append(filepath)
            continue
        library_name = identify_library(src)
        file_info.append((src, library_name))

    if not file_info and missing:
        return "ERROR: None of the provided files exist:\n" + "\n".join(
            f"  - {m}" for m in missing
        )

    if not confirm:
        result = f"PREVIEW -- {action} {len(file_info)} file(s) to:\n"
        result += f"   {destination}\n\n"
        result += "Files:\n"
        for i, (src, lib_name) in enumerate(file_info, 1):
            result += f"  {i}. {src.name} ({lib_name})\n"
        if missing:
            result += f"\n{len(missing)} file(s) not found (will be skipped):\n"
            for m in missing:
                result += f"  - {m}\n"
        result += f"\nACTION REQUIRED: Call again with confirm=true to execute this {action.lower()}."
        if move:
            result += "\nWARNING: This will PERMANENTLY MOVE files -- originals will be deleted!"
        return result

    # Execute mode
    done = 0
    errors = []
    for src, library_name in file_info:
        try:
            copy_or_move(src, dest_path, move=move)
            done += 1
        except Exception as e:
            errors.append(f"{src.name}: {e}")

    action_past = "moved" if move else "copied"
    result = f"{action_past.capitalize()} {done}/{len(file_info)} file(s) to {destination}\n"
    if missing:
        result += f"Skipped {len(missing)} missing file(s)\n"
    if errors:
        result += f"\n{len(errors)} error(s):\n"
        for err in errors:
            result += f"  - {err}\n"
    return result


async def collect_search_results(
    result_numbers: str,
    destination: str,
    move: bool = False,
    confirm: bool = False,
) -> str:
    """Copy or move specific samples from the LAST search_samples results by result number.

    Call search_samples first, then use result numbers (e.g., '1,3,7' or '1-5') to select files.
    First call returns a PREVIEW. Call again with confirm=true to execute.
    """
    last_results = get_last_search_results()
    if not last_results:
        return (
            "ERROR: No search results cached.\n"
            "Hint: Run search_samples(keyword=\"your keyword\") first, "
            "then use collect_search_results with the result numbers."
        )

    indices = parse_result_numbers(result_numbers)
    if not indices:
        return (
            f"ERROR: Could not parse result numbers from '{result_numbers}'. "
            "Use comma-separated numbers like '1,3,7' or ranges like '1-5'."
        )

    # Map 1-based result numbers to 0-based indices
    selected: list[tuple[str, str]] = []
    invalid: list[int] = []
    for num in indices:
        idx = num - 1
        if 0 <= idx < len(last_results):
            selected.append(last_results[idx])
        else:
            invalid.append(num)

    if not selected:
        return (
            f"ERROR: None of the result numbers are valid. "
            f"Last search had {len(last_results)} results (1-{len(last_results)})."
        )

    action = "MOVE" if move else "COPY"
    dest_path = Path(destination)

    if not confirm:
        result = f"PREVIEW -- {action} {len(selected)} file(s) to:\n"
        result += f"   {destination}\n\n"
        result += "Files:\n"
        for i, (path, library_name) in enumerate(selected, 1):
            result += f"  {i}. {Path(path).name} ({library_name})\n"
        if invalid:
            result += f"\nInvalid result numbers (skipped): {', '.join(str(n) for n in invalid)}\n"
        result += f"\nACTION REQUIRED: Call again with confirm=true to execute this {action.lower()}."
        if move:
            result += "\nWARNING: This will PERMANENTLY MOVE files -- originals will be deleted!"
        return result

    # Execute mode
    done = 0
    errors = []
    for path, library_name in selected:
        src = Path(path)
        try:
            copy_or_move(src, dest_path, move=move)
            done += 1
        except Exception as e:
            errors.append(f"{src.name}: {e}")

    action_past = "moved" if move else "copied"
    result = f"{action_past.capitalize()} {done}/{len(selected)} file(s) to {destination}\n"
    if errors:
        result += f"\n{len(errors)} error(s):\n"
        for err in errors:
            result += f"  - {err}\n"
    return result


async def rename_with_metadata(
    filepaths: Union[list[str], str],
    prefix: str | None = None,
    include_bpm: bool = False,
    include_key: bool = False,
    confirm: bool = False,
) -> str:
    """Rename audio samples by adding a prefix and/or appending detected BPM and musical key.

    First call returns a PREVIEW of old -> new names. Call again with confirm=true to execute.
    Prefix-only renaming is free. BPM/key detection requires a Pro license and [audio] extras.

    include_bpm and include_key default to FALSE and must be asked for. Both
    write a permanent, un-typed-back change to the user's filenames on the
    strength of an estimate, so they are opt-in rather than assumed. A tempo
    the filename already states is kept as-is and never overwritten; a tempo
    or key already present is not appended a second time.
    """
    needs_audio = include_bpm or include_key

    # Only gate behind Pro when audio analysis is requested
    if needs_audio:
        gate = require_pro("rename_with_metadata")
        if gate:
            return gate

        # If the heavy audio stack is still cold-loading in the background,
        # return a fast note instead of blocking past Claude's 240s timeout.
        warming = audio_warming_message()
        if warming:
            return warming

    audio_engine = None
    np = None
    if needs_audio:
        try:
            from . import _audio_analysis as audio_engine
            import numpy as np
        except ImportError:
            return (
                "ERROR: Audio analysis requires the 'audio' extras. "
                "Install with: pip install digr[audio]"
            )

    import warnings

    warnings.filterwarnings("ignore")

    paths = parse_filepaths(filepaths)
    if not paths:
        return "ERROR: No file paths provided"

    if not needs_audio and not prefix:
        return "ERROR: Nothing to do. Provide a prefix, or set include_bpm/include_key to true."

    # Analyze all files and build rename plan
    plan: list[tuple[Path, Path, str]] = []
    for filepath in paths:
        src = Path(filepath)
        if not src.exists():
            plan.append((src, src, "FILE NOT FOUND"))
            continue

        try:
            parts = []
            # Tags the file already carries. Reported so the preview explains
            # why it is shorter than the caller asked for, rather than looking
            # as though detection silently failed.
            already: list[str] = []
            stem = src.stem

            if needs_audio:
                y, sr = audio_engine.load_audio(str(src), duration=30)

                if include_bpm:
                    tempo_result = audio_engine.detect_tempo_with_hint(
                        y, sr=sr, filename=src.name
                    )
                    tempo = tempo_result.tempo
                    if tempo > 0:
                        # Compare as whole numbers: a stem saying "112" and a
                        # result of 112.0 are the same statement.
                        existing_bpm = extract_bpm_from_filename(stem)
                        if existing_bpm is not None and round(existing_bpm) == round(tempo):
                            already.append(f"{tempo:.0f}bpm already labelled")
                        else:
                            parts.append(f"{tempo:.0f}bpm")
                            # A label-sourced tempo normally dedups above,
                            # since the label came off this same stem. If one
                            # reaches here the stem said it in a form the
                            # dedup could not match, so the preview has to say
                            # the number was read rather than measured.
                            if tempo_result.source != SOURCE_DETECTED:
                                already.append("from the filename, not measured")

                if include_key:
                    chroma = audio_engine.compute_chroma(y, sr=sr)
                    key_idx = int(np.argmax(np.sum(chroma, axis=1)))
                    key_names = [
                        "C", "Cs", "D", "Ds", "E", "F",
                        "Fs", "G", "Gs", "A", "As", "B",
                    ]
                    # Enharmonics normalise, so a stem ending "D#m" already
                    # states the key that would be appended as "Ds".
                    existing_key = extract_key_from_filename(stem)
                    if existing_key == key_idx:
                        already.append(f"{key_names[key_idx]} already labelled")
                    else:
                        parts.append(key_names[key_idx])

            suffix = src.suffix
            new_name = prefix + "_" + stem if prefix else stem
            if parts:
                new_name += "_" + "_".join(parts)
            new_name += suffix
            new_path = src.parent / new_name
            info_parts = []
            if prefix:
                info_parts.append(f"prefix: {prefix}")
            if parts:
                info_parts.extend(parts)
            info_parts.extend(already)
            info = " + ".join(info_parts) if info_parts else "no changes"
            plan.append((src, new_path, info))

        except Exception as e:
            plan.append((src, src, f"ANALYSIS ERROR: {e}"))

    if not confirm:
        result = "PREVIEW -- Rename plan:\n\n"
        for old, new, info in plan:
            if old == new:
                result += f"  {old.name} -- {info} (SKIPPED)\n"
            else:
                result += f"  {old.name}\n  -> {new.name} ({info})\n\n"
        result += f"ACTION REQUIRED: Call again with confirm=true to rename these {len(plan)} files."
        result += "\nThis will modify filenames permanently."
        return result

    # Execute mode
    renamed = 0
    errors = []
    # Only the renames that actually landed, so the undo log never claims one
    # that did not happen.
    performed: list[tuple[Path, Path]] = []
    for old, new, info in plan:
        if old == new:
            continue
        try:
            old.rename(new)
            renamed += 1
            performed.append((old, new))
        except Exception as e:
            errors.append(f"{old.name}: {e}")

    # Recorded for EVERY rename, prefix-only included. The free path is just as
    # irreversible as the detected one -- a typo in a prefix applied to 500
    # files needs undo exactly as much as a wrong BPM does.
    record_batch(performed)

    result = f"Renamed {renamed}/{len(plan)} files\n"
    if errors:
        result += f"\n{len(errors)} errors:\n"
        for err in errors:
            result += f"  - {err}\n"
    if renamed:
        result += "\nTo reverse this, call undo_rename().\n"
    return result


async def undo_rename(confirm: bool = False) -> str:
    """Reverse the most recent rename_with_metadata batch, restoring old filenames.

    First call returns a PREVIEW of what would be restored. Call again with
    confirm=true to execute. Free tool -- no license required.
    """
    batch = last_batch()
    if batch is None:
        return (
            "ERROR: No renames to undo.\n"
            "Digr has no record of a rename in this config. Only renames made "
            "by rename_with_metadata are logged, and only the most recent "
            f"{MAX_BATCHES} batches are kept."
        )

    when = batch.get("timestamp", "an earlier run")
    entries = batch["renames"]

    # A rename is reversible only if the file is still where Digr left it and
    # the name it came from is still free. Both are checked BEFORE anything
    # moves, so the preview tells the truth about what confirm would do.
    restorable: list[tuple[Path, Path, dict]] = []
    blocked: list[str] = []
    blocked_entries: list[dict] = []
    for entry in entries:
        old, new = Path(entry["from"]), Path(entry["to"])
        if not new.exists():
            blocked.append(f"{new.name} — no longer there; moved or renamed again since")
            blocked_entries.append(entry)
        elif old.exists():
            blocked.append(f"{new.name} — cannot restore, {old.name} already exists")
            blocked_entries.append(entry)
        else:
            restorable.append((old, new, entry))

    if not confirm:
        result = f"PREVIEW -- Undo the rename batch from {when}:\n\n"
        for old, new, _ in restorable:
            result += f"  {new.name}\n  -> {old.name}\n\n"
        if blocked:
            result += f"{len(blocked)} file(s) CANNOT be restored and will be skipped:\n"
            for note in blocked:
                result += f"  - {note}\n"
            result += "\n"
        if not restorable:
            return result + "Nothing can be restored from this batch."
        result += (
            f"ACTION REQUIRED: Call again with confirm=true to restore "
            f"these {len(restorable)} file(s)."
        )
        return result

    restored = 0
    errors = []
    # Anything not put back stays in the log so a later undo can retry it.
    # Dropping the whole batch would strand exactly the files that failed.
    unreversed = list(blocked_entries)
    for old, new, entry in restorable:
        try:
            new.rename(old)
            restored += 1
        except Exception as e:
            errors.append(f"{new.name}: {e}")
            unreversed.append(entry)

    replace_last_batch(unreversed)

    result = f"Restored {restored}/{len(entries)} file(s) from the batch renamed at {when}\n"
    if blocked:
        result += f"\n{len(blocked)} skipped:\n"
        for note in blocked:
            result += f"  - {note}\n"
    if errors:
        result += f"\n{len(errors)} error(s):\n"
        for err in errors:
            result += f"  - {err}\n"
    if unreversed:
        result += (
            "\nThe entries that could not be restored are kept in the history, "
            "so undo_rename() can retry them once the obstruction is cleared.\n"
        )
    return result


async def sort_samples(
    source_keyword: str,
    destination: str,
    categories: str | None = None,
    max_results: int = 100,
    move: bool = False,
    confirm: bool = False,
) -> str:
    """Sort samples matching a keyword into categorized subfolders.

    Default categories: Kicks, Snares, Claps, HiHats, Percussion, Bass, FX, Loops, Other.
    First call returns a PREVIEW. Call again with confirm=true to execute. Pro feature.
    """
    gate = require_pro("sort_samples")
    if gate:
        return gate

    matches = search_all_libraries(source_keyword, max_results)
    if not matches:
        return f"No samples found matching '{source_keyword}' across all libraries"

    cat_list = [
        c.strip()
        for c in (
            categories or "Kicks,Snares,Claps,HiHats,Percussion,Bass,FX,Loops,Other"
        ).split(",")
    ]
    if "Other" in cat_list:
        cat_list.remove("Other")
    cat_list.append("Other")

    # Categorize each file
    sorted_files: dict[str, list[tuple[str, str]]] = {cat: [] for cat in cat_list}
    for path, library_name in matches:
        path_lower = str(path).lower()
        matched_cat = "Other"
        for cat in cat_list:
            if cat == "Other":
                continue
            if cat.lower() in path_lower:
                matched_cat = cat
                break
        sorted_files[matched_cat].append((path, library_name))

    action = "MOVE" if move else "COPY"
    dest_path = Path(destination)

    if not confirm:
        result = f"PREVIEW -- Sort {len(matches)} samples into {destination}:\n\n"
        for cat, files in sorted_files.items():
            if not files:
                continue
            result += f"  {cat}/ ({len(files)} files)\n"
            for path, lib_name in files[:5]:
                result += f"   - {Path(path).name} ({lib_name})\n"
            if len(files) > 5:
                result += f"   ... and {len(files) - 5} more\n"
            result += "\n"

        empty_cats = [c for c, f in sorted_files.items() if not f]
        if empty_cats:
            result += f"(Empty categories skipped: {', '.join(empty_cats)})\n\n"

        result += f"ACTION REQUIRED: Call again with confirm=true to execute this {action.lower()}."
        if move:
            result += "\nWARNING: This will PERMANENTLY MOVE files -- originals will be deleted!"
        return result

    # Execute mode
    total_done = 0
    errors = []
    summary: dict[str, int] = {}
    for cat, files in sorted_files.items():
        if not files:
            continue
        cat_dir = dest_path / cat
        done = 0
        for path, library_name in files:
            try:
                copy_or_move(Path(path), cat_dir, move=move)
                done += 1
            except Exception as e:
                errors.append(f"{Path(path).name}: {e}")
        summary[cat] = done
        total_done += done

    action_past = "moved" if move else "copied"
    result = f"{action_past.capitalize()} {total_done}/{len(matches)} samples into {destination}:\n\n"
    for cat, count in summary.items():
        result += f"  {cat}/: {count} files\n"
    if errors:
        result += f"\n{len(errors)} errors:\n"
        for err in errors:
            result += f"  - {err}\n"
    return result
