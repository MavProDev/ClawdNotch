"""Tests for claude_notch.hooks — HookServer TCP acceptance & install_hooks."""

import json
import socket
import time
import tempfile
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claude_notch.hooks import HookServer, install_hooks


def test_hook_server_accepts_tcp(qapp):
    """Send a JSON payload to HookServer over TCP; the signal should fire."""
    received = []

    # Use a high ephemeral port to avoid conflicts
    port = 19799
    server = HookServer(port=port)
    server.event_received.connect(lambda evt: received.append(evt))
    server.start()
    time.sleep(0.5)  # give the server a moment to bind

    try:
        payload = json.dumps({"event": "PostToolUse", "session_id": "tcp-test"})
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(("127.0.0.1", port))
        sock.sendall((payload + "\n").encode())
        # Read the response
        try:
            sock.recv(1024)
        except socket.timeout:
            pass
        sock.close()
        time.sleep(0.5)  # give the signal time to propagate
        # Process Qt events so the signal can be delivered
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()
        time.sleep(0.3)
        QApplication.processEvents()
    finally:
        server.stop()
        server.wait(3000)

    assert len(received) >= 1, "HookServer did not emit event_received"
    assert received[0]["session_id"] == "tcp-test"


def test_install_hooks_creates_ps1(tmp_config_dir):
    """install_hooks should create the PowerShell hook script."""
    import claude_notch.config as cfg_mod
    import claude_notch.hooks as hooks_mod

    # Patch CONFIG_DIR in hooks module
    with patch.object(hooks_mod, "CONFIG_DIR", tmp_config_dir):
        # Also patch the settings.json path so we don't touch real config
        fake_claude_dir = tmp_config_dir / ".claude"
        fake_claude_dir.mkdir(exist_ok=True)
        fake_settings = fake_claude_dir / "settings.json"

        with patch("claude_notch.hooks.Path.home", return_value=tmp_config_dir):
            install_hooks(port=19748)

    ps1 = tmp_config_dir / "hooks" / "claude_notch_hook.ps1"
    assert ps1.exists(), "PowerShell hook script was not created"
    content = ps1.read_text()
    assert "EventType" in content


def test_install_hooks_modifies_settings(tmp_config_dir):
    """install_hooks should add hook entries to settings.json."""
    import claude_notch.hooks as hooks_mod

    with patch.object(hooks_mod, "CONFIG_DIR", tmp_config_dir):
        fake_claude_dir = tmp_config_dir / ".claude"
        fake_claude_dir.mkdir(exist_ok=True)
        fake_settings = fake_claude_dir / "settings.json"
        fake_settings.write_text("{}")

        with patch("claude_notch.hooks.Path.home", return_value=tmp_config_dir):
            install_hooks(port=19748)

    with open(fake_settings) as f:
        settings = json.load(f)

    assert "hooks" in settings
    # Every expected event type should have an entry
    for ev in ("PreToolUse", "PostToolUse", "Stop", "Notification", "SessionStart", "SessionEnd"):
        assert ev in settings["hooks"], f"Missing hook entry for {ev}"
