"""
claude_notch.hooks — Hook server & installer
==============================================
HookServer listens on a local TCP port for Claude Code hook events.
install_hooks() writes the PowerShell hook script and registers it
in ~/.claude/settings.json.

BUG FIX #9: install_hooks now writes settings.json atomically via
tempfile + os.replace instead of plain open("w"), preventing corruption
if the process is interrupted mid-write.
"""

import os
import sys
import json
import socket
import tempfile
import threading
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from claude_notch.config import CONFIG_DIR, HOOK_SERVER_PORT


class HookServer(QThread):
    event_received = pyqtSignal(dict)

    # Valid event types from Claude Code hooks
    VALID_EVENTS = {
        "PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop",
        "Notification", "SessionStart", "SessionEnd", "UserPromptSubmit",
        "SubagentStop",
    }

    def __init__(self, port=HOOK_SERVER_PORT, parent=None):
        super().__init__(parent)
        self.port = port
        self._running = True
        self._max_connections = threading.Semaphore(16)

    def stop(self):
        self._running = False

    def run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", self.port))
        except OSError as e:
            print(f"[HookServer] Port {self.port} in use: {e}")
            srv.close()
            return
        srv.listen(32)
        srv.settimeout(1.0)
        print(f"[HookServer] Listening on localhost:{self.port}")
        while self._running:
            try:
                conn, _ = srv.accept()
                if self._max_connections.acquire(timeout=0.1):
                    threading.Thread(target=self._handle_wrapped, args=(conn,), daemon=True).start()
                else:
                    conn.close()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    print(f"[HookServer] {e}")
        srv.close()

    def _handle_wrapped(self, conn):
        try:
            self._handle(conn)
        finally:
            self._max_connections.release()

    def _handle(self, conn):
        try:
            data = b""
            conn.settimeout(2.0)
            while True:
                c = conn.recv(4096)
                if not c:
                    break
                data += c
                if b"\n" in data or len(data) > 1048576:
                    break
            if data:
                t = data.decode("utf-8", errors="ignore").strip()
                if t.startswith(("POST", "GET")):
                    for sep in ("\r\n\r\n", "\n\n"):
                        p = t.split(sep, 1)
                        if len(p) > 1:
                            t = p[1]
                            break
                try:
                    parsed = json.loads(t)
                    if not isinstance(parsed, dict):
                        raise ValueError("Expected JSON object")
                    if parsed.get("event") not in self.VALID_EVENTS:
                        raise ValueError(f"Unknown event: {parsed.get('event')}")
                    if not isinstance(parsed.get("session_id", ""), str) or not parsed.get("session_id"):
                        raise ValueError("Missing or invalid session_id")
                    self.event_received.emit(parsed)
                    try:
                        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
                    except (socket.timeout, OSError):
                        pass
                except (json.JSONDecodeError, ValueError):
                    try:
                        conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\nBAD")
                    except (socket.timeout, OSError):
                        pass
        except Exception as e:
            if str(e):
                print(f"[HookServer] Connection error: {e}", file=sys.stderr)
        finally:
            conn.close()


def install_hooks(port=HOOK_SERVER_PORT):
    """Install Claude Code hooks and register them in settings.json.

    BUG FIX #9: The final write to ~/.claude/settings.json now uses
    atomic write (tempfile + os.replace) instead of plain open("w").

    The PowerShell hook script is loaded from a .ps1.template file
    (lintable, testable) rather than an embedded f-string.
    """
    hd = CONFIG_DIR / "hooks"; hd.mkdir(parents=True, exist_ok=True)
    # Load PS1 template from package directory
    template_path = Path(__file__).parent / "claude_notch_hook.ps1.template"
    if not template_path.exists():
        print(f"[Hooks] Template not found: {template_path}", file=sys.stderr)
        return
    ps1_content = template_path.read_text(encoding="utf-8").replace("{{PORT}}", str(port))
    (hd / "claude_notch_hook.ps1").write_text(ps1_content, encoding="utf-8")
    sp = Path.home() / ".claude" / "settings.json"; sp.parent.mkdir(parents=True, exist_ok=True)
    settings = {}
    if sp.exists():
        try:
            with open(sp) as f: settings = json.load(f)
        except Exception as e:
            print(f"[Hooks] Failed to read settings: {e}", file=sys.stderr)
    base_cmd = f'powershell.exe -ExecutionPolicy Bypass -File "{hd / "claude_notch_hook.ps1"}"'
    if "hooks" not in settings: settings["hooks"] = {}
    def _is_our_hook(h):
        if isinstance(h, dict):
            for h_entry in h.get("hooks", []):
                if isinstance(h_entry, dict) and "claude_notch_hook" in h_entry.get("command", ""):
                    return True
        return False

    for ev in ["PreToolUse","PostToolUse","PostToolUseFailure","Stop","Notification","SessionStart","SessionEnd","UserPromptSubmit","SubagentStop"]:
        cmd = f'{base_cmd} -EventType {ev}'
        hook = {"type": "command", "command": cmd, "timeout": 3000}
        if ev not in settings["hooks"]: settings["hooks"][ev] = []
        settings["hooks"][ev] = [h for h in settings["hooks"][ev] if not _is_our_hook(h)]
        settings["hooks"][ev].append({"hooks": [hook]})
    # BUG FIX #9: Atomic write — use tempfile + os.replace instead of plain open("w")
    try:
        fd, tmp = tempfile.mkstemp(dir=sp.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(settings, f, indent=2)
            os.replace(tmp, sp)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        print(f"[Hooks] Failed to write settings: {e}", file=sys.stderr)
    print(f"[Hooks] Installed at {hd}")
