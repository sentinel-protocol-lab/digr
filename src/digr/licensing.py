"""License activation against Gumroad, with a signed local token for offline use.

Flow:
1. First run with a key: ask Gumroad's verify API whether the key is genuine.
   This counts as one "activation"; a license allows MAX_ACTIVATIONS devices.
2. On success: save a signed token file so later runs work offline without
   contacting Gumroad again (and without burning further activations).
3. Every RECHECK_DAYS, silently re-confirm the key with Gumroad (without
   incrementing the activation count) so refunded keys degrade back to the
   free tier. If offline at re-check time, the saved token keeps working.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

GUMROAD_VERIFY_URL = "https://api.gumroad.com/v2/licenses/verify"

# The DIGR Pro product on Gumroad. Not a secret — it ships in the client and
# only identifies which product a license key is checked against.
GUMROAD_PRODUCT_ID: str | None = "hM1w8acHqoJeNaMorXv8gw=="

MAX_ACTIVATIONS = 5

# Days between silent re-checks of an already-activated license. Matches the
# 14-day refund window so a refunded key stops unlocking Pro within one cycle.
RECHECK_DAYS = 14

_REQUEST_TIMEOUT_SECONDS = 10

# Signs the local token file so it can't be casually hand-edited. Anyone
# determined can extract this from the source; that is an accepted trade-off
# for a one-time-purchase tool, not a defect to fix with heavier DRM.
_TOKEN_SECRET = b"digr-license-token-v1-2f8a91c4d7e6b350"


@dataclass
class VerifyResult:
    """Outcome of one Gumroad verify call.

    status is one of: "valid", "invalid", "refunded", "activation_limit",
    "network_error", "not_configured". message is shown to the user when
    Pro stays locked, so it must be plain English with a next step.
    """

    status: str
    message: str
    uses: int | None = None


def _product_id() -> str | None:
    return os.environ.get("DIGR_GUMROAD_PRODUCT_ID") or GUMROAD_PRODUCT_ID


def _http_post_form(url: str, fields: dict[str, str]) -> tuple[int, dict]:
    """POST form fields; return (HTTP status, decoded JSON body).

    Gumroad answers 404 (with a JSON body) for unknown keys, so HTTP errors
    are returned as data rather than raised. Network-level failures still
    raise (URLError/TimeoutError/OSError) for the caller to handle.

    Tests replace this function to simulate Gumroad responses.
    """
    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            body = {}
        return error.code, body


def verify_license(license_key: str, *, increment_uses: bool) -> VerifyResult:
    """Ask Gumroad whether this key belongs to a real, non-refunded purchase.

    increment_uses=True counts as an activation (first unlock on a device);
    False is for silent re-checks. Gumroad's default is to increment, so the
    flag is always sent explicitly.
    """
    product_id = _product_id()
    if not product_id:
        return VerifyResult(
            "not_configured",
            "This build can't check licenses yet (no product configured). "
            "Please report this at https://github.com/sentinel-protocol-lab/digr/issues",
        )

    fields = {
        "product_id": product_id,
        "license_key": license_key,
        "increment_uses_count": "true" if increment_uses else "false",
    }
    try:
        status_code, body = _http_post_form(GUMROAD_VERIFY_URL, fields)
    except (urllib.error.URLError, TimeoutError, OSError):
        return VerifyResult(
            "network_error",
            "Couldn't reach the license server. Check your internet "
            "connection and try the Pro tool again.",
        )

    if status_code == 404 or not body.get("success"):
        return VerifyResult(
            "invalid",
            "That license key wasn't recognised. Check it for typos (it looks "
            "like XXXXXXXX-XXXXXXXX-XXXXXXXX-XXXXXXXX, from your Gumroad "
            "receipt). Still stuck? Email support with your receipt.",
        )

    purchase = body.get("purchase") or {}
    if purchase.get("refunded") or purchase.get("chargebacked") or purchase.get("disputed"):
        return VerifyResult(
            "refunded",
            "This purchase was refunded, so Pro features are switched off. "
            "The free tools all still work. To unlock Pro again, buy a new "
            "license at https://sentinelprotocol.co.uk/digr",
        )

    uses = body.get("uses") if isinstance(body.get("uses"), int) else None
    if increment_uses and uses is not None and uses > MAX_ACTIVATIONS:
        return VerifyResult(
            "activation_limit",
            f"This license key has already been activated on "
            f"{MAX_ACTIVATIONS} devices, which is the limit. If you've "
            f"replaced an old machine, email support with your receipt and "
            f"we'll reset it.",
            uses=uses,
        )

    return VerifyResult("valid", "License verified.", uses=uses)


# --- Local activation token ---


def _token_path() -> Path:
    from .platform_detect import default_config_dir

    return default_config_dir() / "license.token"


def _key_fingerprint(license_key: str) -> str:
    return hashlib.sha256(license_key.encode("utf-8")).hexdigest()


def _sign(payload_bytes: bytes) -> str:
    return hmac.new(_TOKEN_SECRET, payload_bytes, hashlib.sha256).hexdigest()


def write_activation_token(license_key: str) -> None:
    """Record a successful verification so future runs work offline."""
    payload = {
        "key_fingerprint": _key_fingerprint(license_key),
        "verified_at": time.time(),
    }
    payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
    token = {"payload": payload, "signature": _sign(payload_bytes)}
    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(token, indent=2), encoding="utf-8")


def read_activation_token(license_key: str) -> dict | None:
    """Return the token payload if it exists, is untampered, and matches this key."""
    path = _token_path()
    if not path.exists():
        return None
    try:
        token = json.loads(path.read_text(encoding="utf-8"))
        payload = token["payload"]
        payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
        if not hmac.compare_digest(token["signature"], _sign(payload_bytes)):
            return None
        if payload.get("key_fingerprint") != _key_fingerprint(license_key):
            return None
        return payload
    except (json.JSONDecodeError, KeyError, TypeError, OSError, UnicodeDecodeError):
        return None


def delete_activation_token() -> None:
    try:
        _token_path().unlink(missing_ok=True)
    except OSError:
        pass


def _needs_recheck(payload: dict) -> bool:
    verified_at = payload.get("verified_at")
    if not isinstance(verified_at, (int, float)):
        return True
    return (time.time() - verified_at) > RECHECK_DAYS * 86400


def activate_or_check(license_key: str | None) -> tuple[bool, str | None]:
    """Decide whether Pro is unlocked. Returns (licensed, reason_if_not).

    Fail-closed: anything unexpected leaves Pro locked. The one deliberate
    exception is a previously activated install that can't reach Gumroad at
    re-check time — the saved token keeps working so a flaky connection never
    locks a paying customer out.
    """
    if not license_key:
        return False, None

    payload = read_activation_token(license_key)
    if payload is not None:
        if not _needs_recheck(payload):
            return True, None
        result = verify_license(license_key, increment_uses=False)
        if result.status == "valid":
            write_activation_token(license_key)
            return True, None
        if result.status in ("network_error", "not_configured"):
            return True, None
        delete_activation_token()
        return False, result.message

    result = verify_license(license_key, increment_uses=True)
    if result.status == "valid":
        write_activation_token(license_key)
        return True, None
    return False, result.message
