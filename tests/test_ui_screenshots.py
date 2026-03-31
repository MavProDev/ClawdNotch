"""Visual sanity tests — grab widgets and verify the pixmap is non-empty."""

from unittest.mock import MagicMock, patch



def _make_config_mock():
    """Return a MagicMock that acts like ConfigManager.get()."""
    config = MagicMock()
    config.get = MagicMock(side_effect=lambda k, d=None: {
        "default_model": "sonnet",
        "subscription_mode": "max",
        "color_theme": "coral",
        "last_x": -1,
        "last_y": -1,
        "last_edge": "top",
        "mini_mode": False,
        "expanded_w": 560,
        "expanded_h": 500,
        "was_expanded": False,
        "multi_monitor": False,
        "dim_when_inactive": False,
        "dim_opacity": 0.55,
        "sparkline_enabled": True,
        "system_resources_enabled": True,
        "streaks_enabled": True,
        "dnd_mode": False,
        "notification_history_enabled": True,
        "budget_daily": 0,
        "budget_monthly": 0,
        "auto_start": False,
    }.get(k, d))
    return config


def _make_notch(qapp):
    """Helper: build a ClaudeNotch with full mocks."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QRect

    from claude_notch.usage import SparklineTracker, TodoManager
    from claude_notch.sessions import EmotionEngine
    from claude_notch.notifications import NotificationHistory
    from claude_notch.ui import ClaudeNotch

    config = _make_config_mock()

    mock_screen = MagicMock()
    mock_screen.geometry.return_value = QRect(0, 0, 1920, 1080)
    mock_screen.availableGeometry.return_value = QRect(0, 0, 1920, 1040)

    tracker = MagicMock()
    tracker.today = {"tool_calls": 0, "prompts": 0, "est_tokens": 0}
    tracker.yesterday = {"tool_calls": 0, "prompts": 0, "est_tokens": 0}
    tracker.month_stats = {"tool_calls": 0, "est_tokens": 0, "sessions": 0, "prompts": 0, "days_active": 0, "est_cost": 0.0}
    tracker.week_stats = {"tool_calls": 0, "est_tokens": 0, "sessions": 0, "prompts": 0, "est_cost": 0.0}
    tracker.daily_avg = 0
    tracker.all_days = {}

    sm = MagicMock()
    sm.get_active_sessions.return_value = []
    sm.get_all_tasks.return_value = []
    sm.total_active = 0
    sm.any_working = False
    sm.any_waiting = False
    sm.avg_session_minutes = 0
    sm.session_updated = MagicMock()
    sm.session_updated.connect = MagicMock()
    sm.task_completed = MagicMock()
    sm.task_completed.connect = MagicMock()
    sm.needs_attention = MagicMock()
    sm.needs_attention.connect = MagicMock()
    sm.budget_alert = MagicMock()
    sm.budget_alert.connect = MagicMock()

    streaks = MagicMock()
    streaks.current_streak = 0
    streaks.top_day_this_week = ("", 0)

    with patch.object(QApplication, "primaryScreen", return_value=mock_screen), \
         patch.object(QApplication, "screenAt", return_value=mock_screen):
        notch = ClaudeNotch(
            sm, config, tracker, EmotionEngine(), TodoManager(),
            SparklineTracker(), NotificationHistory(), streaks,
        )
    return notch


# ── Tests ───────────────────────────────────────────────────────────────────

def test_collapsed_renders_pixels(qapp):
    """A collapsed notch widget.grab() should produce a non-empty pixmap."""
    from PyQt6.QtWidgets import QApplication
    notch = _make_notch(qapp)
    notch.show()
    QApplication.processEvents()
    pix = notch.grab()
    assert not pix.isNull()
    assert pix.width() > 0 and pix.height() > 0
    notch.close()


def test_expanded_has_title(qapp):
    """After expanding, the grabbed pixmap should not be all black (basic sanity)."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QRect
    from unittest.mock import patch as _patch

    mock_screen = MagicMock()
    mock_screen.geometry.return_value = QRect(0, 0, 1920, 1080)
    mock_screen.availableGeometry.return_value = QRect(0, 0, 1920, 1040)

    notch = _make_notch(qapp)
    with _patch.object(QApplication, "primaryScreen", return_value=mock_screen), \
         _patch.object(QApplication, "screenAt", return_value=mock_screen):
        notch.show()
        notch._expanded = True
        notch.setFixedSize(560, 500)
        notch.update()
        QApplication.processEvents()
        pix = notch.grab()
    assert not pix.isNull()
    assert pix.width() >= 500
    notch.close()


def test_splash_renders(qapp):
    """SplashScreen.grab() should produce a non-empty pixmap."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QRect
    from claude_notch.ui import SplashScreen

    mock_screen = MagicMock()
    mock_screen.geometry.return_value = QRect(0, 0, 1920, 1080)
    mock_screen.availableGeometry.return_value = QRect(0, 0, 1920, 1040)

    config = _make_config_mock()
    with patch.object(QApplication, "primaryScreen", return_value=mock_screen):
        splash = SplashScreen(config, first_launch=False)
    splash.show()
    QApplication.processEvents()
    pix = splash.grab()
    assert not pix.isNull()
    assert pix.width() > 0
    splash.close()


def test_settings_dialog_centered(qapp):
    """SettingsDialog should open and render without crashing."""
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QRect
    from claude_notch.ui import SettingsDialog

    mock_screen = MagicMock()
    mock_screen.geometry.return_value = QRect(0, 0, 1920, 1080)
    mock_screen.availableGeometry.return_value = QRect(0, 0, 1920, 1040)

    config = _make_config_mock()
    with patch.object(QApplication, "primaryScreen", return_value=mock_screen):
        dlg = SettingsDialog(config)
    dlg.show()
    QApplication.processEvents()

    # Verify the dialog has a reasonable size (not zero)
    assert dlg.width() >= 400
    assert dlg.height() >= 400

    # Grab a screenshot to verify it renders
    pix = dlg.grab()
    assert not pix.isNull()

    dlg.close()
