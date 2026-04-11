"""
claude_notch.ui.toast — ClawdToast branded notification popup
==============================================================
Custom notification popup with animated Clawd, coral border, slide-in
animation. Replaces generic Windows toast with branded ClawdNotch aesthetic.
"""

import math

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPainterPath, QFont

from claude_notch.config import C, SPINNER_FRAMES
from claude_notch.system_monitor import _focus_window_by_pid
from claude_notch.ui.clawd import draw_clawd, _with_alpha


class ClawdToast(QWidget):
    """Custom notification popup with animated Clawd, coral border, slide-in animation.

    Slides in from the bottom-right corner, auto-dismisses with fade-out.
    Click to focus the relevant terminal window.
    """

    _active_toasts = []  # class-level stack so multiple toasts don't overlap

    def __init__(self, title, message, timeout=8, pid=0, ntype="info"):
        super().__init__()
        self._title = title
        self._message = message
        self._timeout = timeout
        self._pid = pid
        self._ntype = ntype  # "completion", "attention", "budget", "info"
        self._bounce = 0.0
        self._pulse = 0.0
        self._opacity = 0.0
        self._phase = "slide_in"  # slide_in -> visible -> fade_out -> done
        self._slide_progress = 0.0
        self._visible_timer_count = 0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(340, 88)

        # Position: bottom-right corner, stacked above existing toasts
        screen = QApplication.primaryScreen()
        if not screen:
            self.close()
            self.deleteLater()
            return
        scr = screen.geometry()
        stack_offset = len(ClawdToast._active_toasts) * 96
        self._target_x = scr.x() + scr.width() - 340 - 16
        self._target_y = scr.y() + scr.height() - 88 - 16 - stack_offset
        self._start_y = self._target_y + 40  # start 40px lower for slide-up
        self.move(self._target_x, self._start_y)

        ClawdToast._active_toasts.append(self)

        # Animation timer
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60fps
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _tick(self):
        self._bounce += 0.12
        self._pulse += 0.15

        if self._phase == "slide_in":
            self._slide_progress = min(1.0, self._slide_progress + 0.06)
            self._opacity = min(1.0, self._opacity + 0.08)
            # Ease-out slide
            t = 1 - (1 - self._slide_progress) ** 3
            y = int(self._start_y + (self._target_y - self._start_y) * t)
            self.move(self._target_x, y)
            self.setWindowOpacity(self._opacity)
            if self._slide_progress >= 1.0:
                self._phase = "visible"

        elif self._phase == "visible":
            self._visible_timer_count += 1
            # Smoothly slide to target position (handles restack after dismiss)
            cur_y = self.pos().y()
            if abs(cur_y - self._target_y) > 1:
                new_y = cur_y + int((self._target_y - cur_y) * 0.15)
                self.move(self._target_x, new_y)
            # Auto-dismiss after timeout (at 60fps)
            if self._visible_timer_count > self._timeout * 60:
                self._phase = "fade_out"

        elif self._phase == "fade_out":
            self._opacity -= 0.04
            self.setWindowOpacity(max(0, self._opacity))
            if self._opacity <= 0:
                self._dismiss()
                return

        self.update()

    def __del__(self):
        """Safety net: remove from active list if widget is garbage collected without _dismiss."""
        if self in ClawdToast._active_toasts:
            ClawdToast._active_toasts.remove(self)

    def _dismiss(self):
        self._timer.stop()
        if self in ClawdToast._active_toasts:
            ClawdToast._active_toasts.remove(self)
            ClawdToast._restack()
        self.close()
        self.deleteLater()

    @staticmethod
    def _restack():
        """Reposition all active toasts so there are no gaps after a dismiss."""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        scr = screen.geometry()
        for i, toast in enumerate(ClawdToast._active_toasts):
            toast._target_y = scr.y() + scr.height() - 88 - 16 - i * 96
            toast._target_x = scr.x() + scr.width() - 340 - 16

    def mousePressEvent(self, e):
        if self._pid:
            _focus_window_by_pid(self._pid)
        self._phase = "fade_out"

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background with rounded corners
        path = QPainterPath()
        path.addRoundedRect(QRectF(1, 1, w - 2, h - 2), 12, 12)
        p.setBrush(QBrush(QColor(12, 12, 14, 245)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)

        # Border — color based on notification type
        border_color = {
            "completion": C.get("green", QColor(72, 199, 132)),
            "attention": C.get("coral", QColor(217, 119, 87)),
            "budget": C.get("amber", QColor(240, 185, 55)),
        }.get(self._ntype, C.get("coral", QColor(217, 119, 87)))

        # Subtle outer glow
        glow_alpha = int(30 + 20 * math.sin(self._pulse * 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_with_alpha(border_color, glow_alpha), 3.0))
        p.drawPath(path)
        # Crisp inner border
        p.setPen(QPen(border_color, 1.2))
        p.drawPath(path)

        # Animated Clawd on the left
        ps = 2.8
        cx = 12
        cy = (h - 10 * ps) / 2
        is_attention = self._ntype == "attention"
        draw_clawd(p, cx, cy, ps, self._bounce, border_color if is_attention else None,
                   0, 0, "happy" if self._ntype == "completion" else "neutral",
                   eye_glow=is_attention, glow_phase=self._pulse)

        # Text area — right of Clawd
        tx = 52
        # Title
        p.setPen(QPen(border_color))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        title = self._title
        if len(title) > 35:
            title = title[:33] + "..."
        p.drawText(tx, 12, w - tx - 12, 20, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)

        # Message
        p.setPen(QPen(C.get("text_md", QColor(155, 148, 142))))
        p.setFont(QFont("Segoe UI", 9))
        msg = self._message
        if len(msg) > 50:
            msg = msg[:48] + "..."
        p.drawText(tx, 32, w - tx - 12, 18, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, msg)

        # Spinner + subtle hint
        frame_idx = int(self._pulse) % len(SPINNER_FRAMES)
        spinner = SPINNER_FRAMES[frame_idx]
        p.setPen(QPen(C.get("text_lo", QColor(85, 80, 76))))
        p.setFont(QFont("Segoe UI", 8))
        hint = "Click to focus" if self._pid else "Click to dismiss"
        p.drawText(tx, 54, w - tx - 12, 16, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{spinner} {hint}")

        # Type indicator dot — top right
        p.setBrush(QBrush(border_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(w - 16, 8, 6, 6))

        p.end()


def show_clawd_toast(title, message, timeout=8, pid=0, ntype="info"):
    """Show a custom ClawdToast notification. Call from any thread via QTimer."""
    toast = ClawdToast(title, message, timeout, pid, ntype)
    toast.show()
    return toast
