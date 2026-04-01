"""
claude_notch.token_aggregator — Real token usage from Claude Code JSONL files
==============================================================================
Reads actual token counts from ~/.claude/projects/{hash}/{session_id}.jsonl
instead of relying on rough estimates from TOKEN_ESTIMATES.

v4.0.0: Extracted from usage.py for single-responsibility.
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path


class TokenAggregator:
    """Reads actual token usage from Claude Code's session JSONL files.

    Claude Code stores every API response with real token counts at:
        ~/.claude/projects/{project-hash}/{session-id}.jsonl

    Each assistant message line contains a "usage" object with:
        input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens
    """

    CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

    def __init__(self, cache_ttl_seconds=30):
        self._lock = threading.Lock()
        self._cache = {}
        self._session_cache = {}
        self._last_scan = 0.0
        self._ttl = cache_ttl_seconds

    def get_today(self) -> dict:
        self._maybe_refresh()
        today_key = datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            return dict(self._cache.get(today_key, {
                "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total": 0
            }))

    def get_date(self, date_str: str) -> dict:
        self._maybe_refresh()
        with self._lock:
            return dict(self._cache.get(date_str, {
                "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total": 0
            }))

    def get_session(self, session_id: str) -> dict:
        """Get real token usage for a specific session."""
        if not session_id or not self.CLAUDE_PROJECTS_DIR.exists():
            return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total": 0}
        # Skip process-detected session IDs (proc-XXXX) — no JSONL files for those
        if session_id.startswith("proc-"):
            return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total": 0}

        with self._lock:
            cached = self._session_cache.get(session_id)
            if cached is not None:
                now = time.time()
                if now - cached.get("_ts", 0) < self._ttl:
                    return {k: v for k, v in cached.items() if k != "_ts"}

        result = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total": 0}
        try:
            for project_dir in self.CLAUDE_PROJECTS_DIR.iterdir():
                if not project_dir.is_dir():
                    continue
                jsonl_file = project_dir / f"{session_id}.jsonl"
                if jsonl_file.exists():
                    acc = {}
                    self._parse_jsonl(jsonl_file, acc)
                    for day_data in acc.values():
                        result["input"] += day_data.get("input", 0)
                        result["output"] += day_data.get("output", 0)
                        result["cache_read"] += day_data.get("cache_read", 0)
                        result["cache_write"] += day_data.get("cache_write", 0)
                        result["total"] += day_data.get("total", 0)
                    break
        except Exception:
            pass

        with self._lock:
            self._session_cache[session_id] = {**result, "_ts": time.time()}
        return result

    def get_month_total(self) -> int:
        self._maybe_refresh()
        prefix = datetime.now().strftime("%Y-%m")
        with self._lock:
            return sum(v["total"] for k, v in self._cache.items() if k.startswith(prefix))

    def _maybe_refresh(self):
        now = time.time()
        if now - self._last_scan < self._ttl:
            return
        self._scan()
        self._last_scan = now

    def _scan(self):
        if not self.CLAUDE_PROJECTS_DIR.exists():
            return
        cutoff_ts = time.time() - (31 * 86400)
        new_cache = {}
        try:
            for project_dir in self.CLAUDE_PROJECTS_DIR.iterdir():
                if not project_dir.is_dir():
                    continue
                for jsonl_file in project_dir.glob("*.jsonl"):
                    try:
                        mtime = jsonl_file.stat().st_mtime
                        if mtime < cutoff_ts:
                            continue
                        self._parse_jsonl(jsonl_file, new_cache)
                    except Exception:
                        continue
        except Exception:
            return
        with self._lock:
            self._cache = new_cache

    def _parse_jsonl(self, path: Path, accumulator: dict):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or '"usage"' not in line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    usage = None
                    msg = data.get("message", {})
                    if isinstance(msg, dict):
                        usage = msg.get("usage")
                    if not usage or not isinstance(usage, dict):
                        continue
                    ts = data.get("timestamp", "")
                    if not ts:
                        continue
                    try:
                        date_key = ts[:10]
                        if len(date_key) != 10 or date_key[4] != '-':
                            continue
                    except (IndexError, TypeError):
                        continue
                    if date_key not in accumulator:
                        accumulator[date_key] = {
                            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "total": 0
                        }
                    day = accumulator[date_key]
                    inp = usage.get("input_tokens", 0) or 0
                    out = usage.get("output_tokens", 0) or 0
                    cache_read = usage.get("cache_read_input_tokens", 0) or 0
                    cache_write = usage.get("cache_creation_input_tokens", 0) or 0
                    day["input"] += inp
                    day["output"] += out
                    day["cache_read"] += cache_read
                    day["cache_write"] += cache_write
                    day["total"] += inp + out + cache_read + cache_write
        except (OSError, PermissionError):
            pass
