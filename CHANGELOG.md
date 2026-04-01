# Changelog

## [4.0.0] - 2026-04-01

### Architecture Overhaul — ui.py split, session dedup, context bar fix, 3 new modules

#### Critical Bug Fixes
- **Ghost/duplicate session detection** — Process scanning created "unknown" ghost sessions that duplicated hook-detected sessions. Now merges process PIDs into existing hook sessions by project directory matching instead of creating duplicates. Sessions without project info are hidden from the display.
- **Context bar overflow** — Context bar showed lifetime tokens (e.g. "3019k / 200k") which was meaningless. Now shows "X.XM total" when tokens exceed the context limit, and "Xk / 200k" only when within a single context window.
- **"unknown" session names** — Process-detected sessions with no project now show "PID XXXX" instead of "unknown". Non-displayable ghost sessions are filtered from the session list entirely.

#### Architecture
- **Split `ui.py` (2,694 lines) into `ui/` package** — 6 focused sub-modules:
  - `ui/clawd.py` — Clawd mascot renderer, color utilities, `_lerp_color` (extracted from nested function)
  - `ui/toast.py` — ClawdToast branded notification popup
  - `ui/splash.py` — Terminal-style boot splash screen (now uses configurable port in loading text)
  - `ui/settings.py` — SettingsDialog + shared `open_settings_dialog()` helper (deduplicated)
  - `ui/notch.py` — Main ClaudeNotch overlay widget
  - `ui/tray.py` — System tray icon and menu
  - `ui/__init__.py` — Re-exports for backward compatibility
- **Extracted `token_aggregator.py`** — TokenAggregator moved from usage.py to own module. Now skips `proc-XXXX` session IDs (no JSONL files for those).
- **Extracted `update_checker.py`** — GitHub release checker moved from usage.py to own module.
- **Added `pyproject.toml`** — Centralizes version, deps, metadata, and tool config.
- All existing imports continue to work via re-exports.

#### Session Management
- `SessionManager._projects_match()` — New method for flexible project directory matching (exact path, then basename).
- `SessionManager._find_matching_hook_session()` — Finds existing hook sessions by PID or project directory.
- `Session.is_displayable` property — Filters out process-detected noise from the UI.
- `handle_event()` now merges with existing process-detected sessions instead of creating duplicates.
- `scan_processes()` now tries to assign PIDs to existing hook sessions before creating new entries.
- `cleanup_dead()` more aggressively removes process ghosts with no project (2 min timeout).
- Session state now persists PID and detected_via across restarts.

#### Cleanup
- Deleted `files.zip` (unreferenced 11KB binary in repo root)
- Deleted root `__pycache__/` (dead bytecache from old monolith)
- Fixed `.gitignore` — `*.spec` no longer ignored (ClawdNotch.spec is intentionally tracked)
- Moved `import re` to module level in `system_monitor.py` (was inside function body)
- Splash screen loading text now shows actual configured port instead of hardcoded 19748

#### Additional Bug Fixes
- **Settings dialog crash** — Opening settings from tray after a previous settings dialog was closed caused a segfault. Root cause: `WA_DeleteOnClose` destroys the C++ widget but Python keeps a stale pointer. Fixed by using `finished` signal + explicit `deleteLater()` instead of `WA_DeleteOnClose`.
- **Mini mode rendering** — 6 code paths used hardcoded `HW`/`HH`/`VW`/`VH` constants instead of the `nw`/`nh` properties that respect mini mode. Clawd, status dot, text overlay, edge detection, eye tracking, and tray reset all painted outside the 28x28 widget bounds. All fixed to use `nw`/`nh`.
- **Tray settings hidden behind notch** — Settings dialog from tray was invisible behind the always-on-top expanded notch. Now force-collapses the notch before opening settings.

#### Stats
- **68 tests, all passing** (zero breakage from the split)
- Source: 5,262 lines → 10 modules + 6 ui sub-modules (16 total)
- `ui.py` eliminated: 2,694 lines → 6 files averaging 270 lines each
- `usage.py` trimmed: 747 lines → 517 lines + 2 extracted modules

## [3.1.0] - 2026-03-31

### Deep Dive Audit — 9 fixes, 18 new tests, 8 files changed

#### Security
- **DPAPI encryption** for API keys at rest — keys stored as encrypted blobs in config.json using Windows CryptProtectData. Zero new dependencies. Existing plaintext keys auto-migrated on startup.

#### Performance
- **Adaptive tick rate** — overlay drops from 30fps to 10fps when collapsed and idle, saving CPU. Ramps back to 30fps during animation or active sessions.
- **Font caching** — 13 QFont objects cached as class constants. Eliminates ~900 QFont allocations/second during paint.
- **ConfigManager lock scope** — file I/O now happens outside the threading lock, preventing potential UI thread blocks on slow disks.

#### Features
- **Real per-session token tracking** — context bar now shows actual token counts from Claude Code JSONL files (not rough estimates). JSONL filenames correlate directly with session IDs.
- **Toast restacking** — dismissing a toast smoothly repositions remaining toasts to close the gap instead of leaving a dead space.
- **Settings QScrollArea** — Settings dialog now scrollable on 1080p screens. Custom styled scrollbar matches dark theme.

#### Architecture
- **PS1 template extraction** — PowerShell hook script moved from embedded f-string to `claude_notch_hook.ps1.template`. Now lintable, testable, and debuggable independently.
- **Event handler dict dispatch** — `SessionManager.handle_event` refactored from 70-line if/elif chain to method dispatch via dict lookup. Cleaner, more extensible.
- **Safer hook merge** — settings.json cleanup now checks the `command` field specifically instead of string-matching entire hook dicts.

#### Tests
- 18 new tests (68 total): TokenAggregator JSONL parsing, per-session lookup, caching, DPAPI encrypt/decrypt roundtrip, ClawdToast lifecycle/stacking/restack, check_for_updates with mocked HTTP.

## [3.0.0] - 2026-03-30

### Architecture
- Split 2,757-line monolith into 10-module Python package (`claude_notch/`)
- Modules: config, sessions, hooks, usage, notifications, system_monitor, git_checkpoints, ui, __main__
- No circular imports — clean dependency graph

### Added
- **Booping spinner** — Claude Code's exact `· ✻ ✽ ✶ ✳ ✢` animation with 90 thinking words
- **Splash screen** — terminal-style matrix boot on every launch, animated Clawd, contact info
- **First-run welcome** — auto-detect missing hooks, one-click install button
- **50 tests** — unit, integration, smoke, and UI screenshot tests (pytest + pytest-qt)
- **GitHub Actions CI** — lint (ruff) + test on every push/PR
- **GitHub Actions Release** — PyInstaller .exe build on version tags, auto-uploaded to Releases
- **Contact info** — @ReelDad, MavProGroup@gmail.com in splash and README

### Fixed (20 bugs from audit)
- **Bug #1**: ConfigManager now thread-safe (added threading.Lock)
- **Bug #3**: Removed dead `was_expanded` config write
- **Bug #4**: Monthly budget alerts now functional (were silently ignored)
- **Bug #5**: Fixed 64-bit ctypes types for HWND/LPARAM in EnumWindows
- **Bug #7**: Bar text contrast improved with dark shadow (WCAG AA)
- **Bug #8**: Lock file TOCTOU documented
- **Bug #9**: `install_hooks` now writes `~/.claude/settings.json` atomically
- **Bug #10/11**: Desktop path no longer hardcodes OneDrive
- **Bug #12**: Collapsed text truncation now uses dynamic QFontMetrics
- **Bug #13**: Process scan cached with 10s TTL (was spawning PowerShell every 15s)
- **Bug #14**: Bare `except` in SettingsDialog._check() → `except Exception`
- **Bug #15**: create_shortcut.py config write now atomic
- **Bug #20**: Streak counter behavior documented

### Changed
- Launcher uses `python -m claude_notch` (survives folder moves)
- README rewritten for public launch — fun tone, quick start, feature grid
- Process scan interval increased from 15s to 30s
- Version bumped to 3.0.0

## [2.0.0] - 2026-03-30

### Added
- **Color themes** — 8 accent colors (coral, blue, green, purple, cyan, amber, pink, red) with toggle in settings
- **Click-to-focus** — click a session row to bring that terminal window to the foreground
- **Sparkline graph** — 30-minute activity chart in usage section and collapsed view
- **Custom notification sounds** — pick .wav files for completion and attention events
- **Cost budget alerts** — set daily/monthly budget, get toast notification at 80%
- **Session time estimates** — shows estimated time remaining based on historical average
- **Export usage reports** — markdown or CSV report saved to Desktop from tray or expanded panel
- **Notification history** — scrollable log of recent notifications in expanded panel
- **Floating mini-mode** — ultra-compact 28x28 collapsed state showing just Clawd + status dot
- **Copy-to-clipboard** — click session to copy project path
- **Coding streaks** — tracks consecutive active days and top day this week
- **System resource overlay** — CPU and RAM usage bars in expanded panel
- **DND mode** — Do Not Disturb toggle (Ctrl+Shift+D) mutes all sounds and toasts
- **Dim when inactive** — notch fades to 55% opacity when no sessions active (not invisible)
- **Multi-monitor support** — snaps to the correct edge on any screen
- **Periodic session save** — sessions saved every 60s (survives crashes)
- **All features have toggles** in the scrollable Settings dialog
- **Stable launcher** — shortcut points to ~/.claude-notch/launcher.pyw, survives folder moves

### Fixed
- Desktop shortcut breaks when project folder is moved (now uses stable launcher)
- Auto-start registry entry breaks on folder move (now uses launcher)
- `wmic` process detection replaced with PowerShell `Get-CimInstance` (wmic deprecated on Win11)
- `tempfile.mktemp()` replaced with `tempfile.mkstemp()` in GitCheckpoints (security fix)
- Bare `except: pass` in UsageTracker._load() now logs errors to stderr
- Dead config key `notch_opacity` cleaned up during migration
- Context limit now model-aware (200k standard, 1M extended)

### Changed
- Version bumped to 2.0.0
- Settings dialog now scrollable with categorized sections
- Session manager tracks completed session durations for estimates
- Collapsed view shows mini sparkline when enabled
- DND button added to expanded panel title bar
- Export button added to expanded panel footer
- Tray menu includes DND toggle and Export option

## [1.0.0] - 2026-03-29

### Added
- Sentiment-driven Clawd emotions (happy, sad, sob states based on prompt analysis)
- Real dollar cost estimates per day and month (Opus/Sonnet/Haiku pricing)
- Todo list display (parses TodoWrite/TaskCreate events from Claude Code)
- Permission/attention UI (coral highlight + "Needs input!" for waiting sessions)
- Sound auto-mute when terminal/IDE is focused
- Git checkpoints (Ctrl+Shift+S to snapshot, restore from system tray)
- Glow border effect (rotating coral gradient when expanded, activity-linked)
- Context progress bar per session (color-coded token usage vs 200k limit)

### Fixed
- UsagePoller no longer burns API tokens (uses GET /v1/models instead of POST /v1/messages)
- PyQt6 import guard shows friendly install message instead of traceback
- Better error logging to stderr for debugging (replaces bare except:pass)

### Changed
- Hook script now forwards user_prompt and tool_input fields
- Expanded panel height increased to accommodate new sections
- Cost shown alongside tool calls and prompts in daily stats
- Rate limits demoted to compact secondary line
