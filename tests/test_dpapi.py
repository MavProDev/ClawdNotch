"""Tests for DPAPI encryption/decryption of API keys."""

import sys


def test_dpapi_roundtrip():
    """Encrypt a key with DPAPI, then decrypt it — should get original back."""
    from claude_notch.config import _dpapi_encrypt, _dpapi_decrypt

    original = "sk-ant-api03-test-key-1234567890"
    encrypted = _dpapi_encrypt(original)

    if sys.platform == "win32":
        # On Windows, should get dpapi: prefix
        assert encrypted.startswith("dpapi:")
        assert encrypted != original
        decrypted = _dpapi_decrypt(encrypted)
        assert decrypted == original
    else:
        # On non-Windows, falls back to plaintext
        assert encrypted == original


def test_dpapi_decrypt_plaintext_passthrough():
    """Non-encrypted strings (no dpapi: prefix) pass through unchanged."""
    from claude_notch.config import _dpapi_decrypt

    plain = "sk-ant-api03-some-key"
    assert _dpapi_decrypt(plain) == plain


def test_dpapi_decrypt_invalid_data():
    """Corrupted dpapi: data returns as-is without crashing."""
    from claude_notch.config import _dpapi_decrypt

    corrupted = "dpapi:not-valid-base64!!!"
    result = _dpapi_decrypt(corrupted)
    assert result == ""  # returns empty string instead of ciphertext blob (security fix)


def test_config_manager_encrypts_on_migrate(tmp_config_dir):
    """ConfigManager._migrate() should encrypt plaintext API keys."""
    import json
    import claude_notch.config as cfg_mod

    # Write config with plaintext key
    config_file = tmp_config_dir / "config.json"
    config_file.write_text(json.dumps({
        "api_keys": [{"key": "sk-ant-test-key-plaintext", "label": "Test", "added": "2026-03-31"}]
    }))

    cm = cfg_mod.ConfigManager()

    if sys.platform == "win32":
        # Key should now be encrypted
        raw_key = cm.config["api_keys"][0]["key"]
        assert raw_key.startswith("dpapi:")
        # But get_api_keys_decrypted returns the original
        decrypted = cm.get_api_keys_decrypted()
        assert decrypted[0]["key"] == "sk-ant-test-key-plaintext"
    else:
        # Non-Windows: key stays as-is
        assert cm.config["api_keys"][0]["key"] == "sk-ant-test-key-plaintext"
