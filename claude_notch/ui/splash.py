"""
claude_notch.ui.splash — Terminal-style boot splash screen
===========================================================
Shows on every launch. Skippable via click or Escape.
First launch shows "Install Hooks" button.
"""

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QTimer, QRectF, Signal
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPainterPath, QFont

from claude_notch.config import C, SPINNER_FRAMES, HOOK_SERVER_PORT
from claude_notch.ui.clawd import draw_clawd, _with_alpha


class SplashScreen(QWidget):
    """Terminal-style boot splash. Shows on every launch. Skippable."""

    finished = Signal()

    # Cached fonts
    _FS24B = QFont("Segoe UI", 24, QFont.Weight.Bold)
    _FS10 = QFont("Segoe UI", 10)
    _FS12B = QFont("Segoe UI", 12, QFont.Weight.Bold)
    _FS9 = QFont("Segoe UI", 9)
    _FC10 = QFont("Consolas", 10)

    LOADING_LINES = [
        "Initializing hook server on :{port}...",
        "Loading session state...",
        "Scanning for Claude processes...",
        "Applying theme: coral",
        "ClawdNotch v{version} ready. Let's go.",
    ]

    def __init__(self, config, first_launch=False):
        super().__init__()
        self._config = config
        self._first_launch = first_launch
        self._bounce = 0.0
        self._pulse = 0.0
        self._visible_lines = []
        self._line_index = 0
        self._phase = "loading"  # loading -> done -> fading
        self._opacity = 1.0
        self._show_button = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(480, 360)

        screen = QApplication.primaryScreen()
        if screen:
            scr = screen.geometry()
        else:
            from PySide6.QtCore import QRect
            scr = QRect(0, 0, 1920, 1080)
        self.move(scr.x() + (scr.width() - 480) // 2,
                  scr.y() + (scr.height() - 360) // 2)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(33)
        self._anim_timer.timeout.connect(self._tick)
        self._anim_timer.start()

        delay = 150 if config.get("auto_start") else 250
        self._line_timer = QTimer(self)
        self._line_timer.setInterval(delay)
        self._line_timer.timeout.connect(self._next_line)
        self._line_timer.start()

        from claude_notch import __version__
        port = config.get("hook_server_port", HOOK_SERVER_PORT)
        self._lines = [l.format(version=__version__, port=port) for l in self.LOADING_LINES]

    def _tick(self):
        self._bounce += 0.08
        self._pulse += 0.1
        if self._phase == "fading":
            self._opacity -= 0.02
            self.setWindowOpacity(max(0, self._opacity))
            if self._opacity <= 0:
                self._anim_timer.stop()
                self.finished.emit()
                self.close()
        self.update()

    def _next_line(self):
        if self._line_index < len(self._lines):
            frame = SPINNER_FRAMES[self._line_index % len(SPINNER_FRAMES)]
            self._visible_lines.append(f"[{frame}] {self._lines[self._line_index]}")
            self._line_index += 1
        else:
            self._line_timer.stop()
            if self._first_launch:
                self._show_button = True
                self._phase = "done"
            else:
                QTimer.singleShot(500, self._start_fade)

    def _start_fade(self):
        self._phase = "fading"

    def _dismiss(self):
        self._line_timer.stop()
        self._anim_timer.stop()
        self.finished.emit()
        self.close()

    def _install_and_go(self):
        from claude_notch.hooks import install_hooks
        install_hooks(self._config.get("hook_server_port", HOOK_SERVER_PORT))
        self._visible_lines.append("[\u2736] Hooks installed! Restart Claude Code sessions.")
        self._show_button = False
        self.update()
        QTimer.singleShot(1500, self._dismiss)

    def mousePressEvent(self, e):
        if self._show_button:
            btn_x = (480 - 220) // 2
            btn_y = 290
            if btn_x <= e.pos().x() <= btn_x + 220 and btn_y <= e.pos().y() <= btn_y + 36:
                self._install_and_go()
                return
            skip_y = 330
            if 180 <= e.pos().x() <= 300 and skip_y <= e.pos().y() <= skip_y + 20:
                self._dismiss()
                return
        else:
            self._dismiss()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self._dismiss()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 16, 16)
        p.setBrush(QBrush(QColor(12, 12, 14)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)

        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_with_alpha(C["coral"], 60), 2.0))
        p.drawPath(path)
        p.setPen(QPen(C["coral"], 1.0))
        p.drawPath(path)

        ps = 4.0
        clawd_w = 11 * ps
        cx = (w - clawd_w) / 2
        cy = 30
        draw_clawd(p, cx, cy, ps, self._bounce, None, 0, 0, "neutral",
                   eye_glow=True, glow_phase=self._pulse)

        p.setPen(QPen(C["coral"]))
        p.setFont(self._FS24B)
        p.drawText(0, 85, w, 40, Qt.AlignmentFlag.AlignCenter, "ClawdNotch")

        from claude_notch import __version__
        p.setPen(QPen(C["text_lo"]))
        p.setFont(self._FS10)
        p.drawText(0, 118, w, 20, Qt.AlignmentFlag.AlignCenter, f"v{__version__}")

        p.setFont(self._FC10)
        y = 150
        for line in self._visible_lines:
            if line.startswith("["):
                bracket_end = line.index("]") + 1
                p.setPen(QPen(C["coral"]))
                p.drawText(40, y, w - 80, 18, Qt.AlignmentFlag.AlignLeft, line[:bracket_end])
                p.setPen(QPen(C["text_md"]))
                fm = p.fontMetrics()
                offset = fm.horizontalAdvance(line[:bracket_end])
                p.drawText(40 + offset, y, w - 80 - offset, 18, Qt.AlignmentFlag.AlignLeft, line[bracket_end:])
            else:
                p.setPen(QPen(C["text_md"]))
                p.drawText(40, y, w - 80, 18, Qt.AlignmentFlag.AlignLeft, line)
            y += 22

        if self._show_button:
            btn_w, btn_h = 220, 36
            btn_x = (w - btn_w) // 2
            btn_y = 290
            p.setBrush(QBrush(C["coral"]))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(btn_x, btn_y, btn_w, btn_h), 8, 8)
            p.setPen(QPen(QColor(255, 255, 255)))
            p.setFont(self._FS12B)
            p.drawText(btn_x, btn_y, btn_w, btn_h, Qt.AlignmentFlag.AlignCenter, "Install Hooks & Start")
            p.setPen(QPen(C["text_lo"]))
            p.setFont(self._FS9)
            p.drawText(0, 330, w, 20, Qt.AlignmentFlag.AlignCenter, "Skip")

        p.setPen(QPen(C["text_lo"]))
        p.setFont(self._FS9)
        p.drawText(0, h - 28, w, 18, Qt.AlignmentFlag.AlignCenter,
                   "@ReelDad  \u00b7  MavProGroup@gmail.com  \u00b7  Bugs? Ideas? Don't hesitate to reach out.")
        p.end()
