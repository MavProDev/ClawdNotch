"""Shared fixtures for the Claude Notch test suite."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# QApplication singleton — created once per test session, reused everywhere
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    """Create a single QApplication for the entire test session.

    Qt requires exactly one QApplication per process.  We also mock
    ``primaryScreen`` so tests that never display real windows can run
    in headless / CI environments.
    """
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QRect

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    # Mock primaryScreen so geometry calls don't crash in headless mode
    mock_screen = MagicMock()
    mock_screen.geometry.return_value = QRect(0, 0, 1920, 1080)
    mock_screen.availableGeometry.return_value = QRect(0, 0, 1920, 1040)
    with patch.object(QApplication, "primaryScreen", return_value=mock_screen):
        yield app


# ---------------------------------------------------------------------------
# Temporary config directory — isolates every test from the real user config
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_config_dir(tmp_path, monkeypatch):
    """Point CONFIG_DIR / CONFIG_FILE at a disposable temp directory.

    Patches both ``claude_notch.config`` **and** any module that has already
    imported those names, so ConfigManager and friends write to *tmp_path*
    instead of the user's real ``~/.claude-notch``.
    """
    import claude_notch.config as cfg_mod

    cfg_dir = tmp_path / ".claude-notch"
    cfg_dir.mkdir()
    cfg_file = cfg_dir / "config.json"

    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(cfg_mod, "LOCK_FILE", cfg_dir / "notch.lock")

    # Also patch any downstream modules that import CONFIG_DIR at module level
    for mod_name in ("claude_notch.sessions", "claude_notch.hooks",
                     "claude_notch.usage", "claude_notch.system_monitor"):
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "CONFIG_DIR"):
            monkeypatch.setattr(mod, "CONFIG_DIR", cfg_dir)

    # Patch SESSIONS_FILE and USAGE_FILE if the modules are already loaded
    sessions_mod = sys.modules.get("claude_notch.sessions")
    if sessions_mod:
        monkeypatch.setattr(sessions_mod, "SESSIONS_FILE", cfg_dir / "sessions_state.json")
    usage_mod = sys.modules.get("claude_notch.usage")
    if usage_mod:
        monkeypatch.setattr(usage_mod, "USAGE_FILE", cfg_dir / "usage_history.json")

    return cfg_dir


# ---------------------------------------------------------------------------
# Mock hook event — returns a dict in the format produced by the hook server
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_event():
    """Factory fixture: call with overrides to get a hook-event dict."""
    def _make(**overrides):
        base = {
            "event": "PostToolUse",
            "session_id": "test-session-1",
            "project_dir": "/home/user/my-project",
            "tool_name": "Edit",
            "user_prompt": "",
            "tool_input": "",
            "timestamp": "2026-03-30T12:00:00",
        }
        base.update(overrides)
        return base
    return _make
