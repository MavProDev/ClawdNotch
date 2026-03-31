"""Tests for claude_notch.notifications — NotificationHistory and NotificationManager."""

from unittest.mock import MagicMock, patch

import pytest

from claude_notch.notifications import NotificationHistory, NotificationManager


# ── NotificationHistory ─────────────────────────────────────────────────────

def test_history_records():
    """notify_task_complete should add an entry to history."""
    history = NotificationHistory()
    config = MagicMock()
    config.get = MagicMock(side_effect=lambda k, d=None: {
        "notification_history_enabled": True,
        "sound_enabled": False,
        "toast_enabled": False,
        "dnd_mode": False,
        "auto_mute_when_focused": False,
    }.get(k, d))

    nm = NotificationManager(config, history)
    nm.notify_task_complete("my-project", "Build succeeded")

    recent = history.get_recent()
    assert len(recent) == 1
    assert "my-project" in recent[0]["title"]


def test_history_max_items():
    """History should be capped at 50 items (the default max)."""
    history = NotificationHistory(max_items=50)
    for i in range(60):
        history.add(f"title-{i}", f"msg-{i}")
    # Internal list should be trimmed
    assert len(history._items) == 50


# ── NotificationManager ────────────────────────────────────────────────────

def test_dnd_suppresses_sound():
    """When dnd_mode is True, _should_mute must return True."""
    config = MagicMock()
    config.get = MagicMock(side_effect=lambda k, d=None: {
        "dnd_mode": True,
    }.get(k, d))

    nm = NotificationManager(config)
    assert nm._should_mute() is True


def test_custom_sound_path_used():
    """_play_sound should attempt to play the custom sound file when set."""
    config = MagicMock()
    config.get = MagicMock(side_effect=lambda k, d=None: {
        "custom_sound_completion": "C:/sounds/done.wav",
    }.get(k, d))

    nm = NotificationManager(config)

    mock_winsound = MagicMock()
    mock_winsound.SND_FILENAME = 0x00020000
    mock_winsound.SND_NODEFAULT = 0x00000002

    with patch("claude_notch.notifications.winsound", mock_winsound), \
         patch("claude_notch.notifications.HAS_SOUND", True), \
         patch("os.path.exists", return_value=True):
        nm._play_sound("completion")

    mock_winsound.PlaySound.assert_called_once()
    call_args = mock_winsound.PlaySound.call_args
    assert call_args[0][0] == "C:/sounds/done.wav"
