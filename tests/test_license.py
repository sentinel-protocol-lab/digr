"""Tests for Gumroad license verification, the offline token, and Pro tool gating.

No test here touches the network or the real config directory: the HTTP layer
is replaced via digr.licensing._http_post_form and the token file is pointed
at a pytest tmp_path.
"""

import json
import time
import urllib.error

import pytest

import digr.licensing as licensing
import digr.platform_detect as platform_detect
import digr.tools._shared as shared
from digr.licensing import (
    activate_or_check,
    read_activation_token,
    verify_license,
    write_activation_token,
)
from digr.tools._shared import is_pro_licensed, require_pro, set_license_key
from digr.tools.license import activate_license

TEST_KEY = "A1B2C3D4-E5F60718-9ABCDEF0-1234ABCD"


@pytest.fixture(autouse=True)
def isolated_token_path(tmp_path, monkeypatch):
    """Keep activation tokens inside the test's tmp directory."""
    monkeypatch.setattr(licensing, "_token_path", lambda: tmp_path / "license.token")
    return tmp_path / "license.token"


@pytest.fixture
def configured_product(monkeypatch):
    """Pretend the Gumroad product ID is configured."""
    monkeypatch.setenv("DIGR_GUMROAD_PRODUCT_ID", "prod_test_123")


def gumroad_response(*, success=True, uses=1, refunded=False, chargebacked=False):
    """A minimal Gumroad verify response body."""
    return {
        "success": success,
        "uses": uses,
        "purchase": {
            "license_key": TEST_KEY,
            "refunded": refunded,
            "chargebacked": chargebacked,
            "test": False,
        },
    }


def fake_post(status_code, body):
    """Build an _http_post_form replacement returning a canned response."""

    def _post(url, fields):
        _post.calls.append(fields)
        return status_code, body

    _post.calls = []
    return _post


class TestVerifyLicense:
    """The single Gumroad API call, every response shape."""

    def test_valid_key(self, configured_product, monkeypatch):
        monkeypatch.setattr(licensing, "_http_post_form", fake_post(200, gumroad_response()))
        result = verify_license(TEST_KEY, increment_uses=True)
        assert result.status == "valid"

    def test_unknown_key_404(self, configured_product, monkeypatch):
        monkeypatch.setattr(
            licensing,
            "_http_post_form",
            fake_post(404, {"success": False, "message": "That license does not exist..."}),
        )
        result = verify_license("WRONG-KEY", increment_uses=True)
        assert result.status == "invalid"
        assert "typo" in result.message.lower() or "recognised" in result.message.lower()

    def test_success_false_is_invalid(self, configured_product, monkeypatch):
        monkeypatch.setattr(
            licensing, "_http_post_form", fake_post(200, {"success": False})
        )
        assert verify_license(TEST_KEY, increment_uses=True).status == "invalid"

    def test_refunded_purchase(self, configured_product, monkeypatch):
        monkeypatch.setattr(
            licensing, "_http_post_form", fake_post(200, gumroad_response(refunded=True))
        )
        result = verify_license(TEST_KEY, increment_uses=False)
        assert result.status == "refunded"
        assert "free" in result.message.lower()

    def test_chargebacked_purchase(self, configured_product, monkeypatch):
        monkeypatch.setattr(
            licensing,
            "_http_post_form",
            fake_post(200, gumroad_response(chargebacked=True)),
        )
        assert verify_license(TEST_KEY, increment_uses=False).status == "refunded"

    def test_activation_limit_on_activation(self, configured_product, monkeypatch):
        monkeypatch.setattr(
            licensing, "_http_post_form", fake_post(200, gumroad_response(uses=6))
        )
        result = verify_license(TEST_KEY, increment_uses=True)
        assert result.status == "activation_limit"

    def test_high_uses_ok_on_recheck(self, configured_product, monkeypatch):
        # Re-checks don't activate a new device, so the cap doesn't apply.
        monkeypatch.setattr(
            licensing, "_http_post_form", fake_post(200, gumroad_response(uses=6))
        )
        assert verify_license(TEST_KEY, increment_uses=False).status == "valid"

    def test_network_error(self, configured_product, monkeypatch):
        def _post(url, fields):
            raise urllib.error.URLError("no route to host")

        monkeypatch.setattr(licensing, "_http_post_form", _post)
        result = verify_license(TEST_KEY, increment_uses=True)
        assert result.status == "network_error"
        assert "internet" in result.message.lower()

    def test_no_product_id_never_calls_api(self, monkeypatch):
        post = fake_post(200, gumroad_response())
        monkeypatch.setattr(licensing, "_http_post_form", post)
        result = verify_license(TEST_KEY, increment_uses=True)
        assert result.status == "not_configured"
        assert post.calls == []

    def test_increment_flag_sent_explicitly(self, configured_product, monkeypatch):
        # Gumroad defaults to incrementing, so "false" must be sent explicitly.
        post = fake_post(200, gumroad_response())
        monkeypatch.setattr(licensing, "_http_post_form", post)
        verify_license(TEST_KEY, increment_uses=False)
        assert post.calls[0]["increment_uses_count"] == "false"


class TestActivationToken:
    """The signed offline token file."""

    def test_roundtrip(self):
        write_activation_token(TEST_KEY)
        payload = read_activation_token(TEST_KEY)
        assert payload is not None
        assert payload["verified_at"] <= time.time()

    def test_missing_file(self):
        assert read_activation_token(TEST_KEY) is None

    def test_wrong_key_rejected(self):
        write_activation_token(TEST_KEY)
        assert read_activation_token("FFFFFFFF-FFFFFFFF-FFFFFFFF-FFFFFFFF") is None

    def test_tampered_payload_rejected(self, isolated_token_path):
        write_activation_token(TEST_KEY)
        token = json.loads(isolated_token_path.read_text())
        token["payload"]["verified_at"] = time.time() + 10_000_000
        isolated_token_path.write_text(json.dumps(token))
        assert read_activation_token(TEST_KEY) is None

    def test_garbage_file_rejected(self, isolated_token_path):
        isolated_token_path.write_text("not json at all")
        assert read_activation_token(TEST_KEY) is None

    def test_delete(self, isolated_token_path):
        write_activation_token(TEST_KEY)
        licensing.delete_activation_token()
        assert not isolated_token_path.exists()


class TestActivateOrCheck:
    """The full unlock decision."""

    def test_no_key(self):
        assert activate_or_check(None) == (False, None)

    def test_first_activation_writes_token(self, configured_product, monkeypatch):
        post = fake_post(200, gumroad_response())
        monkeypatch.setattr(licensing, "_http_post_form", post)
        licensed, reason = activate_or_check(TEST_KEY)
        assert licensed and reason is None
        assert post.calls[0]["increment_uses_count"] == "true"
        assert read_activation_token(TEST_KEY) is not None

    def test_failed_activation_no_token(self, configured_product, monkeypatch):
        monkeypatch.setattr(
            licensing, "_http_post_form", fake_post(404, {"success": False})
        )
        licensed, reason = activate_or_check(TEST_KEY)
        assert not licensed
        assert reason
        assert read_activation_token(TEST_KEY) is None

    def test_fresh_token_skips_network(self, monkeypatch):
        write_activation_token(TEST_KEY)

        def _post(url, fields):
            raise AssertionError("network must not be touched with a fresh token")

        monkeypatch.setattr(licensing, "_http_post_form", _post)
        assert activate_or_check(TEST_KEY) == (True, None)

    def test_stale_token_rechecked_and_refreshed(self, configured_product, monkeypatch):
        write_activation_token(TEST_KEY)
        monkeypatch.setattr(licensing, "_needs_recheck", lambda payload: True)
        post = fake_post(200, gumroad_response())
        monkeypatch.setattr(licensing, "_http_post_form", post)
        assert activate_or_check(TEST_KEY) == (True, None)
        assert post.calls[0]["increment_uses_count"] == "false"

    def test_stale_token_refunded_locks_and_deletes(self, configured_product, monkeypatch):
        write_activation_token(TEST_KEY)
        monkeypatch.setattr(licensing, "_needs_recheck", lambda payload: True)
        monkeypatch.setattr(
            licensing, "_http_post_form", fake_post(200, gumroad_response(refunded=True))
        )
        licensed, reason = activate_or_check(TEST_KEY)
        assert not licensed
        assert "refunded" in reason.lower()
        assert read_activation_token(TEST_KEY) is None

    def test_stale_token_offline_keeps_working(self, configured_product, monkeypatch):
        write_activation_token(TEST_KEY)
        monkeypatch.setattr(licensing, "_needs_recheck", lambda payload: True)

        def _post(url, fields):
            raise urllib.error.URLError("offline")

        monkeypatch.setattr(licensing, "_http_post_form", _post)
        assert activate_or_check(TEST_KEY) == (True, None)

    def test_stale_token_unknown_key_keeps_working(self, configured_product, monkeypatch):
        # A proven-good install must NOT be locked out just because the product
        # was taken down or the seller vanished (Gumroad answers "not found").
        # Contrast with test_failed_activation_no_token: the same 404 refuses a
        # FIRST activation but keeps an already-activated customer unlocked.
        write_activation_token(TEST_KEY)
        monkeypatch.setattr(licensing, "_needs_recheck", lambda payload: True)
        monkeypatch.setattr(
            licensing, "_http_post_form", fake_post(404, {"success": False})
        )
        assert activate_or_check(TEST_KEY) == (True, None)
        assert read_activation_token(TEST_KEY) is not None  # token kept, not deleted


class TestRequireProGating:
    """require_pro messages and pass-through."""

    def setup_method(self):
        self._original = shared.ENFORCE_LICENSE_GATE
        shared.ENFORCE_LICENSE_GATE = True

    def teardown_method(self):
        shared.ENFORCE_LICENSE_GATE = self._original

    def test_blocks_without_license(self):
        set_license_key(None)
        result = require_pro("analyze_sample")
        assert result is not None
        assert "Pro feature" in result

    def test_message_contains_tool_name(self):
        set_license_key(None)
        assert "analyze_sample" in require_pro("analyze_sample")

    def test_message_contains_setup_instructions(self):
        set_license_key(None)
        result = require_pro("read_midi")
        assert "license.key" in result
        assert "DIGR_LICENSE_KEY" in result

    def test_message_shows_this_platforms_key_path(self):
        # The manual-setup path must be the REAL location for this OS
        # (e.g. %APPDATA%\digr on Windows), not a hardcoded Mac path.
        from digr.platform_detect import default_config_dir

        set_license_key(None)
        result = require_pro("read_midi")
        assert str(default_config_dir() / "license.key") in result

    def test_message_offers_paste_activation(self):
        # The gate should nudge the frictionless path: paste the key, no restart.
        set_license_key(None)
        result = require_pro("analyze_sample")
        assert "paste" in result.lower()

    def test_message_contains_purchase_url(self):
        set_license_key(None)
        assert "sentinelprotocol.co.uk/digr" in require_pro("read_midi")

    def test_message_lists_free_tools(self):
        set_license_key(None)
        result = require_pro("sort_samples")
        assert "search_samples" in result
        assert "collect_search_results" in result

    def test_failure_reason_shown_to_user(self, configured_product, monkeypatch):
        monkeypatch.setattr(
            licensing, "_http_post_form", fake_post(404, {"success": False})
        )
        set_license_key("WRONG-KEY")
        result = require_pro("analyze_sample")
        assert result is not None
        assert "recognised" in result.lower()

    def test_passes_with_activated_license(self, configured_product, monkeypatch):
        monkeypatch.setattr(licensing, "_http_post_form", fake_post(200, gumroad_response()))
        set_license_key(TEST_KEY)
        assert require_pro("analyze_sample") is None
        assert is_pro_licensed()

    def test_passes_for_all_pro_tools(self, configured_product, monkeypatch):
        monkeypatch.setattr(licensing, "_http_post_form", fake_post(200, gumroad_response()))
        set_license_key(TEST_KEY)
        for tool in ["analyze_sample", "read_midi", "search_samples_by_bpm",
                     "sort_samples", "rename_with_metadata"]:
            assert require_pro(tool) is None

    def test_activation_happens_once_per_run(self, configured_product, monkeypatch):
        post = fake_post(200, gumroad_response())
        monkeypatch.setattr(licensing, "_http_post_form", post)
        set_license_key(TEST_KEY)
        require_pro("analyze_sample")
        licensing.delete_activation_token()  # force re-activation if memoization broke
        require_pro("read_midi")
        require_pro("sort_samples")
        assert len(post.calls) == 1


class TestEnforceLicenseGateOff:
    """All Pro tools unlocked when ENFORCE_LICENSE_GATE is False."""

    def setup_method(self):
        self._original = shared.ENFORCE_LICENSE_GATE
        shared.ENFORCE_LICENSE_GATE = False

    def teardown_method(self):
        shared.ENFORCE_LICENSE_GATE = self._original

    def test_all_pro_tools_unlocked_without_key(self):
        set_license_key(None)
        for tool in ["analyze_sample", "read_midi", "search_samples_by_bpm",
                     "sort_samples", "rename_with_metadata"]:
            assert require_pro(tool) is None


@pytest.fixture
def isolated_config_dir(tmp_path, monkeypatch):
    """Point the saved-key location (default_config_dir) at the test tmp dir.

    The activation token is already isolated by the autouse isolated_token_path
    fixture; this covers the license.key file the activate_license tool writes.
    """
    monkeypatch.setattr(platform_detect, "default_config_dir", lambda: tmp_path)
    return tmp_path


class TestActivateLicenseTool:
    """The activate_license tool: paste a key -> Pro unlocked + key saved, no restart."""

    def setup_method(self):
        self._original = shared.ENFORCE_LICENSE_GATE
        shared.ENFORCE_LICENSE_GATE = True

    def teardown_method(self):
        shared.ENFORCE_LICENSE_GATE = self._original

    async def test_valid_key_unlocks_in_session_and_saves(
        self, configured_product, isolated_config_dir, monkeypatch
    ):
        monkeypatch.setattr(licensing, "_http_post_form", fake_post(200, gumroad_response()))
        result = await activate_license(TEST_KEY)

        assert "activated" in result.lower()
        # Pro is live this session with no restart...
        assert require_pro("analyze_sample") is None
        assert is_pro_licensed()
        # ...and the key was saved for next time, exact bytes, no BOM.
        key_file = isolated_config_dir / "license.key"
        assert key_file.read_bytes() == TEST_KEY.encode("utf-8")

    async def test_pasted_whitespace_is_trimmed_before_saving(
        self, configured_product, isolated_config_dir, monkeypatch
    ):
        monkeypatch.setattr(licensing, "_http_post_form", fake_post(200, gumroad_response()))
        await activate_license(f"  {TEST_KEY}\n")
        assert (isolated_config_dir / "license.key").read_text(encoding="utf-8") == TEST_KEY

    async def test_typo_key_reports_and_does_not_save(
        self, configured_product, isolated_config_dir, monkeypatch
    ):
        monkeypatch.setattr(licensing, "_http_post_form", fake_post(404, {"success": False}))
        result = await activate_license("WRONG-KEY")

        assert "couldn't activate" in result.lower()
        assert "recognised" in result.lower()
        assert not (isolated_config_dir / "license.key").exists()
        assert require_pro("analyze_sample") is not None  # still locked

    async def test_offline_refuses_and_saves_nothing(
        self, configured_product, isolated_config_dir, monkeypatch
    ):
        # Option A: no internet on first activation -> tell them to reconnect,
        # and DON'T leave a key file behind.
        def _post(url, fields):
            raise urllib.error.URLError("offline")

        monkeypatch.setattr(licensing, "_http_post_form", _post)
        result = await activate_license(TEST_KEY)

        assert "couldn't activate" in result.lower()
        assert "internet" in result.lower()
        assert not (isolated_config_dir / "license.key").exists()

    async def test_empty_key_prompts_without_touching_network(
        self, isolated_config_dir, monkeypatch
    ):
        post = fake_post(200, gumroad_response())
        monkeypatch.setattr(licensing, "_http_post_form", post)
        result = await activate_license("   ")

        assert "no license key" in result.lower()
        assert post.calls == []
        assert not (isolated_config_dir / "license.key").exists()

    async def test_already_activated_machine_resaves_key_without_network(
        self, isolated_config_dir, monkeypatch
    ):
        # A machine that already holds a valid token (e.g. activated earlier via
        # env var) can re-paste to persist the key file, with no network call.
        write_activation_token(TEST_KEY)

        def _post(url, fields):
            raise AssertionError("network must not be touched with a fresh token")

        monkeypatch.setattr(licensing, "_http_post_form", _post)
        result = await activate_license(TEST_KEY)

        assert "activated" in result.lower()
        assert (isolated_config_dir / "license.key").read_text(encoding="utf-8") == TEST_KEY
