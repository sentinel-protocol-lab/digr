"""License tool: activate_license — save the Pro key and unlock Pro in-session.

This is the frictionless activation path. The customer pastes the license key
from their Gumroad receipt; this tool verifies it, saves it to the right place
for them, and turns on the Pro tools immediately — no Notepad, no hunting for a
config folder, no Claude restart. The manual file/env-var route still works for
anyone who prefers it (see config.py and the require_pro message).
"""

from ._shared import activate_license_key


async def activate_license(license_key: str) -> str:
    """Activate Digr Pro with a license key — saves it and unlocks Pro right away, no restart.

    Use this whenever the user provides or pastes their Digr Pro license key
    (from their Gumroad receipt) and wants to turn on the Pro features. It
    verifies the key, saves it to the correct location automatically, and
    unlocks the Pro tools (BPM/key detection, MIDI reading, auto-sort, metadata
    renaming) for the current session immediately.

    Args:
        license_key: The Pro license key from the Gumroad receipt. Looks like
            XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX.
    """
    key = license_key.strip() if isinstance(license_key, str) else ""
    if not key:
        return (
            "No license key found. Paste the key from your Gumroad receipt "
            "(it looks like XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX) and I'll "
            "activate it."
        )

    # Verify against Gumroad and refresh the gate so Pro works this session.
    licensed, reason = activate_license_key(key)

    if not licensed:
        # Option A: on ANY failure — typo, refund, activation limit, or no
        # internet — we deliberately do NOT save the key. That way a mistyped
        # key or an offline attempt never leaves a broken key file on disk for
        # the next startup to choke on. The reason text already tells the user
        # what to do next (fix the typo, reconnect, etc.).
        detail = reason or (
            "That key wasn't recognised. Check it for typos and try again."
        )
        return f"Couldn't activate Digr Pro.\n\n{detail}\n\nFix that, then paste your key again."

    # Verified. Persist the key (clean UTF-8, no BOM, key only) so Pro stays
    # unlocked across restarts too — not just this session. The activation token
    # was already written by the verification step above.
    save_warning = ""
    try:
        from ..platform_detect import default_config_dir

        key_path = default_config_dir() / "license.key"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(key, encoding="utf-8")
    except OSError:
        # Pro is live for this session regardless; we just couldn't save the
        # file for next time. Tell the truth rather than claim a clean save.
        save_warning = (
            "\n\n(Note: I couldn't save the key file, so you may need to "
            "activate again after restarting. Pro is unlocked for now.)"
        )

    return (
        "Digr Pro is activated. The Pro tools — BPM/key detection, MIDI "
        "reading, auto-sort, and metadata renaming — are unlocked and ready to "
        "use now, no restart needed." + save_warning
    )
