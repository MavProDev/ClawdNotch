"""
claude_notch.system_monitor -- System & process monitoring
==========================================================
Extracted from claude_notch_v2_backup.py.

Provides:
    - SystemMonitor          CPU / RAM stats via Win32 APIs
    - _is_terminal_focused   Check if foreground window is a terminal/IDE
    - _find_claude_windows   Enumerate visible windows running Claude Code
    - _find_claude_processes  Find node.js Claude Code CLI processes
    - _focus_window_by_pid   Bring a window to foreground by PID
    - acquire_lock / release_lock   Single-instance guard via lock file
    - set_auto_start         Toggle Windows auto-start registry entry
"""

import ctypes
import ctypes.wintypes
import subprocess
import os
import sys
import time
import threading

from claude_notch.config import CONFIG_DIR, LOCK_FILE

# ---------------------------------------------------------------------------
# Shared ctypes callback type for EnumWindows (used by multiple functions)
# ---------------------------------------------------------------------------

WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_bool,
    ctypes.wintypes.HWND,
    ctypes.wintypes.LPARAM,
)

# ---------------------------------------------------------------------------
# Conditional imports
# ---------------------------------------------------------------------------

try:
    import winreg
    HAS_WINREG = True
except ImportError:
    HAS_WINREG = False


# ---------------------------------------------------------------------------
# BUG FIX #13 -- cache for _find_claude_processes
# Prevents CPU spikes from spawning PowerShell every 15 seconds.
# ---------------------------------------------------------------------------
_cached_claude_processes: list = []
_cached_claude_processes_ts: float = 0.0
_PROCESS_CACHE_TTL: float = 10.0  # seconds
_process_cache_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
# Single-instance lock
# ═══════════════════════════════════════════════════════════════════════════════

def acquire_lock():
    """Acquire a file-based single-instance lock.

    BUG FIX #8 (documented): This implementation has a known TOCTOU
    (time-of-check-to-time-of-use) race condition.  Between the moment we
    check whether the lock file exists / the old PID is alive and the
    moment we write our own PID, another process could do the same check
    and also conclude the lock is free.  In practice this is unlikely
    because the window is very small and the overlay is typically launched
    by a single user action, but a fully robust solution would use an OS
    mutex (e.g. CreateMutex on Windows) or advisory file locking.
    """
    try:
        if LOCK_FILE.exists():
            try:
                old_pid = int(LOCK_FILE.read_text().strip())
                h = ctypes.windll.kernel32.OpenProcess(0x1000, False, old_pid)
                if h:
                    ctypes.windll.kernel32.CloseHandle(h)
                    return False
            except Exception:
                pass
        LOCK_FILE.write_text(str(os.getpid()))
        return True
    except Exception:
        return True


def release_lock():
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Auto-start (registry)
# ═══════════════════════════════════════════════════════════════════════════════

def set_auto_start(enabled):
    if not HAS_WINREG:
        return
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
        if enabled:
            exe = sys.executable.replace("python.exe", "pythonw.exe")
            if not os.path.exists(exe):
                exe = sys.executable
            launcher = CONFIG_DIR / "launcher.pyw"
            target = str(launcher) if launcher.exists() else os.path.abspath(__file__)
            winreg.SetValueEx(
                key, "ClaudeNotch", 0, winreg.REG_SZ,
                f'"{exe}" "{target}"',
            )
        else:
            try:
                winreg.DeleteValue(key, "ClaudeNotch")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        print(f"[AutoStart] {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Terminal / window helpers
# ═══════════════════════════════════════════════════════════════════════════════

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


def _is_claude_desktop_app(exe_path: str) -> bool:
    """Distinguish Claude desktop app from Claude Code CLI by exe path.

    Desktop app lives in: C:\\Program Files\\WindowsApps\\Claude_*\\app\\Claude.exe
    CLI lives in:         AppData\\Local\\Microsoft\\WinGet\\...\\claude.exe
                          or AppData\\Roaming\\npm\\claude.exe, etc.
    """
    lower = exe_path.lower()
    return "windowsapps\\claude_" in lower or "\\app\\claude.exe" in lower


def _find_claude_windows() -> list:
    """Find visible terminal windows that are actively running Claude Code CLI.

    Claude Code runs either:
      1. Inside terminals (Windows Terminal, cmd, PowerShell, etc.)
      2. As its own claude.exe native binary (WinGet/npm install)

    We look for windows whose title suggests Claude Code is running.
    We EXCLUDE: the Claude desktop app, browser tabs, and our own overlay.
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
                # Get the process name to verify it's a terminal or CLI, not the desktop app
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                pid_val = pid.value
                # Check process exe path
                h_proc = ctypes.windll.kernel32.OpenProcess(0x0410, False, pid_val)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
                if h_proc:
                    exe_buf = ctypes.create_unicode_buffer(260)
                    size = ctypes.c_ulong(260)
                    if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_proc, 0, exe_buf, ctypes.byref(size)):
                        exe_path = exe_buf.value
                        exe_name = exe_path.split("\\")[-1].lower()
                        ctypes.windll.kernel32.CloseHandle(h_proc)
                        # Reject the Claude desktop app (Electron)
                        if exe_name == "claude.exe" and _is_claude_desktop_app(exe_path):
                            return True
                        # Accept: terminal processes OR claude.exe CLI
                        if exe_name not in TERMINAL_EXES and exe_name != "claude.exe":
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
    """Find running Claude Code CLI processes using PowerShell.

    Detects both:
      1. node.exe running Claude Code (legacy npm installs)
      2. claude.exe CLI binary (WinGet / native installs)

    Excludes the Claude desktop app (Electron) by filtering out processes
    whose exe path contains 'WindowsApps\\Claude_'.

    BUG FIX #13: Results are cached for 10 seconds to avoid repeated
    PowerShell spawns that cause CPU spikes.

    Returns list of dicts: {'name': 'claude-code', 'pid': int, 'cwd': str}
    where cwd is the working directory extracted from the command line (best effort).
    """
    global _cached_claude_processes, _cached_claude_processes_ts

    now = time.monotonic()
    with _process_cache_lock:
        if now - _cached_claude_processes_ts < _PROCESS_CACHE_TTL:
            return list(_cached_claude_processes)

    results = []
    try:
        # Query 1: node.exe running Claude Code (legacy)
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"name='node.exe'\" | "
             "Where-Object { $_.CommandLine -match 'claude' -and ($_.CommandLine -match 'anthropic' -or $_.CommandLine -match 'claude-code') } | "
             "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"],
            capture_output=True, text=True, timeout=8,
            creationflags=0x08000000,
        )
        for line in r.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if '|' in line:
                pid_str, cmdline = line.split('|', 1)
            else:
                pid_str, cmdline = line, ""
            pid_str = pid_str.strip()
            if pid_str and pid_str.isdigit():
                cwd = _extract_project_from_cmdline(cmdline)
                results.append({'name': 'claude-code', 'pid': int(pid_str), 'cwd': cwd})
    except Exception as e:
        print(f"[ProcessScan] PowerShell node.exe scan failed: {e}", file=sys.stderr)

    try:
        # Query 2: claude.exe CLI binary (WinGet / native installs)
        # Exclude desktop app (WindowsApps) and child processes (--type=renderer etc.)
        r2 = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"name='claude.exe'\" | "
             "Where-Object { $_.ExecutablePath -notmatch 'WindowsApps' -and "
             "$_.CommandLine -notmatch '--type=' } | "
             "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"],
            capture_output=True, text=True, timeout=8,
            creationflags=0x08000000,
        )
        seen_pids = {r['pid'] for r in results}
        for line in r2.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if '|' in line:
                pid_str, cmdline = line.split('|', 1)
            else:
                pid_str, cmdline = line, ""
            pid_str = pid_str.strip()
            if pid_str and pid_str.isdigit() and int(pid_str) not in seen_pids:
                cwd = _extract_project_from_cmdline(cmdline)
                results.append({'name': 'claude-code', 'pid': int(pid_str), 'cwd': cwd})
    except Exception as e:
        print(f"[ProcessScan] PowerShell claude.exe scan failed: {e}", file=sys.stderr)

    with _process_cache_lock:
        _cached_claude_processes = list(results)
        _cached_claude_processes_ts = now
    return results


def _extract_project_from_cmdline(cmdline: str) -> str:
    """Best-effort extraction of project directory from Claude Code command line."""
    # Claude Code often has the project dir as the cwd or a --project arg
    # Command lines look like: "node .../@anthropic-ai/claude-code/... --project C:\path"
    # or just: "node .../claude-code/cli.js" with cwd being the project
    import re
    m = re.search(r'--project\s+"?([^"]+)"?', cmdline)
    if m:
        return m.group(1).strip()
    # Try to find a path-like argument after the main script
    m = re.search(r'--cwd\s+"?([^"]+)"?', cmdline)
    if m:
        return m.group(1).strip()
    return ""


def _focus_window_by_pid(pid):
    """Bring the window belonging to a PID to the foreground."""
    try:
        target_hwnd = None

        def callback(hwnd, _):
            nonlocal target_hwnd
            if not ctypes.windll.user32.IsWindowVisible(hwnd):
                return True
            p = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid:
                target_hwnd = hwnd
                return False
            return True
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)
        if target_hwnd:
            ctypes.windll.user32.ShowWindow(target_hwnd, 9)
            ctypes.windll.user32.SetForegroundWindow(target_hwnd)
    except Exception as e:
        print(f"[Focus] {e}", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════════════════
# SystemMonitor -- CPU & RAM via Win32
# ═══════════════════════════════════════════════════════════════════════════════

class SystemMonitor:
    """CPU and RAM usage via Windows APIs."""

    _last_idle = _last_kernel = _last_user = 0
    _cpu_pct = 0.0

    @staticmethod
    def get_ram():
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            total = mem.ullTotalPhys / (1024**3)
            used = (mem.ullTotalPhys - mem.ullAvailPhys) / (1024**3)
            return {"pct": mem.dwMemoryLoad, "used_gb": round(used, 1), "total_gb": round(total, 1)}
        except Exception:
            return {"pct": 0, "used_gb": 0, "total_gb": 0}

    @staticmethod
    def update_cpu():
        try:
            idle = ctypes.c_ulonglong()
            kernel = ctypes.c_ulonglong()
            user = ctypes.c_ulonglong()
            ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user),
            )
            di = idle.value - SystemMonitor._last_idle
            dk = kernel.value - SystemMonitor._last_kernel
            du = user.value - SystemMonitor._last_user
            SystemMonitor._last_idle = idle.value
            SystemMonitor._last_kernel = kernel.value
            SystemMonitor._last_user = user.value
            total = dk + du
            if total > 0 and SystemMonitor._last_idle > 0:
                SystemMonitor._cpu_pct = max(0, min(100, ((total - di) / total) * 100))
        except Exception:
            pass

    @staticmethod
    def get_cpu():
        return round(SystemMonitor._cpu_pct, 1)
