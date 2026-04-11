# Deferred Findings

All previously deferred findings have been resolved in the fortress/audit-2026-04-10 branch.

### F-006: GPL-3.0 / MIT License Incompatibility (PyQt6)
- **Status:** resolved
- **Resolved date:** 2026-04-11
- **Resolution:** Migrated from PyQt6 (GPL-3.0) to PySide6 (LGPL-3.0). MIT license is now compatible.

### F-012: Config Directory Default Permissions
- **Status:** resolved
- **Resolved date:** 2026-04-11
- **Resolution:** Added _secure_directory() using icacls to restrict ~/.claude-notch/ to current user only.

### F-015: Registry Auto-Start Targets Mutable Launcher Script
- **Status:** resolved
- **Resolved date:** 2026-04-11
- **Resolution:** Launcher now validates install_path (absolute, local, no UNC, contains __init__.py).

### F-016: Unsigned Binary Distribution
- **Status:** resolved
- **Resolved date:** 2026-04-11
- **Resolution:** SHA-256 checksum generated and published alongside .exe in release workflow.

### F-023: No Structured Audit Logging
- **Status:** resolved
- **Resolved date:** 2026-04-11
- **Resolution:** Added RotatingFileHandler (2MB, 3 backups) at ~/.claude-notch/clawdnotch.log. Security-critical messages migrated to logger.
