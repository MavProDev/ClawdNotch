"""
Claude Notch — Production Windows Desktop Overlay
===================================================
The Windows equivalent of Notchy/Notchi for macOS.
A notch-shaped overlay that tracks all Claude Code sessions in real-time,
with the Clawd pixel mascot, API rate limit monitoring, and notifications.

ARCHITECTURE:
    ClaudeNotch (UI) — 300x34 (h) / 34x200 (v) collapsed, 560x500 expanded
    HookServer (TCP :19748) — receives JSON from Claude Code hooks
    SessionManager — per-session state machine with tint colors
    UsagePoller — reads rate limit headers from minimal API calls
    ConfigManager — persistent config with position save/restore

Author: @ReelDad
License: MIT
"""

import sys, os, json, math, socket, threading, time, ctypes, subprocess, tempfile
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from ctypes import wintypes
import requests

try:
    from PyQt6.QtWidgets import (
        QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
        QSystemTrayIcon, QMenu, QLineEdit, QPushButton, QDialog, QCheckBox,
    QScrollArea, QFrame, QComboBox, QFileDialog
    )
    from PyQt6.QtCore import Qt, QTimer, QPoint, QRectF, pyqtSignal, QObject, QThread
    from PyQt6.QtGui import (
        QPainter, QColor, QFont, QPainterPath, QLinearGradient, QConicalGradient,
        QPen, QBrush, QPixmap, QAction, QIcon, QCursor
    )
except ImportError:
    print("\n  Claude Notch requires PyQt6.\n  Install with: pip install PyQt6>=6.6.0\n")
    sys.exit(1)

# Process protection
try: ctypes.windll.kernel32.SetConsoleTitleW("claude-notch-overlay")
except Exception: pass

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False
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
try:
    import keyboard as kb_module
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

__version__ = "2.0.0"

HOOK_SERVER_PORT = 19748
CONFIG_DIR = Path.home() / ".claude-notch"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOCK_FILE = CONFIG_DIR / "notch.lock"

SESSIONS_FILE = CONFIG_DIR / "sessions_state.json"

DEFAULT_CONFIG = {
    "hook_server_port": HOOK_SERVER_PORT,
    "sound_enabled": True, "toast_enabled": True, "auto_start": False,
    "poll_interval_seconds": 60, "max_sessions_shown": 6,
    "last_x": -1, "last_y": -1, "last_edge": "top",
    "auto_mute_when_focused": True, "default_model": "sonnet",
    "expanded_w": 560, "expanded_h": 500, "was_expanded": False,
    "subscription_mode": "max",
    "api_keys": [],
    "install_path": "",
    # v2 Feature toggles
    "click_to_focus": True,
    "sparkline_enabled": True,
    "custom_sound_completion": "",
    "custom_sound_attention": "",
    "budget_daily": 0.0,
    "budget_monthly": 0.0,
    "session_estimate_enabled": True,
    "notification_history_enabled": True,
    "color_theme": "coral",
    "mini_mode": False,
    "clipboard_on_click": True,
    "streaks_enabled": True,
    "system_resources_enabled": True,
    "dnd_mode": False,
    "dim_when_inactive": True,
    "dim_opacity": 0.55,
    "export_format": "markdown",
    "multi_monitor": False,
}

# ═══════════════════════════════════════════════════════════════════════════════
# COLOR THEMES
# ═══════════════════════════════════════════════════════════════════════════════

THEMES = {
    "coral":  {"accent": (217, 119, 87), "accent_light": (235, 155, 120)},
    "blue":   {"accent": (88, 166, 255), "accent_light": (130, 190, 255)},
    "green":  {"accent": (72, 199, 132), "accent_light": (110, 220, 160)},
    "purple": {"accent": (180, 130, 220), "accent_light": (200, 160, 235)},
    "cyan":   {"accent": (80, 200, 220), "accent_light": (120, 220, 235)},
    "amber":  {"accent": (240, 185, 55), "accent_light": (250, 205, 100)},
    "pink":   {"accent": (220, 100, 160), "accent_light": (240, 140, 185)},
    "red":    {"accent": (230, 72, 72), "accent_light": (245, 110, 110)},
}

MODEL_CONTEXT_LIMITS = {
    "opus": 200_000, "sonnet": 200_000, "haiku": 200_000,
    "opus-1m": 1_000_000, "sonnet-1m": 1_000_000,
}

def apply_theme(name):
    t = THEMES.get(name, THEMES["coral"])
    C["coral"] = QColor(*t["accent"])
    C["coral_light"] = QColor(*t["accent_light"])

SESSION_TINTS = [
    QColor(217,119,87), QColor(88,166,255), QColor(72,199,132),
    QColor(180,130,220), QColor(240,185,55), QColor(220,100,160),
]

def _atomic_write(path: Path, data: dict):
    """Write JSON atomically: write to temp file, then rename over target."""
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except Exception:
            try: os.unlink(tmp)
            except OSError: pass
            raise
    except Exception as e:
        print(f"[Write] Failed to save {path.name}: {e}", file=sys.stderr)

class ConfigManager:
    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self.config = self._load()
        self._migrate()
        self._dirty = False

    def _migrate(self):
        """Migrate old single-key config to multi-key format."""
        old_key = self.config.pop("anthropic_api_key", None)
        if old_key and old_key.startswith("sk-ant") and not self.config.get("api_keys"):
            self.config["api_keys"] = [{
                "key": old_key, "label": "Default",
                "added": datetime.now().strftime("%Y-%m-%d"),
            }]
            self.save()
    def _load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f: return {**DEFAULT_CONFIG, **json.load(f)}
            except Exception as e:
                print(f"[Config] Failed to load: {e}", file=sys.stderr)
        return dict(DEFAULT_CONFIG)
    def save(self):
        _atomic_write(CONFIG_FILE, self.config)
        self._dirty = False
    def get(self, key, default=None): return self.config.get(key, default)
    def set(self, key, value, save_now=True):
        self.config[key] = value
        if save_now: self.save()
        else: self._dirty = True
    def set_many(self, updates):
        self.config.update(updates); self.save()
    def flush(self):
        if self._dirty: self.save()

def acquire_lock():
    try:
        if LOCK_FILE.exists():
            try:
                old_pid = int(LOCK_FILE.read_text().strip())
                h = ctypes.windll.kernel32.OpenProcess(0x1000, False, old_pid)
                if h:
                    ctypes.windll.kernel32.CloseHandle(h)
                    return False
            except Exception: pass
        LOCK_FILE.write_text(str(os.getpid()))
        return True
    except Exception: return True

def release_lock():
    try: LOCK_FILE.unlink(missing_ok=True)
    except Exception: pass

def set_auto_start(enabled):
    if not HAS_WINREG: return
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
        if enabled:
            exe = sys.executable.replace("python.exe", "pythonw.exe")
            if not os.path.exists(exe): exe = sys.executable
            launcher = CONFIG_DIR / "launcher.pyw"
            target = str(launcher) if launcher.exists() else os.path.abspath(__file__)
            winreg.SetValueEx(key, "ClaudeNotch", 0, winreg.REG_SZ,
                f'"{exe}" "{target}"')
        else:
            try: winreg.DeleteValue(key, "ClaudeNotch")
            except FileNotFoundError: pass
        winreg.CloseKey(key)
    except Exception as e: print(f"[AutoStart] {e}")

@dataclass
class Session:
    session_id: str
    project_dir: str = ""
    state: str = "idle"
    current_tool: str = ""
    last_activity: datetime = field(default_factory=datetime.now)
    tool_count: int = 0
    tasks_completed: list = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.now)
    tint_index: int = 0
    emotion: str = "neutral"
    session_tokens: int = 0
    context_limit: int = 200_000
    model: str = "sonnet"
    pid: int = 0
    detected_via: str = "hook"
    @property
    def project_name(self): return Path(self.project_dir).name if self.project_dir else "unknown"
    @property
    def age_str(self):
        m = int((datetime.now() - self.started_at).total_seconds() / 60)
        return "now" if m < 1 else f"{m}m" if m < 60 else f"{m//60}h {m%60}m"
    @property
    def age_minutes(self): return int((datetime.now() - self.started_at).total_seconds() / 60)
    @property
    def tint(self): return SESSION_TINTS[self.tint_index % len(SESSION_TINTS)]
    @property
    def is_stale(self): return (datetime.now() - self.last_activity).total_seconds() > 7200

class SessionManager(QObject):
    session_updated = pyqtSignal()
    task_completed = pyqtSignal(str, str)
    needs_attention = pyqtSignal(str)
    budget_alert = pyqtSignal(str)
    def __init__(self, usage_tracker, emotion_engine=None, todo_manager=None, sparkline=None, config=None):
        super().__init__()
        self.sessions = {}
        self._lock = threading.Lock()
        self._next_tint = 0
        self._tracker = usage_tracker
        self._emotion = emotion_engine
        self._todos = todo_manager
        self._sparkline = sparkline
        self._config = config
        self._completed_durations = []
    def handle_event(self, event):
        et = event.get("event", "")
        sid = event.get("session_id", "unknown")
        pd = event.get("project_dir", "")
        self._tracker.record_event(et)
        if self._sparkline: self._sparkline.record()
        with self._lock:
            if sid not in self.sessions:
                model = (self._config.get("default_model", "sonnet") if self._config else "sonnet")
                ctx = MODEL_CONTEXT_LIMITS.get(model, 200_000)
                self.sessions[sid] = Session(session_id=sid, project_dir=pd, tint_index=self._next_tint, model=model, context_limit=ctx)
                self._next_tint += 1
            s = self.sessions[sid]
            s.last_activity = datetime.now()
            if pd: s.project_dir = pd
            est = TOKEN_ESTIMATES.get(et, 100)
            s.session_tokens += est
            if et == "SessionStart": s.state = "idle"
            elif et == "PreToolUse": s.state = "working"; s.current_tool = event.get("tool_name", "")
            elif et == "PostToolUse":
                s.state = "working"; s.tool_count += 1; s.current_tool = ""
                tool_name = event.get("tool_name", "tool")
                if self._todos:
                    self._todos.process_tool_event(sid, tool_name, event.get("tool_input", ""))
                s.tasks_completed.append({"summary": f"Used {tool_name}", "time": datetime.now().strftime("%H:%M"), "status": "completed"})
                s.tasks_completed = s.tasks_completed[-20:]
            elif et == "PostToolUseFailure": s.state = "error"; s.current_tool = ""
            elif et == "Notification": s.state = "waiting"; self.needs_attention.emit(s.project_name)
            elif et == "Stop":
                s.state = "idle"  # Task done but session still alive — waiting for next prompt
                sm = event.get("summary", "Task completed")
                s.tasks_completed.append({"summary": sm, "time": datetime.now().strftime("%H:%M"), "status": "completed"})
                self.task_completed.emit(s.project_name, sm)
            elif et == "SessionEnd":
                s.state = "completed"
                dur = (datetime.now() - s.started_at).total_seconds() / 60
                self._completed_durations.append(dur)
                self._completed_durations = self._completed_durations[-50:]
                s.last_activity = datetime.now() - timedelta(minutes=3)
            elif et == "UserPromptSubmit":
                s.state = "working"
                if self._emotion:
                    prompt_text = event.get("user_prompt", "")
                    s.emotion = self._emotion.process(sid, prompt_text)
        # Budget alert check (once per threshold crossing, not every event)
        if self._config and self._config.get("subscription_mode") == "api":
            daily_budget = self._config.get("budget_daily", 0)
            if daily_budget > 0:
                cost = self._tracker.today.get("est_cost", 0)
                alert_key = f"budget_alert_{self._tracker._today_key}"
                if cost >= daily_budget * 0.8 and not getattr(self, '_budget_alerted', None) == alert_key:
                    self._budget_alerted = alert_key
                    self.budget_alert.emit(f"Daily budget: ${cost:.2f} / ${daily_budget:.2f}")
        self.session_updated.emit()

    @property
    def avg_session_minutes(self):
        if not self._completed_durations: return 0
        return int(sum(self._completed_durations) / len(self._completed_durations))

    def scan_processes(self):
        """Scan for running Claude Code windows/processes and keep sessions alive."""
        windows = _find_claude_windows()
        processes = _find_claude_processes()
        active_pids = {w['pid'] for w in windows} | {p['pid'] for p in processes}
        with self._lock:
            # Touch hook-detected sessions whose process is still running
            for sid, s in self.sessions.items():
                # Don't resurrect completed sessions — they ended intentionally
                if s.state == "completed":
                    continue
                if s.pid and s.pid in active_pids:
                    # Process still alive — keep session, don't let it go stale
                    if (datetime.now() - s.last_activity).total_seconds() > 30:
                        s.last_activity = datetime.now()
            # Create sessions for newly found Claude Code terminal windows not yet tracked
            known_pids = {s.pid for s in self.sessions.values() if s.pid}
            for w in windows:
                if w['pid'] not in known_pids:
                    # Extract project name from window title
                    title = w.get('title', '')
                    pdir = ""
                    for sep in [' — ', ' - ', ': ']:
                        if sep in title:
                            parts = title.split(sep)
                            for part in parts:
                                part = part.strip()
                                if part.lower() not in ('claude', 'claude code', 'windows terminal',
                                                         'command prompt', 'powershell', 'cmd'):
                                    pdir = part
                                    break
                            if pdir:
                                break
                    sid = f"proc-{w['pid']}"
                    self.sessions[sid] = Session(
                        session_id=sid, project_dir=pdir,
                        state="idle", tint_index=self._next_tint,
                        pid=w['pid'], detected_via="process",
                    )
                    self._next_tint += 1
        self.session_updated.emit()

    def cleanup_dead(self):
        """Remove sessions that are no longer active.

        Called on refresh press and automatically every 60s. Rules:
        - completed sessions: remove immediately
        - process-detected sessions: remove if PID is gone
        - hook sessions with no activity for 5+ min: remove (Claude sends events
          frequently while working; 5 min silence = dead or user closed it)
        - any session inactive 10+ min without a live process: remove
        """
        active_pids = set()
        try:
            windows = _find_claude_windows()
            processes = _find_claude_processes()
            active_pids = {w['pid'] for w in windows} | {p['pid'] for p in processes}
        except Exception:
            pass
        with self._lock:
            to_remove = []
            for sid, v in self.sessions.items():
                age = (datetime.now() - v.last_activity).total_seconds()
                proc_alive = v.pid and v.pid in active_pids
                # Completed sessions: remove immediately
                if v.state == "completed":
                    to_remove.append(sid)
                    continue
                # Process-detected sessions: remove if PID is gone
                if v.detected_via == "process" and not proc_alive:
                    to_remove.append(sid)
                    continue
                # Hook sessions with no PID: only trust recent activity
                # Claude Code sends events constantly while working. 5 min silence = dead.
                if not v.pid and age > 300:
                    to_remove.append(sid)
                    continue
                # Any session inactive 10+ min with dead/unknown process
                if age > 600 and not proc_alive:
                    to_remove.append(sid)
                    continue
            for sid in to_remove:
                del self.sessions[sid]
                if self._emotion:
                    self._emotion.remove_session(sid)
                if self._todos:
                    self._todos.remove_session(sid)

    def save_state(self):
        with self._lock:
            _save_sessions_state(self.sessions)

    def restore_state(self):
        restored = _load_sessions_state()
        if restored:
            with self._lock:
                for sid, s in restored.items():
                    if sid not in self.sessions:
                        self.sessions[sid] = s
                        self._next_tint = max(self._next_tint, s.tint_index + 1)
            self.session_updated.emit()

    def get_active_sessions(self):
        with self._lock:
            a = [s for s in self.sessions.values()
                 if s.state != "completed"
                 and (datetime.now() - s.last_activity).total_seconds() < 7200]
            a.sort(key=lambda s: s.last_activity, reverse=True); return a
    def get_all_tasks(self, limit=10):
        t = []
        with self._lock:
            for s in self.sessions.values():
                for tk in s.tasks_completed: t.append({**tk, "project": s.project_name})
        t.sort(key=lambda x: x.get("time",""), reverse=True); return t[:limit]
    @property
    def total_active(self): return len(self.get_active_sessions())
    @property
    def any_working(self): return any(s.state=="working" for s in self.get_active_sessions())
    @property
    def any_waiting(self): return any(s.state=="waiting" for s in self.get_active_sessions())

class HookServer(QThread):
    event_received = pyqtSignal(dict)
    def __init__(self, port=HOOK_SERVER_PORT, parent=None):
        super().__init__(parent); self.port = port; self._running = True
    def stop(self): self._running = False
    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try: srv.bind(("127.0.0.1", self.port))
        except OSError as e: print(f"[HookServer] Port {self.port} in use: {e}"); return
        srv.listen(32); srv.settimeout(1.0)
        print(f"[HookServer] Listening on localhost:{self.port}")
        while self._running:
            try:
                conn, _ = srv.accept()
                threading.Thread(target=self._handle, args=(conn,), daemon=True).start()
            except socket.timeout: continue
            except Exception as e:
                if self._running: print(f"[HookServer] {e}")
        srv.close()
    def _handle(self, conn):
        try:
            data = b""; conn.settimeout(2.0)  # Read + write timeout
            while True:
                c = conn.recv(4096)
                if not c: break
                data += c
                if b"\n" in data or len(data) > 65536: break
            if data:
                t = data.decode("utf-8", errors="ignore").strip()
                if t.startswith(("POST","GET")):
                    for sep in ("\r\n\r\n","\n\n"):
                        p = t.split(sep, 1)
                        if len(p)>1: t=p[1]; break
                try:
                    self.event_received.emit(json.loads(t))
                    try: conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
                    except (socket.timeout, OSError): pass
                except json.JSONDecodeError:
                    try: conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\nBAD")
                    except (socket.timeout, OSError): pass
        except Exception as e:
            if str(e): print(f"[HookServer] Connection error: {e}", file=sys.stderr)
        finally: conn.close()

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
    def notify_needs_attention(self, project):
        if self.history and self.config.get("notification_history_enabled", True):
            self.history.add(f"Claude Code — {project}", "Needs your attention!", "attention")
        if self.config.get("sound_enabled") and HAS_SOUND and not self._should_mute():
            threading.Thread(target=self._play_sound, args=("attention",), daemon=True).start()
        if self.config.get("toast_enabled") and HAS_TOAST and not self.config.get("dnd_mode"):
            threading.Thread(target=self._toast, args=(f"Claude Code — {project}", "Needs your attention!", 10), daemon=True).start()
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

def _is_terminal_focused() -> bool:
    """Check if the foreground window is a known terminal or IDE."""
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.lower()
        patterns = [
            "windows terminal", "command prompt", "powershell",
            "visual studio code", "cursor", "windsurf", "zed",
            "wezterm", "alacritty", "hyper", "kitty", "tabby",
            "intellij", "pycharm", "webstorm", "rider",
            "claude", "terminal", "cmd.exe", "warp",
        ]
        return any(p in title for p in patterns)
    except Exception:
        return False


def _find_claude_windows() -> list:
    """Find visible terminal windows that are actively running Claude Code CLI.

    Claude Code runs inside terminals (Windows Terminal, cmd, PowerShell, etc.)
    and typically sets the window title to include the project directory name.
    We look for terminal processes whose title suggests Claude Code is running.
    We explicitly EXCLUDE: the Claude desktop app (claude.exe), browser tabs,
    and our own Claude Notch overlay windows.
    """
    results = []
    # Known terminal process names (the exe that hosts Claude Code CLI)
    TERMINAL_EXES = {
        "windowsterminal.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
        "wezterm-gui.exe", "alacritty.exe", "hyper.exe", "kitty.exe",
        "tabby.exe", "warp.exe", "conhost.exe", "mintty.exe",
        "code.exe", "cursor.exe", "windsurf.exe",  # IDE integrated terminals
    }
    try:
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        def callback(hwnd, _):
            try:
                if not ctypes.windll.user32.IsWindowVisible(hwnd):
                    return True
                buf = ctypes.create_unicode_buffer(512)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                title = buf.value
                lower = title.lower()
                # Skip our own windows
                if 'claude notch' in lower or 'claude-notch' in lower:
                    return True
                # Skip browser windows (common false positives)
                if any(b in lower for b in ('chrome', 'firefox', 'edge', 'brave', 'opera', 'safari', 'vivaldi')):
                    return True
                # Only match if 'claude' appears in the title
                if 'claude' not in lower:
                    return True
                # Get the process name to verify it's a terminal, not the Claude desktop app
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                pid_val = pid.value
                # Check process name
                h_proc = ctypes.windll.kernel32.OpenProcess(0x0410, False, pid_val)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
                if h_proc:
                    exe_buf = ctypes.create_unicode_buffer(260)
                    size = ctypes.c_ulong(260)
                    if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_proc, 0, exe_buf, ctypes.byref(size)):
                        exe_name = exe_buf.value.split("\\")[-1].lower()
                        ctypes.windll.kernel32.CloseHandle(h_proc)
                        # Only accept terminal processes, not claude.exe (desktop app)
                        if exe_name == "claude.exe":
                            return True
                        if exe_name not in TERMINAL_EXES:
                            return True
                    else:
                        ctypes.windll.kernel32.CloseHandle(h_proc)
                        return True
                else:
                    return True
                results.append({'title': title, 'pid': pid_val, 'hwnd': hwnd})
            except Exception:
                pass
            return True
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)
    except Exception as e:
        print(f"[ProcessScan] EnumWindows failed: {e}", file=sys.stderr)
    return results


def _find_claude_processes() -> list:
    """Find running node.js processes that are Claude Code CLI using PowerShell."""
    results = []
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"name='node.exe'\" | "
             "Where-Object { $_.CommandLine -match 'claude' -and ($_.CommandLine -match 'anthropic' -or $_.CommandLine -match 'claude-code') } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=8,
            creationflags=0x08000000
        )
        for line in r.stdout.strip().split("\n"):
            line = line.strip()
            if line and line.isdigit():
                results.append({'name': 'claude-code', 'pid': int(line)})
    except Exception as e:
        print(f"[ProcessScan] PowerShell process scan failed: {e}", file=sys.stderr)
    return results


def _save_sessions_state(sessions: dict):
    """Persist session metadata to disk for restore on restart."""
    try:
        state = {}
        for sid, s in sessions.items():
            # Don't persist completed sessions — they're dead
            if s.state == "completed":
                continue
            state[sid] = {
                "session_id": s.session_id, "project_dir": s.project_dir,
                "state": s.state, "tool_count": s.tool_count,
                "started_at": s.started_at.isoformat(),
                "last_activity": s.last_activity.isoformat(),
                "tint_index": s.tint_index, "emotion": s.emotion,
                "session_tokens": s.session_tokens,
                "detected_via": s.detected_via,
                "model": s.model,
            }
        _atomic_write(SESSIONS_FILE, {"saved_at": datetime.now().isoformat(), "sessions": state})
    except Exception as e:
        print(f"[Sessions] Save failed: {e}", file=sys.stderr)


def _load_sessions_state() -> dict:
    """Load persisted session state from disk.

    Only restores sessions that were recently active. Completed/stale sessions
    are discarded — they'll reappear via hooks if still alive.
    """
    if not SESSIONS_FILE.exists():
        return {}
    try:
        with open(SESSIONS_FILE) as f:
            data = json.load(f)
        saved_at = datetime.fromisoformat(data.get("saved_at", "2000-01-01"))
        # Don't restore sessions older than 1 hour
        if (datetime.now() - saved_at).total_seconds() > 3600:
            return {}
        result = {}
        for sid, s in data.get("sessions", {}).items():
            saved_state = s.get("state", "idle")
            last_act = datetime.fromisoformat(s.get("last_activity", datetime.now().isoformat()))
            age = (datetime.now() - last_act).total_seconds()
            # Skip completed sessions and sessions inactive for 10+ minutes
            if saved_state == "completed" or age > 600:
                continue
            model = s.get("model", "sonnet")
            result[sid] = Session(
                session_id=s["session_id"], project_dir=s.get("project_dir", ""),
                state="idle",
                tool_count=s.get("tool_count", 0),
                started_at=datetime.fromisoformat(s.get("started_at", datetime.now().isoformat())),
                last_activity=last_act,
                tint_index=s.get("tint_index", 0), emotion=s.get("emotion", "neutral"),
                session_tokens=s.get("session_tokens", 0),
                model=model, context_limit=MODEL_CONTEXT_LIMITS.get(model, 200_000),
            )
        return result
    except Exception as e:
        print(f"[Sessions] Load failed: {e}", file=sys.stderr)
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# LOCAL USAGE TRACKER — daily/monthly stats persisted to disk
# ═══════════════════════════════════════════════════════════════════════════════

USAGE_FILE = CONFIG_DIR / "usage_history.json"

# Rough token estimates per event type (based on typical Claude Code usage)
TOKEN_ESTIMATES = {
    "PreToolUse": 50,        # Hook overhead
    "PostToolUse": 800,      # Avg tool call ~800 tokens
    "PostToolUseFailure": 400,
    "Stop": 200,             # Final response
    "UserPromptSubmit": 500,  # User prompt avg
    "Notification": 100,
    "SessionStart": 0,
    "SessionEnd": 0,
    "SubagentStop": 300,
}

MODEL_PRICING = {
    "opus":   {"input": 15.0,  "output": 75.0, "cache_read": 1.50},
    "sonnet": {"input": 3.0,   "output": 15.0, "cache_read": 0.30},
    "haiku":  {"input": 0.80,  "output": 4.0,  "cache_read": 0.08},
}


class UsageTracker:
    """
    Tracks tool calls, estimated tokens, and sessions per day/month.
    Persists to ~/.claude-notch/usage_history.json.

    Structure:
    {
        "days": {
            "2026-03-29": {"tool_calls": 142, "est_tokens": 113600, "sessions": 3, "prompts": 28},
            "2026-03-28": {"tool_calls": 97, ...},
            ...
        }
    }
    """

    def __init__(self, config=None):
        self._lock = threading.Lock()
        self._data = self._load()
        self._today_key = datetime.now().strftime("%Y-%m-%d")
        self._model = (config.get("default_model", "sonnet") if config else "sonnet")
        self._sub_mode = (config.get("subscription_mode", "max") if config else "max")
        self._config = config

    def _load(self) -> dict:
        if USAGE_FILE.exists():
            try:
                with open(USAGE_FILE) as f:
                    return json.load(f)
            except Exception as e:
                print(f"[Usage] Failed to load usage history: {e}", file=sys.stderr)
        return {"days": {}}

    def _save(self):
        _atomic_write(USAGE_FILE, self._data)

    def _ensure_today(self):
        """Make sure today's entry exists, roll over if date changed."""
        key = datetime.now().strftime("%Y-%m-%d")
        if key != self._today_key:
            self._today_key = key
        if key not in self._data["days"]:
            self._data["days"][key] = {
                "tool_calls": 0, "est_tokens": 0, "sessions": 0, "prompts": 0, "est_cost": 0.0
            }
            # Prune entries older than 90 days
            cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
            self._data["days"] = {
                k: v for k, v in self._data["days"].items() if k >= cutoff
            }

    def _estimate_cost(self, tokens: int) -> float:
        """Estimate cost in dollars for a given token count."""
        pricing = MODEL_PRICING.get(self._model, MODEL_PRICING["sonnet"])
        input_tok = tokens * 0.4
        output_tok = tokens * 0.6
        return (input_tok * pricing["input"] + output_tok * pricing["output"]) / 1_000_000

    def record_event(self, event_type: str):
        """Record a hook event — called from SessionManager."""
        with self._lock:
            self._ensure_today()
            today = self._data["days"][self._today_key]
            est = TOKEN_ESTIMATES.get(event_type, 100)
            today["est_tokens"] += est
            # Only track cost for API-token users (not Max subscribers)
            self._sub_mode = self._config.get("subscription_mode", "max") if self._config else "max"
            if self._sub_mode == "api":
                today["est_cost"] = today.get("est_cost", 0.0) + self._estimate_cost(est)
            if event_type in ("PostToolUse", "PostToolUseFailure"):
                today["tool_calls"] += 1
            elif event_type == "UserPromptSubmit":
                today["prompts"] += 1
            elif event_type == "SessionStart":
                today["sessions"] += 1
            # Save every 10th event to avoid thrashing disk
            total = today["tool_calls"] + today["prompts"]
            if total % 10 == 0:
                self._save()

    def flush(self):
        with self._lock:
            self._save()

    @property
    def today(self) -> dict:
        with self._lock:
            self._ensure_today()
            return dict(self._data["days"].get(self._today_key, {}))

    @property
    def yesterday(self) -> dict:
        with self._lock:
            key = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            return dict(self._data["days"].get(key, {}))

    @property
    def month_stats(self) -> dict:
        """Aggregate stats for the current calendar month."""
        with self._lock:
            prefix = datetime.now().strftime("%Y-%m")
            total = {"tool_calls": 0, "est_tokens": 0, "sessions": 0, "prompts": 0, "days_active": 0, "est_cost": 0.0}
            for key, day in self._data["days"].items():
                if key.startswith(prefix):
                    total["tool_calls"] += day.get("tool_calls", 0)
                    total["est_tokens"] += day.get("est_tokens", 0)
                    total["sessions"] += day.get("sessions", 0)
                    total["prompts"] += day.get("prompts", 0)
                    total["est_cost"] += day.get("est_cost", 0.0)
                    total["days_active"] += 1
            return total

    @property
    def week_stats(self) -> dict:
        """Aggregate stats for the last 7 days."""
        with self._lock:
            cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            total = {"tool_calls": 0, "est_tokens": 0, "sessions": 0, "prompts": 0, "est_cost": 0.0}
            for key, day in self._data["days"].items():
                if key >= cutoff:
                    total["tool_calls"] += day.get("tool_calls", 0)
                    total["est_tokens"] += day.get("est_tokens", 0)
                    total["sessions"] += day.get("sessions", 0)
                    total["prompts"] += day.get("prompts", 0)
                    total["est_cost"] += day.get("est_cost", 0.0)
            return total

    @property
    def daily_avg(self) -> int:
        """Average tool calls per active day this month."""
        m = self.month_stats
        return m["tool_calls"] // max(1, m["days_active"])

    @property
    def all_days(self) -> dict:
        with self._lock:
            return dict(self._data.get("days", {}))

class UsagePoller(QThread):
    usage_updated = pyqtSignal(list)  # list of per-key status dicts
    def __init__(self, config, parent=None):
        super().__init__(parent); self.config = config; self._running = True
        self._results = []
        self._error_counts = {}  # key_redacted -> consecutive error count
    def stop(self): self._running = False
    def run(self):
        poll_count = 0
        while self._running:
            poll_count += 1
            api_keys = list(self.config.get("api_keys", []))  # snapshot the list
            if api_keys:
                results = []
                for i, entry in enumerate(api_keys):
                    if not self._running: return
                    key = entry.get("key", "")
                    label = entry.get("label", f"Key {i+1}")
                    redacted = _redact_key(key)
                    # Skip keys with repeated errors (backoff: skip every N cycles based on error count)
                    err_count = self._error_counts.get(redacted, 0)
                    if err_count >= 3 and poll_count % min(err_count, 10) != 0:
                        # Re-use last result with updated skip note
                        for old in self._results:
                            if old.get("key_redacted") == redacted:
                                results.append(old); break
                        else:
                            results.append({"label": label, "key_redacted": redacted,
                                            "health": "error", "error": "Skipped (repeated errors)",
                                            "last_poll": ""})
                        continue
                    if key and key.startswith("sk-ant"):
                        result = self._poll_one(key, label)
                    else:
                        result = {"label": label, "key_redacted": redacted,
                                  "health": "error", "error": "Invalid key format",
                                  "last_poll": datetime.now().strftime("%H:%M")}
                    # Track consecutive errors for backoff
                    if result.get("health") == "error":
                        self._error_counts[redacted] = self._error_counts.get(redacted, 0) + 1
                    else:
                        self._error_counts[redacted] = 0
                    results.append(result)
                    # 2-second stagger between keys to avoid burst
                    if i < len(api_keys) - 1:
                        for _ in range(4):
                            if not self._running: return
                            time.sleep(0.5)
                self._results = results
            else:
                self._results = []
            self.usage_updated.emit(list(self._results))
            for _ in range(self.config.get("poll_interval_seconds", 60) * 2):
                if not self._running: return
                time.sleep(0.5)

    def _poll_one(self, key: str, label: str) -> dict:
        """Poll a single API key and return its status with health classification."""
        result = {"label": label, "key_redacted": _redact_key(key), "last_poll": datetime.now().strftime("%H:%M")}
        try:
            r = requests.get("https://api.anthropic.com/v1/models",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                timeout=15)
            if r.status_code == 429:
                result.update({"health": "throttled", "error": "Rate limited (429)",
                               "rpm_used": 0, "rpm_limit": 0, "tpm_used": 0, "tpm_limit": 0})
                return result
            if r.status_code == 401:
                result.update({"health": "error", "error": "Invalid API key (401)"}); return result
            h = r.headers
            rl = int(h.get("anthropic-ratelimit-requests-limit", 0))
            rr = int(h.get("anthropic-ratelimit-requests-remaining", 0))
            tl = int(h.get("anthropic-ratelimit-tokens-limit", 0))
            tr = int(h.get("anthropic-ratelimit-tokens-remaining", 0))
            rpm_used = rl - rr; tpm_used = tl - tr
            # Health classification
            if rl == 0 and tl == 0:
                health = "healthy"  # headers unavailable, assume ok
            else:
                rpm_pct = (rpm_used / max(1, rl)) if rl else 0
                tpm_pct = (tpm_used / max(1, tl)) if tl else 0
                usage_pct = max(rpm_pct, tpm_pct)
                if usage_pct > 0.85: health = "throttled"
                elif usage_pct > 0.60: health = "warm"
                else: health = "healthy"
            result.update({
                "health": health, "error": None,
                "rpm_used": rpm_used, "rpm_limit": rl,
                "tpm_used": tpm_used, "tpm_limit": tl,
                "requests_remaining": rr, "tokens_remaining": tr,
            })
        except requests.RequestException as e:
            result.update({"health": "error", "error": str(e)[:50]})
        return result

class EmotionEngine:
    """
    Classifies user prompt sentiment and maintains cumulative emotion scores.
    Outputs: neutral, happy, sad, sob.
    """

    POSITIVE = {"awesome", "perfect", "works", "nice", "great", "love", "amazing",
                "finally", "beautiful", "excellent", "fantastic", "brilliant", "nailed"}
    NEGATIVE = {"bug", "error", "broken", "wrong", "fail", "crash", "stuck", "hate",
                "stupid", "terrible", "awful", "worst", "ugh", "frustrated", "annoying"}
    POSITIVE_PROFANITY = {"fucking awesome", "hell yeah", "holy shit yes", "damn nice",
                          "lets fucking go", "let's fucking go"}
    NEGATIVE_PROFANITY = {"what the fuck", "goddamn", "fucking broken", "shit broke",
                          "fucking hell", "damn it"}

    def __init__(self):
        self._scores = {}  # session_id -> {"happy": float, "sad": float, "neutral": float}
        self._lock = threading.Lock()

    def _ensure(self, sid):
        if sid not in self._scores:
            self._scores[sid] = {"happy": 0.0, "sad": 0.0, "neutral": 0.0}

    def process(self, session_id: str, prompt: str) -> str:
        """Classify prompt and update cumulative score. Returns emotion state."""
        if not prompt:
            return self.get_emotion(session_id)

        with self._lock:
            self._ensure(session_id)
            s = self._scores[session_id]
            lower = prompt.lower()
            words = set(lower.split())

            emotion = "neutral"
            intensity = 0.2

            # Check profanity phrases first (highest priority)
            matched_profanity = False
            for phrase in self.POSITIVE_PROFANITY:
                if phrase in lower:
                    emotion = "happy"; intensity = 0.5; matched_profanity = True; break
            if not matched_profanity:
                for phrase in self.NEGATIVE_PROFANITY:
                    if phrase in lower:
                        emotion = "sad"; intensity = 0.5; matched_profanity = True; break

            # Keyword matching (if profanity didn't match)
            if not matched_profanity:
                pos_hits = len(words & self.POSITIVE)
                neg_hits = len(words & self.NEGATIVE)
                if pos_hits > neg_hits:
                    emotion = "happy"; intensity = min(0.4 + pos_hits * 0.1, 0.6)
                elif neg_hits > pos_hits:
                    emotion = "sad"; intensity = min(0.4 + neg_hits * 0.1, 0.6)

            # Modifiers
            caps_words = sum(1 for w in prompt.split() if w.isupper() and len(w) > 1)
            if caps_words >= 2:
                intensity += 0.2
            if prompt.count("!") >= 3 and emotion != "sad":
                emotion = "happy"; intensity += 0.15
            if len(prompt.strip()) < 10:
                emotion = "neutral"; intensity = 0.1

            # Apply score with dampening
            s[emotion] += intensity * 0.5
            # Cross-emotion decay
            for e in s:
                if e != emotion:
                    s[e] *= 0.9
            # Neutral decays faster
            s["neutral"] *= 0.85

            return self._resolve(session_id)

    def _resolve(self, sid) -> str:
        s = self._scores.get(sid, {})
        if s.get("sad", 0) > 0.9:
            return "sob"
        if s.get("sad", 0) > 0.45:
            return "sad"
        if s.get("happy", 0) > 0.6:
            return "happy"
        return "neutral"

    def get_emotion(self, sid) -> str:
        with self._lock:
            return self._resolve(sid)

    def decay_all(self):
        """Called every 60 seconds to decay all scores toward neutral."""
        with self._lock:
            for sid in self._scores:
                for e in self._scores[sid]:
                    self._scores[sid][e] *= 0.92

    def remove_session(self, sid):
        with self._lock:
            self._scores.pop(sid, None)

class TodoManager:
    """Parses TodoWrite/TaskCreate/TaskUpdate tool events into a todo list per session."""

    def __init__(self):
        self._todos = {}  # session_id -> {task_id: {id, text, status}}
        self._lock = threading.Lock()

    def process_tool_event(self, session_id: str, tool_name: str, tool_input_raw: str):
        if tool_name not in ("TodoWrite", "TaskCreate", "TaskUpdate"):
            return
        if not tool_input_raw:
            return
        try:
            data = json.loads(tool_input_raw) if isinstance(tool_input_raw, str) else tool_input_raw
        except (json.JSONDecodeError, TypeError):
            return

        with self._lock:
            if session_id not in self._todos:
                self._todos[session_id] = {}
            todos = self._todos[session_id]

            if tool_name == "TodoWrite":
                for item in data.get("todos", []):
                    tid = str(item.get("id", ""))
                    if tid:
                        todos[tid] = {
                            "id": tid,
                            "text": item.get("content", item.get("subject", ""))[:80],
                            "status": item.get("status", "pending"),
                        }
            elif tool_name == "TaskCreate":
                tid = str(data.get("id", data.get("taskId", len(todos) + 1)))
                todos[tid] = {
                    "id": tid,
                    "text": data.get("subject", data.get("content", ""))[:80],
                    "status": "pending",
                }
            elif tool_name == "TaskUpdate":
                tid = str(data.get("taskId", data.get("id", "")))
                if tid in todos:
                    if "status" in data:
                        todos[tid]["status"] = data["status"]
                    if "subject" in data:
                        todos[tid]["text"] = data["subject"][:80]

    def get_all_todos(self) -> list:
        with self._lock:
            items = []
            for sid_todos in self._todos.values():
                items.extend(sid_todos.values())
        order = {"in_progress": 0, "pending": 1, "completed": 2}
        items.sort(key=lambda x: order.get(x.get("status", "pending"), 1))
        return items

    def remove_session(self, sid):
        with self._lock:
            self._todos.pop(sid, None)

class GitCheckpoints:
    """Creates and restores non-destructive git snapshots using custom refs."""

    @staticmethod
    def is_git_repo(project_dir: str) -> bool:
        try:
            r = subprocess.run(["git", "rev-parse", "--git-dir"],
                               cwd=project_dir, capture_output=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    @staticmethod
    def create(project_dir: str) -> str | None:
        """Create a snapshot. Returns the commit hash or None on failure."""
        if not project_dir or not GitCheckpoints.is_git_repo(project_dir):
            return None
        try:
            fd, tmp_idx = tempfile.mkstemp(suffix=".git-index")
            os.close(fd)
            env = {**os.environ, "GIT_INDEX_FILE": tmp_idx}
            subprocess.run(["git", "add", "-A"], cwd=project_dir, env=env,
                           capture_output=True, timeout=10)
            r = subprocess.run(["git", "write-tree"], cwd=project_dir, env=env,
                               capture_output=True, timeout=10, text=True)
            if r.returncode != 0:
                return None
            tree = r.stdout.strip()
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            r = subprocess.run(
                ["git", "commit-tree", tree, "-m", f"Claude Notch snapshot {ts}"],
                cwd=project_dir, capture_output=True, timeout=10, text=True)
            if r.returncode != 0:
                return None
            commit = r.stdout.strip()
            proj = Path(project_dir).name
            ref_ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            ref = f"refs/claude-notch/snapshots/{proj}/{ref_ts}"
            subprocess.run(["git", "update-ref", ref, commit],
                           cwd=project_dir, capture_output=True, timeout=10)
            try:
                os.unlink(tmp_idx)
            except Exception:
                pass
            return commit
        except Exception as e:
            print(f"[GitCheckpoints] Create failed: {e}", file=sys.stderr)
            return None

    @staticmethod
    def list_snapshots(project_dir: str) -> list:
        if not project_dir or not GitCheckpoints.is_git_repo(project_dir):
            return []
        try:
            r = subprocess.run(
                ["git", "for-each-ref", "refs/claude-notch/snapshots/",
                 "--sort=-creatordate",
                 "--format=%(refname)\t%(objectname:short)\t%(creatordate:short)\t%(subject)"],
                cwd=project_dir, capture_output=True, timeout=10, text=True)
            if r.returncode != 0:
                return []
            snaps = []
            for line in r.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("\t", 3)
                if len(parts) >= 3:
                    snaps.append({
                        "ref": parts[0], "hash": parts[1],
                        "date": parts[2], "message": parts[3] if len(parts) > 3 else "",
                    })
            return snaps[:10]
        except Exception:
            return []

    @staticmethod
    def restore(project_dir: str, commit_hash: str) -> bool:
        try:
            r = subprocess.run(["git", "checkout", commit_hash, "--", "."],
                               cwd=project_dir, capture_output=True, timeout=30)
            return r.returncode == 0
        except Exception:
            return False

    @staticmethod
    def clear(project_dir: str) -> bool:
        try:
            snaps = GitCheckpoints.list_snapshots(project_dir)
            for s in snaps:
                subprocess.run(["git", "update-ref", "-d", s["ref"]],
                               cwd=project_dir, capture_output=True, timeout=5)
            return True
        except Exception:
            return False

# ═══════════════════════════════════════════════════════════════════════════════
# v2 UTILITIES — Sparkline, Notification History, Streaks, System Monitor
# ═══════════════════════════════════════════════════════════════════════════════

class SparklineTracker:
    """Per-minute activity counter for sparkline graphs."""
    def __init__(self, buckets=30):
        self._buckets = [0] * buckets
        self._n = buckets
        self._current_minute = int(time.time() // 60)
        self._lock = threading.Lock()
    def record(self):
        now = int(time.time() // 60)
        with self._lock:
            diff = now - self._current_minute
            if diff > 0:
                shift = min(diff, self._n)
                self._buckets = self._buckets[shift:] + [0] * shift
                self._current_minute = now
            self._buckets[-1] += 1
    def get_data(self) -> list:
        now = int(time.time() // 60)
        with self._lock:
            diff = now - self._current_minute
            if diff > 0:
                shift = min(diff, self._n)
                return self._buckets[shift:] + [0] * shift
            return list(self._buckets)


class NotificationHistory:
    """Keeps a log of recent notifications."""
    def __init__(self, max_items=50):
        self._items = []; self._max = max_items
    def add(self, title, message, ntype="info"):
        self._items.append({"title": title, "message": message, "type": ntype,
                            "time": datetime.now().strftime("%H:%M")})
        if len(self._items) > self._max: self._items = self._items[-self._max:]
    def get_recent(self, n=8): return list(reversed(self._items[-n:]))


class StreakTracker:
    """Tracks consecutive coding days."""
    def __init__(self, tracker):
        self._tracker = tracker
    @property
    def current_streak(self):
        days_data = self._tracker.all_days
        if not days_data: return 0
        streak = 0; check_date = datetime.now(); today = datetime.now().strftime("%Y-%m-%d")
        for _ in range(365):
            key = check_date.strftime("%Y-%m-%d")
            day = days_data.get(key, {})
            if day.get("tool_calls", 0) > 0 or day.get("prompts", 0) > 0:
                streak += 1; check_date -= timedelta(days=1)
            else:
                if key == today: check_date -= timedelta(days=1); continue
                break
        return streak
    @property
    def top_day_this_week(self):
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        best_date, best_count = "", 0
        for date, data in self._tracker.all_days.items():
            if date >= cutoff:
                tc = data.get("tool_calls", 0)
                if tc > best_count: best_count = tc; best_date = date
        if best_date:
            try: return datetime.strptime(best_date, "%Y-%m-%d").strftime("%A"), best_count
            except Exception: pass
        return "", best_count


class SystemMonitor:
    """CPU and RAM usage via Windows APIs."""
    _last_idle = _last_kernel = _last_user = 0
    _cpu_pct = 0.0
    @staticmethod
    def get_ram():
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            mem = MEMORYSTATUSEX(); mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            total = mem.ullTotalPhys / (1024**3); used = (mem.ullTotalPhys - mem.ullAvailPhys) / (1024**3)
            return {"pct": mem.dwMemoryLoad, "used_gb": round(used, 1), "total_gb": round(total, 1)}
        except Exception: return {"pct": 0, "used_gb": 0, "total_gb": 0}
    @staticmethod
    def update_cpu():
        try:
            idle = ctypes.c_ulonglong(); kernel = ctypes.c_ulonglong(); user = ctypes.c_ulonglong()
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
            di = idle.value - SystemMonitor._last_idle
            dk = kernel.value - SystemMonitor._last_kernel
            du = user.value - SystemMonitor._last_user
            SystemMonitor._last_idle = idle.value; SystemMonitor._last_kernel = kernel.value; SystemMonitor._last_user = user.value
            total = dk + du
            if total > 0 and SystemMonitor._last_idle > 0:
                SystemMonitor._cpu_pct = max(0, min(100, ((total - di) / total) * 100))
        except Exception: pass
    @staticmethod
    def get_cpu(): return round(SystemMonitor._cpu_pct, 1)


def _focus_window_by_pid(pid):
    """Bring the window belonging to a PID to the foreground."""
    try:
        target_hwnd = None
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        def callback(hwnd, _):
            nonlocal target_hwnd
            if not ctypes.windll.user32.IsWindowVisible(hwnd): return True
            p = ctypes.c_ulong(); ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid: target_hwnd = hwnd; return False
            return True
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)
        if target_hwnd:
            ctypes.windll.user32.ShowWindow(target_hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(target_hwnd)
    except Exception as e: print(f"[Focus] {e}", file=sys.stderr)


def export_usage_report(tracker, config, fmt="markdown"):
    td = tracker.today; mo = tracker.month_stats; wk = tracker.week_stats
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    if fmt == "csv":
        lines = ["Date,ToolCalls,Prompts,Tokens,Sessions,Cost"]
        for date in sorted(tracker.all_days.keys()):
            d = tracker.all_days[date]
            lines.append(f"{date},{d.get('tool_calls',0)},{d.get('prompts',0)},{d.get('est_tokens',0)},{d.get('sessions',0)},{d.get('est_cost',0):.4f}")
        content = "\n".join(lines); ext = "csv"
    else:
        content = f"# Claude Notch Usage Report — {ts}\n\n## Today\n- Tool calls: {td.get('tool_calls',0)}\n- Prompts: {td.get('prompts',0)}\n- Est. tokens: {td.get('est_tokens',0):,}\n\n"
        content += f"## This Month ({datetime.now().strftime('%B')})\n- Tool calls: {mo.get('tool_calls',0)}\n- Days active: {mo.get('days_active',0)}\n- Est. tokens: {mo.get('est_tokens',0):,}\n- Est. cost: ${mo.get('est_cost',0):.2f}\n"
        ext = "md"
    desktop = Path.home() / "OneDrive" / "Desktop"
    if not desktop.exists(): desktop = Path.home() / "Desktop"
    out = desktop / f"claude-notch-report-{ts}.{ext}"
    out.write_text(content, encoding="utf-8")
    return str(out)


def _redact_key(key: str) -> str:
    """Redact API key: show first 7 + last 4 chars."""
    if len(key) <= 11:
        return key[:3] + "..." + key[-2:] if len(key) > 5 else "***"
    return key[:7] + "..." + key[-4:]

C = {"notch_bg": QColor(12,12,14), "notch_border": QColor(40,40,48), "card_bg": QColor(28,28,34),
     "divider": QColor(44,44,52), "text_hi": QColor(240,236,232), "text_md": QColor(155,148,142),
     "text_lo": QColor(85,80,76), "coral": QColor(217,119,87), "coral_light": QColor(235,155,120),
     "green": QColor(72,199,132), "amber": QColor(240,185,55), "red": QColor(230,72,72)}
STATUS_COLORS = {"idle": C["text_lo"], "working": C["amber"], "waiting": C["coral"], "completed": C["green"], "error": C["red"]}

CLAWD = [
    [0,0,1,1,0,0,0,1,1,0,0],[0,1,1,1,1,1,1,1,1,1,0],[0,1,1,1,1,1,1,1,1,1,0],
    [0,1,2,2,1,1,1,2,2,1,0],[0,1,2,2,1,1,1,2,2,1,0],[0,1,1,1,1,1,1,1,1,1,0],
    [0,0,1,1,1,1,1,1,1,0,0],[0,0,1,0,1,0,1,0,1,0,0],[0,0,1,0,1,0,1,0,1,0,0],[0,0,1,0,1,0,1,0,1,0,0],
]

EMOTION_STYLES = {
    "neutral": {"bounce_mult": 1.0, "tint": None, "leg_droop": 0, "tremble": False, "eye_droop": 0},
    "happy":   {"bounce_mult": 1.5, "tint": QColor(235,155,120), "leg_droop": 0, "tremble": False, "eye_droop": 0},
    "sad":     {"bounce_mult": 0.5, "tint": QColor(180,130,120), "leg_droop": 1, "tremble": False, "eye_droop": 0.5},
    "sob":     {"bounce_mult": 0.3, "tint": QColor(200,100,90),  "leg_droop": 2, "tremble": True, "eye_droop": 0.5},
}

def draw_clawd(painter, x, y, ps, bounce=0, tint=None, ex=0, ey=0, emotion="neutral", eye_glow=False, glow_phase=0.0):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    style = EMOTION_STYLES.get(emotion, EMOTION_STYLES["neutral"])
    body = tint or style["tint"] or C["coral"]
    eye = QColor(35, 25, 22)
    # Matrix green eye color when coding is active
    if eye_glow:
        glow_intensity = 0.5 + 0.5 * math.sin(glow_phase * 1.8)
        eye_r = int(0 + 35 * (1 - glow_intensity))
        eye_g = int(200 + 55 * glow_intensity)
        eye_b = int(40 + 25 * glow_intensity)
        eye = QColor(eye_r, eye_g, eye_b)
    adj_bounce = bounce * style["bounce_mult"]
    tremble_x = (math.sin(time.time() * 47) * 0.3) if style["tremble"] else 0
    tremble_y = (math.cos(time.time() * 53) * 0.3) if style["tremble"] else 0
    for ri, row in enumerate(CLAWD):
        for ci, cell in enumerate(row):
            if cell == 0:
                continue
            color = body if cell == 1 else eye
            px = x + ci * ps + tremble_x
            py = y + math.sin(adj_bounce) * 1.2 + ri * ps + tremble_y
            if ri >= 7:
                py += math.sin(adj_bounce * 0.5 + ci * 0.8) * 0.5
                py += style["leg_droop"]
            if cell == 2:
                px += ex
                py += ey + style["eye_droop"]
                # Draw green glow halo behind eyes when coding
                if eye_glow:
                    glow_a = int(40 + 30 * math.sin(glow_phase * 1.8))
                    glow_c = QColor(0, 255, 65, glow_a)
                    gs = ps * 2.2
                    painter.fillRect(QRectF(px - ps * 0.6, py - ps * 0.6, gs, gs), QBrush(glow_c))
            painter.fillRect(QRectF(px, py, ps + 0.5, ps + 0.5), QBrush(color))
    painter.restore()

class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent); self.config = config
        self.setWindowTitle("Claude Notch — Settings"); self.setMinimumSize(500, 520)
        self.setStyleSheet("QDialog{background:#121216;color:#f0ece8;}QLabel{color:#9b948e;font-size:12px;}"
            "QLineEdit{background:#1c1c24;border:1px solid #2c2c34;color:#f0ece8;padding:8px;border-radius:4px;font-size:12px;}"
            "QCheckBox{color:#f0ece8;font-size:12px;spacing:8px;}QCheckBox::indicator{width:16px;height:16px;}"
            "QRadioButton{color:#f0ece8;font-size:12px;spacing:8px;}"
            "QPushButton{background:#d97757;color:white;border:none;padding:10px 20px;border-radius:6px;font-weight:bold;font-size:13px;}"
            "QPushButton:hover{background:#eb9b78;}")
        from PyQt6.QtWidgets import QRadioButton, QScrollArea, QFrame
        L = QVBoxLayout(self); L.setSpacing(8); L.setContentsMargins(24,20,24,20)

        # ── Display Mode ──
        L.addWidget(QLabel("How do you use Claude Code?"))
        sub_h = QHBoxLayout()
        self.rb_max = QRadioButton("Subscription (Pro/Max/Team)")
        self.rb_api = QRadioButton("API Tokens (pay-per-use)")
        cur_mode = config.get("subscription_mode", "max")
        self.rb_max.setChecked(cur_mode == "max"); self.rb_api.setChecked(cur_mode == "api")
        sub_h.addWidget(self.rb_max); sub_h.addWidget(self.rb_api); sub_h.addStretch()
        L.addLayout(sub_h)
        sn = QLabel("This only changes what Notch displays. Subscription hides cost estimates\n(you already pay flat-rate). API mode shows estimated $ cost per session.")
        sn.setStyleSheet("color:#5a504c;font-size:10px;"); sn.setWordWrap(True); L.addWidget(sn)
        L.addSpacing(6)

        # ── API Keys ──
        L.addWidget(QLabel("API Keys:"))
        self._keys_layout = QVBoxLayout(); self._keys_layout.setSpacing(4)
        self._key_rows = []
        for entry in config.get("api_keys", []):
            self._add_key_row(entry.get("label", ""), entry.get("key", ""), entry.get("added", ""))
        L.addLayout(self._keys_layout)
        add_row = QHBoxLayout()
        self._new_label = QLineEdit(); self._new_label.setPlaceholderText("Label (e.g. MyProject)")
        self._new_label.setMaximumWidth(140)
        self._new_key = QLineEdit(); self._new_key.setPlaceholderText("sk-ant-...")
        self._new_key.setEchoMode(QLineEdit.EchoMode.Password)
        add_btn = QPushButton("Add"); add_btn.setStyleSheet("QPushButton{background:#2c2c34;font-size:11px;padding:6px 14px;}QPushButton:hover{background:#3c3c4c;}")
        add_btn.clicked.connect(self._add_key)
        add_row.addWidget(self._new_label); add_row.addWidget(self._new_key); add_row.addWidget(add_btn)
        L.addLayout(add_row)
        kn = QLabel("Keys are stored locally in ~/.claude-notch/config.json"); kn.setStyleSheet("color:#5a504c;font-size:10px;"); L.addWidget(kn)
        L.addSpacing(6)

        # ── Appearance ──
        sec = QLabel("Appearance"); sec.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;margin-top:6px;"); L.addWidget(sec)
        th = QHBoxLayout(); th.addWidget(QLabel("Color Theme:"))
        self.theme_combo = QComboBox()
        for t in THEMES: self.theme_combo.addItem(t.capitalize(), t)
        idx = self.theme_combo.findData(config.get("color_theme", "coral"))
        if idx >= 0: self.theme_combo.setCurrentIndex(idx)
        th.addWidget(self.theme_combo); th.addStretch(); L.addLayout(th)
        self.mini_mode = QCheckBox("Mini mode (tiny 28px dot when collapsed)"); self.mini_mode.setChecked(config.get("mini_mode", False)); L.addWidget(self.mini_mode)
        self.dim_inactive = QCheckBox("Dim when no sessions active"); self.dim_inactive.setChecked(config.get("dim_when_inactive", True)); L.addWidget(self.dim_inactive)
        L.addSpacing(4)

        # ── Notifications ──
        sec2 = QLabel("Notifications"); sec2.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;margin-top:6px;"); L.addWidget(sec2)
        self.snd = QCheckBox("Play sound on task completion"); self.snd.setChecked(config.get("sound_enabled",True)); L.addWidget(self.snd)
        self.tst = QCheckBox("Windows toast notifications"); self.tst.setChecked(config.get("toast_enabled",True)); L.addWidget(self.tst)
        self.mute = QCheckBox("Auto-mute when terminal/IDE focused"); self.mute.setChecked(config.get("auto_mute_when_focused", True)); L.addWidget(self.mute)
        self.dnd = QCheckBox("Do Not Disturb (mute everything)"); self.dnd.setChecked(config.get("dnd_mode", False)); L.addWidget(self.dnd)
        self.notif_hist = QCheckBox("Notification history in panel"); self.notif_hist.setChecked(config.get("notification_history_enabled", True)); L.addWidget(self.notif_hist)
        cs_h = QHBoxLayout(); cs_h.addWidget(QLabel("Completion sound:"))
        self.cs_comp = QLineEdit(config.get("custom_sound_completion", "")); self.cs_comp.setPlaceholderText("Default beep")
        cs_b = QPushButton("..."); cs_b.setStyleSheet("QPushButton{background:#2c2c34;font-size:11px;padding:6px 10px;min-width:30px;}QPushButton:hover{background:#3c3c4c;}")
        cs_b.clicked.connect(lambda: self._browse_wav(self.cs_comp))
        cs_h.addWidget(self.cs_comp); cs_h.addWidget(cs_b); L.addLayout(cs_h)
        ca_h = QHBoxLayout(); ca_h.addWidget(QLabel("Attention sound:"))
        self.cs_attn = QLineEdit(config.get("custom_sound_attention", "")); self.cs_attn.setPlaceholderText("Default beep")
        ca_b = QPushButton("..."); ca_b.setStyleSheet("QPushButton{background:#2c2c34;font-size:11px;padding:6px 10px;min-width:30px;}QPushButton:hover{background:#3c3c4c;}")
        ca_b.clicked.connect(lambda: self._browse_wav(self.cs_attn))
        ca_h.addWidget(self.cs_attn); ca_h.addWidget(ca_b); L.addLayout(ca_h)
        L.addSpacing(4)

        # ── Features ──
        sec3 = QLabel("Features"); sec3.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;margin-top:6px;"); L.addWidget(sec3)
        self.click_focus = QCheckBox("Click session to focus terminal"); self.click_focus.setChecked(config.get("click_to_focus", True)); L.addWidget(self.click_focus)
        self.sparkline = QCheckBox("Sparkline activity graph"); self.sparkline.setChecked(config.get("sparkline_enabled", True)); L.addWidget(self.sparkline)
        self.clipboard = QCheckBox("Click to copy project path"); self.clipboard.setChecked(config.get("clipboard_on_click", True)); L.addWidget(self.clipboard)
        self.sess_est = QCheckBox("Session time estimates"); self.sess_est.setChecked(config.get("session_estimate_enabled", True)); L.addWidget(self.sess_est)
        self.streaks_cb = QCheckBox("Coding streaks & stats"); self.streaks_cb.setChecked(config.get("streaks_enabled", True)); L.addWidget(self.streaks_cb)
        self.sys_res = QCheckBox("System resources (CPU/RAM)"); self.sys_res.setChecked(config.get("system_resources_enabled", True)); L.addWidget(self.sys_res)
        self.multi_mon = QCheckBox("Multi-monitor support"); self.multi_mon.setChecked(config.get("multi_monitor", False)); L.addWidget(self.multi_mon)
        L.addSpacing(4)

        # ── Budget ──
        sec4 = QLabel("Budget Alerts (API mode)"); sec4.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;margin-top:6px;"); L.addWidget(sec4)
        bg = QHBoxLayout(); bg.addWidget(QLabel("Daily $:"))
        self.budget_d = QLineEdit(str(config.get("budget_daily", 0.0) or "")); self.budget_d.setMaximumWidth(80); self.budget_d.setPlaceholderText("0=off")
        bg.addWidget(self.budget_d); bg.addWidget(QLabel("Monthly $:"))
        self.budget_m = QLineEdit(str(config.get("budget_monthly", 0.0) or "")); self.budget_m.setMaximumWidth(80); self.budget_m.setPlaceholderText("0=off")
        bg.addWidget(self.budget_m); bg.addStretch(); L.addLayout(bg)
        L.addSpacing(4)

        # ── System ──
        sec5 = QLabel("System"); sec5.setStyleSheet("color:#d97757;font-size:13px;font-weight:bold;margin-top:6px;"); L.addWidget(sec5)
        self.auto = QCheckBox("Start with Windows"); self.auto.setChecked(config.get("auto_start",False)); L.addWidget(self.auto)
        ef = QHBoxLayout(); ef.addWidget(QLabel("Export format:"))
        self.export_fmt = QComboBox(); self.export_fmt.addItem("Markdown", "markdown"); self.export_fmt.addItem("CSV", "csv")
        eidx = self.export_fmt.findData(config.get("export_format", "markdown"))
        if eidx >= 0: self.export_fmt.setCurrentIndex(eidx)
        ef.addWidget(self.export_fmt); ef.addStretch(); L.addLayout(ef)
        pl = QLabel(f"Port: {config.get('hook_server_port',HOOK_SERVER_PORT)}  ·  Ctrl+Shift+C/E/S/D")
        pl.setStyleSheet("color:#5a504c;font-size:10px;"); L.addWidget(pl)
        L.addStretch()
        br = QHBoxLayout()
        self._ib = QPushButton(); self._style_ib(self._check()); self._ib.clicked.connect(self._inst); br.addWidget(self._ib)
        sb = QPushButton("Save"); sb.clicked.connect(self._save); br.addWidget(sb)
        L.addLayout(br)

    def _add_key_row(self, label: str, key: str, added: str = ""):
        """Add a key display row with remove button."""
        row = QHBoxLayout()
        lbl = QLabel(f"{label}:  {_redact_key(key)}"); lbl.setStyleSheet("color:#f0ece8;font-size:11px;font-family:Consolas;")
        rm = QPushButton("✕"); rm.setStyleSheet("QPushButton{background:#2a1a1a;color:#e64848;font-size:11px;padding:4px 8px;border-radius:4px;}QPushButton:hover{background:#3a2020;}")
        rm.setFixedWidth(30)
        idx = len(self._key_rows)
        rm.clicked.connect(lambda _, i=idx: self._remove_key(i))
        row.addWidget(lbl); row.addStretch(); row.addWidget(rm)
        self._keys_layout.addLayout(row)
        self._key_rows.append({"label": label, "key": key, "added": added or datetime.now().strftime("%Y-%m-%d"), "layout": row, "widgets": [lbl, rm]})

    def _add_key(self):
        active_count = sum(1 for r in self._key_rows if r is not None)
        if active_count >= 10:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Limit", "Maximum 10 API keys supported.")
            return
        label = self._new_label.text().strip() or f"Key {len(self._key_rows) + 1}"
        key = self._new_key.text().strip()
        if not key:
            return
        if not key.startswith("sk-ant") or len(key) < 20:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Invalid Key", "API key should start with 'sk-ant' and be at least 20 characters.")
            return
        self._add_key_row(label, key)
        self._new_label.clear(); self._new_key.clear()

    def _remove_key(self, idx):
        if idx < len(self._key_rows):
            row = self._key_rows[idx]
            for w in row["widgets"]:
                w.setParent(None)
            self._key_rows[idx] = None  # mark as removed

    def _browse_wav(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(self, "Select Sound File", "", "WAV Files (*.wav);;All Files (*)")
        if path: line_edit.setText(path)

    def _style_ib(self, ok):
        if ok: self._ib.setText("✓ Hooks Installed"); self._ib.setStyleSheet("QPushButton{background:#1c3a2a;font-size:11px;padding:8px 14px;color:#48c784;}QPushButton:hover{background:#2c4a3a;}")
        else: self._ib.setText("Install Claude Code Hooks"); self._ib.setStyleSheet("QPushButton{background:#2c2c34;font-size:11px;padding:8px 14px;}QPushButton:hover{background:#3c3c4c;}")
    def _save(self):
        def _float(s, default=0.0):
            try: return float(s) if s else default
            except ValueError: return default
        sub_mode = "max" if self.rb_max.isChecked() else "api"
        api_keys = [{"key": r["key"], "label": r["label"], "added": r.get("added", "")}
                    for r in self._key_rows if r is not None]
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
            "dim_when_inactive": self.dim_inactive.isChecked(),
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
        set_auto_start(self.auto.isChecked()); self.accept()
    def _inst(self):
        install_hooks(self.config.get("hook_server_port",HOOK_SERVER_PORT)); self._style_ib(True)
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Done", "Hooks installed! Restart Claude Code sessions.")
    @staticmethod
    def _check():
        p = Path.home() / ".claude" / "settings.json"
        if not p.exists(): return False
        try:
            with open(p) as f: d = json.load(f)
            return any("claude_notch_hook" in str(h) for hs in d.get("hooks",{}).values() for h in hs)
        except: return False

def install_hooks(port=HOOK_SERVER_PORT):
    hd = CONFIG_DIR / "hooks"; hd.mkdir(parents=True, exist_ok=True)
    (hd / "claude_notch_hook.ps1").write_text(f'''param([string]$EventType = "Unknown")
$ij=[Console]::In.ReadToEnd()
$p=$ij|ConvertFrom-Json -EA SilentlyContinue
$et=$EventType
$up=""; if($p.user_prompt){{$up=$p.user_prompt.ToString().Substring(0,[Math]::Min($p.user_prompt.ToString().Length,500))}}
$ti=""; if($p.tool_input){{try{{$ti=($p.tool_input|ConvertTo-Json -Compress -Depth 3).Substring(0,[Math]::Min(($p.tool_input|ConvertTo-Json -Compress -Depth 3).Length,4096))}}catch{{}}}}
$pl=@{{event=$et;session_id=if($p.session_id){{$p.session_id}}else{{$env:CLAUDE_SESSION_ID}};project_dir=$env:CLAUDE_PROJECT_DIR;tool_name=if($p.tool_name){{$p.tool_name}}else{{""}};user_prompt=$up;tool_input=$ti;timestamp=(Get-Date -Format "o")}}|ConvertTo-Json -Compress
try{{$c=New-Object System.Net.Sockets.TcpClient;$c.Connect("127.0.0.1",{port});$s=$c.GetStream();$b=[Text.Encoding]::UTF8.GetBytes($pl+"`n");$s.Write($b,0,$b.Length);$s.Flush();Start-Sleep -Ms 50;$c.Close()}}catch{{}}
exit 0''', encoding="utf-8")
    sp = Path.home() / ".claude" / "settings.json"; sp.parent.mkdir(parents=True, exist_ok=True)
    settings = {}
    if sp.exists():
        try:
            with open(sp) as f: settings = json.load(f)
        except Exception as e:
            print(f"[Hooks] Failed to read settings: {e}", file=sys.stderr)
    base_cmd = f'powershell.exe -ExecutionPolicy Bypass -File "{hd / "claude_notch_hook.ps1"}"'
    if "hooks" not in settings: settings["hooks"] = {}
    for ev in ["PreToolUse","PostToolUse","PostToolUseFailure","Stop","Notification","SessionStart","SessionEnd","UserPromptSubmit","SubagentStop"]:
        cmd = f'{base_cmd} -EventType {ev}'
        hook = {"type": "command", "command": cmd, "timeout": 3000}
        if ev not in settings["hooks"]: settings["hooks"][ev] = []
        # Remove old entries without -EventType, then add fixed version
        settings["hooks"][ev] = [h for h in settings["hooks"][ev] if "claude_notch_hook" not in str(h)]
        settings["hooks"][ev].append({"hooks": [hook]})
    with open(sp, "w") as f: json.dump(settings, f, indent=2)
    print(f"[Hooks] Installed at {hd}")

class ClaudeNotch(QWidget):
    HW, HH, EW, EH = 300, 34, 560, 500
    VW, VH = 34, 200

    MINI_SZ = 28

    def __init__(self, sessions, config, tracker, emotion_engine=None, todo_manager=None,
                 sparkline=None, notif_history=None, streaks=None):
        super().__init__(); self.sessions = sessions; self.config = config
        self.tracker = tracker; self.emotion_engine = emotion_engine
        self.todo_manager = todo_manager; self.sparkline = sparkline
        self.notif_history = notif_history; self.streaks = streaks
        self._started = datetime.now()
        self._expanded = self._pinned = self._dragging = self._was_exp = False
        self._drag_cooldown = False
        self._resizing = False; self._resize_edges = set()
        self._resize_start_pos = QPoint(); self._resize_start_geom = None
        self._refresh_btn_rect = QRectF(0, 0, 0, 0)
        self._dnd_btn_rect = QRectF(0, 0, 0, 0)
        self._export_btn_rect = QRectF(0, 0, 0, 0)
        self._session_click_rects = []
        self._scroll_offset = 0; self._max_scroll = 0
        self._target_opacity = 1.0; self._current_opacity = 1.0
        self._drag_off = QPoint(); self._anim_p = self._bounce = self._pulse = 0.0
        self._anim_dir = 0; self._ori = "horizontal"; self._edge = "top"
        self._anchor_pos = QPoint(0, 0)
        self._usage_keys = []  # list of per-key status dicts from UsagePoller
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(self.nw, self.nh)
        lx, ly = config.get("last_x",-1), config.get("last_y",-1)
        scr = self._screen_geom()
        if lx >= 0 and ly >= 0:
            self.move(lx, ly); le = config.get("last_edge","top")
            self._edge = le; self._ori = "vertical" if le in ("left","right") else "horizontal"
            self.setFixedSize(self.nw, self.nh); self._anchor_pos = QPoint(lx, ly)
        else:
            ax = (scr.width()-self.HW)//2
            self.move(ax, 0); self._anchor_pos = QPoint(ax, 0)
        self._ht = QTimer(self); self._ht.setSingleShot(True); self._ht.setInterval(250); self._ht.timeout.connect(self._expand)
        self._ct = QTimer(self); self._ct.setSingleShot(True); self._ct.setInterval(600); self._ct.timeout.connect(self._collapse)
        self._tt = QTimer(self); self._tt.setInterval(33); self._tt.timeout.connect(self._tick); self._tt.start()
        self._at = QTimer(self); self._at.setInterval(16); self._at.timeout.connect(self._animate)
        # Safety-net hover poll: catches missed enter/leave events
        self._hover_timer = QTimer(self); self._hover_timer.setInterval(200)
        self._hover_timer.timeout.connect(self._hover_check); self._hover_timer.start()
        self._clt = QTimer(self); self._clt.setInterval(60000); self._clt.timeout.connect(sessions.cleanup_dead); self._clt.start()
        if self.emotion_engine:
            self._emo_timer = QTimer(self); self._emo_timer.setInterval(60000)
            self._emo_timer.timeout.connect(self.emotion_engine.decay_all)
            self._emo_timer.start()
        self._vis_timer = QTimer(self); self._vis_timer.setInterval(5000)
        self._vis_timer.timeout.connect(self._ensure_visible); self._vis_timer.start()
        # Periodic session save every 60s
        self._save_timer = QTimer(self); self._save_timer.setInterval(60000)
        self._save_timer.timeout.connect(sessions.save_state); self._save_timer.start()
        # System monitor CPU sampling every 3s
        self._sys_timer = QTimer(self); self._sys_timer.setInterval(3000)
        self._sys_timer.timeout.connect(SystemMonitor.update_cpu); self._sys_timer.start()
        SystemMonitor.update_cpu()
        # Performance cache — avoid recalculating tracker stats every paint frame
        self._cached_today = {}; self._cached_yesterday = {}
        self._cached_week = {}; self._cached_month = {}; self._cached_avg = 0
        self._cached_period_label = "today"; self._cached_period_data = {}
        self._cache_timer = QTimer(self); self._cache_timer.setInterval(5000)
        self._cache_timer.timeout.connect(self._refresh_cache); self._cache_timer.start()
        self._refresh_cache()
        sessions.session_updated.connect(self.update)

    def _screen_geom(self):
        if self.config.get("multi_monitor", False):
            screen = QApplication.screenAt(self.pos())
            if screen: return screen.geometry()
        return QApplication.primaryScreen().geometry()

    @property
    def nw(self):
        if self.config.get("mini_mode"): return self.MINI_SZ
        return self.VW if self._ori=="vertical" else self.HW
    @property
    def nh(self):
        if self.config.get("mini_mode"): return self.MINI_SZ
        return self.VH if self._ori=="vertical" else self.HH
    @property
    def ew(self): return self.config.get("expanded_w", self.EW)
    @property
    def eh(self): return self.config.get("expanded_h", self.EH)
    @property
    def uptime(self):
        m=int((datetime.now()-self._started).total_seconds()/60)
        return "<1m" if m<1 else f"{m}m" if m<60 else f"{m//60}h {m%60}m"

    def _det_edge(self):
        """Detect which screen edge we're nearest to — always locks to an edge."""
        scr = self._screen_geom(); p = self.pos(); old = self._ori
        cw, ch = (self.VW if self._ori == "vertical" else self.HW), (self.VH if self._ori == "vertical" else self.HH)
        cx, cy = p.x() + cw / 2, p.y() + ch / 2  # center of widget
        # Distance from each edge
        d_left = p.x()
        d_right = scr.width() - (p.x() + cw)
        d_top = p.y()
        d_bottom = scr.height() - (p.y() + ch)
        # Find nearest edge
        dists = {"left": d_left, "right": d_right, "top": d_top, "bottom": d_bottom}
        nearest = min(dists, key=dists.get)
        if nearest in ("left", "right"):
            self._edge, self._ori = nearest, "vertical"
        else:
            self._edge, self._ori = nearest, "horizontal"
        if old != self._ori and not self._expanded:
            self.setFixedSize(self.nw, self.nh)

    def _save_pos(self): self.config.set_many({"last_x":self.pos().x(),"last_y":self.pos().y(),"last_edge":self._edge})
    def update_usage(self, keys_data): self._usage_keys=keys_data; self.update()

    def _refresh_cache(self):
        """Refresh cached tracker stats every 5s instead of every paint frame."""
        td = self.tracker.today; mo = self.tracker.month_stats; avg = self.tracker.daily_avg
        self._cached_today = td; self._cached_month = mo; self._cached_avg = avg
        period_label = "today"
        if td.get("tool_calls", 0) == 0 and td.get("prompts", 0) == 0:
            yd = self.tracker.yesterday
            self._cached_yesterday = yd
            if yd.get("tool_calls", 0) > 0 or yd.get("prompts", 0) > 0:
                td = yd; period_label = "yesterday"
            else:
                wk = self.tracker.week_stats
                self._cached_week = wk
                if wk.get("tool_calls", 0) > 0 or wk.get("prompts", 0) > 0:
                    td = wk; period_label = "this week"
        self._cached_period_label = period_label
        self._cached_period_data = td
        # Update dim target
        if self.config.get("dim_when_inactive", True) and self.sessions.total_active == 0:
            self._target_opacity = max(0.45, self.config.get("dim_opacity", 0.55))
        else:
            self._target_opacity = 1.0

    def _tick(self):
        self._bounce+=0.08; self._pulse+=0.1
        # Smooth dim transition
        if abs(self._current_opacity - self._target_opacity) > 0.01:
            self._current_opacity += (self._target_opacity - self._current_opacity) * 0.05
            self.setWindowOpacity(self._current_opacity)
        self.update()

    def _animate(self):
        sp=0.08
        if self._anim_dir>0: self._anim_p=min(1.0,self._anim_p+sp);
        elif self._anim_dir<0: self._anim_p=max(0.0,self._anim_p-sp)
        if self._anim_p>=1.0 and self._anim_dir>0: self._at.stop()
        if self._anim_p<=0.0 and self._anim_dir<0: self._at.stop(); self._expanded=False; self._anchor_pos=self.pos()
        t=1-(1-self._anim_p)**3; w=int(self.nw+(self.ew-self.nw)*t); h=int(self.nh+(self.eh-self.nh)*t)
        ax,ay=self._anchor_pos.x(),self._anchor_pos.y(); scr=self._screen_geom()
        if self._edge=="right": nx=scr.width()-w; ny=ay
        elif self._edge=="bottom": nx=ax+self.nw//2-w//2; ny=scr.height()-h
        elif self._edge=="left": nx=0; ny=ay
        else: nx=ax+self.nw//2-w//2; ny=ay
        self.setFixedSize(w,h); self.move(max(0,min(nx,scr.width()-w)),max(0,min(ny,scr.height()-h))); self.update()

    def _expand(self):
        if not self._expanded:
            self._expanded = True; self._anim_dir = 1; self._at.start()

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
            self._anim_dir = -1; self._at.start()

    def toggle_expand(self):
        """Toggle expand/collapse — used by hotkey."""
        if self._expanded:
            self._collapse(force=True)
        else:
            self._pinned = True
            self._expand()

    # ── Hover detection ──
    # enterEvent/leaveEvent are the primary mechanism.
    # A 200ms background poll (_hover_check) is the safety net for when
    # Qt misses a leave event (widget resize, fast mouse, compositing).

    def enterEvent(self, e):
        self._ct.stop()
        if not self._expanded and not self._dragging and not self._drag_cooldown and not self._resizing:
            self._ht.start()

    def leaveEvent(self, e):
        self._ht.stop()
        if self._expanded and not self._pinned:
            self._ct.start()

    def _hover_check(self):
        """Safety net: poll cursor position every 200ms to catch missed leave events."""
        if self._dragging or self._resizing or self._drag_cooldown:
            return
        inside = self.geometry().contains(QCursor.pos())
        if not inside and self._expanded and not self._pinned:
            # Mouse is outside but we're still expanded — start collapse
            if not self._ct.isActive() and self._anim_dir >= 0:
                self._ct.start()
        elif inside and self._expanded and not self._pinned:
            # Mouse is inside — cancel any pending collapse
            self._ct.stop()

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
                    self._do_refresh(); return
                if self._dnd_btn_rect.contains(e.pos().x(), e.pos().y()):
                    self._toggle_dnd(); return
                if self._export_btn_rect.contains(e.pos().x(), e.pos().y()):
                    self._do_export(); return
                # Click-to-focus or clipboard on session row
                for rect, sess in self._session_click_rects:
                    if rect.contains(e.pos().x(), e.pos().y()):
                        if self.config.get("click_to_focus", True) and sess.pid:
                            _focus_window_by_pid(sess.pid); return
                        elif self.config.get("clipboard_on_click", True) and sess.project_dir:
                            QApplication.clipboard().setText(sess.project_dir); return
            self._ht.stop(); self._ct.stop()
            self._drag_cooldown = False
            # Always collapse expanded to collapsed size before dragging
            if self._expanded:
                self._was_exp = True
                click_x, click_y = e.pos().x(), e.pos().y()
                self._anim_p = 0; self._anim_dir = 0; self._at.stop()
                self._expanded = False; self._pinned = False
                self.setFixedSize(self.nw, self.nh)
                # Re-center collapsed notch on cursor
                self.move(self.pos().x() + click_x - self.nw // 2,
                          self.pos().y() + click_y - self.nh // 2)
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
            self.move(n); self._det_edge()
            if not self._expanded:
                self.setFixedSize(self.nw, self.nh)
            self.update()
        elif self._expanded and self._anim_p >= 1.0:
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
            self._det_edge(); self._snap(); self._save_pos()
            if mv < 5:
                # Click (not drag)
                if self._was_exp:
                    # Was expanded, we collapsed it on mousePress for drag-readiness.
                    # Since user didn't actually drag (mv<5), this was a click-to-collapse.
                    # Already collapsed — just stay collapsed.
                    pass
                elif not self._expanded:
                    # Collapsed → expand + pin
                    self._pinned = True
                    self._expand()
            else:
                # Real drag completed — block hover for 800ms then check cursor
                self._drag_cooldown = True
                self._ht.stop(); self._ct.stop()
                QTimer.singleShot(800, self._drag_cooldown_end)
            self.update()

    def _drag_cooldown_end(self):
        """Called 800ms after drag release to re-enable hover."""
        self._drag_cooldown = False
        inside = self.geometry().contains(QCursor.pos())
        if inside and not self._expanded and not self._pinned:
            self._ht.start()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            try:
                # Check if claude is available before spawning
                check = subprocess.run(["where", "claude"], capture_output=True, timeout=3,
                                       creationflags=0x08000000)
                if check.returncode == 0:
                    subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", "claude"],
                                     creationflags=0x00000008)
            except Exception:
                pass

    def wheelEvent(self, e):
        """Scroll the Recent Activity area when expanded."""
        if self._expanded:
            delta = e.angleDelta().y()
            self._scroll_offset = max(0, min(self._max_scroll,
                                              self._scroll_offset - delta // 4))
            self.update()

    def _snap(self):
        """Snap to the nearest screen edge using COLLAPSED dimensions."""
        s = self._screen_geom()
        x, y = self.pos().x(), self.pos().y()
        # Use collapsed dimensions for snapping (not current, which may be expanded)
        cw, ch = self.nw, self.nh
        if self._edge == "top":
            y = 0
        elif self._edge == "bottom":
            y = s.height() - ch
        elif self._edge == "left":
            x = 0
        elif self._edge == "right":
            x = s.width() - cw
        self.move(x, y)
        self._anchor_pos = QPoint(x, y)

    def _ensure_visible(self):
        if not self.isVisible(): return
        scr=self._screen_geom(); p=self.pos()
        x=max(0,min(p.x(),scr.width()-self.width())); y=max(0,min(p.y(),scr.height()-self.height()))
        if x!=p.x() or y!=p.y(): self.move(x,y); self._anchor_pos=QPoint(x,y); self._save_pos()
        self.raise_()

    def force_show(self):
        """Reliably show and raise — used by tray click and hotkeys."""
        self.show()
        self._ensure_visible()

    def showEvent(self, e):
        super().showEvent(e); self._ensure_visible()

    def _toggle_dnd(self):
        cur = self.config.get("dnd_mode", False)
        self.config.set("dnd_mode", not cur); self.update()

    def _do_export(self):
        fmt = self.config.get("export_format", "markdown")
        path = export_usage_report(self.tracker, self.config, fmt)
        if HAS_TOAST:
            threading.Thread(target=lambda: toast_notify.notify(
                title="Claude Notch", message=f"Report saved to {Path(path).name}",
                app_name="Claude Notch", timeout=5), daemon=True).start()

    def _eye_shift(self):
        try:
            cur=QCursor.pos(); cx=self.pos().x()+14+5*2.5; cy=self.pos().y()+self.HH//2
            dx,dy=cur.x()-cx,cur.y()-cy; d=max(1,math.sqrt(dx*dx+dy*dy))
            return dx/d*1.2, dy/d*1.0
        except: return 0,0

    RESIZE_MARGIN = 8  # pixels from edge for resize handle detection
    MIN_EW, MIN_EH = 440, 400
    MAX_EW, MAX_EH = 900, 900

    def _resize_edge_at(self, pos):
        """Detect which edges the cursor is near for resize."""
        if not self._expanded or self._anim_p < 1.0:
            return set()
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        m = self.RESIZE_MARGIN
        edges = set()
        if x < m: edges.add("left")
        if x > w - m: edges.add("right")
        if y < m: edges.add("top")
        if y > h - m: edges.add("bottom")
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

    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w,h=self.width(),self.height(); t=1-(1-self._anim_p)**3
        self._ps(p,w,h,t); self._pc(p,t)
        if t<0.3: self._pcol(p,w,t)
        if t>0.1: self._pexp(p,w,h,t)
        p.end()

    def _ps(self,p,w,h,t):
        path=QPainterPath(); e=self._edge; r=int(10+4*t); s=2
        tl=s if e in("top","left") else r; tr=s if e in("top","right") else r
        br=s if e in("bottom","right") else r; bl=s if e in("bottom","left") else r
        path.moveTo(tl,0); path.lineTo(w-tr,0); path.arcTo(w-tr*2,0,tr*2,tr*2,90,-90)
        path.lineTo(w,h-br); path.arcTo(w-br*2,h-br*2,br*2,br*2,0,-90)
        path.lineTo(bl,h); path.arcTo(0,h-bl*2,bl*2,bl*2,-90,-90)
        path.lineTo(0,tl); path.arcTo(0,0,tl*2,tl*2,180,-90)
        bg=QLinearGradient(0,0,0,h); bg.setColorAt(0,C["notch_bg"]); bg.setColorAt(1,QColor(8,8,10) if t>0.5 else C["notch_bg"])
        p.setBrush(QBrush(bg)); p.setPen(Qt.PenStyle.NoPen); p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(QPen(QColor(217,119,87,40),3.0)); p.drawPath(path)
        p.setPen(QPen(C["coral"],1.0)); p.drawPath(path)
        if t>0.2:
            a=min(255,int(t*300)); c1=QColor(217,119,87,0); c2=QColor(217,119,87,a); c3=QColor(235,155,120,a)
            if e=="left": g=QLinearGradient(1,20,1,h-20); g.setColorAt(0,c1);g.setColorAt(0.3,c2);g.setColorAt(0.7,c3);g.setColorAt(1,c1); p.setPen(QPen(QBrush(g),1.5)); p.drawLine(1,20,1,h-20)
            elif e=="right": g=QLinearGradient(w-1,20,w-1,h-20); g.setColorAt(0,c1);g.setColorAt(0.3,c2);g.setColorAt(0.7,c3);g.setColorAt(1,c1); p.setPen(QPen(QBrush(g),1.5)); p.drawLine(w-1,20,w-1,h-20)
            elif e=="bottom": g=QLinearGradient(20,h-1,w-20,h-1); g.setColorAt(0,c1);g.setColorAt(0.3,c2);g.setColorAt(0.7,c3);g.setColorAt(1,c1); p.setPen(QPen(QBrush(g),1.5)); p.drawLine(20,h-1,w-20,h-1)
            else: g=QLinearGradient(20,1,w-20,1); g.setColorAt(0,c1);g.setColorAt(0.3,c2);g.setColorAt(0.7,c3);g.setColorAt(1,c1); p.setPen(QPen(QBrush(g),1.5)); p.drawLine(20,1,w-20,1)
        # Animated glow border — always visible, intensity scales with activity
        glow_alpha = 15
        if self.sessions.any_working:
            glow_alpha = int(120 + 60 * math.sin(self._pulse * 2))
        elif self.sessions.any_waiting:
            glow_alpha = int(90 + 50 * math.sin(self._pulse * 2.5))
        elif self.sessions.total_active > 0:
            glow_alpha = 35
        # Collapsed: subtler glow; expanded: full intensity
        if t < 0.5:
            glow_alpha = int(glow_alpha * (0.5 + t))
        else:
            glow_alpha = int(glow_alpha * min(1.0, (t - 0.3) * 2))

        if glow_alpha > 3:
            cx, cy = w / 2, h / 2
            grad = QConicalGradient(cx, cy, (self._pulse * 20) % 360)
            gc1 = QColor(217, 119, 87, glow_alpha)
            gc2 = QColor(235, 155, 120, glow_alpha)
            grad.setColorAt(0.0, gc1); grad.setColorAt(0.25, gc2)
            grad.setColorAt(0.5, gc1); grad.setColorAt(0.75, gc2)
            grad.setColorAt(1.0, gc1)

            glow_path = QPainterPath()
            gr = r + 1
            gtl = (s + 1) if e in ("top", "left") else gr
            gtr = (s + 1) if e in ("top", "right") else gr
            gbr = (s + 1) if e in ("bottom", "right") else gr
            gbl = (s + 1) if e in ("bottom", "left") else gr
            glow_path.moveTo(gtl, -1); glow_path.lineTo(w - gtr + 1, -1)
            glow_path.arcTo(w - gtr * 2, -1, gtr * 2 + 1, gtr * 2 + 1, 90, -90)
            glow_path.lineTo(w + 1, h - gbr)
            glow_path.arcTo(w - gbr * 2, h - gbr * 2, gbr * 2 + 1, gbr * 2 + 1, 0, -90)
            glow_path.lineTo(gbl, h + 1)
            glow_path.arcTo(-1, h - gbl * 2, gbl * 2 + 1, gbl * 2 + 1, -90, -90)
            glow_path.lineTo(-1, gtl)
            glow_path.arcTo(-1, -1, gtl * 2 + 1, gtl * 2 + 1, 180, -90)

            p.setBrush(Qt.BrushStyle.NoBrush)
            glow_width = 1.5 + t * 0.5  # Thinner when collapsed, thicker expanded
            p.setPen(QPen(QBrush(grad), glow_width))
            p.drawPath(glow_path)

    def _pc(self, p, t):
        ps = 2.5; gh = 10 * ps; ex, ey = self._eye_shift()
        if self._ori == "vertical" and t < 0.3:
            cx = (self.VW - 11 * ps) / 2; cy = 6
        else:
            cx = 14; cy = (self.HH - gh) / 2 + 1
        b = self._bounce; tint = None
        is_working = self.sessions.any_working
        if self.sessions.any_waiting:
            tint = C["coral"]
        elif is_working:
            q = 0.5 + 0.5 * math.sin(self._pulse * 2)
            tint = QColor(int(217 + 23 * q), int(119 + 66 * q), int(87 - 32 * q))
        active = self.sessions.get_active_sessions()
        emotion = active[0].emotion if active else "neutral"
        draw_clawd(p, cx, cy, ps, b, tint, ex, ey, emotion,
                   eye_glow=is_working, glow_phase=self._pulse)

    def _pcol(self,p,w,t):
        op=1-t*3
        if op<=0: return
        p.save(); p.setOpacity(op)
        dc=C["amber"] if self.sessions.any_working else C["coral"] if self.sessions.any_waiting else C["green"] if self.sessions.total_active>0 else C["text_lo"]
        if self._ori=="vertical":
            dx,dy=self.VW//2,38
            if self.sessions.any_working or self.sessions.any_waiting:
                q=0.5+0.5*math.sin(self._pulse*2.5); gr=3.5+q*3
                p.setBrush(QBrush(QColor(dc.red(),dc.green(),dc.blue(),int(40+q*40)))); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(dx-gr,dy-gr,gr*2,gr*2))
            p.setBrush(QBrush(dc)); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QRectF(dx-3.5,dy-3.5,7,7))
            c=self.sessions.total_active
            if c>0: p.setPen(QPen(C["text_md"])); p.setFont(QFont("Segoe UI",7)); p.drawText(0,48,self.VW,14,Qt.AlignmentFlag.AlignCenter,str(c))
        else:
            dx,dy=48,self.HH//2
            if self.sessions.any_working or self.sessions.any_waiting:
                q=0.5+0.5*math.sin(self._pulse*2.5); gr=3.5+q*3
                p.setBrush(QBrush(QColor(dc.red(),dc.green(),dc.blue(),int(40+q*40)))); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(dx-gr,dy-gr,gr*2,gr*2))
            p.setBrush(QBrush(dc)); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QRectF(dx-3.5,dy-3.5,7,7))
            a=self.sessions.get_active_sessions()
            if a and a[0].state == "waiting":
                tx = f"{a[0].project_name}: Needs input!"
            elif a:
                tx = f"{a[0].project_name}: {a[0].current_tool or a[0].state}"
            else:
                tx = "No active sessions"
            if len(tx)>34: tx=tx[:32]+"…"
            p.setPen(QPen(C["text_md"])); p.setFont(QFont("Segoe UI",8))
            p.drawText(58,0,w-100,self.HH,Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,tx)
            c=self.sessions.total_active
            if c>0:
                bx,by=w-28,self.HH//2
                p.setBrush(QBrush(C["coral"] if c>1 else C["text_lo"])); p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(bx-8,by-8,16,16))
                p.setPen(QPen(QColor(255,255,255))); p.setFont(QFont("Segoe UI",7,QFont.Weight.Bold))
                p.drawText(int(bx-8),int(by-8),16,16,Qt.AlignmentFlag.AlignCenter,str(c))
        p.restore()

    def _pexp(self, pr, w, h, t):
        if t < 0.15: return
        pr.save(); pr.setOpacity(min(1, (t - 0.15) / 0.4))
        top, L, R = self.HH + 10, 20, w - 20; cw = R - L
        self._session_click_rects = []

        # ── CLAWD ICON (small, top-left) ──
        draw_clawd(pr, L, top + 2, 2.0, self._bounce, None, 0, 0, "neutral",
                   eye_glow=self.sessions.any_working, glow_phase=self._pulse)

        # ── TITLE BAR with session pill + refresh button ──
        pr.setPen(QPen(C["text_hi"])); pr.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        pr.drawText(L + 28, top, cw - 28, 26, Qt.AlignmentFlag.AlignLeft, "Claude Notch")
        ac = self.sessions.get_active_sessions()

        # DND button
        dnd_sz = 22; dnd_x = R - dnd_sz; dnd_y = top + 3
        self._dnd_btn_rect = QRectF(dnd_x, dnd_y, dnd_sz, dnd_sz)
        dnd_on = self.config.get("dnd_mode", False)
        pr.setBrush(QBrush(QColor(230,72,72,40) if dnd_on else QColor(C["coral"].red(),C["coral"].green(),C["coral"].blue(),20)))
        pr.setPen(QPen(C["red"] if dnd_on else C["coral"], 1.0))
        pr.drawRoundedRect(self._dnd_btn_rect, 6, 6)
        pr.setFont(QFont("Segoe UI", 9)); pr.drawText(int(dnd_x), int(dnd_y), int(dnd_sz), int(dnd_sz), Qt.AlignmentFlag.AlignCenter, "M" if dnd_on else "N")

        # Refresh button
        refresh_sz = 22; refresh_x = dnd_x - refresh_sz - 4; refresh_y = top + 3
        self._refresh_btn_rect = QRectF(refresh_x, refresh_y, refresh_sz, refresh_sz)
        pr.setBrush(QBrush(QColor(217, 119, 87, 20))); pr.setPen(QPen(C["coral"], 1.0))
        pr.drawRoundedRect(self._refresh_btn_rect, 6, 6)
        # Draw refresh arrow icon
        pr.setPen(QPen(C["coral"], 1.5))
        pr.setFont(QFont("Segoe UI", 11))
        pr.drawText(int(refresh_x), int(refresh_y), int(refresh_sz), int(refresh_sz),
                    Qt.AlignmentFlag.AlignCenter, "⟳")

        # Session pill
        sc_text = f"{len(ac)} session{'s' if len(ac) != 1 else ''}"
        pr.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold)); fm = pr.fontMetrics()
        pill_w = fm.horizontalAdvance(sc_text) + 20; pill_x = refresh_x - pill_w - 8
        pr.setBrush(QBrush(QColor(217, 119, 87, 35))); pr.setPen(QPen(C["coral"], 1.0))
        pr.drawRoundedRect(QRectF(pill_x, top + 4, pill_w, 20), 10, 10)
        pr.setPen(QPen(C["coral"]))
        pr.drawText(int(pill_x), top + 4, int(pill_w), 20, Qt.AlignmentFlag.AlignCenter, sc_text)
        top += 32
        pr.setPen(QPen(C["divider"])); pr.drawLine(L, top, R, top); top += 10

        # ── SESSIONS with coral accent underline ──
        pr.setPen(QPen(C["coral"])); pr.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        pr.drawText(L, top, cw, 18, Qt.AlignmentFlag.AlignLeft, "Sessions")
        pr.setPen(QPen(C["coral"], 2.0)); pr.drawLine(L, top + 18, L + 62, top + 18)
        top += 24
        avg_min = self.sessions.avg_session_minutes
        for s in ac[:self.config.get("max_sessions_shown", 6)]:
            rh = 28
            row_rect = QRectF(L - 4, top - 2, cw + 8, rh + 4)
            self._session_click_rects.append((row_rect, s))
            if s.state == "waiting":
                pr.setBrush(QBrush(QColor(217, 119, 87, 25))); pr.setPen(Qt.PenStyle.NoPen)
                pr.drawRoundedRect(QRectF(L - 4, top - 2, cw + 8, rh + 4), 6, 6)
            dc = s.tint if s.state == "working" else STATUS_COLORS.get(s.state, C["text_lo"])
            pr.setBrush(QBrush(dc)); pr.setPen(Qt.PenStyle.NoPen)
            pr.drawEllipse(QRectF(L + 1, top + rh / 2 - 4, 8, 8))
            pr.setPen(QPen(C["text_hi"])); pr.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            nm = s.project_name; nm = nm[:28] + "..." if len(nm) > 30 else nm
            pr.drawText(L + 16, top, int(cw * 0.55), rh, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, nm)
            pr.setPen(QPen(C["coral"] if s.state == "waiting" else C["text_lo"]))
            pr.setFont(QFont("Segoe UI", 9))
            if s.state == "waiting": st = "Needs input!"
            elif self.config.get("session_estimate_enabled") and avg_min > 0 and s.state == "working":
                remaining = max(0, avg_min - s.age_minutes)
                st = f"{s.state} · {s.age_str} · ~{remaining}m left" if remaining > 0 else f"{s.state} · {s.age_str}"
            else: st = f"{s.state}  ·  {s.age_str}"
            pr.drawText(int(L + cw * 0.55), top, int(cw * 0.45), rh, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, st)
            top += rh
            # Context bar
            ctx_pct = min(1.0, s.session_tokens / max(1, s.context_limit))
            bar_h = 4
            pr.setBrush(QBrush(C["card_bg"])); pr.setPen(Qt.PenStyle.NoPen)
            pr.drawRoundedRect(QRectF(L + 16, top, cw - 16, bar_h), 2, 2)
            if ctx_pct > 0:
                bc = C["red"] if ctx_pct > 0.95 else C["coral"] if ctx_pct > 0.80 else C["amber"] if ctx_pct > 0.50 else C["green"]
                pr.setBrush(QBrush(bc))
                pr.drawRoundedRect(QRectF(L + 16, top, max(bar_h, (cw - 16) * ctx_pct), bar_h), 2, 2)
            pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Segoe UI", 7))
            ctx_text = f"~{s.session_tokens // 1000}k / {s.context_limit // 1000}k"
            txt_h = 12
            pr.drawText(int(L + 16), int(top + bar_h + 1), int(cw - 16), txt_h, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, ctx_text)
            top += bar_h + txt_h + 2
        if not ac:
            pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Segoe UI", 9))
            pr.drawText(L, top, cw, 20, Qt.AlignmentFlag.AlignLeft, "No active sessions"); top += 24
        top += 4; pr.setPen(QPen(C["divider"])); pr.drawLine(L, top, R, top); top += 10

        # ── TASKS with coral header ──
        if self.todo_manager:
            all_todos = self.todo_manager.get_all_todos()
            if all_todos:
                done = sum(1 for td_item in all_todos if td_item["status"] == "completed")
                pr.setPen(QPen(C["coral"])); pr.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
                pr.drawText(L, top, cw // 2, 18, Qt.AlignmentFlag.AlignLeft, "Tasks")
                pr.setPen(QPen(C["coral"], 2.0)); pr.drawLine(L, top + 18, L + 40, top + 18)
                pr.setPen(QPen(C["coral_light"])); pr.setFont(QFont("Segoe UI", 9))
                pr.drawText(L + cw // 2, top, cw // 2, 18, Qt.AlignmentFlag.AlignRight, f"{done}/{len(all_todos)} done")
                top += 24
                todo_colors = {"pending": C["amber"], "in_progress": C["coral"], "completed": C["green"]}
                for item in all_todos[:4]:
                    rh = 20; tc = todo_colors.get(item["status"], C["text_lo"])
                    pr.setBrush(QBrush(tc)); pr.setPen(Qt.PenStyle.NoPen)
                    pr.drawEllipse(QRectF(L + 1, top + rh / 2 - 3, 6, 6))
                    pr.setPen(QPen(C["text_hi"])); pr.setFont(QFont("Segoe UI", 9))
                    txt = item["text"]; txt = txt[:55] + "..." if len(txt) > 57 else txt
                    pr.drawText(L + 14, top, cw - 14, rh, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, txt)
                    top += rh + 2
                top += 4; pr.setPen(QPen(C["divider"])); pr.drawLine(L, top, R, top); top += 10

        # ── USAGE with coral stat cards ──
        sub_mode = self.config.get("subscription_mode", "max")
        pr.setPen(QPen(C["coral"])); pr.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        pr.drawText(L, top, cw, 18, Qt.AlignmentFlag.AlignLeft, "Usage")
        pr.setPen(QPen(C["coral"], 2.0)); pr.drawLine(L, top + 18, L + 44, top + 18)
        # Subscription mode pill
        mode_text = "Subscription" if sub_mode == "max" else "API Tokens"
        pr.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold)); fm = pr.fontMetrics()
        mp_w = fm.horizontalAdvance(mode_text) + 12
        mp_c = C["green"] if sub_mode == "max" else C["amber"]
        pr.setBrush(QBrush(QColor(mp_c.red(), mp_c.green(), mp_c.blue(), 30)))
        pr.setPen(QPen(mp_c, 0.8))
        pr.drawRoundedRect(QRectF(L + 50, top + 2, mp_w, 16), 8, 8)
        pr.setPen(QPen(mp_c)); pr.drawText(int(L + 50), int(top + 2), int(mp_w), 16, Qt.AlignmentFlag.AlignCenter, mode_text)
        top += 26

        td = self._cached_period_data; mo = self._cached_month; avg = self._cached_avg
        period_label = self._cached_period_label

        tc_today = td.get("tool_calls", 0); pr_today = td.get("prompts", 0)

        # ── Coral-bordered stat cards (3 across) — subscription-aware ──
        card_gap = 8; card_w = (cw - card_gap * 2) // 3; card_h = 52; card_r = 8
        if sub_mode == "max":
            # Max Plan: show sessions count instead of est. cost
            sess_count = self.sessions.total_active
            stats = [
                (str(tc_today), f"tools {period_label}", C["coral"]),
                (str(pr_today), "prompts", C["coral_light"]),
                (str(sess_count), "sessions", C["green"]),
            ]
        else:
            # API mode: show est. cost
            cost_today = td.get("est_cost", 0.0)
            stats = [
                (str(tc_today), f"tools {period_label}", C["coral"]),
                (str(pr_today), "prompts", C["coral_light"]),
                (f"${cost_today:.2f}" if cost_today < 100 else f"${cost_today:.0f}", "est. cost", C["green"]),
            ]
        for i, (val, label, color) in enumerate(stats):
            cx = L + i * (card_w + card_gap)
            pr.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 12)))
            pr.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 70), 1.0))
            pr.drawRoundedRect(QRectF(cx, top, card_w, card_h), card_r, card_r)
            pr.setPen(QPen(color)); pr.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
            pr.drawText(int(cx + 8), int(top + 2), int(card_w - 16), 28, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, val)
            pr.setPen(QPen(C["text_md"])); pr.setFont(QFont("Segoe UI", 8))
            pr.drawText(int(cx + 8), int(top + 32), int(card_w - 16), 14, Qt.AlignmentFlag.AlignLeft, label)
        top += card_h + 8

        # Token summary
        est_tok = td.get("est_tokens", 0)
        tok_str = f"~{est_tok / 1_000_000:.1f}M" if est_tok > 1_000_000 else f"~{est_tok / 1000:.0f}k" if est_tok > 1000 else f"~{est_tok}"
        pr.setPen(QPen(C["text_md"])); pr.setFont(QFont("Segoe UI", 9))
        pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft, f"{tok_str} est. tokens {period_label}  ·  {td.get('sessions', 0)} sessions")
        top += 18

        # Monthly bar
        mo_calls = mo.get("tool_calls", 0); mo_cap = max(1000, mo_calls + 500)
        top = self._bar(pr, L, top, cw, f"This Month — {datetime.now().strftime('%B')}", min(1.0, mo_calls / mo_cap), f"{mo_calls:,} calls") + 4

        # Monthly details
        mo_tok = mo.get("est_tokens", 0)
        mo_tok_str = f"~{mo_tok / 1_000_000:.1f}M" if mo_tok > 1_000_000 else f"~{mo_tok / 1000:.0f}k" if mo_tok > 1000 else f"~{mo_tok}"
        pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Segoe UI", 8))
        if sub_mode == "api":
            mo_cost = mo.get("est_cost", 0.0); mo_cost_str = f"${mo_cost:.2f}" if mo_cost < 100 else f"${mo_cost:.0f}"
            pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft, f"{mo_tok_str} tokens  ·  {mo_cost_str}  ·  {mo.get('days_active', 0)} days  ·  avg {avg}/day")
        else:
            pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft, f"{mo_tok_str} tokens  ·  {mo.get('days_active', 0)} days active  ·  avg {avg}/day")
        top += 16

        # ── SPARKLINE ──
        if self.sparkline and self.config.get("sparkline_enabled"):
            data = self.sparkline.get_data(); mx = max(data) if data else 1
            if mx > 0:
                sl_h = 16; bw = max(1.5, (cw - 4) / len(data))
                for i, v in enumerate(data):
                    if v > 0:
                        bh = max(1, (v / mx) * sl_h)
                        pr.setBrush(QBrush(QColor(C["coral"].red(), C["coral"].green(), C["coral"].blue(), 80 + int(v/mx*120))))
                        pr.setPen(Qt.PenStyle.NoPen)
                        pr.drawRoundedRect(QRectF(L + i * bw, top + sl_h - bh, bw - 0.8, bh), 1, 1)
                pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Segoe UI", 7))
                pr.drawText(L, int(top + sl_h + 1), cw, 10, Qt.AlignmentFlag.AlignRight, "activity (30 min)")
                top += sl_h + 12

        # ── STREAKS ──
        if self.streaks and self.config.get("streaks_enabled"):
            streak = self.streaks.current_streak
            top_day, top_count = self.streaks.top_day_this_week
            pr.setPen(QPen(C["coral"])); pr.setFont(QFont("Segoe UI", 9))
            streak_text = f"  {streak}-day streak" if streak > 1 else "Start your streak today!"
            extra = f"  ·  Top: {top_day} ({top_count})" if top_day else ""
            pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft, streak_text + extra)
            top += 16

        # ── SYSTEM RESOURCES ──
        if self.config.get("system_resources_enabled"):
            ram = SystemMonitor.get_ram(); cpu = SystemMonitor.get_cpu()
            pr.setPen(QPen(C["text_md"])); pr.setFont(QFont("Segoe UI", 8))
            pr.drawText(L, top, cw, 12, Qt.AlignmentFlag.AlignLeft, f"CPU {cpu:.0f}%  ·  RAM {ram['used_gb']}GB/{ram['total_gb']}GB ({ram['pct']}%)")
            top += 14
            half = (cw - 8) // 2
            for i, (lbl, pct, clr) in enumerate([("CPU", cpu / 100, C["coral"]), ("RAM", ram["pct"] / 100, C["amber"])]):
                bx = L + i * (half + 8); bw_r = half; bh_r = 4
                pr.setBrush(QBrush(C["card_bg"])); pr.setPen(Qt.PenStyle.NoPen)
                pr.drawRoundedRect(QRectF(bx, top, bw_r, bh_r), 2, 2)
                if pct > 0:
                    pr.setBrush(QBrush(C["red"] if pct > 0.9 else clr))
                    pr.drawRoundedRect(QRectF(bx, top, max(bh_r, bw_r * min(1, pct)), bh_r), 2, 2)
            top += 8

        # ── API KEYS section — shown when keys are configured ──
        HEALTH_COLORS = {"healthy": C["green"], "warm": C["amber"], "throttled": C["red"], "error": QColor(120, 110, 105)}
        MAX_KEYS_SHOWN = 5
        if self._usage_keys:
            pr.setPen(QPen(C["coral"])); pr.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            pr.drawText(L, top, cw, 16, Qt.AlignmentFlag.AlignLeft, "API Keys")
            pr.setPen(QPen(C["coral"], 1.5)); pr.drawLine(L, top + 15, L + 58, top + 15)
            top += 20
            for kd in self._usage_keys[:MAX_KEYS_SHOWN]:
                row_h = 22
                hc = HEALTH_COLORS.get(kd.get("health", "error"), HEALTH_COLORS["error"])
                # Health dot
                pr.setBrush(QBrush(hc)); pr.setPen(Qt.PenStyle.NoPen)
                pr.drawEllipse(QRectF(L + 1, top + row_h / 2 - 3.5, 7, 7))
                # Label
                pr.setPen(QPen(C["text_hi"])); pr.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
                lbl = kd.get("label", "Key")
                lbl = lbl[:14] + ".." if len(lbl) > 15 else lbl
                pr.drawText(int(L + 14), int(top), int(cw * 0.28), row_h,
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, lbl)
                # Redacted key
                pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Consolas", 8))
                pr.drawText(int(L + cw * 0.28 + 4), int(top), int(cw * 0.32), row_h,
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, kd.get("key_redacted", ""))
                # Usage bar or status text
                bar_x = int(L + cw * 0.63); bar_w = int(cw * 0.37 - 4)
                err = kd.get("error")
                if err:
                    pr.setPen(QPen(hc)); pr.setFont(QFont("Segoe UI", 7))
                    err_short = err[:22] + ".." if len(err) > 24 else err
                    pr.drawText(bar_x, int(top), bar_w, row_h,
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, err_short)
                else:
                    # Mini usage bar
                    rpm_l = kd.get("rpm_limit", 0); rpm_u = kd.get("rpm_used", 0)
                    pct = (rpm_u / max(1, rpm_l)) if rpm_l else 0
                    bar_y = int(top + row_h / 2 - 3); bh = 6; bw = bar_w - 36
                    pr.setBrush(QBrush(C["card_bg"])); pr.setPen(Qt.PenStyle.NoPen)
                    pr.drawRoundedRect(QRectF(bar_x, bar_y, bw, bh), 3, 3)
                    if pct > 0:
                        pr.setBrush(QBrush(hc))
                        pr.drawRoundedRect(QRectF(bar_x, bar_y, max(bh, bw * min(1, pct)), bh), 3, 3)
                    pr.setPen(QPen(C["text_md"])); pr.setFont(QFont("Segoe UI", 7))
                    pr.drawText(bar_x + bw + 4, int(top), 32, row_h,
                                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                                f"{int(pct * 100)}%")
                top += row_h + 2
            if len(self._usage_keys) > MAX_KEYS_SHOWN:
                extra = len(self._usage_keys) - MAX_KEYS_SHOWN
                pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Segoe UI", 8))
                pr.drawText(L + 14, int(top), int(cw - 14), 16,
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                            f"+ {extra} more key{'s' if extra > 1 else ''}")
                top += 18
        elif sub_mode == "api":
            pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Segoe UI", 8))
            pr.drawText(L, top, cw, 14, Qt.AlignmentFlag.AlignLeft, "Add API keys in Settings to monitor usage"); top += 14

        top += 4; pr.setPen(QPen(C["divider"])); pr.drawLine(L, top, R, top); top += 8

        # ── NOTIFICATION HISTORY ──
        if self.notif_history and self.config.get("notification_history_enabled"):
            recent = self.notif_history.get_recent(4)
            if recent:
                pr.setPen(QPen(C["coral"])); pr.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
                pr.drawText(L, top, cw, 16, Qt.AlignmentFlag.AlignLeft, "Notifications")
                pr.setPen(QPen(C["coral"], 1.5)); pr.drawLine(L, top + 15, L + 90, top + 15); top += 20
                ntype_colors = {"completion": C["green"], "attention": C["coral"], "budget": C["amber"]}
                for n in recent:
                    rh_n = 18; nc = ntype_colors.get(n["type"], C["text_lo"])
                    pr.setBrush(QBrush(nc)); pr.setPen(Qt.PenStyle.NoPen)
                    pr.drawEllipse(QRectF(L + 1, top + rh_n / 2 - 2.5, 5, 5))
                    pr.setPen(QPen(C["text_hi"])); pr.setFont(QFont("Segoe UI", 8))
                    pr.drawText(int(L + 12), int(top), int(cw - 50), rh_n, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, n["message"][:50])
                    pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Segoe UI", 7))
                    pr.drawText(int(L + cw - 36), int(top), 36, rh_n, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, n["time"])
                    top += rh_n + 1
                top += 4; pr.setPen(QPen(C["divider"])); pr.drawLine(L, top, R, top); top += 8

        # ── RECENT ACTIVITY — scrollable ──
        pr.setPen(QPen(C["coral"])); pr.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        pr.drawText(L, top, cw, 18, Qt.AlignmentFlag.AlignLeft, "Recent Activity")
        pr.setPen(QPen(C["coral"], 2.0)); pr.drawLine(L, top + 18, L + 112, top + 18)
        top += 24

        footer_h = 36  # reserved for footer
        avail = h - top - footer_h
        rh = 22  # row height per activity item
        tasks = self.sessions.get_all_tasks(20)  # get more for scrolling

        if tasks:
            total_content = len(tasks) * (rh + 1)
            self._max_scroll = max(0, total_content - avail)
            self._scroll_offset = max(0, min(self._scroll_offset, self._max_scroll))

            # Clip to activity area
            pr.save()
            pr.setClipRect(QRectF(L - 2, top, cw + 4, avail))

            item_y = top - self._scroll_offset
            for tk in tasks:
                # Skip items fully above visible area
                if item_y + rh < top:
                    item_y += rh + 1
                    continue
                # Stop if below visible area
                if item_y > top + avail:
                    break
                sc = C["green"] if tk.get("status") == "completed" else C["coral"]
                pr.setBrush(QBrush(sc)); pr.setPen(Qt.PenStyle.NoPen)
                pr.drawEllipse(QRectF(L + 1, item_y + rh / 2 - 3, 6, 6))
                pr.setPen(QPen(C["text_hi"])); pr.setFont(QFont("Segoe UI", 9))
                max_chars = max(30, int((cw - 70) / 6.5))
                d = f"{tk.get('project', '')}: {tk.get('summary', '')}"
                d = d[:max_chars] + "..." if len(d) > max_chars + 2 else d
                pr.drawText(int(L + 14), int(item_y), int(cw - 64), rh,
                            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, d)
                pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Segoe UI", 8))
                pr.drawText(int(L + cw - 44), int(item_y), 44, rh,
                            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, tk.get("time", ""))
                item_y += rh + 1

            pr.restore()

            # Scroll indicator (thin bar on right if scrollable)
            if self._max_scroll > 0:
                track_h = avail - 4
                thumb_h = max(12, int(track_h * avail / total_content))
                thumb_y = top + 2 + int((track_h - thumb_h) * self._scroll_offset / max(1, self._max_scroll))
                pr.setBrush(QBrush(QColor(217, 119, 87, 60))); pr.setPen(Qt.PenStyle.NoPen)
                pr.drawRoundedRect(QRectF(R - 3, thumb_y, 3, thumb_h), 1.5, 1.5)
        else:
            self._max_scroll = 0
            pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Segoe UI", 9))
            pr.drawText(L, top, cw, 18, Qt.AlignmentFlag.AlignLeft, "No recent activity")

        # ── FOOTER ──
        # Export button
        exp_w = 50; exp_h = 16; exp_x = R - exp_w; exp_y = h - 32
        self._export_btn_rect = QRectF(exp_x, exp_y, exp_w, exp_h)
        pr.setBrush(QBrush(QColor(C["coral"].red(), C["coral"].green(), C["coral"].blue(), 20))); pr.setPen(QPen(C["coral"], 0.8))
        pr.drawRoundedRect(self._export_btn_rect, 4, 4)
        pr.setPen(QPen(C["coral"])); pr.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        pr.drawText(int(exp_x), int(exp_y), int(exp_w), int(exp_h), Qt.AlignmentFlag.AlignCenter, "Export")
        pr.setPen(QPen(C["coral"])); pr.setFont(QFont("Segoe UI", 8))
        pin = "Pinned" if self._pinned else "Click = expand  ·  Hover = peek  ·  DblClick = new session"
        pr.drawText(L, h - 32, cw - exp_w - 8, 14, Qt.AlignmentFlag.AlignLeft, pin)
        pr.setPen(QPen(C["text_lo"])); pr.setFont(QFont("Segoe UI", 8))
        pr.drawText(L, h - 18, cw, 14, Qt.AlignmentFlag.AlignCenter, f"v{__version__}  ·  Running {self.uptime}")
        pr.restore()

    def _bar(self, p, x, y, w, label, val, txt):
        bh, br = 14, 7
        p.setPen(QPen(C["text_md"])); p.setFont(QFont("Segoe UI", 9))
        p.drawText(x, y, w, 16, Qt.AlignmentFlag.AlignLeft, label); y += 17
        p.setBrush(QBrush(C["card_bg"])); p.setPen(QPen(C["divider"], 0.5))
        p.drawRoundedRect(QRectF(x, y, w, bh), br, br)
        v = max(0, min(1, val))
        if v > 0:
            fw = max(bh, w * v); g = QLinearGradient(x, y, x + fw, y)
            g.setColorAt(0, C["coral"]); g.setColorAt(1, C["red"] if v > 0.8 else C["coral_light"])
            p.setBrush(QBrush(g)); p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(x + 1, y + 1, fw - 2, bh - 2), br - 1, br - 1)
        p.setPen(QPen(C["text_hi"])); p.setFont(QFont("Segoe UI", 8))
        p.drawText(int(x), int(y), int(w - 4), int(bh), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, txt)
        return y + bh

def make_tray(app, notch, config, sm=None, do_snapshot=None):
    pix=QPixmap(32,32); pix.fill(QColor(0,0,0,0)); p=QPainter(pix); draw_clawd(p,3,2,2.5,emotion="neutral"); p.end()
    tray=QSystemTrayIcon(QIcon(pix),app)
    menu=QMenu()
    menu.setStyleSheet("QMenu{background:#121216;color:#f0ece8;border:1px solid #2c2c34;padding:4px;font-size:12px;}QMenu::item:selected{background:#d97757;}")
    menu.addAction("Show / Hide").triggered.connect(lambda: notch.hide() if notch.isVisible() else notch.force_show())
    dnd_action = menu.addAction("Do Not Disturb: OFF")
    def _toggle_dnd():
        cur = config.get("dnd_mode", False); config.set("dnd_mode", not cur)
        dnd_action.setText(f"Do Not Disturb: {'ON' if not cur else 'OFF'}"); notch.update()
    dnd_action.triggered.connect(_toggle_dnd)
    def _export():
        fmt = config.get("export_format", "markdown")
        path = export_usage_report(notch.tracker, config, fmt)
        if HAS_TOAST:
            threading.Thread(target=lambda: toast_notify.notify(title="Claude Notch", message=f"Report: {Path(path).name}", app_name="Claude Notch", timeout=5), daemon=True).start()
    menu.addAction("Export Usage Report").triggered.connect(_export)
    def _open_settings():
        # Non-modal dialog so notch stays interactive while settings are open
        if hasattr(notch, '_settings_dlg') and notch._settings_dlg and notch._settings_dlg.isVisible():
            notch._settings_dlg.raise_(); notch._settings_dlg.activateWindow(); return
        dlg = SettingsDialog(config)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        dlg.show()
        notch._settings_dlg = dlg  # prevent GC
    menu.addAction("Settings...").triggered.connect(_open_settings)
    if not SettingsDialog._check():
        menu.addAction("Install Hooks").triggered.connect(lambda: install_hooks(config.get("hook_server_port",HOOK_SERVER_PORT)))
    def _r():
        s=QApplication.primaryScreen().geometry(); notch._edge="top"; notch._ori="horizontal"
        notch.setFixedSize(notch.HW,notch.HH); notch.move((s.width()-notch.HW)//2,0); notch._save_pos()
    menu.addAction("Reset Position").triggered.connect(_r)
    snap_menu = QMenu("Git Snapshots", menu)
    snap_menu.setStyleSheet(menu.styleSheet())
    def _refresh_snaps():
        snap_menu.clear()
        # Header explaining what this does
        info = snap_menu.addAction("Save/restore code checkpoints via git refs")
        info.setEnabled(False)
        snap_menu.addSeparator()
        active = sm.get_active_sessions() if sm else []
        if not active:
            a = snap_menu.addAction("No active sessions detected"); a.setEnabled(False)
            return
        pdir = active[0].project_dir
        if not pdir:
            a = snap_menu.addAction("Active session has no project directory"); a.setEnabled(False)
            return
        if not GitCheckpoints.is_git_repo(pdir):
            a = snap_menu.addAction(f"Not a git repo: {Path(pdir).name}"); a.setEnabled(False)
            return
        snap_menu.addAction(f"Create Snapshot — {Path(pdir).name} (Ctrl+Shift+S)").triggered.connect(
            lambda: do_snapshot() if do_snapshot else None)
        snap_menu.addSeparator()
        snaps = GitCheckpoints.list_snapshots(pdir)
        if not snaps:
            a = snap_menu.addAction("No snapshots yet"); a.setEnabled(False)
        else:
            for s in snaps[:8]:
                a = snap_menu.addAction(f"{s['date']}  {s['hash']}")
                commit = s["hash"]
                d = pdir
                a.triggered.connect(lambda checked, c=commit, p=d: _restore_snap(c, p))
        snap_menu.addSeparator()
        snap_menu.addAction("Clear All Snapshots").triggered.connect(
            lambda: GitCheckpoints.clear(pdir) if pdir else None)
    def _restore_snap(commit, pdir):
        from PyQt6.QtWidgets import QMessageBox
        r = QMessageBox.question(None, "Restore Snapshot",
            f"Restore snapshot {commit}?\nThis overwrites working directory files.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            GitCheckpoints.restore(pdir, commit)
    snap_menu.aboutToShow.connect(_refresh_snaps)
    menu.addMenu(snap_menu)
    menu.addSeparator(); menu.addAction("Quit").triggered.connect(app.quit)
    tray.setContextMenu(menu); tray.setToolTip("Claude Notch — @ReelDad")
    tray.activated.connect(lambda reason: notch.force_show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    return tray

def main():
    app=QApplication(sys.argv); app.setQuitOnLastWindowClosed(False)
    if not acquire_lock(): print("Another instance running."); sys.exit(1)
    config=ConfigManager(); tracker=UsageTracker(config)
    apply_theme(config.get("color_theme", "coral"))
    emotion=EmotionEngine(); todos=TodoManager()
    sparkline=SparklineTracker(); notif_history=NotificationHistory()
    streaks=StreakTracker(tracker)
    sm=SessionManager(tracker, emotion, todos, sparkline, config)
    nm=NotificationManager(config, notif_history)
    sm.task_completed.connect(nm.notify_task_complete); sm.needs_attention.connect(nm.notify_needs_attention)
    sm.budget_alert.connect(nm.notify_budget_alert)
    port=config.get("hook_server_port",HOOK_SERVER_PORT)
    hs=HookServer(port); hs.event_received.connect(sm.handle_event); hs.start()
    notch=ClaudeNotch(sm, config, tracker, emotion, todos, sparkline, notif_history, streaks); notch.show()
    up=UsagePoller(config); up.usage_updated.connect(notch.update_usage); up.start()
    def do_snapshot():
        active = sm.get_active_sessions()
        if active and active[0].project_dir:
            h = GitCheckpoints.create(active[0].project_dir)
            if h and HAS_TOAST:
                threading.Thread(target=lambda: toast_notify.notify(
                    title="Claude Notch", message=f"Checkpoint saved for {active[0].project_name}",
                    app_name="Claude Notch", timeout=3), daemon=True).start()

    # Restore persisted sessions from previous run
    sm.restore_state()
    # Scan for running Claude processes immediately
    sm.scan_processes()
    # Periodic process scan every 15 seconds
    proc_timer = QTimer()
    proc_timer.setInterval(15000)
    proc_timer.timeout.connect(sm.scan_processes)
    proc_timer.start()

    tray = make_tray(app, notch, config, sm, do_snapshot)
    if HAS_KEYBOARD:
        try:
            kb_module.add_hotkey("ctrl+shift+c", lambda: notch.hide() if notch.isVisible() else notch.force_show())
            kb_module.add_hotkey("ctrl+shift+e", lambda: notch.toggle_expand())
            kb_module.add_hotkey("ctrl+shift+d", lambda: notch._toggle_dnd())
            print("[Hotkey] Ctrl+Shift+C = show/hide, E = expand, D = DND")
        except: pass
    if HAS_KEYBOARD:
        try:
            kb_module.add_hotkey("ctrl+shift+s", do_snapshot)
            print("[Hotkey] Ctrl+Shift+S = git snapshot")
        except Exception:
            pass
    print(f"╔══════════════════════════════════════╗\n║   Claude Notch v{__version__} on :{port}    ║\n║   @ReelDad                          ║\n╚══════════════════════════════════════╝")
    def cleanup():
        proc_timer.stop(); notch._save_timer.stop(); notch._sys_timer.stop()
        up.stop(); hs.stop(); up.wait(2000); hs.wait(2000)
        sm.save_state(); tracker.flush()
        config.set("was_expanded", notch._expanded, save_now=False)
        config.flush(); release_lock()
    app.aboutToQuit.connect(cleanup)
    sys.exit(app.exec())

if __name__=="__main__": main()
