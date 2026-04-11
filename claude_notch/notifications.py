"""
claude_notch.notifications -- Notification & history management
================================================================
Provides:
    - NotificationHistory   Simple ring buffer of recent notifications (max 50)
    - NotificationManager   DND support, custom sounds, ClawdToast, history
"""

import os
import threading
from datetime import datetime

from claude_notch.system_monitor import _is_terminal_focused

try:
    import winsound
    HAS_SOUND = True
except ImportError:
    HAS_SOUND = False


class NotificationHistory:
    """Keeps a log of recent notifications."""
    def __init__(self, max_items=50):
        self._items = []
        self._max = max_items
        self._lock = threading.Lock()

    def add(self, title, message, ntype="info"):
        with self._lock:
            self._items.append({"title": title, "message": message, "type": ntype,
                                "time": datetime.now().strftime("%H:%M")})
            if len(self._items) > self._max:
                self._items = self._items[-self._max:]

    def get_recent(self, n=8):
        with self._lock:
            return list(reversed(self._items[-n:]))


class NotificationManager:
    """Manages all notifications — sound, custom ClawdToast popups, history.

    Uses ClawdToast (branded popup with animated Clawd) instead of generic
    Windows toast notifications. The toast is created on the main Qt thread
    via QTimer.singleShot to avoid cross-thread widget creation.
    """

    def __init__(self, config, history=None):
        self.config = config
        self.history = history

    def _should_mute(self) -> bool:
        if self.config.get("dnd_mode", False): return True
        return self.config.get("auto_mute_when_focused", True) and _is_terminal_focused()

    def notify_task_complete(self, project, summary, pid=0):
        if self.history and self.config.get("notification_history_enabled", True):
            self.history.add(f"Claude Code — {project}", summary[:200], "completion")
        if self.config.get("sound_enabled") and HAS_SOUND and not self._should_mute():
            threading.Thread(target=self._play_sound, args=("completion",), daemon=True).start()
        if self.config.get("toast_enabled") and not self.config.get("dnd_mode"):
            self._show_clawd_toast(f"Claude Code — {project}", summary[:200], 6, pid, "completion")

    def notify_needs_attention(self, project, pid=0):
        if self.history and self.config.get("notification_history_enabled", True):
            self.history.add(f"Claude Code — {project}", "Needs your attention!", "attention")
        if self.config.get("sound_enabled") and HAS_SOUND and not self._should_mute():
            threading.Thread(target=self._play_sound, args=("attention",), daemon=True).start()
        if self.config.get("toast_enabled") and not self.config.get("dnd_mode"):
            self._show_clawd_toast(f"Claude Code — {project}", "Needs your attention!", 10, pid, "attention")

    def notify_budget_alert(self, message):
        if self.history: self.history.add("Budget Alert", message, "budget")
        if not self.config.get("dnd_mode"):
            self._show_clawd_toast("Claude Notch — Budget", message, 10, 0, "budget")

    def notify_achievement(self, message):
        if self.history and self.config.get("notification_history_enabled", True):
            self.history.add("Achievement", message, "completion")
        if not self.config.get("dnd_mode"):
            self._show_clawd_toast("Achievement Unlocked!", message, 8, 0, "completion")

    def _show_clawd_toast(self, title, message, timeout, pid, ntype):
        """Show a ClawdToast on the main thread. Safe to call from any thread."""
        from PySide6.QtCore import QTimer
        # QTimer.singleShot(0, ...) schedules on the main thread's event loop
        QTimer.singleShot(0, lambda: self._create_toast(title, message, timeout, pid, ntype))

    def _create_toast(self, title, message, timeout, pid, ntype):
        """Actually create the toast widget. Must run on the main Qt thread."""
        from claude_notch.ui import show_clawd_toast
        show_clawd_toast(title, message, timeout, pid, ntype)

    def _play_sound(self, sound_type):
        custom = self.config.get(f"custom_sound_{sound_type}", "")
        if custom and not custom.startswith("\\\\") and not custom.startswith("//") and os.path.exists(custom):
            try: winsound.PlaySound(custom, winsound.SND_FILENAME | winsound.SND_NODEFAULT); return
            except Exception: pass
        try:
            if sound_type == "completion": winsound.Beep(800, 150); winsound.Beep(1000, 150); winsound.Beep(1200, 200)
            else: winsound.Beep(600, 300); winsound.Beep(600, 300)
        except Exception: pass
