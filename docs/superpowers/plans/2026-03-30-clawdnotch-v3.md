# ClawdNotch v3.0 Production Release — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the 2,757-line single-file prototype into a production-grade open-source package with module split, 20 bug fixes, spinner animation, splash screen, 55 tests, CI/CD, and .exe build.

**Architecture:** Extract claude_notch.py into a 10-file Python package (claude_notch/). Fix 20 bugs inline during extraction. Add "Booping" spinner and splash screen. Write full test suite. Set up GitHub Actions CI + PyInstaller release pipeline.

**Tech Stack:** Python 3.12, PyQt6, pytest, pytest-qt, ruff, PyInstaller, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-03-30-clawdnotch-v3-production-design.md`

---

### Task 1: Module split — create package structure and extract all modules

**Files:**
- Rename: `claude_notch.py` → `claude_notch_v2_backup.py`
- Create: `claude_notch/__init__.py`, `config.py`, `sessions.py`, `hooks.py`, `usage.py`, `notifications.py`, `system_monitor.py`, `git_checkpoints.py`, `ui.py`, `__main__.py`

All 20 bug fixes applied inline during extraction. See spec Section 2 for complete bug list with fixes.

- [ ] Rename old file to prevent import collision
- [ ] Create package dir + `__init__.py` with version
- [ ] Extract `config.py` (Bug #1: add threading.Lock to ConfigManager)
- [ ] Extract `git_checkpoints.py` (tempfile already fixed)
- [ ] Extract `system_monitor.py` (Bug #5: fix ctypes types, Bug #13: cache process scan)
- [ ] Extract `notifications.py` (imports _is_terminal_focused from system_monitor)
- [ ] Extract `usage.py` (Bug #10: fix desktop path)
- [ ] Extract `sessions.py` (Bug #4: add monthly budget check, Bug #3: remove was_expanded)
- [ ] Extract `hooks.py` (Bug #9: atomic write for settings.json)
- [ ] Extract `ui.py` (Bug #7: bar contrast, Bug #12: dynamic truncation, Bug #14: bare except)
- [ ] Wire `__main__.py` with all imports and signal connections
- [ ] Verify: `python -m claude_notch` launches correctly
- [ ] Delete backup file
- [ ] Commit

### Task 2: Add "Booping" spinner

**Files:**
- Modify: `claude_notch/ui.py` (THINKING_WORDS, SPINNER_FRAMES, paint code)
- Modify: `claude_notch/sessions.py` (Session.thinking_word field, state transition logic)

- [ ] Add `thinking_word` field to Session dataclass
- [ ] Add random word selection on state transition to "working" in SessionManager
- [ ] Add THINKING_WORDS (90 words) and SPINNER_FRAMES to ui.py
- [ ] Update `_pcol` to show spinner in collapsed horizontal view
- [ ] Update `_pexp` to show spinner in session rows
- [ ] Verify visually
- [ ] Commit

### Task 3: Add splash screen

**Files:**
- Modify: `claude_notch/ui.py` (new SplashScreen class)
- Modify: `claude_notch/__main__.py` (show splash before notch)

- [ ] Create SplashScreen class (frameless QWidget, animated Clawd, loading lines, fade-out)
- [ ] Add first-launch detection (hooks not installed → show Install button)
- [ ] Wire into __main__.py: splash shows first, notch shows after fade
- [ ] Add contact info line
- [ ] Verify both first-launch and subsequent-launch modes
- [ ] Commit

### Task 4: Update create_shortcut.py for package structure

**Files:**
- Modify: `create_shortcut.py` (launcher uses `python -m claude_notch`, Bug #15: atomic write)

- [ ] Update launcher.pyw to use `python -m claude_notch` instead of `python claude_notch.py`
- [ ] Fix non-atomic config write
- [ ] Commit

### Task 5: Write test suite

**Files:**
- Create: `tests/conftest.py`, `test_config.py`, `test_sessions.py`, `test_emotion.py`, `test_usage.py`, `test_todos.py`, `test_notifications.py`, `test_system_monitor.py`, `test_git_checkpoints.py`, `test_hooks.py`, `test_export.py`, `test_smoke.py`, `test_ui_screenshots.py`

- [ ] Write conftest.py with QApplication fixture, temp dirs, mock events
- [ ] Write all unit tests (~25 tests across config, emotion, usage, todos, system_monitor)
- [ ] Write integration tests (~8 tests: hooks, session flow, budget, export)
- [ ] Write smoke test (app instantiation)
- [ ] Write UI screenshot tests (QWidget.grab based, ~6 tests)
- [ ] Run full suite, fix any failures
- [ ] Commit

### Task 6: Set up CI/CD and build infrastructure

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/release.yml`, `requirements-dev.txt`

- [ ] Create requirements-dev.txt
- [ ] Create CI workflow (lint + test on push/PR)
- [ ] Create Release workflow (PyInstaller build + GitHub Release on tags)
- [ ] Test PyInstaller build locally
- [ ] Commit

### Task 7: Rewrite README, update CHANGELOG, release

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

- [ ] Rewrite README with fun tone, quick start, features, contact info
- [ ] Update CHANGELOG with v3.0.0 entry
- [ ] Final commit
- [ ] Tag v3.0.0 and push
