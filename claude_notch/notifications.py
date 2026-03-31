"""
claude_notch.notifications -- Notification & history management
================================================================
Extracted from claude_notch_v2_backup.py.

Provides:
    - NotificationHistory   Simple ring buffer of recent notifications (max 50)
    - NotificationManager   DND support, custom sounds, toast, history integration
"""

import os
import threading
from datetime import datetime

from claude_notch.system_monitor import _is_terminal_focused, _focus_window_by_pid

# ---------------------------------------------------------------------------
# Conditional imports
# ---------------------------------------------------------------------------
try:
    from plyer import notification as toast_notify
    HAS_TOAST = True
except ImportError:
    HAS_TOAST = False

try:
    import winsound
    HAS_SOUND = True
except ImportError:
    HAS_SOUND = False


# ---------------------------------------------------------------------------
# NotificationHistory -- ring buffer of recent notifications
# ---------------------------------------------------------------------------
class NotificationHistory:
    """Keeps a log of recent notifications."""
    def __init__(self, max_items=50):
        self._items = []; self._max = max_items
    def add(self, title, message, ntype="info"):
        self._items.append({"title": title, "message": message, "type": ntype,
                            "time": datetime.now().strftime("%H:%M")})
        if len(self._items) > self._max: self._items = self._items[-self._max:]
    def get_recent(self, n=8): return list(reversed(self._items[-n:]))


# ---------------------------------------------------------------------------
# NotificationManager -- DND, custom sounds, toast, history
# ---------------------------------------------------------------------------
class NotificationManager:
    def __init__(self, config, history=None):
        self.config = config; self.history = history
    def _should_mute(self) -> bool:
        if self.config.get("dnd_mode", False): return True
        return self.config.get("auto_mute_when_focused", True) and _is_terminal_focused()
    def notify_task_complete(self, project, summary):
        if self.history and self.config.get("notification_history_enabled", True):
            self.history.add(f"Claude Code — {project}", summary[:200], "completion")
        if self.config.get("sound_enabled") and HAS_SOUND and not self._should_mute():
            threading.Thread(target=self._play_sound, args=("completion",), daemon=True).start()
        if self.config.get("toast_enabled") and HAS_TOAST and not self.config.get("dnd_mode"):
            threading.Thread(target=self._toast, args=(f"Claude Code — {project}", summary[:200], 5), daemon=True).start()
    def notify_needs_attention(self, project, pid=0):
        if self.history and self.config.get("notification_history_enabled", True):
            self.history.add(f"Claude Code — {project}", "Needs your attention!", "attention")
        if self.config.get("sound_enabled") and HAS_SOUND and not self._should_mute():
            threading.Thread(target=self._play_sound, args=("attention",), daemon=True).start()
        if self.config.get("toast_enabled") and HAS_TOAST and not self.config.get("dnd_mode"):
            threading.Thread(target=self._toast_and_focus, args=(
                f"Claude Code — {project}", "Needs your attention!", 10, pid), daemon=True).start()

    @staticmethod
    def _toast_and_focus(title, msg, timeout, pid):
        """Show toast notification, then focus the terminal window."""
        try:
            toast_notify.notify(title=title, message=msg, app_name="Claude Notch", timeout=timeout)
        except Exception: pass
        # Give the toast a moment to display, then focus the terminal
        if pid:
            import time
            time.sleep(0.5)
            _focus_window_by_pid(pid)
    def notify_budget_alert(self, message):
        if self.history: self.history.add("Budget Alert", message, "budget")
        if HAS_TOAST and not self.config.get("dnd_mode"):
            threading.Thread(target=self._toast, args=("Claude Notch — Budget", message, 10), daemon=True).start()
    def _play_sound(self, sound_type):
        custom = self.config.get(f"custom_sound_{sound_type}", "")
        if custom and os.path.exists(custom):
            try: winsound.PlaySound(custom, winsound.SND_FILENAME | winsound.SND_NODEFAULT); return
            except Exception: pass
        try:
            if sound_type == "completion": winsound.Beep(800,150); winsound.Beep(1000,150); winsound.Beep(1200,200)
            else: winsound.Beep(600,300); winsound.Beep(600,300)
        except Exception: pass
    @staticmethod
    def _toast(title, msg, timeout):
        try: toast_notify.notify(title=title, message=msg, app_name="Claude Notch", timeout=timeout)
        except Exception: pass
