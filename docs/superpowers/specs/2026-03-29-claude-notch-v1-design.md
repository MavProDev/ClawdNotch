# Claude Notch v1.0 — Design Spec

**Date:** 2026-03-29
**Author:** @ReelDad + Claude
**Status:** Approved

---

## Overview

Upgrade Claude Notch from a functional prototype to a polished, open-source release. Fix existing bugs, add 8 major features inspired by the macOS competitors (Notchi, Notchy, AgentNotch), and prepare for GitHub launch.

**Non-goal:** Do not break existing functionality. All changes are additive or targeted fixes.

---

## 1. Bug Fixes

### 1a. UsagePoller Token Waste

**Problem:** `UsagePoller._poll()` sends a real `POST /v1/messages` to Haiku every 60 seconds just to read rate limit headers. This burns tokens.

**Fix:** Replace with `GET https://api.anthropic.com/v1/models` which returns rate limit headers (`anthropic-ratelimit-*`) without consuming tokens. If the response doesn't include rate headers, try `POST` with `max_tokens: 1` as fallback but increase interval to 5 minutes.

### 1b. No PyQt6 Import Guard

**Problem:** If PyQt6 isn't installed, the script crashes with an ugly traceback.

**Fix:** Wrap PyQt6 imports in a try/except at module level. If missing, print a friendly message and exit:
```
Claude Notch requires PyQt6. Install with: pip install PyQt6>=6.6.0
```

### 1c. Bare except:pass Blocks

**Problem:** ~15 bare `except: pass` blocks hide errors silently.

**Fix:** Replace with `except Exception:` and add `print(f"[Component] {e}")` to stderr for debuggability. Keep the `pass` behavior (don't crash), just log. Only applies to blocks where the exception variable is useful — leave trivial ones (like `winsound.Beep` fallbacks) as-is.

---

## 2. Sentiment-Driven Clawd Emotions

### Architecture

New class: `EmotionEngine`
- Maintains per-session cumulative emotion scores: `happy`, `sad`, `neutral`
- Receives prompt text from `UserPromptSubmit` hook events
- Outputs one of: `neutral`, `happy`, `sad`, `sob`

### Scoring

**Local heuristic (always runs, no API needed):**
- ALL CAPS words → intensity +0.2
- Exclamation marks (3+) → happy +0.3
- Positive keywords ("awesome", "perfect", "works", "nice", "great", "love", "amazing", "finally") → happy +0.4
- Positive profanity ("fucking awesome", "hell yeah") → happy +0.5
- Negative keywords ("bug", "error", "broken", "wrong", "fail", "crash", "stuck", "hate") → sad +0.4
- Negative profanity ("what the fuck", "goddamn") → sad +0.5
- Question marks only → neutral +0.2
- Short prompts (<10 chars) → neutral +0.1

**Score accumulation:**
- New score applied with 0.5 dampening: `score[emotion] += intensity * 0.5`
- Cross-emotion decay: other emotions *= 0.9
- Timer decay: every 60 seconds, all scores *= 0.92
- Neutral counter-decay: neutral score *= 0.85 (returns to baseline faster)

**Thresholds:**
- happy > 0.6 → happy state
- sad > 0.45 → sad state
- sad > 0.9 → sob state (escalation)
- else → neutral

### Clawd Visual Changes

All changes are tint/position modifications to existing pixel art — no new sprite sheets:

| State | Bounce | Tint | Legs | Extra |
|-------|--------|------|------|-------|
| neutral | normal (sin wave) | default coral | normal | — |
| happy | 1.5x speed, +2px amplitude | brighter coral (235,155,120) | normal | — |
| sad | 0.5x speed | desaturated (180,130,120) | droop: legs Y +1px | eye Y +0.5 |
| sob | 0.3x speed | reddish (200,100,90) | tucked: legs Y +2px | tremble: random +-0.3px at 30fps |

### Hook Update

The PowerShell hook script must forward the user's prompt text. Add `user_prompt` field to the JSON payload, extracted from `$p.user_prompt` or `$p.content` (whichever Claude Code provides). Truncate to 500 chars.

### Integration

- `EmotionEngine` instantiated in `main()`, passed to `SessionManager`
- `SessionManager.handle_event()` calls `self._emotion.process(sid, prompt_text)` on `UserPromptSubmit`
- `Session` gets `emotion: str` field (default "neutral")
- `draw_clawd()` reads `emotion` from the active session to adjust rendering
- Emotion decay timer: `QTimer` in `ClaudeNotch`, fires every 60s, calls `emotion_engine.decay_all()`

---

## 3. Real Dollar Cost Estimates

### Pricing Table

```python
MODEL_PRICING = {
    "opus":   {"input": 15.0, "output": 75.0, "cache_read": 1.50},
    "sonnet": {"input": 3.0,  "output": 15.0, "cache_read": 0.30},
    "haiku":  {"input": 0.80, "output": 4.0,  "cache_read": 0.08},
}
```

### Changes to UsageTracker

- Add `est_cost_cents: float` to daily stats
- Each event's token estimate is split 40% input / 60% output (rough Claude Code average)
- Cost = `(input_tokens * input_price + output_tokens * output_price) / 1_000_000`
- Default model: `"sonnet"` (configurable in config as `default_model`)

### Changes to TOKEN_ESTIMATES

Add cost calculation alongside token counts:
```python
def _estimate_cost(self, tokens: int) -> float:
    pricing = MODEL_PRICING.get(self._model, MODEL_PRICING["sonnet"])
    input_tok = tokens * 0.4
    output_tok = tokens * 0.6
    return (input_tok * pricing["input"] + output_tok * pricing["output"]) / 1_000_000
```

### Display

- Big coral number area gets a third stat: `$X.XX` today
- Monthly line: `~$38.20 this month`
- Format: `$0.00` for <$1, `$X.XX` for <$100, `$XXX` for >$100

### Config

- `default_model`: "sonnet" | "opus" | "haiku" — added to DEFAULT_CONFIG
- Dropdown in SettingsDialog

---

## 4. Todo List Display

### Hook Update

Update PowerShell hook script to include `tool_input` in the JSON payload:
```
tool_input=if($p.tool_input){($p.tool_input|ConvertTo-Json -Compress).Substring(0,4096)}else{""}
```

Truncated to 4KB to prevent TCP message bloat.

### TodoManager

New lightweight class (not a full manager — just a parser + store):

```python
class TodoManager:
    def __init__(self):
        self.todos = {}  # session_id -> list of {id, text, status}

    def process_tool_event(self, session_id, tool_name, tool_input):
        if tool_name in ("TodoWrite", "TaskCreate", "TaskUpdate"):
            # Parse and update todos for this session
            ...

    def get_todos(self, session_id) -> list:
        return self.todos.get(session_id, [])
```

Parses `TodoWrite` input for `todos` array with `id`, `content`/`subject`, `status` fields.
Also handles `TaskCreate` and `TaskUpdate` tool names (same concept, different naming).

### Display

New section in expanded panel, between Sessions and Usage:
- Header: "Tasks" with count badge (e.g., "Tasks  3/7")
- Each item: status dot (amber=pending, green=completed, coral=in_progress) + truncated text (max 50 chars)
- Max 6 items shown, sorted: in_progress first, then pending, then completed
- **Only shown if there are todos.** No empty state — section is hidden when empty.

---

## 5. Permission / Attention Display

### Approach

Use existing `waiting` state (triggered by `Notification` hook event). No new hook data needed.

### Collapsed Notch Changes

When any session is in `waiting` state:
- Status text changes from project name to **"Needs input!"** in coral
- Clawd tint goes coral (already happens)
- Status dot pulses with larger radius (already happens)

### Expanded Panel Changes

When a session is `waiting`:
- Session row gets a coral background highlight (subtle, `QColor(217,119,87,25)`)
- State text shows **"waiting for input"** instead of just "waiting"
- If we have the tool name that triggered waiting, show it: "waiting — AskUserQuestion"

### No New Classes

Just UI changes in `_pcol()` and `_pexp()`.

---

## 6. Sound Auto-Mute When IDE Focused

### Detection

```python
def _is_terminal_focused() -> bool:
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
    title = buf.value.lower()
    patterns = [
        "windows terminal", "command prompt", "cmd.exe", "powershell",
        "visual studio code", "cursor", "windsurf", "zed",
        "wezterm", "alacritty", "hyper", "kitty", "tabby",
        "intellij", "pycharm", "webstorm", "rider",
        "claude", "terminal"
    ]
    return any(p in title for p in patterns)
```

### Integration

- `NotificationManager` checks `_is_terminal_focused()` before playing any sound
- If focused → skip sound, still send toast notification (user might glance at corner)
- Config toggle: `auto_mute_when_focused: true` (default True)
- New checkbox in SettingsDialog: "Mute sounds when terminal/IDE is focused"

---

## 7. Git Checkpoints

### Mechanism

Uses detached git commits in custom refs (same technique as Notchy):

```
refs/claude-notch/snapshots/{project_name}/{timestamp}
```

**Process:**
1. Create temp index file
2. `GIT_INDEX_FILE={temp} git add -A` in project dir
3. `git write-tree` → tree hash
4. `git commit-tree {tree} -m "Claude Notch snapshot {timestamp}"` → commit hash
5. `git update-ref refs/claude-notch/snapshots/{name}/{timestamp} {commit}`
6. Delete temp index

**Restore:**
```
git checkout {commit_hash} -- .
```

### Trigger

- Global hotkey: `Ctrl+Shift+S`
- Only works if there's an active session with a `project_dir` that's a git repo
- Toast notification: "Checkpoint saved for {project}"

### UI

- System tray menu → "Snapshots >" submenu
- Lists last 10 snapshots with timestamp + project name
- Click to restore (with confirmation dialog: "Restore snapshot from {time}? This will overwrite working directory files.")
- "Clear All Snapshots" option at bottom

### Class

```python
class GitCheckpoints:
    @staticmethod
    def create(project_dir: str) -> bool: ...
    @staticmethod
    def list_snapshots(project_dir: str) -> list[dict]: ...
    @staticmethod
    def restore(project_dir: str, commit_hash: str) -> bool: ...
    @staticmethod
    def clear(project_dir: str) -> bool: ...
```

All git operations via `subprocess.run()` with `capture_output=True, timeout=10`.

---

## 8. Glow Border Effect

### Implementation

When expanded (`t > 0.5`), draw a rotating gradient border around the panel.

**Gradient:** Angular sweep using `QConicalGradient` centered on the panel:
- Stop 0.0: `QColor(217,119,87, alpha)` (coral)
- Stop 0.33: `QColor(235,155,120, alpha)` (coral_light)
- Stop 0.66: `QColor(217,119,87, alpha)` (coral)
- Stop 1.0: `QColor(235,155,120, alpha)` (coral_light)

**Rotation:** Offset stops by `self._pulse * 0.3` (mod 1.0) for ~3 second rotation.

**Activity-linked opacity:**
- Working: alpha = 180
- Waiting: alpha = 140 (pulsing)
- Idle: alpha = 40
- No sessions: alpha = 20

**Rendering:** Draw the panel path twice:
1. First pass: 2px wider path with gradient pen (the glow)
2. Second pass: normal path with solid fill (covers the glow interior)

No triple shadow layers — that's expensive. Single gradient border is sufficient.

### Performance

- Only draw when `t > 0.5` (past halfway through expand animation)
- Uses existing `self._pulse` counter — no new timers
- `QConicalGradient` is GPU-accelerated on Windows via DirectWrite

---

## 9. Context Progress Bar

### Per-Session Token Tracking

Add to `Session` dataclass:
```python
session_tokens: int = 0
context_limit: int = 200_000  # default 200k
```

Increment `session_tokens` in `SessionManager.handle_event()` using the same `TOKEN_ESTIMATES` dict.

### Display

Thin 3px bar rendered below each session row in the expanded panel:
- Background: `card_bg`
- Fill: gradient based on percentage:
  - 0-50%: green
  - 50-80%: amber
  - 80-95%: coral
  - 95%+: red
- Text overlay (right-aligned, 6pt): "~45k / 200k"

### Token Formatting

```python
def fmt_tokens(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.0f}k"
    return str(n)
```

---

## 10. GitHub & Launch Prep

### Files to Add

- `LICENSE` — MIT, copyright 2026 @ReelDad
- `.gitignore` — Python defaults, `.claude-notch/`, `dist/`, `build/`, `*.exe`, `__pycache__/`, `.env`
- `CHANGELOG.md` — v1.0.0 initial release
- `__version__` — Add `__version__ = "1.0.0"` to top of claude_notch.py, display in expanded panel footer

### README Updates

- Add badges: Python 3.10+, MIT license, Windows 10/11
- Add comparison table vs macOS alternatives
- Add screenshot/GIF placeholder (user provides later)
- Add "Features" section highlighting the 8 new features
- Add "Contributing" section (standard open-source boilerplate)

### Hook Script Update Summary

The PowerShell hook script needs two new fields:
- `user_prompt`: from `$p.user_prompt` or `$p.content`, truncated to 500 chars
- `tool_input`: from `$p.tool_input`, JSON stringified, truncated to 4096 chars

Users must re-run "Install Claude Code Hooks" after updating.

---

## Implementation Order

1. Bug fixes (1a, 1b, 1c) — foundation, don't break anything
2. Hook script update — needed for features 2 and 4
3. EmotionEngine + Clawd emotion rendering (feature 2)
4. Cost estimates in UsageTracker (feature 3)
5. TodoManager + display (feature 4)
6. Permission/attention UI (feature 5)
7. Sound auto-mute (feature 6)
8. Git checkpoints (feature 7)
9. Glow border effect (feature 8)
10. Context progress bar (feature 9)
11. GitHub prep (feature 10)

Each step is independently testable and doesn't depend on later steps.
