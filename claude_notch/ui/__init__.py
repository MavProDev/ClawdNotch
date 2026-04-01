"""
claude_notch.ui — Visual / UI layer (package)
===============================================
v4.0.0: Split from monolithic ui.py (2694 lines) into focused sub-modules.
All public names re-exported here for backward compatibility.
"""

from claude_notch.ui.clawd import draw_clawd as draw_clawd, _with_alpha as _with_alpha, _status_colors as _status_colors, CLAWD as CLAWD, EMOTION_STYLES as EMOTION_STYLES  # noqa: F401
from claude_notch.ui.toast import ClawdToast as ClawdToast, show_clawd_toast as show_clawd_toast  # noqa: F401
from claude_notch.ui.splash import SplashScreen as SplashScreen  # noqa: F401
from claude_notch.ui.settings import SettingsDialog as SettingsDialog  # noqa: F401
from claude_notch.ui.notch import ClaudeNotch as ClaudeNotch  # noqa: F401
from claude_notch.ui.tray import make_tray as make_tray  # noqa: F401
