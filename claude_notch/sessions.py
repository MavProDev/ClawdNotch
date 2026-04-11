"""
claude_notch.sessions -- Session lifecycle management
=====================================================
Session dataclass, SessionManager (QObject), EmotionEngine,
and persistence helpers (_save_sessions_state / _load_sessions_state).

v4.0.0: Fixed ghost/duplicate session detection, PID merging,
context bar semantics, and aggressive ghost cleanup.
"""

import sys
import json
import time
import threading
import random
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field

from PySide6.QtCore import Signal, QObject

from claude_notch.config import (
    CONFIG_DIR,
    TOKEN_ESTIMATES,
    MODEL_CONTEXT_LIMITS,
    SESSION_TINTS,
    THINKING_WORDS,
    _atomic_write,
)

# ═══════════════════════════════════════════════════════════════════════════════
# PERSISTENT FILE
# ═══════════════════════════════════════════════════════════════════════════════

SESSIONS_FILE = CONFIG_DIR / "sessions_state.json"

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION DATACLASS
# ═══════════════════════════════════════════════════════════════════════════════

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
    thinking_word: str = ""

    @property
    def project_name(self):
        if self.project_dir:
            return Path(self.project_dir).name
        if self.pid:
            return f"PID {self.pid}"
        return "unknown"

    @property
    def age_str(self):
        m = int((datetime.now() - self.started_at).total_seconds() / 60)
        return "now" if m < 1 else f"{m}m" if m < 60 else f"{m//60}h {m%60}m"

    @property
    def age_minutes(self):
        return int((datetime.now() - self.started_at).total_seconds() / 60)

    @property
    def tint(self):
        return SESSION_TINTS[self.tint_index % len(SESSION_TINTS)]

    @property
    def is_stale(self):
        return (datetime.now() - self.last_activity).total_seconds() > 7200

    @property
    def is_displayable(self):
        """Whether this session should be shown in the UI.

        Process-detected sessions with no project info are background noise
        used only for PID matching and keep-alive. Don't clutter the display.
        """
        if self.detected_via == "process" and not self.project_dir:
            return False
        return True

# ═══════════════════════════════════════════════════════════════════════════════
# EMOTION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

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

# ═══════════════════════════════════════════════════════════════════════════════
# SESSION MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class SessionManager(QObject):
    session_updated = Signal()
    task_completed = Signal(str, str)
    needs_attention = Signal(str, int)  # project_name, pid
    budget_alert = Signal(str)
    achievement = Signal(str)  # achievement message

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
        self._active_cache = []
        self._active_cache_ts = 0.0
        self._achievements_fired = set()

    # ── Project matching helpers ──

    @staticmethod
    def _projects_match(dir_a: str, dir_b: str) -> bool:
        """Check if two project directories refer to the same project.

        Matches by exact normalized path first. Falls back to basename
        matching only when one of the values is a bare name (no path
        separators), which handles window titles that contain only the
        folder name.
        """
        if not dir_a or not dir_b:
            return False
        # Normalize paths for comparison
        a = dir_a.replace("\\", "/").rstrip("/").lower()
        b = dir_b.replace("\\", "/").rstrip("/").lower()
        if a == b:
            return True
        # Only basename match if at least one value is a bare name (no path separators)
        # This handles window titles like "Claude Notch" matching full paths
        a_is_bare = "/" not in a
        b_is_bare = "/" not in b
        if not (a_is_bare or b_is_bare):
            return False
        name_a = a.rsplit("/", 1)[-1]
        name_b = b.rsplit("/", 1)[-1]
        return name_a == name_b and name_a != ""

    def _find_matching_hook_session(self, project_dir: str, pid: int = 0):
        """Find an existing hook-detected session that matches a process.

        Returns the session_id if found, None otherwise.
        Checks PID first (if session has one), then project_dir match.
        """
        if pid:
            for sid, s in self.sessions.items():
                if s.pid == pid:
                    return sid
        if project_dir:
            for sid, s in self.sessions.items():
                if s.detected_via == "hook" and self._projects_match(s.project_dir, project_dir):
                    return sid
        return None

    # ── Event handlers ──

    def _on_session_start(self, s, event):
        s.state = "idle"

    def _on_pre_tool_use(self, s, event):
        if s.state != "working":
            s.thinking_word = random.choice(THINKING_WORDS)
        s.state = "working"
        s.current_tool = event.get("tool_name", "")

    def _on_post_tool_use(self, s, event):
        sid = s.session_id
        s.state = "working"; s.tool_count += 1; s.current_tool = ""
        tool_name = event.get("tool_name", "tool")
        if self._todos:
            self._todos.process_tool_event(sid, tool_name, event.get("tool_input", ""))
        s.tasks_completed.append({"summary": f"Used {tool_name}", "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "status": "completed"})
        s.tasks_completed = s.tasks_completed[-20:]

    def _on_post_tool_use_failure(self, s, event):
        s.state = "error"; s.current_tool = ""

    def _on_notification(self, s, event):
        s.state = "waiting"
        self.needs_attention.emit(s.project_name, s.pid)

    def _on_stop(self, s, event):
        s.state = "idle"
        sm = str(event.get("summary", "Task completed"))[:500]
        s.tasks_completed.append({"summary": sm, "time": datetime.now().strftime("%Y-%m-%d %H:%M"), "status": "completed"})
        s.tasks_completed = s.tasks_completed[-20:]
        self.task_completed.emit(s.project_name[:200], sm)

    def _on_session_end(self, s, event):
        s.state = "completed"
        dur = (datetime.now() - s.started_at).total_seconds() / 60
        self._completed_durations.append(dur)
        self._completed_durations = self._completed_durations[-50:]
        s.last_activity = datetime.now() - timedelta(minutes=3)

    def _on_user_prompt(self, s, event):
        if s.state != "working":
            s.thinking_word = random.choice(THINKING_WORDS)
        s.state = "working"
        if self._emotion:
            prompt_text = event.get("user_prompt", "")
            s.emotion = self._emotion.process(s.session_id, prompt_text)

    _EVENT_HANDLERS = {
        "SessionStart": _on_session_start,
        "PreToolUse": _on_pre_tool_use,
        "PostToolUse": _on_post_tool_use,
        "PostToolUseFailure": _on_post_tool_use_failure,
        "Notification": _on_notification,
        "Stop": _on_stop,
        "SessionEnd": _on_session_end,
        "UserPromptSubmit": _on_user_prompt,
    }

    def handle_event(self, event):
        et = event.get("event", "")
        sid = event.get("session_id", "unknown")
        pd = event.get("project_dir", "")
        self._tracker.record_event(et)
        if self._sparkline:
            self._sparkline.record()
        with self._lock:
            if sid not in self.sessions:
                # Cap maximum sessions to prevent unbounded growth
                if len(self.sessions) >= 50:
                    oldest = min(
                        (s for s in self.sessions if self.sessions[s].state != "working"),
                        key=lambda s: self.sessions[s].last_activity,
                        default=None,
                    )
                    if oldest:
                        del self.sessions[oldest]
                        if self._emotion:
                            self._emotion.remove_session(oldest)
                        if self._todos:
                            self._todos.remove_session(oldest)
                model = (self._config.get("default_model", "sonnet") if self._config else "sonnet")
                ctx = MODEL_CONTEXT_LIMITS.get(model, 200_000)
                new_session = Session(
                    session_id=sid, project_dir=pd,
                    tint_index=self._next_tint, model=model, context_limit=ctx,
                )
                # v4.0.0: Merge with existing process-detected ghost session
                # If a process session was already created for this Claude instance,
                # steal its PID and remove the ghost instead of having two entries.
                if pd:
                    for existing_sid in list(self.sessions):
                        es = self.sessions[existing_sid]
                        if es.detected_via == "process" and es.pid:
                            if self._projects_match(pd, es.project_dir):
                                new_session.pid = es.pid
                                del self.sessions[existing_sid]
                                if self._emotion:
                                    self._emotion.remove_session(existing_sid)
                                if self._todos:
                                    self._todos.remove_session(existing_sid)
                                break
                self.sessions[sid] = new_session
                self._next_tint += 1
            s = self.sessions[sid]
            s.last_activity = datetime.now()
            if pd:
                s.project_dir = pd
            est = TOKEN_ESTIMATES.get(et, 100)
            s.session_tokens += est
            handler = self._EVENT_HANDLERS.get(et)
            if handler:
                handler(self, s, event)
        # Budget alert check
        if self._config and self._config.get("subscription_mode") == "api":
            daily_budget = self._config.get("budget_daily", 0)
            if daily_budget > 0:
                cost = self._tracker.today.get("est_cost", 0)
                alert_key = f"budget_alert_{self._tracker._today_key}"
                if cost >= daily_budget * 0.8 and not getattr(self, '_budget_alerted', None) == alert_key:
                    self._budget_alerted = alert_key
                    self.budget_alert.emit(f"Daily budget: ${cost:.2f} / ${daily_budget:.2f}")
            budget_monthly = self._config.get("budget_monthly", 0)
            if budget_monthly > 0:
                month = self._tracker.month_stats
                month_cost = month.get("est_cost", 0)
                month_key = datetime.now().strftime("%Y-%m")
                monthly_alert_key = f"budget_monthly_alert_{month_key}"
                if month_cost >= budget_monthly * 0.8 and not getattr(self, '_budget_monthly_alerted', None) == monthly_alert_key:
                    self._budget_monthly_alerted = monthly_alert_key
                    self.budget_alert.emit(f"Monthly budget: ${month_cost:.2f} / ${budget_monthly:.2f}")
        # Achievement milestones
        if self._tracker:
            today = self._tracker.today
            tc = today.get("tool_calls", 0)
            milestones = [
                (50,   "50 tool calls today!"),
                (100,  "100 tool calls today — keep going!"),
                (250,  "250 tool calls — you're on fire!"),
                (500,  "500 tool calls — legendary session!"),
                (1000, "1,000 tool calls — absolute beast!"),
            ]
            for threshold, msg in milestones:
                key = f"tc_{threshold}_{self._tracker._today_key}"
                if tc >= threshold and key not in self._achievements_fired:
                    self._achievements_fired.add(key)
                    self.achievement.emit(msg)
                    break
        self.session_updated.emit()

    @property
    def avg_session_minutes(self):
        if not self._completed_durations:
            return 0
        return int(sum(self._completed_durations) / len(self._completed_durations))

    def scan_processes(self):
        """Scan for running Claude Code windows/processes and keep sessions alive.

        v4.0.0: Merges process-detected PIDs into existing hook sessions
        instead of creating duplicate "unknown" ghost entries.
        """
        from claude_notch.system_monitor import _find_claude_windows, _find_claude_processes
        windows = _find_claude_windows()
        processes = _find_claude_processes()
        active_pids = {w['pid'] for w in windows} | {p['pid'] for p in processes}
        with self._lock:
            # Pass 1: Keep existing sessions alive if their process is still running
            for sid, s in self.sessions.items():
                if s.state == "completed":
                    continue
                if s.pid and s.pid in active_pids:
                    if (datetime.now() - s.last_activity).total_seconds() > 30:
                        s.last_activity = datetime.now()

            # Pass 2: For PIDs with no session yet, try to merge with existing
            # hook sessions before creating new process-detected entries
            known_pids = {s.pid for s in self.sessions.values() if s.pid}

            for w in windows:
                if w['pid'] in known_pids:
                    continue
                # Extract project name from window title
                title = w.get('title', '')
                pdir = self._extract_project_from_title(title)

                # Try to match this PID to an existing hook session with no PID
                matched = False
                if pdir:
                    for sid, s in self.sessions.items():
                        if s.detected_via == "hook" and not s.pid:
                            if self._projects_match(pdir, s.project_dir):
                                s.pid = w['pid']
                                known_pids.add(w['pid'])
                                matched = True
                                break
                    if not matched:
                        # Also check hook sessions that have a PID but it died
                        for sid, s in self.sessions.items():
                            if s.detected_via == "hook" and s.pid and s.pid not in active_pids:
                                if self._projects_match(pdir, s.project_dir):
                                    s.pid = w['pid']
                                    known_pids.add(w['pid'])
                                    matched = True
                                    break

                if not matched:
                    # Truly new — no hook session for this project yet
                    sid = f"proc-{w['pid']}"
                    self.sessions[sid] = Session(
                        session_id=sid, project_dir=pdir,
                        state="idle", tint_index=self._next_tint,
                        pid=w['pid'], detected_via="process",
                    )
                    self._next_tint += 1
                    known_pids.add(w['pid'])

            # Also create sessions from process-detected Claude Code that had no window
            for p in processes:
                if p['pid'] in known_pids:
                    continue
                pdir = p.get('cwd', '')
                # Try to merge with existing hook session
                matched = False
                if pdir:
                    for sid, s in self.sessions.items():
                        if s.detected_via == "hook" and not s.pid:
                            if self._projects_match(pdir, s.project_dir):
                                s.pid = p['pid']
                                known_pids.add(p['pid'])
                                matched = True
                                break
                if not matched:
                    sid = f"proc-{p['pid']}"
                    self.sessions[sid] = Session(
                        session_id=sid, project_dir=pdir,
                        state="idle", tint_index=self._next_tint,
                        pid=p['pid'], detected_via="process",
                    )
                    self._next_tint += 1
                    known_pids.add(p['pid'])

        self.session_updated.emit()

    @staticmethod
    def _extract_project_from_title(title: str) -> str:
        """Extract project directory/name from a window title."""
        if not title:
            return ""
        for sep in [' \u2014 ', ' - ', ': ']:
            if sep in title:
                parts = title.split(sep)
                for part in parts:
                    part = part.strip()
                    if part.lower() not in ('claude', 'claude code', 'windows terminal',
                                             'command prompt', 'powershell', 'cmd'):
                        return part
        return ""

    def cleanup_dead(self):
        """Remove sessions that are no longer active.

        v4.0.0: More aggressive cleanup of process-detected ghosts.
        """
        from claude_notch.system_monitor import _find_claude_windows, _find_claude_processes
        active_pids = set()
        scan_ok = False
        try:
            windows = _find_claude_windows()
            processes = _find_claude_processes()
            active_pids = {w['pid'] for w in windows} | {p['pid'] for p in processes}
            scan_ok = True
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
                # Process-detected with no project: remove if PID gone OR after 2 min idle
                if v.detected_via == "process" and not v.project_dir:
                    if (scan_ok and not proc_alive) or age > 120:
                        to_remove.append(sid)
                        continue
                # Process-detected with project: remove if PID gone
                if v.detected_via == "process" and scan_ok and not proc_alive:
                    to_remove.append(sid)
                    continue
                # Hook sessions with no PID: only trust recent activity
                if not v.pid and age > 300:
                    to_remove.append(sid)
                    continue
                # Any session inactive 10+ min with dead/unknown process
                if age > 600 and scan_ok and not proc_alive:
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
        """Return active, displayable sessions sorted by most recent activity.

        v4.0.0: Filters out non-displayable process ghosts so they don't
        consume slots in the session list.
        """
        now = time.monotonic()
        if now - self._active_cache_ts < 0.1:
            return list(self._active_cache)
        with self._lock:
            a = [s for s in self.sessions.values()
                 if s.state != "completed"
                 and (datetime.now() - s.last_activity).total_seconds() < 7200
                 and s.is_displayable]
            a.sort(key=lambda s: s.last_activity, reverse=True)
        self._active_cache = a
        self._active_cache_ts = now
        return a

    def get_all_tasks(self, limit=10):
        t = []
        with self._lock:
            for s in self.sessions.values():
                for tk in s.tasks_completed:
                    t.append({**tk, "project": s.project_name})
        t.sort(key=lambda x: x.get("time", ""), reverse=True)
        return t[:limit]

    @property
    def total_active(self):
        return len(self.get_active_sessions())

    @property
    def any_working(self):
        return any(s.state == "working" for s in self.get_active_sessions())

    @property
    def any_waiting(self):
        return any(s.state == "waiting" for s in self.get_active_sessions())

# ═══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _save_sessions_state(sessions: dict):
    """Persist session metadata to disk for restore on restart."""
    try:
        state = {}
        for sid, s in sessions.items():
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
                "pid": s.pid,
            }
        _atomic_write(SESSIONS_FILE, {"saved_at": datetime.now().isoformat(), "sessions": state})
    except Exception as e:
        print(f"[Sessions] Save failed: {e}", file=sys.stderr)


def _load_sessions_state() -> dict:
    """Load persisted session state from disk."""
    if not SESSIONS_FILE.exists():
        return {}
    try:
        with open(SESSIONS_FILE) as f:
            data = json.load(f)
        saved_at = datetime.fromisoformat(data.get("saved_at", "2000-01-01"))
        if (datetime.now() - saved_at).total_seconds() > 3600:
            return {}
        result = {}
        for sid, s in data.get("sessions", {}).items():
            saved_state = s.get("state", "idle")
            last_act = datetime.fromisoformat(s.get("last_activity", datetime.now().isoformat()))
            age = (datetime.now() - last_act).total_seconds()
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
                pid=s.get("pid", 0),
                detected_via=s.get("detected_via", "hook"),
            )
        return result
    except Exception as e:
        print(f"[Sessions] Load failed: {e}", file=sys.stderr)
        return {}
