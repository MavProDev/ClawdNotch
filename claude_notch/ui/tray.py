"""
claude_notch.ui.tray — System tray icon and menu
==================================================
"""

from pathlib import Path

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QPainter, QColor, QPixmap, QIcon

from claude_notch.config import HOOK_SERVER_PORT
from claude_notch.hooks import install_hooks
from claude_notch.usage import export_usage_report
from claude_notch.ui.clawd import draw_clawd
from claude_notch.ui.toast import show_clawd_toast
from claude_notch.ui.settings import SettingsDialog, open_settings_dialog


def make_tray(app, notch, config, sm=None, do_snapshot=None):
    pix = QPixmap(32, 32)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    draw_clawd(p, 3, 2, 2.5, emotion="neutral")
    p.end()
    tray = QSystemTrayIcon(QIcon(pix), app)
    menu = QMenu()
    menu.setStyleSheet(
        "QMenu{background:#121216;color:#f0ece8;border:1px solid #2c2c34;padding:4px;font-size:12px;}"
        "QMenu::item:selected{background:#d97757;}"
    )
    menu.addAction("Show / Hide").triggered.connect(
        lambda: notch.hide() if notch.isVisible() else notch.force_show()
    )
    dnd_action = menu.addAction("Do Not Disturb: OFF")

    def _toggle_dnd():
        cur = config.get("dnd_mode", False)
        config.set("dnd_mode", not cur)
        dnd_action.setText(f"Do Not Disturb: {'ON' if not cur else 'OFF'}")
        notch.update()

    dnd_action.triggered.connect(_toggle_dnd)

    def _export():
        try:
            fmt = config.get("export_format", "markdown")
            path = export_usage_report(notch.tracker, config, fmt)
            show_clawd_toast("Export Complete", f"Saved: {Path(path).name}", 5, 0, "completion")
        except Exception as e:
            show_clawd_toast("Export Failed", str(e)[:60], 5, 0, "attention")

    menu.addAction("Export Usage Report").triggered.connect(_export)
    def _open_settings_from_tray():
        # Collapse the notch so it doesn't cover the settings dialog
        if notch._expanded:
            notch._collapse(force=True)
        open_settings_dialog(config, parent_widget=notch)

    menu.addAction("Settings...").triggered.connect(_open_settings_from_tray)
    if not SettingsDialog._check():
        menu.addAction("Install Hooks").triggered.connect(
            lambda: install_hooks(config.get("hook_server_port", HOOK_SERVER_PORT))
        )

    def _r():
        s = QApplication.primaryScreen().geometry()
        notch._edge = "top"
        notch._ori = "horizontal"
        notch.setFixedSize(notch.nw, notch.nh)
        notch.move((s.width() - notch.nw) // 2, 0)
        notch._save_pos()

    menu.addAction("Reset Position").triggered.connect(_r)

    menu.addSeparator()
    menu.addAction("Quit").triggered.connect(app.quit)
    tray.setContextMenu(menu)
    tray.setToolTip("ClawdNotch \u2014 @ReelDad")
    tray.activated.connect(
        lambda reason: notch.force_show()
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray.show()
    return tray
