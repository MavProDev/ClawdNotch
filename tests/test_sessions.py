"""Tests for claude_notch.sessions — Session dataclass and SessionManager."""

import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from claude_notch.sessions import Session, SessionManager, EmotionEngine
from claude_notch.usage import UsageTracker, SparklineTracker, TodoManager


# ── Session dataclass ───────────────────────────────────────────────────────

def test_session_project_name():
    """project_dir='/foo/bar' should yield project_name='bar'."""
    s = Session(session_id="s1", project_dir="/foo/bar")
    assert s.project_name == "bar"


def test_session_age_str():
    """A session that just started should report age 'now'."""
    s = Session(session_id="s2", started_at=datetime.now())
    assert s.age_str == "now"


# ── SessionManager ──────────────────────────────────────────────────────────

@pytest.fixture()
def sm(tmp_config_dir, qapp):
    """Build a SessionManager with minimal stubs."""
    tracker = UsageTracker()
    emotion = EmotionEngine()
    todos = TodoManager()
    spark = SparklineTracker()
    config = MagicMock()
    config.get = MagicMock(side_effect=lambda k, d=None: {
        "default_model": "sonnet",
        "subscription_mode": "max",
        "budget_daily": 0,
        "budget_monthly": 0,
    }.get(k, d))
    mgr = SessionManager(tracker, emotion, todos, spark, config)
    return mgr


def test_handle_event_creates_session(sm, mock_event):
    """Handling an event for a new session_id should create a Session."""
    evt = mock_event(session_id="new-sess", event="PostToolUse")
    sm.handle_event(evt)
    assert "new-sess" in sm.sessions


def test_state_machine_working(sm, mock_event):
    """PreToolUse should set state to 'working'."""
    evt = mock_event(session_id="sm-1", event="PreToolUse", tool_name="Read")
    sm.handle_event(evt)
    assert sm.sessions["sm-1"].state == "working"


def test_state_machine_waiting(sm, mock_event):
    """Notification should set state to 'waiting'."""
    evt = mock_event(session_id="sm-2", event="Notification")
    sm.handle_event(evt)
    assert sm.sessions["sm-2"].state == "waiting"


def test_state_machine_completed(sm, mock_event):
    """SessionEnd should set state to 'completed'."""
    # First create the session
    sm.handle_event(mock_event(session_id="sm-3", event="PreToolUse"))
    # Then end it
    sm.handle_event(mock_event(session_id="sm-3", event="SessionEnd"))
    assert sm.sessions["sm-3"].state == "completed"


def test_cleanup_removes_completed(sm, mock_event):
    """cleanup_dead should remove sessions in 'completed' state."""
    sm.handle_event(mock_event(session_id="done-1", event="SessionEnd"))
    assert sm.sessions["done-1"].state == "completed"

    # _find_claude_windows and _find_claude_processes are imported locally
    # inside cleanup_dead from claude_notch.system_monitor
    with patch("claude_notch.system_monitor._find_claude_windows", return_value=[]), \
         patch("claude_notch.system_monitor._find_claude_processes", return_value=[]):
        sm.cleanup_dead()

    assert "done-1" not in sm.sessions


def test_thinking_word_set_on_transition(sm, mock_event):
    """Entering 'working' state should set a non-empty thinking_word."""
    evt = mock_event(session_id="think-1", event="PreToolUse", tool_name="Bash")
    sm.handle_event(evt)
    assert sm.sessions["think-1"].thinking_word != ""
