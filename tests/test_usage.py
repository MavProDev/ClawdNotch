"""Tests for claude_notch.usage — UsageTracker, SparklineTracker, StreakTracker, TodoManager."""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from claude_notch.usage import (
    UsageTracker,
    SparklineTracker,
    StreakTracker,
    TodoManager,
)


# ── UsageTracker ────────────────────────────────────────────────────────────

def test_record_event_increments(tmp_config_dir):
    """record_event('PostToolUse') should increment tool_calls."""
    tracker = UsageTracker()
    before = tracker.today.get("tool_calls", 0)
    tracker.record_event("PostToolUse")
    after = tracker.today.get("tool_calls", 0)
    assert after == before + 1


def test_cost_estimation(tmp_config_dir):
    """_estimate_cost should return a positive float for a nonzero token count."""
    tracker = UsageTracker()
    cost = tracker._estimate_cost(1000)
    assert isinstance(cost, float)
    assert cost > 0


# ── SparklineTracker ────────────────────────────────────────────────────────

def test_sparkline_record():
    """After record(), the last bucket should be > 0."""
    spark = SparklineTracker(buckets=30)
    spark.record()
    data = spark.get_data()
    assert data[-1] > 0


def test_sparkline_length():
    """get_data() must always return exactly `buckets` items."""
    spark = SparklineTracker(buckets=30)
    assert len(spark.get_data()) == 30
    spark.record()
    assert len(spark.get_data()) == 30


# ── StreakTracker ───────────────────────────────────────────────────────────

def test_streak_zero_if_empty(tmp_config_dir):
    """With no usage data the streak should be 0."""
    tracker = UsageTracker()
    streaks = StreakTracker(tracker)
    assert streaks.current_streak == 0


def test_streak_counts_consecutive(tmp_config_dir):
    """Three consecutive days with activity should give a streak of 3."""
    tracker = UsageTracker()
    # Manually inject 3 consecutive days of data
    today = datetime.now()
    for offset in range(3):
        key = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        tracker._data["days"][key] = {"tool_calls": 10, "prompts": 5, "est_tokens": 0, "sessions": 1}
    streaks = StreakTracker(tracker)
    assert streaks.current_streak == 3


def test_top_day_this_week(tmp_config_dir):
    """top_day_this_week should return a (day_name, count) tuple."""
    tracker = UsageTracker()
    today = datetime.now()
    key = today.strftime("%Y-%m-%d")
    tracker._data["days"][key] = {"tool_calls": 42, "prompts": 10, "est_tokens": 0, "sessions": 2}
    streaks = StreakTracker(tracker)
    day_name, count = streaks.top_day_this_week
    assert isinstance(day_name, str)
    assert count == 42


# ── TodoManager ─────────────────────────────────────────────────────────────

def test_todo_write_parsing():
    """A TodoWrite event should create todo items."""
    tm = TodoManager()
    tool_input = json.dumps({
        "todos": [
            {"id": "1", "content": "Fix the bug", "status": "pending"},
            {"id": "2", "content": "Write tests", "status": "in_progress"},
        ]
    })
    tm.process_tool_event("sess-1", "TodoWrite", tool_input)
    todos = tm.get_all_todos()
    assert len(todos) == 2
    texts = {t["text"] for t in todos}
    assert "Fix the bug" in texts
    assert "Write tests" in texts
