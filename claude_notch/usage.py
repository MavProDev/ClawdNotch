"""
claude_notch.usage — Usage tracking & analytics
=================================================
UsageTracker, UsagePoller, SparklineTracker, StreakTracker, TodoManager,
and the export_usage_report helper.  All persistent state lives under
~/.claude-notch/usage_history.json.
"""

import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
import requests

from claude_notch.config import (
    CONFIG_DIR,
    _atomic_write,
    _redact_key,
    TOKEN_ESTIMATES,
    MODEL_PRICING,
)

# ═══════════════════════════════════════════════════════════════════════════════
# USAGE FILE
# ═══════════════════════════════════════════════════════════════════════════════

USAGE_FILE = CONFIG_DIR / "usage_history.json"


# ═══════════════════════════════════════════════════════════════════════════════
# USAGE TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

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
            total = today["tool_calls"] + today["prompts"] + today.get("sessions", 0)
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


# ═══════════════════════════════════════════════════════════════════════════════
# USAGE POLLER  (QThread — polls Anthropic API rate-limit headers)
# ═══════════════════════════════════════════════════════════════════════════════

class UsagePoller(QThread):
    usage_updated = pyqtSignal(list)  # list of per-key status dicts

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._running = True
        self._results = []
        self._error_counts = {}  # key_redacted -> consecutive error count

    def stop(self):
        self._running = False

    def run(self):
        poll_count = 0
        while self._running:
            poll_count += 1
            api_keys = (self.config.get_api_keys_decrypted()
                        if hasattr(self.config, 'get_api_keys_decrypted')
                        else list(self.config.get("api_keys", [])))
            if api_keys:
                results = []
                for i, entry in enumerate(api_keys):
                    if not self._running:
                        return
                    key = entry.get("key", "")
                    label = entry.get("label", f"Key {i+1}")
                    redacted = _redact_key(key)
                    # Skip keys with repeated errors (backoff: skip every N cycles based on error count)
                    err_count = self._error_counts.get(redacted, 0)
                    if err_count >= 3 and poll_count % min(err_count, 10) != 0:
                        # Re-use last result with updated skip note
                        for old in self._results:
                            if old.get("key_redacted") == redacted:
                                results.append(old)
                                break
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
                            if not self._running:
                                return
                            time.sleep(0.5)
                self._results = results
            else:
                self._results = []
            self.usage_updated.emit(list(self._results))
            for _ in range(self.config.get("poll_interval_seconds", 60) * 2):
                if not self._running:
                    return
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
                result.update({"health": "error", "error": "Invalid API key (401)"})
                return result
            h = r.headers
            rl = int(h.get("anthropic-ratelimit-requests-limit", 0))
            rr = int(h.get("anthropic-ratelimit-requests-remaining", 0))
            tl = int(h.get("anthropic-ratelimit-tokens-limit", 0))
            tr = int(h.get("anthropic-ratelimit-tokens-remaining", 0))
            rpm_used = rl - rr
            tpm_used = tl - tr
            # Health classification
            if rl == 0 and tl == 0:
                health = "healthy"  # headers unavailable, assume ok
            else:
                rpm_pct = (rpm_used / max(1, rl)) if rl else 0
                tpm_pct = (tpm_used / max(1, tl)) if tl else 0
                usage_pct = max(rpm_pct, tpm_pct)
                if usage_pct > 0.85:
                    health = "throttled"
                elif usage_pct > 0.60:
                    health = "warm"
                else:
                    health = "healthy"
            result.update({
                "health": health, "error": None,
                "rpm_used": rpm_used, "rpm_limit": rl,
                "tpm_used": tpm_used, "tpm_limit": tl,
                "requests_remaining": rr, "tokens_remaining": tr,
            })
        except requests.RequestException as e:
            result.update({"health": "error", "error": str(e)[:50]})
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# SPARKLINE TRACKER
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


# ═══════════════════════════════════════════════════════════════════════════════
# STREAK TRACKER  (BUG #20: docstring added)
# ═══════════════════════════════════════════════════════════════════════════════

class StreakTracker:
    """Tracks consecutive coding days.

    Streak counting behaviour
    -------------------------
    The streak is computed by walking backwards from today through up to
    365 days of history.  A day counts toward the streak if it has at
    least one tool_call OR one prompt recorded in UsageTracker.

    Special case: if *today* has no activity yet (e.g. just booted up in
    the morning), today is skipped and the streak is counted starting
    from yesterday.  This prevents the streak from resetting to 0 at the
    start of each day before any coding has occurred.

    ``top_day_this_week`` returns the weekday name and tool-call count
    for the single most-active day in the last seven days.
    """

    def __init__(self, tracker):
        self._tracker = tracker

    @property
    def current_streak(self):
        days_data = self._tracker.all_days
        if not days_data:
            return 0
        streak = 0
        check_date = datetime.now()
        today = datetime.now().strftime("%Y-%m-%d")
        for _ in range(365):
            key = check_date.strftime("%Y-%m-%d")
            day = days_data.get(key, {})
            if day.get("tool_calls", 0) > 0 or day.get("prompts", 0) > 0:
                streak += 1
                check_date -= timedelta(days=1)
            else:
                if key == today:
                    check_date -= timedelta(days=1)
                    continue
                break
        return streak

    @property
    def top_day_this_week(self):
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        best_date, best_count = "", 0
        for date, data in self._tracker.all_days.items():
            if date >= cutoff:
                tc = data.get("tool_calls", 0)
                if tc > best_count:
                    best_count = tc
                    best_date = date
        if best_date:
            try:
                return datetime.strptime(best_date, "%Y-%m-%d").strftime("%A"), best_count
            except Exception:
                pass
        return "", best_count


# ═══════════════════════════════════════════════════════════════════════════════
# TODO MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORT  (BUG FIX #10: use Path.home()/"Desktop" with os.path.exists check)
# ═══════════════════════════════════════════════════════════════════════════════

def export_usage_report(tracker, config, fmt="markdown"):
    """Export usage data to a Markdown or CSV file on the Desktop.

    BUG FIX #10: The original code hardcoded ``OneDrive/Desktop`` which
    fails on machines without OneDrive.  Now we probe for common desktop
    locations using ``os.path.exists`` and fall back to ``Path.home() / "Desktop"``.
    """
    td = tracker.today
    mo = tracker.month_stats
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    if fmt == "csv":
        lines = ["Date,ToolCalls,Prompts,Tokens,Sessions,Cost"]
        for date in sorted(tracker.all_days.keys()):
            d = tracker.all_days[date]
            lines.append(f"{date},{d.get('tool_calls',0)},{d.get('prompts',0)},{d.get('est_tokens',0)},{d.get('sessions',0)},{d.get('est_cost',0):.4f}")
        content = "\n".join(lines)
        ext = "csv"
    else:
        content = (
            f"# Claude Notch Usage Report — {ts}\n\n"
            f"## Today\n"
            f"- Tool calls: {td.get('tool_calls',0)}\n"
            f"- Prompts: {td.get('prompts',0)}\n"
            f"- Est. tokens: {td.get('est_tokens',0):,}\n\n"
            f"## This Month ({datetime.now().strftime('%B')})\n"
            f"- Tool calls: {mo.get('tool_calls',0)}\n"
            f"- Days active: {mo.get('days_active',0)}\n"
            f"- Est. tokens: {mo.get('est_tokens',0):,}\n"
            f"- Est. cost: ${mo.get('est_cost',0):.2f}\n"
        )
        ext = "md"

    # BUG FIX #10 — probe for the actual Desktop path instead of hardcoding OneDrive
    desktop = Path.home() / "Desktop"
    onedrive_desktop = Path.home() / "OneDrive" / "Desktop"
    if os.path.exists(onedrive_desktop):
        desktop = onedrive_desktop
    elif not os.path.exists(desktop):
        desktop = Path.home()  # last-resort fallback

    out = desktop / f"claude-notch-report-{ts}.{ext}"
    try:
        out.write_text(content, encoding="utf-8")
    except (OSError, PermissionError) as e:
        print(f"[Export] Failed to write report: {e}", file=sys.stderr)
        # Fall back to home directory
        out = Path.home() / f"claude-notch-report-{ts}.{ext}"
        out.write_text(content, encoding="utf-8")
    return str(out)


# ═══════════════════════════════════════════════════════════════════════════════
# RE-EXPORTS (backward compatibility)
# ═══════════════════════════════════════════════════════════════════════════════

from claude_notch.token_aggregator import TokenAggregator  # noqa: F401
from claude_notch.update_checker import (  # noqa: F401
    check_for_updates, _parse_version, open_release_page,
)
