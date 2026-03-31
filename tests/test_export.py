"""Tests for export_usage_report (claude_notch.usage)."""

import os
from datetime import datetime
from unittest.mock import patch

import pytest

from claude_notch.usage import UsageTracker, export_usage_report


@pytest.fixture()
def seeded_tracker(tmp_config_dir):
    """Return a UsageTracker with one day of synthetic data."""
    tracker = UsageTracker()
    key = datetime.now().strftime("%Y-%m-%d")
    tracker._data["days"][key] = {
        "tool_calls": 42, "prompts": 10, "est_tokens": 50000,
        "sessions": 3, "est_cost": 1.23,
    }
    return tracker


def test_export_markdown(seeded_tracker, tmp_path):
    """export with fmt='markdown' should produce a .md file with expected headers."""
    config = {"subscription_mode": "max"}

    with patch("claude_notch.usage.Path.home", return_value=tmp_path):
        # Ensure Desktop exists in the temp location
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        path = export_usage_report(seeded_tracker, config, fmt="markdown")

    assert path.endswith(".md")
    assert os.path.exists(path)
    content = open(path).read()
    assert "# Claude Notch Usage Report" in content
    assert "## Today" in content


def test_export_csv(seeded_tracker, tmp_path):
    """export with fmt='csv' should produce a .csv file with a header row."""
    config = {"subscription_mode": "api"}

    with patch("claude_notch.usage.Path.home", return_value=tmp_path):
        desktop = tmp_path / "Desktop"
        desktop.mkdir()
        path = export_usage_report(seeded_tracker, config, fmt="csv")

    assert path.endswith(".csv")
    assert os.path.exists(path)
    lines = open(path).readlines()
    assert lines[0].strip().startswith("Date,")
    assert len(lines) >= 2  # header + at least 1 data row
