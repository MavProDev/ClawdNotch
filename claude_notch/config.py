"""
claude_notch.config — Foundation module
========================================
All constants, themes, color dictionaries, and the thread-safe ConfigManager.
Every other module in claude_notch imports from here.
"""

import sys
import os
import json
import tempfile
import threading
import base64
import ctypes
import ctypes.wintypes
from pathlib import Path
from datetime import datetime

from PyQt6.QtGui import QColor

# ═══════════════════════════════════════════════════════════════════════════════
# PATHS & PORTS
# ═══════════════════════════════════════════════════════════════════════════════

HOOK_SERVER_PORT = 19748
CONFIG_DIR = Path.home() / ".claude-notch"
CONFIG_FILE = CONFIG_DIR / "config.json"
LOCK_FILE = CONFIG_DIR / "notch.lock"

# ═══════════════════════════════════════════════════════════════════════════════
# DEFAULT CONFIG  (35 keys)
# ═══════════════════════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════════════════════
# THINKING / SPINNER DATA
# ═══════════════════════════════════════════════════════════════════════════════

THINKING_WORDS = [
    "Accomplishing", "Actioning", "Actualizing", "Baking", "Booping", "Brewing",
    "Calculating", "Cerebrating", "Channelling", "Churning", "Clauding", "Coalescing",
    "Cogitating", "Combobulating", "Computing", "Concocting", "Conjuring", "Considering",
    "Contemplating", "Cooking", "Crafting", "Creating", "Crunching", "Deciphering",
    "Deliberating", "Determining", "Discombobulating", "Divining", "Doing", "Effecting",
    "Elucidating", "Enchanting", "Envisioning", "Finagling", "Flibbertigibbeting",
    "Forging", "Forming", "Frolicking", "Generating", "Germinating", "Hatching",
    "Herding", "Honking", "Hustling", "Ideating", "Imagining", "Incubating", "Inferring",
    "Jiving", "Manifesting", "Marinating", "Meandering", "Moseying", "Mulling",
    "Mustering", "Musing", "Noodling", "Percolating", "Perusing", "Philosophising",
    "Pondering", "Pontificating", "Processing", "Puttering", "Puzzling", "Reticulating",
    "Ruminating", "Scheming", "Schlepping", "Shimmying", "Shucking", "Simmering",
    "Smooshing", "Spelunking", "Spinning", "Stewing", "Sussing", "Synthesizing",
    "Thinking", "Tinkering", "Transmuting", "Unfurling", "Unravelling", "Vibing",
    "Wandering", "Whirring", "Wibbling", "Wizarding", "Working", "Wrangling",
]

SPINNER_FRAMES = ["·", "✻", "✽", "✶", "✳", "✢"]

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL DATA
# ═══════════════════════════════════════════════════════════════════════════════

MODEL_CONTEXT_LIMITS = {
    "opus": 200_000, "sonnet": 200_000, "haiku": 200_000,
    "opus-1m": 1_000_000, "sonnet-1m": 1_000_000,
}

MODEL_PRICING = {
    "opus":   {"input": 15.0,  "output": 75.0, "cache_read": 1.50},
    "sonnet": {"input": 3.0,   "output": 15.0, "cache_read": 0.30},
    "haiku":  {"input": 0.80,  "output": 4.0,  "cache_read": 0.08},
}

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

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION TINTS & MUTABLE COLOR DICT
# ═══════════════════════════════════════════════════════════════════════════════

SESSION_TINTS = [
    QColor(217, 119, 87), QColor(88, 166, 255), QColor(72, 199, 132),
    QColor(180, 130, 220), QColor(240, 185, 55), QColor(220, 100, 160),
]

C = {
    "notch_bg": QColor(12, 12, 14), "notch_border": QColor(40, 40, 48),
    "card_bg": QColor(28, 28, 34), "divider": QColor(44, 44, 52),
    "text_hi": QColor(240, 236, 232), "text_md": QColor(155, 148, 142),
    "text_lo": QColor(85, 80, 76), "coral": QColor(217, 119, 87),
    "coral_light": QColor(235, 155, 120), "green": QColor(72, 199, 132),
    "amber": QColor(240, 185, 55), "red": QColor(230, 72, 72),
}

# ═══════════════════════════════════════════════════════════════════════════════
# FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def apply_theme(name):
    """Apply a named theme by updating the mutable C dict."""
    t = THEMES.get(name, THEMES["coral"])
    C["coral"] = QColor(*t["accent"])
    C["coral_light"] = QColor(*t["accent_light"])


def _atomic_write(path: Path, data: dict) -> bool:
    """Write JSON atomically: write to temp file, then rename over target.

    Returns True on success, False on failure.
    """
    try:
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
            return True
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        print(f"[Write] Failed to save {path.name}: {e}", file=sys.stderr)
        return False


def _redact_key(key: str) -> str:
    """Redact API key: show first 7 + last 4 chars."""
    if len(key) <= 11:
        return key[:3] + "..." + key[-2:] if len(key) > 5 else "***"
    return key[:7] + "..." + key[-4:]


# ═══════════════════════════════════════════════════════════════════════════════
# DPAPI ENCRYPTION  (Windows-only, zero dependencies)
# ═══════════════════════════════════════════════════════════════════════════════

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi_encrypt(plaintext: str) -> str:
    """Encrypt a string using Windows DPAPI. Returns base64-encoded ciphertext.

    DPAPI ties encryption to the current Windows user account — only the same
    user on the same machine can decrypt. No key management needed.
    Logs a warning and returns plaintext with marker prefix on failure.
    """
    try:
        data = plaintext.encode("utf-8")
        blob_in = _DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                                                      ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        if ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return "dpapi:" + base64.b64encode(encrypted).decode("ascii")
        else:
            print("[SECURITY] DPAPI encryption failed — CryptProtectData returned False", file=sys.stderr)
    except Exception as e:
        print(f"[SECURITY] DPAPI encryption failed: {e}", file=sys.stderr)
    return plaintext  # fallback: return as-is (logged above)


def _dpapi_decrypt(stored: str) -> str:
    """Decrypt a DPAPI-encrypted string. If not encrypted (no dpapi: prefix), returns as-is."""
    if not stored.startswith("dpapi:"):
        return stored
    try:
        encrypted = base64.b64decode(stored[6:])
        blob_in = _DATA_BLOB(len(encrypted), ctypes.cast(
            ctypes.create_string_buffer(encrypted, len(encrypted)),
            ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        if ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        ):
            try:
                plaintext = ctypes.string_at(blob_out.pbData, blob_out.cbData).decode("utf-8")
                return plaintext
            finally:
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        else:
            print("[SECURITY] DPAPI decryption failed — CryptUnprotectData returned False", file=sys.stderr)
    except Exception as e:
        print(f"[SECURITY] DPAPI decryption failed: {e}", file=sys.stderr)
    return ""  # return empty string instead of ciphertext blob


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG MANAGER  (BUG FIX #1: thread-safe with threading.Lock)
# ═══════════════════════════════════════════════════════════════════════════════

class ConfigManager:
    """Persistent configuration with thread-safe access.

    BUG FIX #1: All public accessors (get, set, save, set_many, flush)
    are now wrapped with a threading.Lock to prevent concurrent
    read/write corruption from the hook server thread and UI thread.
    """

    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.config = self._load()
        self._migrate()
        self._dirty = False

    def _migrate(self):
        """Migrate old single-key config to multi-key format, remove dead keys, encrypt API keys."""
        changed = False

        # Migrate old single anthropic_api_key -> api_keys list
        old_key = self.config.pop("anthropic_api_key", None)
        if old_key and old_key.startswith("sk-ant") and not self.config.get("api_keys"):
            self.config["api_keys"] = [{
                "key": old_key, "label": "Default",
                "added": datetime.now().strftime("%Y-%m-%d"),
            }]
            changed = True

        # Remove dead "notch_opacity" key (superseded by "dim_opacity")
        if "notch_opacity" in self.config:
            del self.config["notch_opacity"]
            changed = True

        # Encrypt any plaintext API keys with DPAPI
        for entry in self.config.get("api_keys", []):
            key = entry.get("key", "")
            if key and not key.startswith("dpapi:"):
                entry["key"] = _dpapi_encrypt(key)
                changed = True

        if changed:
            self.save()

    def _load(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    return {**DEFAULT_CONFIG, **json.load(f)}
            except Exception as e:
                print(f"[Config] Failed to load: {e}", file=sys.stderr)
        return dict(DEFAULT_CONFIG)

    def save(self):
        with self._lock:
            snapshot = dict(self.config)
            self._dirty = False
        _atomic_write(CONFIG_FILE, snapshot)

    def get(self, key, default=None):
        with self._lock:
            return self.config.get(key, default)

    def set(self, key, value, save_now=True):
        with self._lock:
            self.config[key] = value
            if save_now:
                snapshot = dict(self.config)
                self._dirty = False
            else:
                self._dirty = True
                snapshot = None
        if snapshot is not None:
            _atomic_write(CONFIG_FILE, snapshot)

    def set_many(self, updates):
        with self._lock:
            self.config.update(updates)
            snapshot = dict(self.config)
            self._dirty = False
        _atomic_write(CONFIG_FILE, snapshot)

    def get_api_keys_decrypted(self) -> list:
        """Return api_keys list with keys decrypted from DPAPI."""
        with self._lock:
            result = []
            for entry in self.config.get("api_keys", []):
                result.append({
                    **entry,
                    "key": _dpapi_decrypt(entry.get("key", "")),
                })
            return result

    def flush(self):
        with self._lock:
            if not self._dirty:
                return
            snapshot = dict(self.config)
            self._dirty = False
        _atomic_write(CONFIG_FILE, snapshot)
