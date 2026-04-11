"""Smoke test — verify the main ClaudeNotch widget can be instantiated."""

from unittest.mock import MagicMock, patch



def test_app_creates_without_crash(qapp):
    """Create ClaudeNotch widget, show it, close it — must not crash."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QRect

    # Build lightweight stubs for every dependency
    from claude_notch.usage import UsageTracker, SparklineTracker, StreakTracker, TodoManager
    from claude_notch.sessions import SessionManager, EmotionEngine
    from claude_notch.notifications import NotificationHistory

    # Mock config
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
    }.get(k, d))

    # Mock primaryScreen for positioning calls
    mock_screen = MagicMock()
    mock_screen.geometry.return_value = QRect(0, 0, 1920, 1080)
    mock_screen.availableGeometry.return_value = QRect(0, 0, 1920, 1040)

    with patch.object(QApplication, "primaryScreen", return_value=mock_screen), \
         patch.object(QApplication, "screenAt", return_value=mock_screen):
        # Build real objects (they don't need disk in this test)
        tracker = MagicMock(spec=UsageTracker)
        tracker.today = {"tool_calls": 0, "prompts": 0, "est_tokens": 0}
        tracker.yesterday = {"tool_calls": 0, "prompts": 0, "est_tokens": 0}
        tracker.month_stats = {"tool_calls": 0, "est_tokens": 0, "sessions": 0, "prompts": 0, "days_active": 0, "est_cost": 0.0}
        tracker.week_stats = {"tool_calls": 0, "est_tokens": 0, "sessions": 0, "prompts": 0, "est_cost": 0.0}
        tracker.daily_avg = 0
        tracker.all_days = {}

        emotion = EmotionEngine()
        todos = TodoManager()
        spark = SparklineTracker()
        notif_history = NotificationHistory()
        streaks = MagicMock(spec=StreakTracker)
        streaks.current_streak = 0
        streaks.top_day_this_week = ("", 0)

        sm = MagicMock(spec=SessionManager)
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

        from claude_notch.ui import ClaudeNotch
        notch = ClaudeNotch(sm, config, tracker, emotion, todos, spark, notif_history, streaks)
        notch.show()
        QApplication.processEvents()
        notch.close()
        QApplication.processEvents()
