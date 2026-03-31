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

from claude_notch.config import CONFIG_DIR, HOOK_SERVER_PORT, _atomic_write


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


def install_hooks(port=HOOK_SERVER_PORT):
    """Install Claude Code hooks and register them in settings.json.

    BUG FIX #9: The final write to ~/.claude/settings.json now uses
    atomic write (tempfile + os.replace) instead of plain open("w").
    """
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
