# Changelog

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
