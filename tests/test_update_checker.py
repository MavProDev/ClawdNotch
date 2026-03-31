"""Tests for check_for_updates and _parse_version."""

from unittest.mock import patch, MagicMock


def test_parse_version():
    from claude_notch.usage import _parse_version

    assert _parse_version("v3.1.0") == (3, 1, 0)
    assert _parse_version("3.1.0") == (3, 1, 0)
    assert _parse_version("v10.20.30") == (10, 20, 30)
    assert _parse_version("invalid") == (0, 0, 0)
    assert _parse_version("") == (0, 0, 0)


def test_check_for_updates_calls_callback(tmp_config_dir):
    """When a newer version exists, callback should be called."""
    from claude_notch.config import ConfigManager
    from claude_notch.usage import check_for_updates

    config = ConfigManager()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": "v99.0.0",
        "html_url": "https://github.com/MavProDev/ClawdNotch/releases/tag/v99.0.0",
    }

    callback = MagicMock()

    with patch("claude_notch.usage.requests.get", return_value=mock_resp):
        check_for_updates(config, callback)

    callback.assert_called_once()
    args = callback.call_args[0]
    assert args[0] == "v99.0.0"


def test_check_for_updates_no_callback_if_current(tmp_config_dir):
    """When current version is latest, callback should NOT be called."""
    from claude_notch.config import ConfigManager
    from claude_notch.usage import check_for_updates
    from claude_notch import __version__

    config = ConfigManager()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "tag_name": f"v{__version__}",
        "html_url": "https://example.com",
    }

    callback = MagicMock()

    with patch("claude_notch.usage.requests.get", return_value=mock_resp):
        check_for_updates(config, callback)

    callback.assert_not_called()


def test_check_for_updates_once_per_day(tmp_config_dir):
    """Should only check once per day."""
    from claude_notch.config import ConfigManager
    from claude_notch.usage import check_for_updates

    config = ConfigManager()
    callback = MagicMock()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"tag_name": "v99.0.0", "html_url": "https://example.com"}

    with patch("claude_notch.usage.requests.get", return_value=mock_resp) as mock_get:
        check_for_updates(config, callback)
        check_for_updates(config, callback)  # second call same day

    # Should only make one HTTP request
    assert mock_get.call_count == 1
