"""The rename history that makes ``rename_with_metadata`` reversible.

A rename that is wrong but undoable is a nuisance. A rename that is wrong and
permanent is data loss -- and every rename Digr performed used to be the second
kind, including the prefix-only ones that involve no detection at all. Prefix
500 files with a typo and it was a manual repair job.

The log lives in the CONFIG DIR, not beside the samples. That directory is
already the only place Digr writes outside a destination folder, and
``DIGR_CONFIG_DIR`` isolates it for tests. Writing it next to the user's audio
would litter their library and would not survive moving the files.

One JSON object per line, one line per BATCH -- a batch being everything a
single confirmed ``rename_with_metadata`` call renamed. Batches are the unit of
undo because they are the unit the user actually thinks in: "put back what that
last call did".

Stdlib only, so the free path can import it. Undo must never need the audio
extra -- see ``undo_rename``, which is deliberately free.
"""

import json
from datetime import datetime
from pathlib import Path

from ..platform_detect import default_config_dir

HISTORY_FILENAME = "rename_history.jsonl"

# How many batches to keep. The log is an append-only file in the user's config
# dir with nothing to prune it, so it needs its own ceiling or it grows for the
# life of the install. Deep history is not what this is for: undo is reached
# for within minutes of a rename that went wrong, so the recent end is the only
# end that matters.
MAX_BATCHES = 50


def history_path() -> Path:
    """Where the log lives. Resolved per call, never cached, because
    ``DIGR_CONFIG_DIR`` is read at call time and the test suite repoints it."""
    return default_config_dir() / HISTORY_FILENAME


def read_batches() -> list[dict]:
    """Every batch in the log, oldest first.

    A line that will not parse is SKIPPED rather than raised on. This file is
    read at the moment a user is trying to undo damage; a stray corrupt line
    must not be what stops them getting the rest of their history back.
    """
    path = history_path()
    if not path.exists():
        return []

    batches = []
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return []

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            batch = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(batch, dict) and batch.get("renames"):
            batches.append(batch)
    return batches


def _write_batches(batches: list[dict]) -> None:
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(b, ensure_ascii=False) for b in batches[-MAX_BATCHES:]]
    content = "".join(line + "\n" for line in lines)
    path.write_text(content, encoding="utf-8")


def record_batch(renames: list[tuple[Path, Path]]) -> None:
    """Append one batch: every ``(old, new)`` pair that actually got renamed.

    Called after the renames land, with only the ones that succeeded, so the
    log never claims a rename that did not happen. Failures here are swallowed:
    a config dir that cannot be written is a reason to lose the undo record,
    never a reason to fail a rename the user already confirmed and that has
    already happened on disk.
    """
    if not renames:
        return

    batch = {
        "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "renames": [{"from": str(old), "to": str(new)} for old, new in renames],
    }
    try:
        _write_batches(read_batches() + [batch])
    except OSError:
        pass


def last_batch() -> dict | None:
    """The most recent batch, or None when there is nothing to undo."""
    batches = read_batches()
    return batches[-1] if batches else None


def replace_last_batch(unreversed: list[dict]) -> None:
    """Swap the newest batch for whatever of it could not be reversed.

    ``unreversed`` is the ``renames`` entries that were SKIPPED. Entries put
    back successfully are dropped; skipped ones STAY, so a later undo can retry
    them. Dropping the whole batch would strand exactly the files that failed
    to restore -- the permanent-loss problem this log exists to remove.
    """
    batches = read_batches()
    if not batches:
        return

    newest = batches.pop()
    if unreversed:
        batches.append({"timestamp": newest["timestamp"], "renames": unreversed})
    try:
        _write_batches(batches)
    except OSError:
        pass
