"""ClawdNotch -- entry point. Run with: python -m claude_notch"""
import sys
import threading
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer

from claude_notch import __version__
from claude_notch.config import ConfigManager, apply_theme, HOOK_SERVER_PORT
from claude_notch.sessions import SessionManager, EmotionEngine
from claude_notch.hooks import HookServer
from claude_notch.usage import UsageTracker, UsagePoller, SparklineTracker, StreakTracker, TodoManager
from claude_notch.token_aggregator import TokenAggregator
from claude_notch.update_checker import check_for_updates
from claude_notch.notifications import NotificationManager, NotificationHistory
from claude_notch.system_monitor import acquire_lock, release_lock
from claude_notch.git_checkpoints import GitCheckpoints
from claude_notch.ui import ClaudeNotch, SplashScreen, SettingsDialog, make_tray

# Conditional imports
try:
    import keyboard as kb_module
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False
try:
    from plyer import notification as toast_notify
    HAS_TOAST = True
except ImportError:
    HAS_TOAST = False


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not acquire_lock():
        print("Another instance running.")
        sys.exit(1)

    config = ConfigManager()
    tracker = UsageTracker(config)
    apply_theme(config.get("color_theme", "coral"))

    emotion = EmotionEngine()
    todos = TodoManager()
    sparkline = SparklineTracker()
    notif_history = NotificationHistory()
    streaks = StreakTracker(tracker)

    sm = SessionManager(tracker, emotion, todos, sparkline, config)
    nm = NotificationManager(config, notif_history)

    sm.task_completed.connect(nm.notify_task_complete)
    sm.needs_attention.connect(nm.notify_needs_attention)
    sm.budget_alert.connect(nm.notify_budget_alert)
    sm.achievement.connect(lambda msg: nm.notify_achievement(msg))

    port = config.get("hook_server_port", HOOK_SERVER_PORT)
    hs = HookServer(port)
    hs.event_received.connect(sm.handle_event)
    hs.start()

    token_agg = TokenAggregator(cache_ttl_seconds=30)
    notch = ClaudeNotch(sm, config, tracker, emotion, todos, sparkline, notif_history, streaks, token_agg)

    # Splash screen — shows on every launch, skippable
    first_launch = not SettingsDialog._check()
    splash = SplashScreen(config, first_launch=first_launch)
    def _on_splash_done():
        notch.show()
        # Check for updates in background after splash — use signal for thread safety
        def _update_callback(version, url):
            notch._update_signal.emit(version, url)
        threading.Thread(
            target=check_for_updates, args=(config, _update_callback), daemon=True
        ).start()

    splash.finished.connect(_on_splash_done)
    splash.show()

    up = UsagePoller(config)
    up.usage_updated.connect(notch.update_usage)
    up.start()

    def do_snapshot():
        active = sm.get_active_sessions()
        if active and active[0].project_dir:
            h = GitCheckpoints.create(active[0].project_dir)
            if h and HAS_TOAST:
                threading.Thread(
                    target=lambda: toast_notify.notify(
                        title="Claude Notch",
                        message=f"Checkpoint saved for {active[0].project_name}",
                        app_name="Claude Notch",
                        timeout=3,
                    ),
                    daemon=True,
                ).start()

    # Restore persisted sessions from previous run
    sm.restore_state()
    # Scan for running Claude processes once event loop is running (not before)
    # so signals fire properly and windows are fully enumerable
    QTimer.singleShot(0, sm.scan_processes)
    # Second scan shortly after startup catches windows that were slow to register titles
    QTimer.singleShot(3000, sm.scan_processes)

    # Periodic process scan every 15 seconds
    proc_timer = QTimer()
    proc_timer.setInterval(15000)
    proc_timer.timeout.connect(sm.scan_processes)
    proc_timer.start()

    make_tray(app, notch, config, sm, do_snapshot)

    if HAS_KEYBOARD:
        try:
            kb_module.add_hotkey(
                "ctrl+shift+c",
                lambda: notch.hide() if notch.isVisible() else notch.force_show(),
            )
            kb_module.add_hotkey("ctrl+shift+e", lambda: notch.toggle_expand())
            kb_module.add_hotkey("ctrl+shift+d", lambda: notch._toggle_dnd())
            print("[Hotkey] Ctrl+Shift+C = show/hide, E = expand, D = DND")
        except Exception:
            pass

    if HAS_KEYBOARD:
        try:
            kb_module.add_hotkey("ctrl+shift+s", do_snapshot)
            print("[Hotkey] Ctrl+Shift+S = git snapshot")
        except Exception:
            pass

    banner_fancy = (
        "\u2554" + "\u2550" * 38 + "\u2557\n"
        "\u2551" + f"   Claude Notch v{__version__} on :{port}    " + "\u2551\n"
        "\u2551" + "   @ReelDad                          " + "\u2551\n"
        "\u255a" + "\u2550" * 38 + "\u255d"
    )
    banner_ascii = (
        "+" + "=" * 38 + "+\n"
        "|" + f"   Claude Notch v{__version__} on :{port}    " + "|\n"
        "|" + "   @ReelDad                          " + "|\n"
        "+" + "=" * 38 + "+"
    )
    try:
        print(banner_fancy)
    except UnicodeEncodeError:
        print(banner_ascii)

    def cleanup():
        proc_timer.stop()
        notch._save_timer.stop()
        notch._sys_timer.stop()
        up.stop()
        hs.stop()
        up.wait(2000)
        hs.wait(2000)
        sm.save_state()
        tracker.flush()
        # BUG FIX #3: Removed dead code that wrote was_expanded during cleanup
        # (was: config.set("was_expanded", notch._expanded, save_now=False))
        config.flush()
        release_lock()

    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
