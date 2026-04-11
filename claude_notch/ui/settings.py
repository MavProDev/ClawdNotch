"""
claude_notch.ui.settings — Settings dialog
============================================
SettingsDialog and the shared open_settings_dialog() helper used by
both the notch panel and the system tray menu.
"""

import json
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QDialog, QLabel, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QCheckBox, QComboBox, QFileDialog, QScrollArea,
    QRadioButton, QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from claude_notch import __version__
from claude_notch.config import (
    THEMES, HOOK_SERVER_PORT, _redact_key, _dpapi_encrypt, apply_theme,
)
from claude_notch.hooks import install_hooks
from claude_notch.system_monitor import set_auto_start


class SettingsDialog(QDialog):
    _update_toast_signal = Signal(str, str, int)  # title, message, timeout

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("ClawdNotch \u2014 Settings")
        self.setMinimumSize(500, 520)
        self.setStyleSheet(
            "QDialog{background:#121216;color:#f0ece8;}QLabel{color:#9b948e;font-size:12px;}"
            "QLineEdit{background:#1c1c24;border:1px solid #2c2c34;color:#f0ece8;padding:8px;border-radius:4px;font-size:12px;}"
            "QCheckBox{color:#f0ece8;font-size:12px;spacing:8px;}QCheckBox::indicator{width:16px;height:16px;}"
            "QRadioButton{color:#f0ece8;font-size:12px;spacing:8px;}"
            "QPushButton{background:#d97757;color:white;border:none;padding:10px 20px;border-radius:6px;font-weight:bold;font-size:13px;}"
            "QPushButton:hover{background:#eb9b78;}"
            "QScrollArea{border:none;background:transparent;}"
            "QScrollBar:vertical{background:#1c1c24;width:8px;border-radius:4px;}"
            "QScrollBar::handle:vertical{background:#3c3c4c;border-radius:4px;min-height:20px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        L = QVBoxLayout(container)
        L.setSpacing(8)
        L.setContentsMargins(24, 20, 24, 20)

        # -- API Keys --
        sec_api = QLabel("API Keys \u2014 Rate Limit Monitoring")
        sec_api.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;")
        L.addWidget(sec_api)
        api_note = QLabel(
            "Add your Anthropic API key(s) to monitor rate limits in real-time. "
            "Supports multiple keys across projects. Keys never leave your machine."
        )
        api_note.setStyleSheet("color:#9b948e;font-size:11px;")
        api_note.setWordWrap(True)
        L.addWidget(api_note)
        self._keys_layout = QVBoxLayout()
        self._keys_layout.setSpacing(4)
        self._key_rows = []
        for entry in config.get("api_keys", []):
            self._add_key_row(entry.get("label", ""), entry.get("key", ""), entry.get("added", ""))
        L.addLayout(self._keys_layout)
        add_row = QHBoxLayout()
        self._new_label = QLineEdit()
        self._new_label.setPlaceholderText("Label")
        self._new_label.setMaximumWidth(100)
        self._new_key = QLineEdit()
        self._new_key.setPlaceholderText("sk-ant-api03-...")
        self._new_key.setEchoMode(QLineEdit.EchoMode.Password)
        add_btn = QPushButton("Add Key")
        add_btn.setStyleSheet(
            "QPushButton{background:#2c2c34;font-size:11px;padding:6px 14px;}"
            "QPushButton:hover{background:#3c3c4c;}"
        )
        add_btn.clicked.connect(self._add_key)
        add_row.addWidget(self._new_label)
        add_row.addWidget(self._new_key)
        add_row.addWidget(add_btn)
        L.addLayout(add_row)
        kn = QLabel("Stored locally at ~/.claude-notch/config.json \u2014 never uploaded anywhere")
        kn.setStyleSheet("color:#5a504c;font-size:10px;")
        L.addWidget(kn)
        L.addSpacing(8)

        # -- Usage Mode --
        sec_mode = QLabel("Usage Mode")
        sec_mode.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;")
        L.addWidget(sec_mode)
        sub_h = QHBoxLayout()
        self.rb_max = QRadioButton("Subscription (Pro/Max/Team)")
        self.rb_api = QRadioButton("API Tokens (pay-per-use)")
        cur_mode = config.get("subscription_mode", "max")
        self.rb_max.setChecked(cur_mode == "max")
        self.rb_api.setChecked(cur_mode == "api")
        sub_h.addWidget(self.rb_max)
        sub_h.addWidget(self.rb_api)
        sub_h.addStretch()
        L.addLayout(sub_h)
        sn = QLabel("Subscription mode hides cost estimates. API mode shows $ per session.")
        sn.setStyleSheet("color:#5a504c;font-size:10px;")
        sn.setWordWrap(True)
        L.addWidget(sn)
        L.addSpacing(6)

        # -- Appearance --
        sec = QLabel("Appearance")
        sec.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;margin-top:6px;")
        L.addWidget(sec)
        th = QHBoxLayout()
        th.addWidget(QLabel("Color Theme:"))
        self.theme_combo = QComboBox()
        for t in THEMES:
            self.theme_combo.addItem(t.capitalize(), t)
        idx = self.theme_combo.findData(config.get("color_theme", "coral"))
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        th.addWidget(self.theme_combo)
        th.addStretch()
        L.addLayout(th)
        self.mini_mode = QCheckBox("Mini mode (tiny 28px dot when collapsed)")
        self.mini_mode.setChecked(config.get("mini_mode", False))
        L.addWidget(self.mini_mode)
        L.addSpacing(4)

        # -- Notifications --
        sec2 = QLabel("Notifications")
        sec2.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;margin-top:6px;")
        L.addWidget(sec2)
        self.snd = QCheckBox("Play sound on task completion")
        self.snd.setChecked(config.get("sound_enabled", True))
        L.addWidget(self.snd)
        self.tst = QCheckBox("Windows toast notifications")
        self.tst.setChecked(config.get("toast_enabled", True))
        L.addWidget(self.tst)
        self.mute = QCheckBox("Auto-mute when terminal/IDE focused")
        self.mute.setChecked(config.get("auto_mute_when_focused", True))
        L.addWidget(self.mute)
        self.dnd = QCheckBox("Do Not Disturb (mute everything)")
        self.dnd.setChecked(config.get("dnd_mode", False))
        L.addWidget(self.dnd)
        self.notif_hist = QCheckBox("Notification history in panel")
        self.notif_hist.setChecked(config.get("notification_history_enabled", True))
        L.addWidget(self.notif_hist)
        cs_h = QHBoxLayout()
        cs_h.addWidget(QLabel("Completion sound:"))
        self.cs_comp = QLineEdit(config.get("custom_sound_completion", ""))
        self.cs_comp.setPlaceholderText("Default beep")
        cs_b = QPushButton("...")
        cs_b.setStyleSheet(
            "QPushButton{background:#2c2c34;font-size:11px;padding:6px 10px;min-width:30px;}"
            "QPushButton:hover{background:#3c3c4c;}"
        )
        cs_b.clicked.connect(lambda: self._browse_wav(self.cs_comp))
        cs_h.addWidget(self.cs_comp)
        cs_h.addWidget(cs_b)
        L.addLayout(cs_h)
        ca_h = QHBoxLayout()
        ca_h.addWidget(QLabel("Attention sound:"))
        self.cs_attn = QLineEdit(config.get("custom_sound_attention", ""))
        self.cs_attn.setPlaceholderText("Default beep")
        ca_b = QPushButton("...")
        ca_b.setStyleSheet(
            "QPushButton{background:#2c2c34;font-size:11px;padding:6px 10px;min-width:30px;}"
            "QPushButton:hover{background:#3c3c4c;}"
        )
        ca_b.clicked.connect(lambda: self._browse_wav(self.cs_attn))
        ca_h.addWidget(self.cs_attn)
        ca_h.addWidget(ca_b)
        L.addLayout(ca_h)
        L.addSpacing(4)

        # -- Features --
        sec3 = QLabel("Features")
        sec3.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;margin-top:6px;")
        L.addWidget(sec3)
        self.click_focus = QCheckBox("Click session to focus terminal")
        self.click_focus.setChecked(config.get("click_to_focus", True))
        L.addWidget(self.click_focus)
        self.sparkline = QCheckBox("Sparkline activity graph")
        self.sparkline.setChecked(config.get("sparkline_enabled", True))
        L.addWidget(self.sparkline)
        self.clipboard = QCheckBox("Click to copy project path")
        self.clipboard.setChecked(config.get("clipboard_on_click", True))
        L.addWidget(self.clipboard)
        self.sess_est = QCheckBox("Session time estimates")
        self.sess_est.setChecked(config.get("session_estimate_enabled", True))
        L.addWidget(self.sess_est)
        self.streaks_cb = QCheckBox("Coding streaks & stats")
        self.streaks_cb.setChecked(config.get("streaks_enabled", True))
        L.addWidget(self.streaks_cb)
        self.sys_res = QCheckBox("System resources (CPU/RAM)")
        self.sys_res.setChecked(config.get("system_resources_enabled", True))
        L.addWidget(self.sys_res)
        model_h = QHBoxLayout()
        model_h.addWidget(QLabel("Default model:"))
        self.model_combo2 = QComboBox()
        for mn in ("sonnet", "opus", "haiku", "sonnet-1m", "opus-1m"):
            self.model_combo2.addItem(mn, mn)
        midx = self.model_combo2.findData(config.get("default_model", "sonnet"))
        if midx >= 0:
            self.model_combo2.setCurrentIndex(midx)
        model_h.addWidget(self.model_combo2)
        model_h.addStretch()
        L.addLayout(model_h)
        self.multi_mon = QCheckBox("Multi-monitor support")
        self.multi_mon.setChecked(config.get("multi_monitor", False))
        L.addWidget(self.multi_mon)
        L.addSpacing(4)

        # -- Budget --
        sec4 = QLabel("Budget Alerts (API mode)")
        sec4.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;margin-top:6px;")
        L.addWidget(sec4)
        bg = QHBoxLayout()
        bg.addWidget(QLabel("Daily $:"))
        self.budget_d = QLineEdit(str(config.get("budget_daily", 0.0) or ""))
        self.budget_d.setMaximumWidth(80)
        self.budget_d.setPlaceholderText("0=off")
        bg.addWidget(self.budget_d)
        bg.addWidget(QLabel("Monthly $:"))
        self.budget_m = QLineEdit(str(config.get("budget_monthly", 0.0) or ""))
        self.budget_m.setMaximumWidth(80)
        self.budget_m.setPlaceholderText("0=off")
        bg.addWidget(self.budget_m)
        bg.addStretch()
        L.addLayout(bg)
        L.addSpacing(4)

        # -- System --
        sec5 = QLabel("System")
        sec5.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;margin-top:6px;")
        L.addWidget(sec5)
        self.auto = QCheckBox("Start with Windows")
        self.auto.setChecked(config.get("auto_start", False))
        L.addWidget(self.auto)
        ef = QHBoxLayout()
        ef.addWidget(QLabel("Export format:"))
        self.export_fmt = QComboBox()
        self.export_fmt.addItem("Markdown", "markdown")
        self.export_fmt.addItem("CSV", "csv")
        eidx = self.export_fmt.findData(config.get("export_format", "markdown"))
        if eidx >= 0:
            self.export_fmt.setCurrentIndex(eidx)
        ef.addWidget(self.export_fmt)
        ef.addStretch()
        L.addLayout(ef)
        pl = QLabel(f"Port: {config.get('hook_server_port', HOOK_SERVER_PORT)}  \u00b7  Ctrl+Shift+C/E/S/D")
        pl.setStyleSheet("color:#5a504c;font-size:10px;")
        L.addWidget(pl)
        L.addStretch()

        upd_btn = QPushButton("Check for Updates")
        upd_btn.setStyleSheet(
            "QPushButton{background:#2c2c34;font-size:11px;padding:8px 14px;}"
            "QPushButton:hover{background:#3c3c4c;}"
        )
        upd_btn.clicked.connect(self._check_updates)
        L.addWidget(upd_btn)
        L.addSpacing(4)
        br = QHBoxLayout()
        self._ib = QPushButton()
        self._style_ib(self._check())
        self._ib.clicked.connect(self._inst)
        br.addWidget(self._ib)
        sb = QPushButton("Save")
        sb.clicked.connect(self._save)
        br.addWidget(sb)
        L.addLayout(br)

        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _add_key_row(self, label: str, key: str, added: str = ""):
        row = QHBoxLayout()
        lbl = QLabel(f"{label}:  {_redact_key(key)}")
        lbl.setStyleSheet("color:#f0ece8;font-size:11px;font-family:Consolas;")
        rm = QPushButton("\u2715")
        rm.setStyleSheet(
            "QPushButton{background:#2a1a1a;color:#e64848;font-size:11px;padding:4px 8px;border-radius:4px;}"
            "QPushButton:hover{background:#3a2020;}"
        )
        rm.setFixedWidth(30)
        idx = len(self._key_rows)
        rm.clicked.connect(lambda _, i=idx: self._remove_key(i))
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(rm)
        self._keys_layout.addLayout(row)
        self._key_rows.append({
            "label": label, "key": key,
            "added": added or datetime.now().strftime("%Y-%m-%d"),
            "layout": row, "widgets": [lbl, rm],
        })

    def _add_key(self):
        active_count = sum(1 for r in self._key_rows if r is not None)
        if active_count >= 10:
            QMessageBox.warning(self, "Limit", "Maximum 10 API keys supported.")
            return
        label = self._new_label.text().strip() or f"Key {len(self._key_rows) + 1}"
        key = self._new_key.text().strip()
        if not key:
            return
        if not key.startswith("sk-ant") or len(key) < 20:
            QMessageBox.warning(self, "Invalid Key",
                                "API key should start with 'sk-ant' and be at least 20 characters.")
            return
        self._add_key_row(label, key)
        self._new_label.clear()
        self._new_key.clear()

    def _remove_key(self, idx):
        if idx < len(self._key_rows):
            row = self._key_rows[idx]
            if row is None:
                return
            for w in row["widgets"]:
                w.setParent(None)
            self._keys_layout.removeItem(row["layout"])
            self._key_rows[idx] = None

    def _init_update_signal(self):
        from claude_notch.ui.toast import show_clawd_toast
        self._update_toast_signal.connect(
            lambda t, m, to: show_clawd_toast(t, m, to, 0, "info")
        )

    def _check_updates(self):
        from claude_notch.update_checker import check_for_updates
        if not hasattr(self, '_update_toast_connected'):
            self._init_update_signal()
            self._update_toast_connected = True

        def _callback(version, url):
            self._update_found = True
            self._update_toast_signal.emit(
                f"ClawdNotch {version} available!",
                "Click to download the latest version.",
                12,
            )

        def _run():
            self._update_found = False
            self.config.set("last_update_check", "", save_now=False)
            check_for_updates(self.config, _callback)
            if not self._update_found:
                self._update_toast_signal.emit(
                    "You're up to date!",
                    f"ClawdNotch v{__version__} is the latest version.",
                    5,
                )
        threading.Thread(target=_run, daemon=True).start()

    def _browse_wav(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Sound File", "", "WAV Files (*.wav);;All Files (*)"
        )
        if path:
            line_edit.setText(path)

    def _style_ib(self, ok):
        if ok:
            self._ib.setText("\u2713 Hooks Installed")
            self._ib.setStyleSheet(
                "QPushButton{background:#1c3a2a;font-size:11px;padding:8px 14px;color:#48c784;}"
                "QPushButton:hover{background:#2c4a3a;}"
            )
        else:
            self._ib.setText("Install Claude Code Hooks")
            self._ib.setStyleSheet(
                "QPushButton{background:#2c2c34;font-size:11px;padding:8px 14px;}"
                "QPushButton:hover{background:#3c3c4c;}"
            )

    def _save(self):
        def _float(s, default=0.0):
            try:
                return float(s) if s else default
            except ValueError:
                return default
        sub_mode = "max" if self.rb_max.isChecked() else "api"
        api_keys = [
            {"key": _dpapi_encrypt(r["key"]) if not r["key"].startswith("dpapi:") else r["key"],
             "label": r["label"], "added": r.get("added", "")}
            for r in self._key_rows if r is not None
        ]
        self.config.set_many({
            "subscription_mode": sub_mode, "api_keys": api_keys,
            "sound_enabled": self.snd.isChecked(), "toast_enabled": self.tst.isChecked(),
            "auto_start": self.auto.isChecked(), "auto_mute_when_focused": self.mute.isChecked(),
            "dnd_mode": self.dnd.isChecked(),
            "notification_history_enabled": self.notif_hist.isChecked(),
            "custom_sound_completion": self.cs_comp.text().strip(),
            "custom_sound_attention": self.cs_attn.text().strip(),
            "color_theme": self.theme_combo.currentData() or "coral",
            "mini_mode": self.mini_mode.isChecked(),
            "default_model": self.model_combo2.currentData() or "sonnet",
            "click_to_focus": self.click_focus.isChecked(),
            "sparkline_enabled": self.sparkline.isChecked(),
            "clipboard_on_click": self.clipboard.isChecked(),
            "session_estimate_enabled": self.sess_est.isChecked(),
            "streaks_enabled": self.streaks_cb.isChecked(),
            "system_resources_enabled": self.sys_res.isChecked(),
            "multi_monitor": self.multi_mon.isChecked(),
            "budget_daily": _float(self.budget_d.text()),
            "budget_monthly": _float(self.budget_m.text()),
            "export_format": self.export_fmt.currentData() or "markdown",
        })
        apply_theme(self.config.get("color_theme", "coral"))
        set_auto_start(self.auto.isChecked())
        self.accept()

    def _inst(self):
        install_hooks(self.config.get("hook_server_port", HOOK_SERVER_PORT))
        self._style_ib(True)
        QMessageBox.information(self, "Done", "Hooks installed! Restart Claude Code sessions.")

    @staticmethod
    def _check():
        p = Path.home() / ".claude" / "settings.json"
        if not p.exists():
            return False
        try:
            with open(p) as f:
                d = json.load(f)
            return any(
                "claude_notch_hook" in str(h)
                for hs in d.get("hooks", {}).values()
                for h in hs
            )
        except Exception:
            return False


def open_settings_dialog(config, parent_widget=None):
    """Shared helper to open or raise a SettingsDialog.

    Uses `finished` signal (not `WA_DeleteOnClose` + `destroyed`) to
    reliably clear the dialog reference and prevent stale-pointer crashes.
    """
    if parent_widget and hasattr(parent_widget, '_settings_dlg'):
        dlg_ref = parent_widget._settings_dlg
        if dlg_ref is not None:
            try:
                if dlg_ref.isVisible():
                    dlg_ref.raise_()
                    dlg_ref.activateWindow()
                    return
            except RuntimeError:
                parent_widget._settings_dlg = None
    dlg = SettingsDialog(config)
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
    scr = QApplication.primaryScreen().geometry()
    dlg.resize(520, min(700, scr.height() - 100))
    dlg.move(scr.x() + (scr.width() - dlg.width()) // 2,
             scr.y() + (scr.height() - dlg.height()) // 2)
    if parent_widget:
        def _on_close():
            parent_widget._settings_dlg = None
            dlg.deleteLater()
        dlg.finished.connect(_on_close)
        parent_widget._settings_dlg = dlg
    dlg.show()
