"""
claude_notch.ui.notch — Main overlay widget
=============================================
The ClaudeNotch widget: collapsed notch bar, expanded panel with sessions,
usage stats, sparklines, streaks, notifications, and recent activity.

v4.0.0: Fixed context bar display, deduplicated _open_settings,
removed nested _lerp_color (now imported from clawd).
"""

import math
import subprocess
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QTimer, QPoint, QRectF, Signal
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPainterPath, QLinearGradient, QConicalGradient,
    QPen, QBrush, QCursor, QFontMetrics,
)

from claude_notch import __version__
from claude_notch.config import C, SPINNER_FRAMES
from claude_notch.usage import export_usage_report
from claude_notch.system_monitor import SystemMonitor, _focus_window_by_pid
from claude_notch.ui.clawd import draw_clawd, _with_alpha, _status_colors, _lerp_color
from claude_notch.ui.toast import show_clawd_toast
from claude_notch.ui.settings import open_settings_dialog

class ClaudeNotch(QWidget):
    _update_signal = Signal(str, str)  # version, url — thread-safe update notification
    HW, HH, EW, EH = 300, 34, 560, 500
    VW, VH = 34, 200

    MINI_SZ = 28

    RESIZE_MARGIN = 8   # pixels from edge for resize handle detection
    MIN_EW, MIN_EH = 440, 400
    MAX_EW, MAX_EH = 900, 900

    # Cached fonts — avoid re-allocating QFont objects every paint frame
    _F7 = QFont("Segoe UI", 7)
    _F7B = QFont("Segoe UI", 7, QFont.Weight.Bold)
    _F8 = QFont("Segoe UI", 8)
    _F8B = QFont("Segoe UI", 8, QFont.Weight.Bold)
    _F9 = QFont("Segoe UI", 9)
    _F9B = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
    _F10 = QFont("Segoe UI", 10)
    _F10B = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
    _F11 = QFont("Segoe UI", 11)
    _F14B = QFont("Segoe UI", 14, QFont.Weight.DemiBold)
    _F18B = QFont("Segoe UI", 18, QFont.Weight.Bold)
    _FC8 = QFont("Consolas", 8)
    _FC10 = QFont("Consolas", 10)

    TICK_IDLE = 100    # 10fps when collapsed + no active sessions
    TICK_ACTIVE = 33   # 30fps when animating or sessions active

    def __init__(self, sessions, config, tracker, emotion_engine=None,
                 todo_manager=None, sparkline=None, notif_history=None, streaks=None,
                 token_aggregator=None):
        super().__init__()
        self.sessions = sessions
        self.config = config
        self.tracker = tracker
        self.emotion_engine = emotion_engine
        self.todo_manager = todo_manager
        self.sparkline = sparkline
        self.notif_history = notif_history
        self.token_aggregator = token_aggregator
        self.streaks = streaks
        self._started = datetime.now()
        self._expanded = self._pinned = self._dragging = self._was_exp = False
        self._drag_cooldown = False
        self._resizing = False
        self._resize_edges = set()
        self._resize_start_pos = QPoint()
        self._resize_start_geom = None
        self._refresh_btn_rect = QRectF(0, 0, 0, 0)
        self._dnd_btn_rect = QRectF(0, 0, 0, 0)
        self._export_btn_rect = QRectF(0, 0, 0, 0)
        self._session_click_rects = []
        self._scroll_offset = 0
        self._max_scroll = 0
        self._target_opacity = 1.0
        self._current_opacity = 1.0
        self._drag_off = QPoint()
        self._anim_p = self._bounce = self._pulse = 0.0
        self._anim_dir = 0
        self._ori = "horizontal"
        self._edge = "top"
        self._anchor_pos = QPoint(0, 0)
        self._usage_keys = []  # list of per-key status dicts from UsagePoller
        self._hover_row_idx = -1  # index of session row under cursor
        self._settings_btn_rect = QRectF(0, 0, 0, 0)

        self.setMouseTracking(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self.nw, self.nh)

        lx, ly = config.get("last_x", -1), config.get("last_y", -1)
        scr = self._screen_geom()
        if lx >= 0 and ly >= 0:
            self.move(lx, ly)
            le = config.get("last_edge", "top")
            self._edge = le
            self._ori = "vertical" if le in ("left", "right") else "horizontal"
            self.setFixedSize(self.nw, self.nh)
            self._anchor_pos = QPoint(lx, ly)
        else:
            ax = (scr.width() - self.nw) // 2
            self.move(ax, 0)
            self._anchor_pos = QPoint(ax, 0)

        # Hover timers
        self._ht = QTimer(self)
        self._ht.setSingleShot(True)
        self._ht.setInterval(250)
        self._ht.timeout.connect(self._expand)

        self._ct = QTimer(self)
        self._ct.setSingleShot(True)
        self._ct.setInterval(600)
        self._ct.timeout.connect(self._collapse)

        # Main tick (animation / bounce)
        self._tt = QTimer(self)
        self._tt.setInterval(33)
        self._tt.timeout.connect(self._tick)
        self._tt.start()

        # Expand/collapse animation
        self._at = QTimer(self)
        self._at.setInterval(16)
        self._at.timeout.connect(self._animate)

        # Safety-net hover poll: catches missed enter/leave events
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(200)
        self._hover_timer.timeout.connect(self._hover_check)
        self._hover_timer.start()

        # Periodic dead-session cleanup every 60 s
        self._clt = QTimer(self)
        self._clt.setInterval(60000)
        self._clt.timeout.connect(sessions.cleanup_dead)
        self._clt.start()

        # Emotion decay
        if self.emotion_engine:
            self._emo_timer = QTimer(self)
            self._emo_timer.setInterval(60000)
            self._emo_timer.timeout.connect(self.emotion_engine.decay_all)
            self._emo_timer.start()

        # Visibility guard
        self._vis_timer = QTimer(self)
        self._vis_timer.setInterval(5000)
        self._vis_timer.timeout.connect(self._ensure_visible)
        self._vis_timer.start()

        # Periodic session save every 60 s
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(60000)
        self._save_timer.timeout.connect(sessions.save_state)
        self._save_timer.start()

        # System monitor CPU sampling every 3 s
        self._sys_timer = QTimer(self)
        self._sys_timer.setInterval(3000)
        self._sys_timer.timeout.connect(SystemMonitor.update_cpu)
        self._sys_timer.start()
        SystemMonitor.update_cpu()

        # Performance cache -- avoid recalculating tracker stats every paint frame
        self._cached_today = {}
        self._cached_yesterday = {}
        self._cached_week = {}
        self._cached_month = {}
        self._cached_avg = 0
        self._cached_period_label = "today"
        self._cached_period_data = {}
        self._cache_timer = QTimer(self)
        self._cache_timer.setInterval(5000)
        self._cache_timer.timeout.connect(self._refresh_cache)
        self._cache_timer.start()
        self._refresh_cache()

        self._update_signal.connect(self._on_update_available)
        sessions.session_updated.connect(self.update)

    # ── helpers / properties ──

    def _on_update_available(self, version, url):
        """Slot for _update_signal — runs on the main thread."""
        self._update_url = url
        show_clawd_toast(
            f"ClawdNotch {version} available!",
            "Click to download the latest version.",
            12, 0, "info",
        )

    def _screen_geom(self):
        if self.config.get("multi_monitor", False):
            screen = QApplication.screenAt(self.pos())
            if screen:
                return screen.geometry()
        return QApplication.primaryScreen().geometry()

    @property
    def nw(self):
        if self.config.get("mini_mode"):
            return self.MINI_SZ
        return self.VW if self._ori == "vertical" else self.HW

    @property
    def nh(self):
        if self.config.get("mini_mode"):
            return self.MINI_SZ
        return self.VH if self._ori == "vertical" else self.HH

    @property
    def ew(self):
        return self.config.get("expanded_w", self.EW)

    @property
    def eh(self):
        return self.config.get("expanded_h", self.EH)

    @property
    def uptime(self):
        m = int((datetime.now() - self._started).total_seconds() / 60)
        return "<1m" if m < 1 else f"{m}m" if m < 60 else f"{m // 60}h {m % 60}m"

    def _det_edge(self):
        """Detect which screen edge we're nearest to -- always locks to an edge."""
        scr = self._screen_geom()
        p = self.pos()
        old = self._ori
        cw = self.nw
        ch = self.nh
        d_left = p.x()
        d_right = scr.width() - (p.x() + cw)
        d_top = p.y()
        d_bottom = scr.height() - (p.y() + ch)
        dists = {"left": d_left, "right": d_right, "top": d_top, "bottom": d_bottom}
        nearest = min(dists, key=dists.get)
        if nearest in ("left", "right"):
            self._edge, self._ori = nearest, "vertical"
        else:
            self._edge, self._ori = nearest, "horizontal"
        if old != self._ori and not self._expanded:
            self.setFixedSize(self.nw, self.nh)

    def _save_pos(self):
        self.config.set_many({
            "last_x": self.pos().x(),
            "last_y": self.pos().y(),
            "last_edge": self._edge,
        })

    def update_usage(self, keys_data):
        self._usage_keys = keys_data
        self.update()

    def _refresh_cache(self):
        """Refresh cached tracker stats every 5 s instead of every paint frame."""
        td = self.tracker.today
        mo = self.tracker.month_stats
        avg = self.tracker.daily_avg
        self._cached_today = td
        self._cached_month = mo
        self._cached_avg = avg
        period_label = "today"
        if td.get("tool_calls", 0) == 0 and td.get("prompts", 0) == 0:
            yd = self.tracker.yesterday
            self._cached_yesterday = yd
            if yd.get("tool_calls", 0) > 0 or yd.get("prompts", 0) > 0:
                td = yd
                period_label = "yesterday"
            else:
                wk = self.tracker.week_stats
                self._cached_week = wk
                if wk.get("tool_calls", 0) > 0 or wk.get("prompts", 0) > 0:
                    td = wk
                    period_label = "this week"
        self._cached_period_label = period_label
        self._cached_period_data = td
        # Always fully visible — no dimming
        self._target_opacity = 1.0

    # ── tick / animation ──

    def _tick(self):
        self._bounce += 0.08
        self._pulse += 0.1
        # Snap dim transition — no fade, just set it
        if abs(self._current_opacity - self._target_opacity) > 0.01:
            self._current_opacity = self._target_opacity
            self.setWindowOpacity(self._current_opacity)
        # Always run at full 30fps so Clawd animates smoothly
        if self._tt.interval() != self.TICK_ACTIVE:
            self._tt.setInterval(self.TICK_ACTIVE)
        self.update()

    def _animate(self):
        sp = 0.08
        if self._anim_dir > 0:
            self._anim_p = min(1.0, self._anim_p + sp)
        elif self._anim_dir < 0:
            self._anim_p = max(0.0, self._anim_p - sp)
        if self._anim_p >= 1.0 and self._anim_dir > 0:
            self._at.stop()
        if self._anim_p <= 0.0 and self._anim_dir < 0:
            self._at.stop()
            self._expanded = False
            self._anchor_pos = self.pos()
        t = 1 - (1 - self._anim_p) ** 3
        w = int(self.nw + (self.ew - self.nw) * t)
        h = int(self.nh + (self.eh - self.nh) * t)
        ax, ay = self._anchor_pos.x(), self._anchor_pos.y()
        scr = self._screen_geom()
        if self._edge == "right":
            nx = scr.width() - w
            ny = ay
        elif self._edge == "bottom":
            nx = ax + self.nw // 2 - w // 2
            ny = scr.height() - h
        elif self._edge == "left":
            nx = 0
            ny = ay
        else:
            nx = ax + self.nw // 2 - w // 2
            ny = ay
        self.setFixedSize(w, h)
        self.move(max(0, min(nx, scr.width() - w)), max(0, min(ny, scr.height() - h)))
        self.update()

    def _expand(self):
        if not self._expanded:
            self._expanded = True
            self._anim_dir = 1
            self._at.start()
            # Snap to full opacity immediately when expanding — no slow fade
            self._target_opacity = 1.0
            self._current_opacity = 1.0
            self.setWindowOpacity(1.0)

    def _collapse(self, force=False):
        """Collapse the expanded notch.
        force=True: always collapse (used by click, hotkey). Also unpins.
        force=False: only if cursor is outside (used by hover-leave timer).
        """
        if force:
            self._pinned = False
        if self._expanded and not self._pinned:
            # For timer-triggered collapses: verify cursor actually left
            if not force and self.geometry().contains(QCursor.pos()):
                return
            self._anim_dir = -1
            self._at.start()

    def toggle_expand(self):
        """Toggle expand/collapse -- used by hotkey."""
        if self._expanded:
            self._collapse(force=True)
        else:
            self._pinned = True
            self._expand()

    # ── Hover detection ──

    def enterEvent(self, e):
        self._ct.stop()
        if (not self._expanded and not self._dragging
                and not self._drag_cooldown and not self._resizing):
            self._ht.start()

    def leaveEvent(self, e):
        self._ht.stop()
        if self._expanded and not self._pinned:
            self._ct.start()

    def _hover_check(self):
        """Safety net: poll cursor position every 200 ms to catch missed leave events."""
        if self._dragging or self._resizing or self._drag_cooldown:
            return
        inside = self.geometry().contains(QCursor.pos())
        if not inside and self._expanded and not self._pinned:
            if not self._ct.isActive() and self._anim_dir >= 0:
                self._ct.start()
        elif inside and self._expanded and not self._pinned:
            self._ct.stop()

    # ── Mouse events ──

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            # Check for resize edge first (when fully expanded)
            if self._expanded and self._anim_p >= 1.0:
                edges = self._resize_edge_at(e.pos())
                if edges:
                    self._resizing = True
                    self._resize_edges = edges
                    self._resize_start_pos = e.globalPosition().toPoint()
                    self._resize_start_geom = self.geometry()
                    return
                if self._refresh_btn_rect.contains(e.pos().x(), e.pos().y()):
                    self._do_refresh()
                    return
                if self._dnd_btn_rect.contains(e.pos().x(), e.pos().y()):
                    self._toggle_dnd()
                    return
                if self._export_btn_rect.contains(e.pos().x(), e.pos().y()):
                    self._do_export()
                    return
                if self._settings_btn_rect.contains(e.pos().x(), e.pos().y()):
                    self._open_settings()
                    return
                # Click-to-focus or clipboard on session row
                for rect, sess in self._session_click_rects:
                    if rect.contains(e.pos().x(), e.pos().y()):
                        if self.config.get("click_to_focus", True) and sess.pid:
                            _focus_window_by_pid(sess.pid)
                            return
                        elif self.config.get("clipboard_on_click", True) and sess.project_dir:
                            QApplication.clipboard().setText(sess.project_dir)
                            return
            self._ht.stop()
            self._ct.stop()
            self._drag_cooldown = False
            # Always collapse expanded to collapsed size before dragging
            if self._expanded:
                self._was_exp = True
                click_x, click_y = e.pos().x(), e.pos().y()
                self._anim_p = 0
                self._anim_dir = 0
                self._at.stop()
                self._expanded = False
                self._pinned = False
                self.setFixedSize(self.nw, self.nh)
                # Re-center collapsed notch on cursor
                self.move(
                    self.pos().x() + click_x - self.nw // 2,
                    self.pos().y() + click_y - self.nh // 2,
                )
                self._drag_off = QPoint(self.nw // 2, self.nh // 2)
            else:
                self._was_exp = False
                self._drag_off = e.pos()
            self._dragging = True

    def mouseMoveEvent(self, e):
        if self._resizing:
            self._do_resize(e.globalPosition().toPoint())
            return
        if self._dragging:
            n = self.pos() + e.pos() - self._drag_off
            s = self._screen_geom()
            n.setX(max(0, min(n.x(), s.width() - self.width())))
            n.setY(max(0, min(n.y(), s.height() - self.height())))
            self.move(n)
            self._det_edge()
            if not self._expanded:
                self.setFixedSize(self.nw, self.nh)
            self.update()
        elif self._expanded and self._anim_p >= 1.0:
            # Track hovered session row for highlight
            old_hover = self._hover_row_idx
            self._hover_row_idx = -1
            for i, (rect, _sess) in enumerate(self._session_click_rects):
                if rect.contains(e.pos().x(), e.pos().y()):
                    self._hover_row_idx = i
                    break
            if old_hover != self._hover_row_idx:
                self.update()
            # Update cursor for resize edges
            edges = self._resize_edge_at(e.pos())
            if edges:
                if edges in ({"left"}, {"right"}):
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                elif edges in ({"top"}, {"bottom"}):
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                elif edges in ({"top", "left"}, {"bottom", "right"}):
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                elif edges in ({"top", "right"}, {"bottom", "left"}):
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
                else:
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._resizing:
                self._resizing = False
                self.config.set_many({"expanded_w": self.width(), "expanded_h": self.height()})
                self.setCursor(Qt.CursorShape.ArrowCursor)
                return
            mv = (e.pos() - self._drag_off).manhattanLength()
            self._dragging = False
            self._det_edge()
            self._snap()
            self._save_pos()
            if mv < 5:
                # Click (not drag)
                if self._was_exp:
                    # Was expanded, collapsed on mousePress — click-to-collapse done
                    pass
                elif not self._expanded:
                    # Collapsed -> expand + pin
                    self._pinned = True
                    self._expand()
            else:
                # Real drag completed -- block hover for 800 ms then check cursor
                self._drag_cooldown = True
                self._ht.stop()
                self._ct.stop()
                QTimer.singleShot(800, self._drag_cooldown_end)
            self.update()

    def _drag_cooldown_end(self):
        """Called 800 ms after drag release to re-enable hover."""
        self._drag_cooldown = False
        inside = self.geometry().contains(QCursor.pos())
        if inside and not self._expanded and not self._pinned:
            self._ht.start()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            try:
                check = subprocess.run(
                    ["where", "claude"], capture_output=True, timeout=3,
                    creationflags=0x08000000,
                )
                if check.returncode != 0:
                    show_clawd_toast(
                        "Claude not found",
                        "Make sure 'claude' is on your PATH.",
                        6, 0, "attention",
                    )
                    return
                # Try Windows Terminal first (nicer UX), fall back to cmd.exe
                wt_check = subprocess.run(
                    ["where", "wt"], capture_output=True, timeout=3,
                    creationflags=0x08000000,
                )
                if wt_check.returncode == 0:
                    subprocess.Popen(
                        ["wt", "new-tab", "cmd", "/k", "claude"],
                        creationflags=0x00000008,
                    )
                else:
                    subprocess.Popen(
                        ["cmd", "/c", "start", "cmd", "/k", "claude"],
                        creationflags=0x00000008,
                    )
            except Exception:
                pass

    def wheelEvent(self, e):
        """Scroll the Recent Activity area when expanded."""
        if self._expanded:
            delta = e.angleDelta().y()
            self._scroll_offset = max(
                0, min(self._max_scroll, self._scroll_offset - delta // 4)
            )
            self.update()

    # ── Snap / visibility ──

    def _snap(self):
        """Snap to the nearest screen edge using COLLAPSED dimensions."""
        s = self._screen_geom()
        x, y = self.pos().x(), self.pos().y()
        if self._edge == "top":
            y = 0
        elif self._edge == "bottom":
            y = s.height() - self.nh
        elif self._edge == "left":
            x = 0
        elif self._edge == "right":
            x = s.width() - self.nw
        self.move(x, y)
        self._anchor_pos = QPoint(x, y)

    def _ensure_visible(self):
        if not self.isVisible():
            return
        scr = self._screen_geom()
        p = self.pos()
        x = max(0, min(p.x(), scr.width() - self.width()))
        y = max(0, min(p.y(), scr.height() - self.height()))
        if x != p.x() or y != p.y():
            self.move(x, y)
            self._anchor_pos = QPoint(x, y)
            self._save_pos()
        self.raise_()

    def force_show(self):
        """Reliably show and raise -- used by tray click and hotkeys."""
        self.show()
        self._ensure_visible()

    def showEvent(self, e):
        super().showEvent(e)
        self._ensure_visible()

    # ── Actions ──

    def _toggle_dnd(self):
        cur = self.config.get("dnd_mode", False)
        self.config.set("dnd_mode", not cur)
        self.update()

    def _do_export(self):
        fmt = self.config.get("export_format", "markdown")
        path = export_usage_report(self.tracker, self.config, fmt)
        show_clawd_toast("Export Complete", f"Saved: {Path(path).name}", 5, 0, "completion")

    def _open_settings(self):
        """Open settings dialog from the expanded panel footer."""
        open_settings_dialog(self.config, parent_widget=self)

    def _eye_shift(self):
        try:
            cur = QCursor.pos()
            cx = self.pos().x() + 14 + 5 * 2.5
            cy = self.pos().y() + self.nh // 2
            dx, dy = cur.x() - cx, cur.y() - cy
            d = max(1, math.sqrt(dx * dx + dy * dy))
            return dx / d * 1.2, dy / d * 1.0
        except Exception:
            return 0, 0

    # ── Resize helpers ──

    def _resize_edge_at(self, pos):
        """Detect which edges the cursor is near for resize."""
        if not self._expanded or self._anim_p < 1.0:
            return set()
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        m = self.RESIZE_MARGIN
        edges = set()
        if x < m:
            edges.add("left")
        if x > w - m:
            edges.add("right")
        if y < m:
            edges.add("top")
        if y > h - m:
            edges.add("bottom")
        return edges

    def _do_resize(self, global_pos):
        """Handle resize drag."""
        dx = global_pos.x() - self._resize_start_pos.x()
        dy = global_pos.y() - self._resize_start_pos.y()
        g = self._resize_start_geom
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        if "right" in self._resize_edges:
            w = max(self.MIN_EW, min(self.MAX_EW, g.width() + dx))
        if "left" in self._resize_edges:
            new_w = max(self.MIN_EW, min(self.MAX_EW, g.width() - dx))
            x = g.x() + g.width() - new_w
            w = new_w
        if "bottom" in self._resize_edges:
            h = max(self.MIN_EH, min(self.MAX_EH, g.height() + dy))
        if "top" in self._resize_edges:
            new_h = max(self.MIN_EH, min(self.MAX_EH, g.height() - dy))
            y = g.y() + g.height() - new_h
            h = new_h
        self.setFixedSize(int(w), int(h))
        self.move(int(x), int(y))
        self.update()

    def _do_refresh(self):
        """Scan for active Claude sessions, prune dead ones, and update."""
        self.sessions.cleanup_dead()
        self.sessions.scan_processes()
        self.update()

    # ══════════════════════════════════════════════════════════════════════
    # PAINTING
    # ══════════════════════════════════════════════════════════════════════

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = 1 - (1 - self._anim_p) ** 3
        self._ps(p, w, h, t)
        self._pc(p, t)
        if t < 0.3:
            self._pcol(p, w, t)
        if t > 0.1:
            self._pexp(p, w, h, t)
        p.end()

    # -- _ps : paint shell / border --

    def _ps(self, p, w, h, t):
        path = QPainterPath()
        e = self._edge
        r = int(10 + 4 * t)
        s = 2
        tl = s if e in ("top", "left") else r
        tr = s if e in ("top", "right") else r
        br = s if e in ("bottom", "right") else r
        bl = s if e in ("bottom", "left") else r
        path.moveTo(tl, 0)
        path.lineTo(w - tr, 0)
        path.arcTo(w - tr * 2, 0, tr * 2, tr * 2, 90, -90)
        path.lineTo(w, h - br)
        path.arcTo(w - br * 2, h - br * 2, br * 2, br * 2, 0, -90)
        path.lineTo(bl, h)
        path.arcTo(0, h - bl * 2, bl * 2, bl * 2, -90, -90)
        path.lineTo(0, tl)
        path.arcTo(0, 0, tl * 2, tl * 2, 180, -90)
        bg = QLinearGradient(0, 0, 0, h)
        bg.setColorAt(0, C["notch_bg"])
        bg.setColorAt(1, QColor(8, 8, 10) if t > 0.5 else C["notch_bg"])
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_with_alpha(C["coral"], 40), 3.0))
        p.drawPath(path)
        p.setPen(QPen(C["coral"], 1.0))
        p.drawPath(path)
        if t > 0.2:
            a = min(255, int(t * 300))
            c1 = _with_alpha(C["coral"], 0)
            c2 = _with_alpha(C["coral"], a)
            c3 = _with_alpha(C["coral_light"], a)
            if e == "left":
                g = QLinearGradient(1, 20, 1, h - 20)
                g.setColorAt(0, c1); g.setColorAt(0.3, c2); g.setColorAt(0.7, c3); g.setColorAt(1, c1)
                p.setPen(QPen(QBrush(g), 1.5)); p.drawLine(1, 20, 1, h - 20)
            elif e == "right":
                g = QLinearGradient(w - 1, 20, w - 1, h - 20)
                g.setColorAt(0, c1); g.setColorAt(0.3, c2); g.setColorAt(0.7, c3); g.setColorAt(1, c1)
                p.setPen(QPen(QBrush(g), 1.5)); p.drawLine(w - 1, 20, w - 1, h - 20)
            elif e == "bottom":
                g = QLinearGradient(20, h - 1, w - 20, h - 1)
                g.setColorAt(0, c1); g.setColorAt(0.3, c2); g.setColorAt(0.7, c3); g.setColorAt(1, c1)
                p.setPen(QPen(QBrush(g), 1.5)); p.drawLine(20, h - 1, w - 20, h - 1)
            else:
                g = QLinearGradient(20, 1, w - 20, 1)
                g.setColorAt(0, c1); g.setColorAt(0.3, c2); g.setColorAt(0.7, c3); g.setColorAt(1, c1)
                p.setPen(QPen(QBrush(g), 1.5)); p.drawLine(20, 1, w - 20, 1)
        # Animated glow border — always alive, brighter when working
        if self.sessions.any_working:
            glow_alpha = int(120 + 60 * math.sin(self._pulse * 2))
        elif self.sessions.any_waiting:
            glow_alpha = int(90 + 50 * math.sin(self._pulse * 2.5))
        elif self.sessions.total_active > 0:
            glow_alpha = int(50 + 20 * math.sin(self._pulse * 1.5))
        else:
            glow_alpha = int(40 + 15 * math.sin(self._pulse * 1.5))
        if t < 0.5:
            glow_alpha = int(glow_alpha * (0.5 + t))
        else:
            glow_alpha = int(glow_alpha * min(1.0, (t - 0.3) * 2))

        if glow_alpha > 3:
            cx, cy = w / 2, h / 2
            grad = QConicalGradient(cx, cy, (self._pulse * 20) % 360)
            gc1 = _with_alpha(C["coral"], glow_alpha)
            gc2 = _with_alpha(C["coral_light"], glow_alpha)
            grad.setColorAt(0.0, gc1); grad.setColorAt(0.25, gc2)
            grad.setColorAt(0.5, gc1); grad.setColorAt(0.75, gc2)
            grad.setColorAt(1.0, gc1)

            glow_path = QPainterPath()
            gr = r + 1
            gtl = (s + 1) if e in ("top", "left") else gr
            gtr = (s + 1) if e in ("top", "right") else gr
            gbr = (s + 1) if e in ("bottom", "right") else gr
            gbl = (s + 1) if e in ("bottom", "left") else gr
            glow_path.moveTo(gtl, -1)
            glow_path.lineTo(w - gtr + 1, -1)
            glow_path.arcTo(w - gtr * 2, -1, gtr * 2 + 1, gtr * 2 + 1, 90, -90)
            glow_path.lineTo(w + 1, h - gbr)
            glow_path.arcTo(w - gbr * 2, h - gbr * 2, gbr * 2 + 1, gbr * 2 + 1, 0, -90)
            glow_path.lineTo(gbl, h + 1)
            glow_path.arcTo(-1, h - gbl * 2, gbl * 2 + 1, gbl * 2 + 1, -90, -90)
            glow_path.lineTo(-1, gtl)
            glow_path.arcTo(-1, -1, gtl * 2 + 1, gtl * 2 + 1, 180, -90)

            p.setBrush(Qt.BrushStyle.NoBrush)
            glow_width = 1.5 + t * 0.5
            p.setPen(QPen(QBrush(grad), glow_width))
            p.drawPath(glow_path)

    # -- _pc : paint CLAWD mascot --

    def _pc(self, p, t):
        ps = 2.5
        ex, ey = self._eye_shift()
        col_w, col_h = self.nw, self.nh
        if self._ori == "vertical" and t < 0.3:
            cx = (col_w - 11 * ps) / 2
            cy = 6
        else:
            cx = min(14, col_w * 0.4)
            cy = (col_h - 10 * ps) / 2 + 1
        b = self._bounce
        # Always pulse the warm coral glow
        q = 0.5 + 0.5 * math.sin(self._pulse * 2)
        tint = QColor(int(217 + 23 * q), int(119 + 66 * q), int(87 - 32 * q))
        active = self.sessions.get_active_sessions()
        emotion = active[0].emotion if active else "neutral"
        draw_clawd(
            p, cx, cy, ps, b, tint, ex, ey, emotion,
            eye_glow=True, glow_phase=self._pulse,
        )
        # Mood particles — tiny hearts (happy) or rain drops (sad/sob)
        if emotion in ("happy", "sad", "sob"):
            p.save()
            clawd_cx = cx + 5.5 * ps
            clawd_top = cy
            for i in range(3):
                seed = self._pulse * 0.8 + i * 2.1
                phase = (seed % 3.0) / 3.0  # 0→1 cycle
                px = clawd_cx + math.sin(seed * 1.7 + i) * 6
                py = clawd_top - phase * 18 - 2
                alpha = int(180 * (1 - phase))
                if emotion == "happy":
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QBrush(QColor(235, 100, 120, alpha)))
                    # Tiny heart: two overlapping circles + triangle
                    sz = 1.5 + (1 - phase) * 0.5
                    p.drawEllipse(QRectF(px - sz, py - sz * 0.5, sz, sz))
                    p.drawEllipse(QRectF(px, py - sz * 0.5, sz, sz))
                    tri = QPainterPath()
                    tri.moveTo(px - sz, py); tri.lineTo(px + sz, py); tri.lineTo(px, py + sz); tri.closeSubpath()
                    p.drawPath(tri)
                else:
                    # Rain drop — simple 2px line
                    drop_py = clawd_top + phase * 14 + 2
                    drop_alpha = int(140 * (1 - phase))
                    p.setPen(QPen(QColor(120, 160, 220, drop_alpha), 1.2))
                    p.drawLine(int(px), int(drop_py), int(px), int(drop_py + 3))
            p.restore()

    # -- _pcol : paint collapsed overlay --

    def _pcol(self, p, w, t):
        """Collapsed overlay — status dot, text, session badge."""
        op = 1 - t * 3
        if op <= 0:
            return
        p.save()
        p.setOpacity(op)
        col_w, col_h = self.nw, self.nh
        dc = (
            C["amber"] if self.sessions.any_working
            else C["coral"] if self.sessions.any_waiting
            else C["green"] if self.sessions.total_active > 0
            else C["text_lo"]
        )
        is_mini = self.config.get("mini_mode")
        if is_mini:
            # Mini mode: just a pulsing status dot centered in 28x28
            dx, dy = col_w // 2, col_h // 2
            if self.sessions.any_working or self.sessions.any_waiting:
                q = 0.5 + 0.5 * math.sin(self._pulse * 2.5)
                gr = 3 + q * 2.5
                p.setBrush(QBrush(_with_alpha(dc, int(40 + q * 40))))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(dx - gr, dy - gr, gr * 2, gr * 2))
            p.setBrush(QBrush(dc))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(dx - 3.5, dy - 3.5, 7, 7))
        elif self._ori == "vertical":
            dx, dy = col_w // 2, 38
            if self.sessions.any_working or self.sessions.any_waiting:
                q = 0.5 + 0.5 * math.sin(self._pulse * 2.5)
                gr = 3.5 + q * 3
                p.setBrush(QBrush(_with_alpha(dc, int(40 + q * 40))))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(dx - gr, dy - gr, gr * 2, gr * 2))
            p.setBrush(QBrush(dc))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(dx - 3.5, dy - 3.5, 7, 7))
            c = self.sessions.total_active
            if c > 0:
                p.setPen(QPen(C["text_md"]))
                p.setFont(self._F7)
                p.drawText(0, 48, col_w, 14, Qt.AlignmentFlag.AlignCenter, str(c))
        else:
            dx, dy = 48, col_h // 2
            if self.sessions.any_working or self.sessions.any_waiting:
                q = 0.5 + 0.5 * math.sin(self._pulse * 2.5)
                gr = 3.5 + q * 3
                p.setBrush(QBrush(_with_alpha(dc, int(40 + q * 40))))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(dx - gr, dy - gr, gr * 2, gr * 2))
            p.setBrush(QBrush(dc))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(dx - 3.5, dy - 3.5, 7, 7))
            a = self.sessions.get_active_sessions()
            if a and a[0].state == "working":
                frame_idx = int(self._pulse) % len(SPINNER_FRAMES)
                spinner_char = SPINNER_FRAMES[frame_idx]
                word = a[0].thinking_word or "Working"
                tx = f"{a[0].project_name}: {spinner_char} {word}..."
            elif a and a[0].state == "waiting":
                tx = f"{a[0].project_name}: Needs input!"
            elif a:
                tx = f"{a[0].project_name}: {a[0].current_tool or a[0].state}"
            else:
                tx = "No active sessions"
            # BUG #12 FIX: dynamic truncation using QFontMetrics
            p.setFont(self._F8)
            fm = QFontMetrics(self._F8)
            avail_w = w - 100  # text area starts at x=58, badge needs ~42px from right
            if fm.horizontalAdvance(tx) > avail_w:
                while len(tx) > 1 and fm.horizontalAdvance(tx + "\u2026") > avail_w:
                    tx = tx[:-1]
                tx = tx + "\u2026"
            p.setPen(QPen(C["text_md"]))
            p.drawText(58, 0, w - 100, col_h,
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tx)
            c = self.sessions.total_active
            if c > 0:
                bx, by = w - 28, col_h // 2
                p.setBrush(QBrush(C["coral"] if c > 1 else C["text_lo"]))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(bx - 8, by - 8, 16, 16))
                p.setPen(QPen(QColor(255, 255, 255)))
                p.setFont(self._F7B)
                p.drawText(int(bx - 8), int(by - 8), 16, 16,
                           Qt.AlignmentFlag.AlignCenter, str(c))
        p.restore()

    # -- _pexp : paint expanded panel --

    def _pexp(self, pr, w, h, t):
        if t < 0.05:
            return
        pr.save()
        pr.setClipRect(QRectF(0, 0, w, h))
        top, L, R = self.HH + 10, 20, w - 20
        cw = R - L
        self._session_click_rects = []

        # -- CLAWD ICON (small, top-left) — always pulsing coral glow
        _q = 0.5 + 0.5 * math.sin(self._pulse * 2)
        _exp_tint = QColor(int(217 + 23 * _q), int(119 + 66 * _q), int(87 - 32 * _q))
        draw_clawd(
            pr, L, top + 2, 2.0, self._bounce, _exp_tint, 0, 0, "neutral",
            eye_glow=True, glow_phase=self._pulse,
        )

        # -- TITLE BAR with session pill + refresh button --
        pr.setPen(QPen(C["text_hi"]))
        pr.setFont(self._F14B)
        pr.drawText(L + 28, top, cw - 28, 26, Qt.AlignmentFlag.AlignLeft, "ClawdNotch")
        ac = self.sessions.get_active_sessions()

        # DND button
        dnd_sz = 22
        dnd_x = R - dnd_sz
        dnd_y = top + 3
        self._dnd_btn_rect = QRectF(dnd_x, dnd_y, dnd_sz, dnd_sz)
        dnd_on = self.config.get("dnd_mode", False)
        pr.setBrush(QBrush(
            QColor(230, 72, 72, 40) if dnd_on
            else _with_alpha(C["coral"], 20)
        ))
        pr.setPen(QPen(C["red"] if dnd_on else C["coral"], 1.0))
        pr.drawRoundedRect(self._dnd_btn_rect, 6, 6)
        # Draw bell icon: simple lines for recognizable shape
        pr.setPen(QPen(C["red"] if dnd_on else C["coral"], 1.5))
        bcx = dnd_x + dnd_sz / 2; bcy = dnd_y + dnd_sz / 2
        # Bell body (arc)
        pr.drawArc(QRectF(bcx - 5, bcy - 6, 10, 10), 0, 180 * 16)
        # Bell sides
        pr.drawLine(int(bcx - 5), int(bcy - 1), int(bcx - 5), int(bcy + 3))
        pr.drawLine(int(bcx + 5), int(bcy - 1), int(bcx + 5), int(bcy + 3))
        # Bell bottom rim
        pr.drawLine(int(bcx - 6), int(bcy + 3), int(bcx + 6), int(bcy + 3))
        # Clapper dot
        pr.setBrush(QBrush(C["red"] if dnd_on else C["coral"]))
        pr.drawEllipse(QRectF(bcx - 1.5, bcy + 4, 3, 3))
        # Strike-through line when muted
        if dnd_on:
            pr.setPen(QPen(C["red"], 2.0))
            pr.drawLine(int(bcx - 7), int(bcy + 6), int(bcx + 7), int(bcy - 8))

        # Refresh button
        refresh_sz = 22
        refresh_x = dnd_x - refresh_sz - 4
        refresh_y = top + 3
        self._refresh_btn_rect = QRectF(refresh_x, refresh_y, refresh_sz, refresh_sz)
        pr.setBrush(QBrush(QColor(217, 119, 87, 20)))
        pr.setPen(QPen(C["coral"], 1.0))
        pr.drawRoundedRect(self._refresh_btn_rect, 6, 6)
        pr.setPen(QPen(C["coral"], 1.5))
        pr.setFont(self._F11)
        pr.drawText(int(refresh_x), int(refresh_y), int(refresh_sz), int(refresh_sz),
                    Qt.AlignmentFlag.AlignCenter, "\u27f3")

        # Session pill
        sc_text = f"{len(ac)} session{'s' if len(ac) != 1 else ''}"
        pr.setFont(self._F9B)
        fm = pr.fontMetrics()
        pill_w = fm.horizontalAdvance(sc_text) + 20
        pill_x = refresh_x - pill_w - 8
        pr.setBrush(QBrush(QColor(217, 119, 87, 35)))
        pr.setPen(QPen(C["coral"], 1.0))
        pr.drawRoundedRect(QRectF(pill_x, top + 4, pill_w, 20), 10, 10)
        pr.setPen(QPen(C["coral"]))
        pr.drawText(int(pill_x), top + 4, int(pill_w), 20, Qt.AlignmentFlag.AlignCenter, sc_text)
        top += 32
        pr.setPen(QPen(C["divider"]))
        pr.drawLine(L, top, R, top)
        top += 10

        # -- SESSIONS with coral accent underline --
        pr.setPen(QPen(C["coral"]))
        pr.setFont(self._F10B)
        pr.drawText(L, top, cw, 18, Qt.AlignmentFlag.AlignLeft, "\u25C9 Sessions")
        pr.setPen(QPen(C["coral"], 2.0))
        pr.drawLine(L, top + 18, L + 75, top + 18)
        top += 24
        avg_min = self.sessions.avg_session_minutes
        for si, s in enumerate(ac[:self.config.get("max_sessions_shown", 6)]):
            rh = 28
            row_rect = QRectF(L - 4, top - 2, cw + 8, rh + 4)
            self._session_click_rects.append((row_rect, s))
            # Hover highlight
            if si == self._hover_row_idx:
                pr.setBrush(QBrush(QColor(255, 255, 255, 12)))
                pr.setPen(Qt.PenStyle.NoPen)
                pr.drawRoundedRect(row_rect, 6, 6)
            if s.state == "waiting":
                pr.setBrush(QBrush(QColor(217, 119, 87, 25)))
                pr.setPen(Qt.PenStyle.NoPen)
                pr.drawRoundedRect(QRectF(L - 4, top - 2, cw + 8, rh + 4), 6, 6)
            dc = s.tint if s.state == "working" else _status_colors().get(s.state, C["text_lo"])
            pr.setBrush(QBrush(dc))
            pr.setPen(Qt.PenStyle.NoPen)
            pr.drawEllipse(QRectF(L + 1, top + rh / 2 - 4, 8, 8))
            pr.setPen(QPen(C["text_hi"]))
            pr.setFont(self._F10B)
            nm = s.project_name
            nm = nm[:28] + "..." if len(nm) > 30 else nm
            pr.drawText(L + 16, top, int(cw * 0.55), rh,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, nm)
            pr.setPen(QPen(C["coral"] if s.state == "waiting" else C["text_lo"]))
            pr.setFont(self._F9)
            if s.state == "waiting":
                st = "Needs input!"
            elif s.state == "working":
                frame_idx = int(self._pulse) % len(SPINNER_FRAMES)
                spinner_char = SPINNER_FRAMES[frame_idx]
                word = s.thinking_word or "Working"
                if self.config.get("session_estimate_enabled") and avg_min > 0:
                    remaining = max(0, avg_min - s.age_minutes)
                    st = f"{spinner_char} {word}...  \u00b7  {s.age_str}" + (f"  \u00b7  ~{remaining}m left" if remaining > 0 else "")
                else:
                    st = f"{spinner_char} {word}...  \u00b7  {s.age_str}"
            else:
                st = f"{s.state}  \u00b7  {s.age_str}"
            pr.drawText(int(L + cw * 0.55), top, int(cw * 0.45), rh,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, st)
            top += rh
            # Context bar — use real tokens from JSONL if available
            real_sess = self.token_aggregator.get_session(s.session_id) if self.token_aggregator else None
            real_total = real_sess.get("total", 0) if real_sess else 0
            display_tokens = real_total if real_total > 0 else s.session_tokens
            ctx_pct = min(1.0, display_tokens / max(1, s.context_limit))
            bar_h = 4
            pr.setBrush(QBrush(C["card_bg"]))
            pr.setPen(Qt.PenStyle.NoPen)
            pr.drawRoundedRect(QRectF(L + 16, top, cw - 16, bar_h), 2, 2)
            if ctx_pct > 0:
                # Smooth color interpolation: green → amber → coral → red
                if ctx_pct <= 0.50:
                    bc = _lerp_color(C["green"], C["amber"], ctx_pct / 0.50)
                elif ctx_pct <= 0.80:
                    bc = _lerp_color(C["amber"], C["coral"], (ctx_pct - 0.50) / 0.30)
                else:
                    bc = _lerp_color(C["coral"], C["red"], (ctx_pct - 0.80) / 0.20)
                pr.setBrush(QBrush(bc))
                pr.drawRoundedRect(
                    QRectF(L + 16, top, max(bar_h, (cw - 16) * ctx_pct), bar_h), 2, 2,
                )
            pr.setPen(QPen(C["text_lo"]))
            pr.setFont(self._F7)
            prefix = "" if real_total > 0 else "~"
            if display_tokens > s.context_limit:
                if display_tokens > 1_000_000:
                    ctx_text = f"{prefix}{display_tokens / 1_000_000:.1f}M total"
                else:
                    ctx_text = f"{prefix}{display_tokens // 1000}k total"
            else:
                ctx_text = f"{prefix}{display_tokens // 1000}k / {s.context_limit // 1000}k"
            txt_h = 12
            pr.drawText(int(L + 16), int(top + bar_h + 1), int(cw - 16), txt_h,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, ctx_text)
            top += bar_h + txt_h + 2
        if not ac:
            # Empty state — Clawd still alive (glowing, dancing, green eyes)
            empty_cx = L + cw // 2 - 22
            empty_cy = top + 4
            _eq = 0.5 + 0.5 * math.sin(self._pulse * 2)
            _empty_tint = QColor(int(217 + 23 * _eq), int(119 + 66 * _eq), int(87 - 32 * _eq))
            draw_clawd(pr, empty_cx, empty_cy, 2.2, self._bounce, _empty_tint, 0, 0, "neutral",
                       eye_glow=True, glow_phase=self._pulse)
            # Thought bubble dots
            bx = empty_cx + 28
            by = empty_cy + 2
            pr.setBrush(QBrush(C["text_lo"]))
            pr.setPen(Qt.PenStyle.NoPen)
            pr.drawEllipse(QRectF(bx, by + 12, 3, 3))
            pr.drawEllipse(QRectF(bx + 5, by + 7, 4, 4))
            # Thought bubble
            bubble = QPainterPath()
            bubble.addRoundedRect(QRectF(bx + 8, by - 4, 120, 24), 10, 10)
            pr.setBrush(QBrush(QColor(40, 40, 48)))
            pr.drawPath(bubble)
            pr.setPen(QPen(C["text_md"]))
            pr.setFont(self._F9)
            pr.drawText(int(bx + 14), int(by - 2), 112, 20,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        "Waiting for Claude...")
            top += 36
        top += 4
        pr.setPen(QPen(C["divider"]))
        pr.drawLine(L, top, R, top)
        top += 10

        # -- TASKS with coral header --
        if self.todo_manager:
            all_todos = self.todo_manager.get_all_todos()
            if all_todos:
                done = sum(1 for td_item in all_todos if td_item["status"] == "completed")
                pr.setPen(QPen(C["coral"]))
                pr.setFont(self._F10B)
                pr.drawText(L, top, cw // 2, 18, Qt.AlignmentFlag.AlignLeft, "\u2610 Tasks")
                pr.setPen(QPen(C["coral"], 2.0))
                pr.drawLine(L, top + 18, L + 52, top + 18)
                pr.setPen(QPen(C["coral_light"]))
                pr.setFont(self._F9)
                pr.drawText(L + cw // 2, top, cw // 2, 18,
                            Qt.AlignmentFlag.AlignRight, f"{done}/{len(all_todos)} done")
                top += 24
                todo_colors = {
                    "pending": C["amber"], "in_progress": C["coral"], "completed": C["green"],
                }
                for item in all_todos[:4]:
                    rh = 20
                    tc = todo_colors.get(item["status"], C["text_lo"])
                    pr.setBrush(QBrush(tc))
                    pr.setPen(Qt.PenStyle.NoPen)
                    pr.drawEllipse(QRectF(L + 1, top + rh / 2 - 3, 6, 6))
                    pr.setPen(QPen(C["text_hi"]))
                    pr.setFont(self._F9)
                    txt = item["text"]
                    txt = txt[:55] + "..." if len(txt) > 57 else txt
                    pr.drawText(L + 14, top, cw - 14, rh,
                                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, txt)
                    top += rh + 2
                top += 4
                pr.setPen(QPen(C["divider"]))
                pr.drawLine(L, top, R, top)
                top += 10

        # -- USAGE with coral stat cards --
        sub_mode = self.config.get("subscription_mode", "max")
        pr.setPen(QPen(C["coral"]))
        pr.setFont(self._F10B)
        pr.drawText(L, top, cw, 18, Qt.AlignmentFlag.AlignLeft, "\u25AE Usage")
        pr.setPen(QPen(C["coral"], 2.0))
        pr.drawLine(L, top + 18, L + 56, top + 18)
        # Subscription mode pill
        mode_text = "Subscription" if sub_mode == "max" else "API Tokens"
        pr.setFont(self._F7B)
        fm = pr.fontMetrics()
        mp_w = fm.horizontalAdvance(mode_text) + 12
        mp_c = C["green"] if sub_mode == "max" else C["amber"]
        pr.setBrush(QBrush(_with_alpha(mp_c, 30)))
        pr.setPen(QPen(mp_c, 0.8))
        pr.drawRoundedRect(QRectF(L + 50, top + 2, mp_w, 16), 8, 8)
        pr.setPen(QPen(mp_c))
        pr.drawText(int(L + 50), int(top + 2), int(mp_w), 16,
                    Qt.AlignmentFlag.AlignCenter, mode_text)
        top += 26

        td = self._cached_period_data
        mo = self._cached_month
        avg = self._cached_avg
        period_label = self._cached_period_label

        tc_today = td.get("tool_calls", 0)
        pr_today = td.get("prompts", 0)

        # -- Coral-bordered stat cards (3 across) --
        card_gap = 8
        card_w = (cw - card_gap * 2) // 3
        card_h = 52
        card_r = 8
        if sub_mode == "max":
            sess_count = self.sessions.total_active
            stats = [
                (str(tc_today), f"tools {period_label}", C["coral"]),
                (str(pr_today), "prompts", C["coral_light"]),
                (str(sess_count), "sessions", C["green"]),
            ]
        else:
            cost_today = td.get("est_cost", 0.0)
            stats = [
                (str(tc_today), f"tools {period_label}", C["coral"]),
                (str(pr_today), "prompts", C["coral_light"]),
                (f"${cost_today:.2f}" if cost_today < 100 else f"${cost_today:.0f}",
                 "est. cost", C["green"]),
            ]
        for i, (val, label, color) in enumerate(stats):
            cx = L + i * (card_w + card_gap)
            pr.setBrush(QBrush(_with_alpha(color, 12)))
            pr.setPen(QPen(_with_alpha(color, 70), 1.0))
            pr.drawRoundedRect(QRectF(cx, top, card_w, card_h), card_r, card_r)
            pr.setPen(QPen(color))
            pr.setFont(self._F18B)
            pr.drawText(int(cx + 8), int(top + 2), int(card_w - 16), 28,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, val)
            pr.setPen(QPen(C["text_md"]))
            pr.setFont(self._F8)
            pr.drawText(int(cx + 8), int(top + 32), int(card_w - 16), 14,
                        Qt.AlignmentFlag.AlignLeft, label)
        top += card_h + 8

        # Token summary
        est_tok = td.get("est_tokens", 0)
        # Real token data from Claude Code JSONL files (if available)
        real_tokens = self.token_aggregator.get_today() if self.token_aggregator else None
        if real_tokens and real_tokens.get("total", 0) > 0:
            rt = real_tokens["total"]
            tok_str = f"{rt / 1_000_000:.1f}M" if rt > 1_000_000 else f"{rt / 1000:.0f}k" if rt > 1000 else str(rt)
            tok_detail = f"{tok_str} tokens today"
            # Show breakdown: input/output/cache
            inp = real_tokens.get("input", 0); out = real_tokens.get("output", 0)
            cr = real_tokens.get("cache_read", 0)
            cwr = real_tokens.get("cache_write", 0)
            parts = []
            if inp: parts.append(f"in:{inp//1000}k")
            if out: parts.append(f"out:{out//1000}k")
            if cr: parts.append(f"cache_r:{cr//1000}k")
            if cwr: parts.append(f"cache_w:{cwr//1000}k")
            detail_str = "  ·  ".join(parts) if parts else ""
            pr.setPen(QPen(C["coral"])); pr.setFont(self._F9B)
            pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft, tok_detail)
            if detail_str:
                top += 15
                pr.setPen(QPen(C["text_lo"])); pr.setFont(self._F8)
                pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft, detail_str)
        else:
            est_tok = td.get("est_tokens", 0)
            tok_str = (
                f"~{est_tok / 1_000_000:.1f}M" if est_tok > 1_000_000
                else f"~{est_tok / 1000:.0f}k" if est_tok > 1000
                else f"~{est_tok}"
            )
            pr.setPen(QPen(C["text_md"])); pr.setFont(self._F9)
            pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft,
                        f"{tok_str} est. tokens {period_label}  \u00b7  {td.get('sessions', 0)} sessions")
        top += 18

        # Monthly bar
        mo_calls = mo.get("tool_calls", 0)
        mo_cap = max(1000, mo_calls + 500)
        top = self._bar(
            pr, L, top, cw,
            f"This Month \u2014 {datetime.now().strftime('%B')}",
            min(1.0, mo_calls / mo_cap),
            f"{mo_calls:,} calls",
        ) + 4

        # Monthly details
        mo_tok = mo.get("est_tokens", 0)
        mo_tok_str = (
            f"~{mo_tok / 1_000_000:.1f}M" if mo_tok > 1_000_000
            else f"~{mo_tok / 1000:.0f}k" if mo_tok > 1000
            else f"~{mo_tok}"
        )
        pr.setPen(QPen(C["text_lo"]))
        pr.setFont(self._F8)
        if sub_mode == "api":
            mo_cost = mo.get("est_cost", 0.0)
            mo_cost_str = f"${mo_cost:.2f}" if mo_cost < 100 else f"${mo_cost:.0f}"
            pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft,
                        f"{mo_tok_str} tokens  \u00b7  {mo_cost_str}  \u00b7  "
                        f"{mo.get('days_active', 0)} days  \u00b7  avg {avg}/day")
        else:
            pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft,
                        f"{mo_tok_str} tokens  \u00b7  {mo.get('days_active', 0)} days active"
                        f"  \u00b7  avg {avg}/day")
        top += 16

        # -- SPARKLINE --
        if self.sparkline and self.config.get("sparkline_enabled"):
            data = self.sparkline.get_data()
            mx = max(data) if data else 1
            if mx > 0:
                sl_h = 16
                bw = max(1.5, (cw - 4) / len(data))
                for i, v in enumerate(data):
                    if v > 0:
                        bh = max(1, (v / mx) * sl_h)
                        pr.setBrush(QBrush(QColor(
                            C["coral"].red(), C["coral"].green(), C["coral"].blue(),
                            80 + int(v / mx * 120),
                        )))
                        pr.setPen(Qt.PenStyle.NoPen)
                        pr.drawRoundedRect(
                            QRectF(L + i * bw, top + sl_h - bh, bw - 0.8, bh), 1, 1,
                        )
                pr.setPen(QPen(C["text_lo"]))
                pr.setFont(self._F7)
                pr.drawText(L, int(top + sl_h + 1), cw, 10,
                            Qt.AlignmentFlag.AlignRight, "activity (30 min)")
                top += sl_h + 12

        # -- STREAKS --
        if self.streaks and self.config.get("streaks_enabled"):
            streak = self.streaks.current_streak
            top_day, top_count = self.streaks.top_day_this_week
            pr.setPen(QPen(C["coral"]))
            pr.setFont(self._F9)
            streak_text = (
                f"  {streak}-day streak" if streak > 1 else "Start your streak today!"
            )
            extra = f"  \u00b7  Top: {top_day} ({top_count})" if top_day else ""
            pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft, streak_text + extra)
            top += 16

        # -- SYSTEM RESOURCES --
        if self.config.get("system_resources_enabled"):
            ram = SystemMonitor.get_ram()
            cpu = SystemMonitor.get_cpu()
            pr.setPen(QPen(C["text_md"]))
            pr.setFont(self._F8)
            pr.drawText(
                L, top, cw, 12, Qt.AlignmentFlag.AlignLeft,
                f"CPU {cpu:.0f}%  \u00b7  RAM {ram['used_gb']}GB/{ram['total_gb']}GB ({ram['pct']}%)",
            )
            top += 14
            half = (cw - 8) // 2
            for i, (lbl, pct, clr) in enumerate([
                ("CPU", cpu / 100, C["coral"]),
                ("RAM", ram["pct"] / 100, C["amber"]),
            ]):
                bx = L + i * (half + 8)
                bw_r = half
                bh_r = 4
                pr.setBrush(QBrush(C["card_bg"]))
                pr.setPen(Qt.PenStyle.NoPen)
                pr.drawRoundedRect(QRectF(bx, top, bw_r, bh_r), 2, 2)
                if pct > 0:
                    pr.setBrush(QBrush(C["red"] if pct > 0.9 else clr))
                    pr.drawRoundedRect(
                        QRectF(bx, top, max(bh_r, bw_r * min(1, pct)), bh_r), 2, 2,
                    )
            top += 8

        # -- API KEYS section --
        HEALTH_COLORS = {
            "healthy": C["green"], "warm": C["amber"],
            "throttled": C["red"], "error": QColor(120, 110, 105),
        }
        MAX_KEYS_SHOWN = 5
        if self._usage_keys:
            pr.setPen(QPen(C["coral"]))
            pr.setFont(self._F9B)
            pr.drawText(L, top, cw, 16, Qt.AlignmentFlag.AlignLeft, "\u26BF API Keys")
            pr.setPen(QPen(C["coral"], 1.5))
            pr.drawLine(L, top + 15, L + 68, top + 15)
            top += 20
            for kd in self._usage_keys[:MAX_KEYS_SHOWN]:
                row_h = 22
                hc = HEALTH_COLORS.get(kd.get("health", "error"), HEALTH_COLORS["error"])
                # Health dot
                pr.setBrush(QBrush(hc))
                pr.setPen(Qt.PenStyle.NoPen)
                pr.drawEllipse(QRectF(L + 1, top + row_h / 2 - 3.5, 7, 7))
                # Label
                pr.setPen(QPen(C["text_hi"]))
                pr.setFont(self._F9B)
                lbl = kd.get("label", "Key")
                lbl = lbl[:14] + ".." if len(lbl) > 15 else lbl
                pr.drawText(int(L + 14), int(top), int(cw * 0.28), row_h,
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lbl)
                # Redacted key
                pr.setPen(QPen(C["text_lo"]))
                pr.setFont(self._FC8)
                pr.drawText(int(L + cw * 0.28 + 4), int(top), int(cw * 0.32), row_h,
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                            kd.get("key_redacted", ""))
                # Usage bar or status text
                bar_x = int(L + cw * 0.63)
                bar_w = int(cw * 0.37 - 4)
                err = kd.get("error")
                if err:
                    pr.setPen(QPen(hc))
                    pr.setFont(self._F7)
                    err_short = err[:22] + ".." if len(err) > 24 else err
                    pr.drawText(bar_x, int(top), bar_w, row_h,
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                err_short)
                else:
                    # Mini usage bar
                    rpm_l = kd.get("rpm_limit", 0)
                    rpm_u = kd.get("rpm_used", 0)
                    pct = (rpm_u / max(1, rpm_l)) if rpm_l else 0
                    bar_y = int(top + row_h / 2 - 3)
                    bh = 6
                    bw_bar = bar_w - 36
                    pr.setBrush(QBrush(C["card_bg"]))
                    pr.setPen(Qt.PenStyle.NoPen)
                    pr.drawRoundedRect(QRectF(bar_x, bar_y, bw_bar, bh), 3, 3)
                    if pct > 0:
                        pr.setBrush(QBrush(hc))
                        pr.drawRoundedRect(
                            QRectF(bar_x, bar_y, max(bh, bw_bar * min(1, pct)), bh), 3, 3,
                        )
                    pr.setPen(QPen(C["text_md"]))
                    pr.setFont(self._F7)
                    pr.drawText(bar_x + bw_bar + 4, int(top), 32, row_h,
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                f"{int(pct * 100)}%")
                top += row_h + 2
            if len(self._usage_keys) > MAX_KEYS_SHOWN:
                extra = len(self._usage_keys) - MAX_KEYS_SHOWN
                pr.setPen(QPen(C["text_lo"]))
                pr.setFont(self._F8)
                pr.drawText(L + 14, int(top), int(cw - 14), 16,
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                            f"+ {extra} more key{'s' if extra > 1 else ''}")
                top += 18
        elif sub_mode == "api":
            pr.setPen(QPen(C["text_lo"]))
            pr.setFont(self._F8)
            pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft,
                        "Add API keys in Settings to monitor usage")
            top += 14

        top += 4
        pr.setPen(QPen(C["divider"]))
        pr.drawLine(L, top, R, top)
        top += 8

        # -- NOTIFICATION HISTORY --
        if self.notif_history and self.config.get("notification_history_enabled"):
            recent = self.notif_history.get_recent(4)
            if recent:
                pr.setPen(QPen(C["coral"]))
                pr.setFont(self._F9B)
                pr.drawText(L, top, cw, 16, Qt.AlignmentFlag.AlignLeft, "\u25C8 Notifications")
                pr.setPen(QPen(C["coral"], 1.5))
                pr.drawLine(L, top + 15, L + 100, top + 15)
                top += 20
                ntype_colors = {
                    "completion": C["green"], "attention": C["coral"], "budget": C["amber"],
                }
                for n in recent:
                    rh_n = 18
                    nc = ntype_colors.get(n["type"], C["text_lo"])
                    pr.setBrush(QBrush(nc))
                    pr.setPen(Qt.PenStyle.NoPen)
                    pr.drawEllipse(QRectF(L + 1, top + rh_n / 2 - 2.5, 5, 5))
                    pr.setPen(QPen(C["text_hi"]))
                    pr.setFont(self._F8)
                    pr.drawText(int(L + 12), int(top), int(cw - 50), rh_n,
                                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                                n["message"][:50])
                    pr.setPen(QPen(C["text_lo"]))
                    pr.setFont(self._F7)
                    pr.drawText(int(L + cw - 36), int(top), 36, rh_n,
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                n["time"])
                    top += rh_n + 1
                top += 4
                pr.setPen(QPen(C["divider"]))
                pr.drawLine(L, top, R, top)
                top += 8

        # -- RECENT ACTIVITY (scrollable) --
        pr.setPen(QPen(C["coral"]))
        pr.setFont(self._F10B)
        pr.drawText(L, top, cw, 18, Qt.AlignmentFlag.AlignLeft, "\u25F7 Recent Activity")
        pr.setPen(QPen(C["coral"], 2.0))
        pr.drawLine(L, top + 18, L + 124, top + 18)
        top += 24

        footer_h = 36
        avail = h - top - footer_h
        rh = 22
        tasks = self.sessions.get_all_tasks(20)

        if tasks:
            total_content = len(tasks) * (rh + 1)
            self._max_scroll = max(0, total_content - avail)
            self._scroll_offset = max(0, min(self._scroll_offset, self._max_scroll))

            pr.save()
            pr.setClipRect(QRectF(L - 2, top, cw + 4, avail))

            item_y = top - self._scroll_offset
            for tk in tasks:
                if item_y + rh < top:
                    item_y += rh + 1
                    continue
                if item_y > top + avail:
                    break
                sc = C["green"] if tk.get("status") == "completed" else C["coral"]
                pr.setBrush(QBrush(sc))
                pr.setPen(Qt.PenStyle.NoPen)
                pr.drawEllipse(QRectF(L + 1, item_y + rh / 2 - 3, 6, 6))
                pr.setPen(QPen(C["text_hi"]))
                pr.setFont(self._F9)
                max_chars = max(30, int((cw - 70) / 6.5))
                d = f"{tk.get('project', '')}: {tk.get('summary', '')}"
                d = d[:max_chars] + "..." if len(d) > max_chars + 2 else d
                pr.drawText(int(L + 14), int(item_y), int(cw - 64), rh,
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, d)
                pr.setPen(QPen(C["text_lo"]))
                pr.setFont(self._F8)
                pr.drawText(int(L + cw - 44), int(item_y), 44, rh,
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                            tk.get("time", ""))
                item_y += rh + 1

            pr.restore()

            # Gradient fade at scroll edges — content fades into view
            if self._max_scroll > 0:
                fade_h = 16
                if self._scroll_offset > 0:
                    fade_top = QLinearGradient(0, top, 0, top + fade_h)
                    fade_top.setColorAt(0, C["notch_bg"])
                    fade_top.setColorAt(1, _with_alpha(C["notch_bg"], 0))
                    pr.setBrush(QBrush(fade_top))
                    pr.setPen(Qt.PenStyle.NoPen)
                    pr.drawRect(QRectF(L - 2, top, cw + 4, fade_h))
                if self._scroll_offset < self._max_scroll:
                    bot = top + avail
                    fade_bot = QLinearGradient(0, bot - fade_h, 0, bot)
                    fade_bot.setColorAt(0, _with_alpha(C["notch_bg"], 0))
                    fade_bot.setColorAt(1, C["notch_bg"])
                    pr.setBrush(QBrush(fade_bot))
                    pr.setPen(Qt.PenStyle.NoPen)
                    pr.drawRect(QRectF(L - 2, bot - fade_h, cw + 4, fade_h))

            # Scroll indicator
            if self._max_scroll > 0:
                track_h = avail - 4
                thumb_h = max(12, int(track_h * avail / total_content))
                thumb_y = top + 2 + int(
                    (track_h - thumb_h) * self._scroll_offset / max(1, self._max_scroll)
                )
                pr.setBrush(QBrush(QColor(217, 119, 87, 60)))
                pr.setPen(Qt.PenStyle.NoPen)
                pr.drawRoundedRect(QRectF(R - 3, thumb_y, 3, thumb_h), 1.5, 1.5)
        else:
            self._max_scroll = 0
            pr.setPen(QPen(C["text_lo"]))
            pr.setFont(self._F9)
            pr.drawText(L, top, cw, 18, Qt.AlignmentFlag.AlignLeft, "No recent activity")

        # -- FOOTER --
        btn_h = 16
        # Settings gear button
        gear_w = 22
        gear_x = R - gear_w
        gear_y = h - 32
        self._settings_btn_rect = QRectF(gear_x, gear_y, gear_w, btn_h)
        pr.setBrush(QBrush(_with_alpha(C["coral"], 20)))
        pr.setPen(QPen(C["coral"], 0.8))
        pr.drawRoundedRect(self._settings_btn_rect, 4, 4)
        pr.setPen(QPen(C["coral"]))
        pr.setFont(self._F9)
        pr.drawText(int(gear_x), int(gear_y), int(gear_w), int(btn_h),
                    Qt.AlignmentFlag.AlignCenter, "\u2699")
        # Export button
        exp_w = 50
        exp_x = gear_x - exp_w - 4
        exp_y = h - 32
        self._export_btn_rect = QRectF(exp_x, exp_y, exp_w, btn_h)
        pr.setBrush(QBrush(_with_alpha(C["coral"], 20)))
        pr.setPen(QPen(C["coral"], 0.8))
        pr.drawRoundedRect(self._export_btn_rect, 4, 4)
        pr.setPen(QPen(C["coral"]))
        pr.setFont(self._F7B)
        pr.drawText(int(exp_x), int(exp_y), int(exp_w), int(btn_h),
                    Qt.AlignmentFlag.AlignCenter, "Export")
        pr.setPen(QPen(C["coral"]))
        pr.setFont(self._F8)
        pin = ("Pinned" if self._pinned
               else "Click = expand  \u00b7  Hover = peek  \u00b7  DblClick = new session")
        pr.drawText(L, h - 32, cw - exp_w - gear_w - 16, 14, Qt.AlignmentFlag.AlignLeft, pin)
        pr.setPen(QPen(C["text_lo"]))
        pr.setFont(self._F8)
        pr.drawText(L, h - 18, cw, 14, Qt.AlignmentFlag.AlignCenter,
                    f"v{__version__}  \u00b7  Running {self.uptime}")
        pr.restore()

    # -- _bar : progress bar helper --

    def _bar(self, p, x, y, w, label, val, txt):
        """BUG FIX #7: 1 px dark text shadow behind bar text."""
        bh, br = 14, 7
        p.setPen(QPen(C["text_md"]))
        p.setFont(self._F9)
        p.drawText(x, y, w, 16, Qt.AlignmentFlag.AlignLeft, label)
        y += 17
        p.setBrush(QBrush(C["card_bg"]))
        p.setPen(QPen(C["divider"], 0.5))
        p.drawRoundedRect(QRectF(x, y, w, bh), br, br)
        v = max(0, min(1, val))
        if v > 0:
            fw = max(bh, w * v)
            g = QLinearGradient(x, y, x + fw, y)
            g.setColorAt(0, C["coral"])
            g.setColorAt(1, C["red"] if v > 0.8 else C["coral_light"])
            p.setBrush(QBrush(g))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x + 1, y + 1, fw - 2, bh - 2), br - 1, br - 1)
        # BUG #7 FIX: draw dark shadow first, then bright text on top
        p.setFont(self._F8)
        p.setPen(QPen(QColor(0, 0, 0, 120)))
        p.drawText(int(x + 1), int(y + 1), int(w - 4), int(bh),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, txt)
        p.setPen(QPen(C["text_hi"]))
        p.drawText(int(x), int(y), int(w - 4), int(bh),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, txt)
        return y + bh
