# ClawdNotch v3.0 — Production Release Design Spec

**Date:** 2026-03-30
**Author:** @ReelDad + Claude
**Status:** Approved
**Repo:** https://github.com/MavProDev/ClawdNotch

---

## Overview

Transform the working v2.0 single-file prototype (2,757 lines) into a production-grade, publicly releasable open-source project. Ship as a standalone `.exe` from GitHub Releases with automated CI/CD, full test suite, and polished first-run experience.

**Non-goals:** PyPI package, macOS/Linux support, web dashboard.

---

## 1. Module Split

Split `claude_notch.py` (2,757 lines) into a proper Python package. Every function, class, and constant has an explicit home.

```
claude_notch/
    __init__.py          # __version__ = "3.0.0"
    config.py            # ConfigManager, DEFAULT_CONFIG, THEMES, MODEL_CONTEXT_LIMITS,
                         #   MODEL_PRICING, TOKEN_ESTIMATES, SESSION_TINTS, C (color dict),
                         #   apply_theme(), _atomic_write(), _redact_key(),
                         #   HOOK_SERVER_PORT, CONFIG_DIR, CONFIG_FILE, LOCK_FILE
    sessions.py          # Session (dataclass), SessionManager, EmotionEngine,
                         #   SESSIONS_FILE, _save_sessions_state(), _load_sessions_state()
    hooks.py             # HookServer, install_hooks()
    usage.py             # UsageTracker, UsagePoller, SparklineTracker, StreakTracker,
                         #   TodoManager, export_usage_report(), USAGE_FILE
    notifications.py     # NotificationManager, NotificationHistory
                         #   (imports _is_terminal_focused from system_monitor)
    system_monitor.py    # SystemMonitor, _is_terminal_focused(), _find_claude_windows(),
                         #   _find_claude_processes(), _focus_window_by_pid(),
                         #   acquire_lock(), release_lock(), set_auto_start()
    git_checkpoints.py   # GitCheckpoints (all @staticmethod, no internal imports)
    ui.py                # ClaudeNotch, SplashScreen, SettingsDialog, draw_clawd(),
                         #   make_tray(), CLAWD pixel grid, EMOTION_STYLES,
                         #   THINKING_WORDS, SPINNER_FRAMES, STATUS_COLORS,
                         #   all painting methods
    __main__.py          # main() entry point — creates all, wires signals, runs app
```

### Import dependency graph (no cycles)
```
config.py          ← imports nothing from package (foundation)
git_checkpoints.py ← imports nothing from package
system_monitor.py  ← imports from config
notifications.py   ← imports from config, system_monitor
usage.py           ← imports from config
sessions.py        ← imports from config (TOKEN_ESTIMATES, MODEL_CONTEXT_LIMITS)
hooks.py           ← imports from config
ui.py              ← imports from ALL modules (top of dependency tree)
__main__.py        ← imports from ALL modules (wiring layer)
```

### Migration strategy (avoids name collision)

The old `claude_notch.py` will be renamed to `claude_notch_v2_backup.py` BEFORE creating the `claude_notch/` package directory. This prevents Python's import system from being confused by a file and directory with the same name coexisting. The backup is deleted once the split is verified working.

Additionally, `create_shortcut.py`'s launcher at `~/.claude-notch/launcher.pyw` will be updated to run `python -m claude_notch` instead of `python claude_notch.py`, so it works with the package structure.

### Bug fixes applied during extraction

Each bug is fixed as its containing code moves to the new module. Bug fixes are NOT a separate step — they happen inline during extraction.

---

## 2. Bug Fixes (20 found in audit, all resolved)

### HIGH priority:

| # | Bug | Fix | Module |
|---|-----|-----|--------|
| 4 | `budget_monthly` configured in UI but never checked | Add monthly budget check in `handle_event`, comparing `month_stats.est_cost` against `budget_monthly * 0.8`. Same once-per-threshold pattern as daily. | sessions.py |
| 9 | `install_hooks` writes `~/.claude/settings.json` non-atomically | Use `_atomic_write` pattern (mkstemp + os.replace). This is Claude Code's own config. | hooks.py |
| 5 | Wrong ctypes types for HWND/LPARAM on 64-bit | Change `ctypes.POINTER(ctypes.c_int)` to `wintypes.HWND` and `wintypes.LPARAM` in both EnumWindows callbacks | system_monitor.py |

### MEDIUM priority:

| # | Bug | Fix | Module |
|---|-----|-----|--------|
| 3 | `was_expanded` written but never read | Remove the dead write in cleanup(). Auto-expanding on startup would be jarring. | __main__.py |
| 7 | Bar text contrast fails WCAG AA on filled bars | Add 1px dark text shadow (`QColor(0,0,0,120)`) behind bar text for contrast | ui.py |
| 13 | PowerShell process scan every 15s = CPU spikes | Increase to 30s. Cache results with 10s TTL. | system_monitor.py |
| 14 | Bare `except` in `SettingsDialog._check()` | Change to `except Exception:` | ui.py |

### LOW priority:

| # | Bug | Fix | Module |
|---|-----|-----|--------|
| 1 | ConfigManager not thread-safe | Add `threading.Lock`, wrap `get()`/`set()`/`save()` | config.py |
| 8 | Lock file race condition | Accept risk. Add comment documenting the known TOCTOU. | system_monitor.py |
| 10/11 | Desktop path hardcodes OneDrive | Use `Path.home() / "Desktop"` with `os.path.exists` fallback | config.py (export), system_monitor.py (shortcut) |
| 12 | Fixed 34-char text truncation in collapsed view | Use `QFontMetrics.horizontalAdvance` for dynamic width | ui.py |
| 15 | `create_shortcut.py` writes config non-atomically | Import and use `_atomic_write` from `claude_notch.config` | create_shortcut.py |
| 20 | Streak counter ambiguity for today | Document: "counts today if active, otherwise starts from yesterday" | usage.py (docstring) |

### WON'T FIX (verified non-issues):

| # | Reason |
|---|--------|
| 2 | Qt auto-marshals cross-thread signals via queued connection — safe |
| 6 | Hook `{"hooks": [...]}` wrapper is correct format (verified against live settings.json) |
| 16 | tasks_completed capped at 20/session, get_all_tasks has limit param |
| 17 | Easing math inputs are clamped [0,1] — safe |
| 18 | Emotion intensity after dampening stays reasonable |
| 19 | Hover/collapse timer interaction traced and confirmed correct |

---

## 3. New Feature: "Booping" Spinner

### Spinner animation (exact Claude Code match)
- **Frames:** `· ✻ ✽ ✶ ✳ ✢` (6 characters)
- **Timing:** 333ms per frame (2-second full cycle)
- **Step animation:** Discrete frame jumps, not smooth

### Thinking words (all 90 Claude Code words)
```python
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
```

### Placement

**Collapsed (horizontal 300x34):** Replace status text with `"ProjectName: ✶ Booping…"` when working.
**Collapsed (vertical 34x200):** Spinner character only, below the status dot.
**Mini mode (28x28):** Skip — no room.
**Expanded panel:** Session row state text becomes `"✶ Booping…"` when working.

### Implementation

New field on `Session`: `thinking_word: str = ""`

State transition logic in `SessionManager.handle_event`:
```python
if s.state != "working":  # only pick new word on state TRANSITION
    s.thinking_word = random.choice(THINKING_WORDS)
s.state = "working"
```

Spinner frame calculation (corrected — `_pulse` increments 0.1/tick at 33ms = ~1.0 per 330ms):
```python
SPINNER_FRAMES = ["·", "✻", "✽", "✶", "✳", "✢"]
frame_idx = int(self._pulse) % len(SPINNER_FRAMES)  # 1 frame per ~330ms
spinner_char = SPINNER_FRAMES[frame_idx]
```

**Note:** The original formula `int(self._pulse * 5) % 6` was wrong — it produced backward-cycling frames. The corrected formula `int(self._pulse) % 6` gives clean forward progression at the right speed.

---

## 4. Splash Screen / Welcome Dialog

### Technical approach

A frameless `QWidget` (NOT QDialog) with `WA_TranslucentBackground`. This avoids QDialog's modal behavior and gives full painting control.

### Z-ordering strategy

The splash and notch are both `WindowStaysOnTopHint`, which makes z-order unpredictable on Windows. To solve this:
1. Create the notch widget but do NOT show it yet
2. Show the splash
3. When splash finishes (fade-out complete or skipped), call `notch.show()`
4. This guarantees the notch appears after the splash — no z-fighting

### Design

- **Background:** `#0C0C0E` (notch_bg), rounded corners, 1px coral border with glow
- **Dimensions:** 480x360, centered on screen
- **Skippable:** Click anywhere or press Escape — immediate dismiss

### Content (top to bottom)

1. **Animated Clawd** — pixel size 4.0, bouncing, green glow eyes, centered
2. **"ClawdNotch"** — 24pt Segoe UI Bold, coral
3. **"v3.0.0"** — 10pt, text_lo
4. **Terminal loading area** — Consolas 10pt, lines appear with 200-300ms delay:
   ```
   [·] Initializing hook server on :19748...
   [✻] Loading session state...
   [✽] Scanning for Claude processes...
   [✶] Applying theme: coral
   [✳] ClawdNotch v3.0.0 ready. Let's go.
   ```
   (Each line's bracket char is the next spinner frame)
5. **Contact** — 9pt text_lo: `"@ReelDad  ·  MavProGroup@gmail.com  ·  Bugs? Ideas? Don't hesitate to reach out."`

### First-launch mode (hooks not installed)

After loading sequence, show instead of auto-dismissing:
- **"Install Hooks & Start"** button (coral, centered)
- **"Skip"** text link below
- Install button runs `install_hooks()`, shows brief success, then dismisses

### Subsequent launches

- Loading plays (~2-3 seconds, faster at 150ms/line if auto-start)
- 500ms pause after last line
- Fade out: opacity 1.0 → 0.0 over 300ms via `setWindowOpacity()` + QTimer
- On fade complete: `splash.close()`, `notch.show()`

---

## 5. Settings Dialog Improvements

**Already fixed this session:** Centered on screen, no longer spawning at (0,0).

**v3 additions:**
- Make resizable (min 480x400, max 700x900)
- Remember last size/position in config

---

## 6. README Rewrite

Fun, confident tone. Not corporate. Structure:

1. Hero — name + one-liner + GIF placeholder
2. What is this? — 2-3 sentences
3. Quick Start — Download exe → double-click → install hooks → done
4. Features — 6-8 key features with emoji bullets
5. Screenshots — collapsed, expanded, settings (placeholders for now)
6. Configuration — `~/.claude-notch/config.json`
7. Building from source — `pip install -r requirements.txt && python -m claude_notch`
8. Credits — @ReelDad, inspired by Notchy/Notchi
9. Contact — MavProGroup@gmail.com, @ReelDad on X
10. License — MIT

---

## 7. Testing

### Test framework: pytest + QWidget.grab() for UI

**Critical note:** Playwright CANNOT test PyQt6 desktop widgets. Playwright is for web browsers. For UI screenshot testing, we use `QWidget.grab()` which returns a `QPixmap` of the widget, save to PNG, and compare against reference screenshots using pixel-level tolerance.

### Test files (~55 tests total)

```
tests/
    conftest.py              # QApplication fixture (shared singleton), temp config dir,
                             #   temp usage dir, mock hook events, temp git repo fixture
    test_config.py           # ConfigManager: defaults, migration, save/load, thread safety,
                             #   theme application, _atomic_write rollback on failure
    test_sessions.py         # Session: all properties (project_name, age_str, age_minutes,
                             #   is_stale, tint). SessionManager: event handling, state
                             #   transitions, cleanup_dead logic, scan_processes data structure,
                             #   save_state/restore_state round-trip, avg_session_minutes,
                             #   budget alert fires once not repeatedly
    test_emotion.py          # EmotionEngine: positive/negative/profanity scoring, decay,
                             #   sob threshold, short prompt → neutral, caps modifier
    test_usage.py            # UsageTracker: record/flush, cost estimation, day rollover,
                             #   90-day pruning. SparklineTracker: record timing, minute
                             #   rollover, get_data returns correct length.
                             #   StreakTracker: current_streak consecutive days,
                             #   top_day_this_week tuple format.
    test_todos.py            # TodoManager: TodoWrite/TaskCreate/TaskUpdate parsing,
                             #   remove_session, ordering by status
    test_notifications.py    # NotificationManager: DND suppresses all, auto-mute logic,
                             #   history recording, custom sound path validation
    test_system_monitor.py   # SystemMonitor: get_ram returns dict with pct/used_gb/total_gb,
                             #   get_cpu returns float, update_cpu doesn't crash.
                             #   _find_claude_processes returns list of dicts.
    test_git_checkpoints.py  # GitCheckpoints: is_git_repo on temp repo, create+list+restore
                             #   round-trip, clear removes refs
    test_hooks.py            # HookServer: accepts TCP, parses JSON, emits signal.
                             #   install_hooks: writes ps1 file, modifies settings.json atomically
    test_export.py           # export_usage_report: generates valid markdown and CSV
    test_smoke.py            # QApplication + ClaudeNotch instantiation + show + close.
                             #   Defensive: mock primaryScreen if None (headless CI)
    test_ui_screenshots.py   # QWidget.grab() based:
                             #   - Collapsed notch renders (not empty)
                             #   - Expanded panel renders (title visible)
                             #   - Mini-mode renders at 28x28
                             #   - Theme change affects accent color in grab
                             #   - Settings dialog opens centered
                             #   - Splash screen renders with Clawd
```

### requirements-dev.txt
```
pytest>=8.0
ruff>=0.4
pyinstaller>=6.0
pytest-qt>=4.2
```

Note: `playwright` and `pytest-playwright` removed — not applicable for desktop apps. Added `pytest-qt` which provides `qtbot` fixture for Qt widget testing.

---

## 8. Build & Distribution

### PyInstaller command (with hidden imports)
```bash
pyinstaller --onefile --noconsole --icon=clawd.ico --name=ClawdNotch \
  --hidden-import=plyer.platforms.win.notification \
  --hidden-import=winreg \
  --hidden-import=winsound \
  claude_notch/__main__.py
```

The icon is embedded in the .exe file metadata. At runtime, the tray icon is drawn programmatically via `draw_clawd()` — no bundled assets needed.

### GitHub Actions CI (.github/workflows/ci.yml)
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: python -m ruff check .
      - run: python -m pytest tests/ -v --timeout=30
```

### GitHub Actions Release (.github/workflows/release.yml)
```yaml
name: Release
on:
  push:
    tags: ['v*']
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r requirements.txt pyinstaller
      - run: >
          pyinstaller --onefile --noconsole --icon=clawd.ico --name=ClawdNotch
          --hidden-import=plyer.platforms.win.notification
          --hidden-import=winreg --hidden-import=winsound
          claude_notch/__main__.py
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/ClawdNotch.exe
          generate_release_notes: true
```

### CI considerations for headless Windows

- `QApplication.primaryScreen()` may return `None` on headless runners. Smoke tests mock screen geometry.
- `keyboard` module may need admin. Tests don't test hotkeys — they're optional at runtime via `try/except`.
- `plyer` notifications will fail silently on headless. Tests mock `toast_notify`.
- `winsound.Beep` may fail. Tests mock sound playback.

---

## 9. Implementation Order

Bug fixes happen DURING extraction (not as a separate step). Each step results in a working app.

1. **Rename `claude_notch.py` → `claude_notch_v2_backup.py`** — prevents import collision
2. **Create `claude_notch/` package** — `__init__.py` (version only), `__main__.py` (imports and runs main)
3. **Extract `config.py`** — ConfigManager + all constants + `_atomic_write` + `_redact_key` + thread lock fix (Bug #1)
4. **Extract `git_checkpoints.py`** — pure static methods, no deps, fixes tempfile (already done)
5. **Extract `system_monitor.py`** — SystemMonitor + process detection + lock + auto-start. Fix ctypes types (Bug #5), cache process scan (Bug #13)
6. **Extract `notifications.py`** — NotificationManager + NotificationHistory (imports `_is_terminal_focused` from system_monitor)
7. **Extract `usage.py`** — UsageTracker + UsagePoller + SparklineTracker + StreakTracker + TodoManager + export. Fix desktop path (Bug #10)
8. **Extract `sessions.py`** — Session + SessionManager + EmotionEngine + save/load state. Fix monthly budget (Bug #4), remove `was_expanded` (Bug #3)
9. **Extract `hooks.py`** — HookServer + install_hooks. Fix atomic write for settings.json (Bug #9)
10. **Extract `ui.py`** — ClaudeNotch + SettingsDialog + draw_clawd + make_tray + STATUS_COLORS. Fix bar contrast (Bug #7), text truncation (Bug #12), bare except (Bug #14)
11. **Wire `__main__.py`** — complete main() with all imports, signal wiring, timer setup
12. **Delete `claude_notch_v2_backup.py`** — verify app runs from package
13. **Update `create_shortcut.py`** — launcher uses `python -m claude_notch`, fix non-atomic write (Bug #15)
14. **Add "Booping" spinner** — THINKING_WORDS, SPINNER_FRAMES, Session.thinking_word, paint changes
15. **Add SplashScreen** — new class in ui.py, first-run detection, loading sequence, fade-out, z-ordering
16. **Write test suite** — all 55 tests across 12 test files
17. **Set up CI** — `.github/workflows/ci.yml` + `release.yml`, `requirements-dev.txt`
18. **Test PyInstaller locally** — build exe, verify all features work
19. **Rewrite README** — new tone, GIF placeholder, quick start
20. **Update CHANGELOG** — v3.0.0 entry
21. **Commit, tag, push** — `git tag v3.0.0 && git push --tags` → CI builds exe → GitHub Release
