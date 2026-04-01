"""
claude_notch.update_checker — GitHub release update checker
=============================================================
Checks MavProDev/ClawdNotch releases for newer versions.

v4.0.0: Extracted from usage.py for single-responsibility.
"""

from datetime import datetime

import requests


def _parse_version(tag: str) -> tuple:
    """Parse 'v3.1.0' or '3.1.0' into (3, 1, 0) for comparison."""
    try:
        return tuple(int(x) for x in tag.lstrip("v").split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def check_for_updates(config, on_update_available=None):
    """Check GitHub Releases for a newer version. Call from a background thread."""
    from claude_notch import __version__

    today = datetime.now().strftime("%Y-%m-%d")
    if config.get("last_update_check") == today:
        return

    try:
        resp = requests.get(
            "https://api.github.com/repos/MavProDev/ClawdNotch/releases/latest",
            timeout=10,
            headers={"Accept": "application/vnd.github.v3+json"},
        )
        config.set("last_update_check", today)
        if resp.status_code != 200:
            return
        data = resp.json()
        latest_tag = data.get("tag_name", "")
        latest_url = data.get("html_url", "")

        if _parse_version(latest_tag) > _parse_version(__version__):
            if on_update_available:
                on_update_available(latest_tag, latest_url)
    except Exception:
        pass


def open_release_page(url: str):
    """Open a GitHub release page in the default browser."""
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass
