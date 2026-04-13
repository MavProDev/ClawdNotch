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
from claude_notch.system_monitor import SystemMonitor, _focus_window_by_pid, _focus_window_by_project
from claude_notch.ui.clawd import draw_clawd, _with_alpha, _lerp_color
from claude_notch.ui.toast import show_clawd_toast
from claude_notch.ui.settings import open_settings_dialog

class ClaudeNotch(QWidget):
    _update_signal = Signal(str, str)  # version, url — thread-safe update notification
    HW, HH, EW, EH = 300, 34, 480, 400
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
        self._ht.setInterval(120)  # snappy expand trigger
        self._ht.timeout.connect(self._expand)

        self._ct = QTimer(self)
        self._ct.setSingleShot(True)
        self._ct.setInterval(300)  # responsive collapse
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
        self._hover_timer.setInterval(150)  # tighter polling for snappier response
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
        sp = 0.14  # faster animation (was 0.08 — now ~7 frames / ~110ms)
        if self._anim_dir > 0:
            self._anim_p = min(1.0, self._anim_p + sp)
        elif self._anim_dir < 0:
            self._anim_p = max(0.0, self._anim_p - sp * 1.3)  # collapse slightly faster than expand
        if self._anim_p >= 1.0 and self._anim_dir > 0:
            self._at.stop()
        if self._anim_p <= 0.0 and self._anim_dir < 0:
            self._at.stop()
            self._expanded = False
            self._anchor_pos = self.pos()
        t = 1 - (1 - self._anim_p) ** 2  # quadratic ease-out (was cubic — snappier start)
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
                        if self.config.get("click_to_focus", True):
                            # Try project name match first (most reliable), then PID
                            if sess.project_name and sess.project_name not in ("unknown",):
                                _focus_window_by_project(sess.project_name)
                                return
                            if not sess.pid:
                                self.sessions.scan_processes()
                            if sess.pid:
                                _focus_window_by_pid(sess.pid)
                                return
                        if self.config.get("clipboard_on_click", True) and sess.project_dir:
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
            # Only repaint if edge or orientation actually changed — avoids
            # forcing a full paintEvent on every pixel of mouse movement
            prev_edge, prev_ori = self._edge, self._ori
            self._det_edge()
            if self._edge != prev_edge or self._ori != prev_ori:
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

    # -- _pexp : paint expanded panel (v4.1 — Ultra Clean) --

    def _pexp(self, pr, w, h, t):
        if t < 0.05:
            return
        pr.save()
        pr.setClipRect(QRectF(0, 0, w, h))
        top, L, R = self.HH + 8, 20, w - 20
        cw = R - L
        self._session_click_rects = []
        ac = self.sessions.get_active_sessions()

        # ── HEADER: Clawd + title + buttons ──
        _q = 0.5 + 0.5 * math.sin(self._pulse * 2)
        _exp_tint = QColor(int(217 + 23 * _q), int(119 + 66 * _q), int(87 - 32 * _q))
        draw_clawd(pr, L, top + 2, 2.0, self._bounce, _exp_tint, 0, 0,
                   ac[0].emotion if ac else "neutral", eye_glow=True, glow_phase=self._pulse)

        pr.setPen(QPen(C["text_hi"]))
        pr.setFont(self._F14B)
        pr.drawText(L + 28, top, cw - 28, 26, Qt.AlignmentFlag.AlignLeft, "ClawdNotch")

        # Settings button (gear)
        gear_sz = 24
        gear_x = R - gear_sz
        gear_y = top + 2
        self._settings_btn_rect = QRectF(gear_x, gear_y, gear_sz, gear_sz)
        pr.setBrush(QBrush(QColor(255, 255, 255, 8)))
        pr.setPen(Qt.PenStyle.NoPen)
        pr.drawRoundedRect(self._settings_btn_rect, 6, 6)
        pr.setPen(QPen(C["text_lo"]))
        pr.setFont(self._F11)
        pr.drawText(int(gear_x), int(gear_y), int(gear_sz), int(gear_sz),
                    Qt.AlignmentFlag.AlignCenter, "\u2699")

        # Refresh button
        refresh_sz = 24
        refresh_x = gear_x - refresh_sz - 4
        refresh_y = top + 2
        self._refresh_btn_rect = QRectF(refresh_x, refresh_y, refresh_sz, refresh_sz)
        pr.setBrush(QBrush(QColor(255, 255, 255, 8)))
        pr.setPen(Qt.PenStyle.NoPen)
        pr.drawRoundedRect(self._refresh_btn_rect, 6, 6)
        pr.setPen(QPen(C["text_lo"]))
        pr.setFont(self._F11)
        pr.drawText(int(refresh_x), int(refresh_y), int(refresh_sz), int(refresh_sz),
                    Qt.AlignmentFlag.AlignCenter, "\u27f3")

        # DND button
        dnd_sz = 24
        dnd_x = refresh_x - dnd_sz - 4
        dnd_y = top + 2
        self._dnd_btn_rect = QRectF(dnd_x, dnd_y, dnd_sz, dnd_sz)
        dnd_on = self.config.get("dnd_mode", False)
        pr.setBrush(QBrush(QColor(230, 72, 72, 30) if dnd_on else QColor(255, 255, 255, 8)))
        pr.setPen(Qt.PenStyle.NoPen)
        pr.drawRoundedRect(self._dnd_btn_rect, 6, 6)
        pr.setPen(QPen(C["red"] if dnd_on else C["text_lo"]))
        pr.setFont(self._F11)
        pr.drawText(int(dnd_x), int(dnd_y), int(dnd_sz), int(dnd_sz),
                    Qt.AlignmentFlag.AlignCenter, "\U0001f515" if dnd_on else "\U0001f514")

        top += 32
        pr.setPen(QPen(QColor(255, 255, 255, 10)))
        pr.drawLine(L, top, R, top)
        top += 12

        # ── SESSION CARDS ──
        for si, s in enumerate(ac[:self.config.get("max_sessions_shown", 6)]):
            card_h = 42
            card_rect = QRectF(L, top, cw, card_h)
            self._session_click_rects.append((card_rect, s))

            # Status-based styling
            if s.state == "waiting":
                border_color = C["coral"]
                bg_alpha = 12
            elif s.state == "working":
                border_color = C["amber"]
                bg_alpha = 8
            elif s.state == "error":
                border_color = C["red"]
                bg_alpha = 8
            else:
                border_color = C["text_lo"]
                bg_alpha = 4

            # Card background
            pr.setBrush(QBrush(_with_alpha(border_color, bg_alpha)))
            pr.setPen(Qt.PenStyle.NoPen)
            pr.drawRoundedRect(card_rect, 10, 10)
            # Left accent border
            pr.setBrush(QBrush(border_color))
            pr.drawRoundedRect(QRectF(L, top + 6, 3, card_h - 12), 1.5, 1.5)
            # Subtle card outline
            pr.setBrush(Qt.BrushStyle.NoBrush)
            pr.setPen(QPen(_with_alpha(border_color, 20), 0.5))
            pr.drawRoundedRect(card_rect, 10, 10)

            # Hover highlight
            if si == self._hover_row_idx:
                pr.setBrush(QBrush(QColor(255, 255, 255, 8)))
                pr.setPen(Qt.PenStyle.NoPen)
                pr.drawRoundedRect(card_rect, 10, 10)

            # Status dot with glow
            dot_x = L + 14
            dot_y = top + 14
            if s.state in ("working", "waiting"):
                glow_a = int(30 + 20 * math.sin(self._pulse * 2.5))
                pr.setBrush(QBrush(_with_alpha(border_color, glow_a)))
                pr.setPen(Qt.PenStyle.NoPen)
                pr.drawEllipse(QRectF(dot_x - 4, dot_y - 4, 14, 14))
            pr.setBrush(QBrush(border_color))
            pr.setPen(Qt.PenStyle.NoPen)
            pr.drawEllipse(QRectF(dot_x, dot_y, 6, 6))

            # Project name
            pr.setPen(QPen(C["text_hi"] if s.state != "idle" else C["text_md"]))
            pr.setFont(self._F10B)
            nm = s.project_name
            nm = nm[:26] + "\u2026" if len(nm) > 28 else nm
            pr.drawText(int(L + 28), int(top + 4), int(cw * 0.5), 18,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, nm)

            # Status text (right side)
            pr.setFont(self._F9)
            if s.state == "waiting":
                pr.setPen(QPen(C["coral"]))
                st = "Needs input"
            elif s.state == "working":
                pr.setPen(QPen(_with_alpha(C["amber"], 180)))
                frame_idx = int(self._pulse) % len(SPINNER_FRAMES)
                word = s.thinking_word or "Working"
                st = f"{SPINNER_FRAMES[frame_idx]} {word}\u2026 \u00b7 {s.age_str}"
            else:
                pr.setPen(QPen(C["text_lo"]))
                st = f"{s.state} \u00b7 {s.age_str}"
            pr.drawText(int(L + cw * 0.5), int(top + 4), int(cw * 0.5 - 12), 18,
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, st)

            # Context bar (integrated into card)
            real_sess = self.token_aggregator.get_session(s.session_id) if self.token_aggregator else None
            real_total = real_sess.get("total", 0) if real_sess else 0
            display_tokens = real_total if real_total > 0 else s.session_tokens
            ctx_pct = min(1.0, display_tokens / max(1, s.context_limit))
            bar_y = top + card_h - 10
            bar_x = L + 12
            bar_w = cw - 24
            pr.setBrush(QBrush(QColor(255, 255, 255, 6)))
            pr.setPen(Qt.PenStyle.NoPen)
            pr.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, 2), 1, 1)
            if ctx_pct > 0:
                if ctx_pct <= 0.50:
                    bc = _lerp_color(C["green"], C["amber"], ctx_pct / 0.50)
                elif ctx_pct <= 0.80:
                    bc = _lerp_color(C["amber"], C["coral"], (ctx_pct - 0.50) / 0.30)
                else:
                    bc = _lerp_color(C["coral"], C["red"], (ctx_pct - 0.80) / 0.20)
                pr.setBrush(QBrush(bc))
                pr.drawRoundedRect(QRectF(bar_x, bar_y, max(2, bar_w * ctx_pct), 2), 1, 1)

            top += card_h + 6

        # Empty state
        if not ac:
            empty_cx = L + cw // 2 - 22
            empty_cy = top + 8
            _eq = 0.5 + 0.5 * math.sin(self._pulse * 2)
            _empty_tint = QColor(int(217 + 23 * _eq), int(119 + 66 * _eq), int(87 - 32 * _eq))
            draw_clawd(pr, empty_cx, empty_cy, 2.2, self._bounce, _empty_tint, 0, 0, "neutral",
                       eye_glow=True, glow_phase=self._pulse)
            bx = empty_cx + 28
            by = empty_cy + 2
            pr.setBrush(QBrush(C["text_lo"]))
            pr.setPen(Qt.PenStyle.NoPen)
            pr.drawEllipse(QRectF(bx, by + 12, 3, 3))
            pr.drawEllipse(QRectF(bx + 5, by + 7, 4, 4))
            bubble = QPainterPath()
            bubble.addRoundedRect(QRectF(bx + 8, by - 4, 120, 24), 10, 10)
            pr.setBrush(QBrush(QColor(40, 40, 48)))
            pr.drawPath(bubble)
            pr.setPen(QPen(C["text_md"]))
            pr.setFont(self._F9)
            pr.drawText(int(bx + 14), int(by - 2), 112, 20,
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                        "Waiting for Claude\u2026")
            top += 44

        # ── STAT PILLS ──
        top += 4
        td = self._cached_period_data
        tc_today = td.get("tool_calls", 0)
        pr_today = td.get("prompts", 0)
        sub_mode = self.config.get("subscription_mode", "max")

        real_tokens = self.token_aggregator.get_today() if self.token_aggregator else None
        rt = real_tokens.get("total", 0) if real_tokens else 0
        tok_str = f"{rt / 1_000_000:.1f}M" if rt > 1_000_000 else f"{rt // 1000}k" if rt > 1000 else f"~{td.get('est_tokens', 0) // 1000}k"

        pills = [
            (f"{tc_today} tools", C["coral"]),
            (f"{pr_today} prompts", C["coral_light"]),
        ]
        if self.streaks and self.config.get("streaks_enabled"):
            streak = self.streaks.current_streak
            if streak > 0:
                pills.append((f"{streak}d streak", C["green"]))
        pills.append((f"{tok_str} tokens", C["text_lo"]))
        if sub_mode == "api":
            cost = td.get("est_cost", 0.0)
            if cost > 0:
                pills.append((f"${cost:.2f}", C["amber"]))

        pill_x = L
        pr.setFont(self._F8)
        fm = pr.fontMetrics()
        for pill_text, pill_color in pills:
            pw = fm.horizontalAdvance(pill_text) + 16
            if pill_x + pw > R:
                pill_x = L
                top += 22
            pr.setBrush(QBrush(_with_alpha(pill_color, 18)))
            pr.setPen(Qt.PenStyle.NoPen)
            pr.drawRoundedRect(QRectF(pill_x, top, pw, 20), 10, 10)
            pr.setPen(QPen(pill_color))
            pr.drawText(int(pill_x), int(top), int(pw), 20,
                        Qt.AlignmentFlag.AlignCenter, pill_text)
            pill_x += pw + 6
        top += 28

        # ── FOOTER ──
        # Export button
        exp_w = 50
        exp_x = R - exp_w
        exp_y = h - 28
        btn_h = 18
        self._export_btn_rect = QRectF(exp_x, exp_y, exp_w, btn_h)
        pr.setBrush(QBrush(QColor(255, 255, 255, 6)))
        pr.setPen(Qt.PenStyle.NoPen)
        pr.drawRoundedRect(self._export_btn_rect, 4, 4)
        pr.setPen(QPen(C["text_lo"]))
        pr.setFont(self._F7B)
        pr.drawText(int(exp_x), int(exp_y), int(exp_w), int(btn_h),
                    Qt.AlignmentFlag.AlignCenter, "Export")

        # System stats + version (whisper quiet)
        ram = SystemMonitor.get_ram()
        cpu = SystemMonitor.get_cpu()
        pr.setPen(QPen(QColor(60, 60, 68)))
        pr.setFont(self._F7)
        pr.drawText(L, h - 28, cw - exp_w - 8, 18, Qt.AlignmentFlag.AlignLeft,
                    f"CPU {cpu:.0f}%  \u00b7  RAM {ram['pct']}%  \u00b7  v{__version__}")
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
