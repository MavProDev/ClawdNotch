"""Tests for claude_notch.config — defaults, themes, atomic writes, ConfigManager."""

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claude_notch.config import (
    DEFAULT_CONFIG,
    THEMES,
    C,
    apply_theme,
    _atomic_write,
    _redact_key,
    ConfigManager,
)


# ── DEFAULT_CONFIG ──────────────────────────────────────────────────────────

def test_default_config_has_all_keys():
    """DEFAULT_CONFIG must have at least 35 keys (documented contract)."""
    assert len(DEFAULT_CONFIG) >= 35, (
        f"Expected >=35 keys in DEFAULT_CONFIG, got {len(DEFAULT_CONFIG)}"
    )


# ── THEMES ──────────────────────────────────────────────────────────────────

def test_themes_count():
    """There must be exactly 8 colour themes."""
    assert len(THEMES) == 8
    for name in ("coral", "blue", "green", "purple", "cyan", "amber", "pink", "red"):
        assert name in THEMES, f"Missing theme: {name}"


# ── apply_theme ─────────────────────────────────────────────────────────────

def test_apply_theme_changes_C():
    """apply_theme('blue') should change C['coral'] to the blue accent."""
    from PyQt6.QtGui import QColor
    original = C["coral"].getRgb()
    apply_theme("blue")
    blue_accent = QColor(*THEMES["blue"]["accent"])
    assert C["coral"].getRgb() == blue_accent.getRgb()
    # Restore default so other tests aren't affected
    apply_theme("coral")


# ── _atomic_write ───────────────────────────────────────────────────────────

def test_atomic_write_creates_file(tmp_path):
    """_atomic_write should create a valid JSON file at the target path."""
    target = tmp_path / "out.json"
    payload = {"hello": "world", "n": 42}
    _atomic_write(target, payload)
    assert target.exists()
    with open(target) as f:
        data = json.load(f)
    assert data == payload


def test_atomic_write_rollback(tmp_path):
    """If the write fails, the original file must remain untouched."""
    target = tmp_path / "safe.json"
    original = {"preserved": True}
    target.write_text(json.dumps(original))

    # Force os.replace to raise so the write cannot complete
    with patch("claude_notch.config.os.replace", side_effect=OSError("disk full")):
        _atomic_write(target, {"bad": "data"})

    with open(target) as f:
        data = json.load(f)
    assert data == original


# ── ConfigManager ───────────────────────────────────────────────────────────

def test_config_manager_save_load(tmp_config_dir):
    """save() then a fresh load should round-trip all values."""
    cm = ConfigManager()
    cm.set("color_theme", "purple")
    cm.set("budget_daily", 5.0)
    cm.save()

    cm2 = ConfigManager()
    assert cm2.get("color_theme") == "purple"
    assert cm2.get("budget_daily") == 5.0


def test_config_manager_migration(tmp_config_dir):
    """Old single 'anthropic_api_key' should be migrated into 'api_keys' list."""
    import claude_notch.config as cfg_mod
    # Seed a legacy config file with the old key name
    legacy = dict(DEFAULT_CONFIG)
    legacy["anthropic_api_key"] = "sk-ant-TESTKEY1234567890abcd"
    legacy["api_keys"] = []
    cfg_mod.CONFIG_FILE.write_text(json.dumps(legacy))

    cm = ConfigManager()
    keys = cm.get("api_keys")
    assert len(keys) == 1
    assert keys[0]["key"] == "sk-ant-TESTKEY1234567890abcd"
    assert "anthropic_api_key" not in cm.config


# ── _redact_key ─────────────────────────────────────────────────────────────

def test_redact_key():
    """_redact_key should show first 7 and last 4 chars for long keys."""
    key = "sk-ant-ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    redacted = _redact_key(key)
    assert redacted.startswith("sk-ant-")
    assert redacted.endswith("WXYZ")
    assert "..." in redacted
