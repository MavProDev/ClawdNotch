# Claude Notch 🫧

**The Windows equivalent of [Notchy](https://github.com/adamlyttleapps/notchy) / [Notchi](https://github.com/sk-ruban/notchi) for macOS.**

A notch-shaped desktop overlay that sits at the top-center of your Windows screen, tracking all your Claude Code sessions in real-time with the Clawd pixel mascot.

---

## Features

- **Notch-shaped overlay** — horizontal pill at top of screen, just like a MacBook notch
- **Clawd pixel mascot** — rendered in code, bounces when idle, pulses amber when working, turns red on errors
- **Multi-session tracking** — see all your Claude Code instances at once (supports 4+ simultaneous sessions)
- **Real-time status** — idle → working → waiting → completed state machine per session
- **Sound notifications** — ascending chime when tasks complete
- **Windows toast notifications** — works even in fullscreen games
- **Hover to expand** — smooth animated dropdown dashboard
- **Click to pin** — keep it open while you work
- **Draggable** — slide along the top edge
- **Auto-start with Windows** — optional, via Settings
- **Settings panel** — API key, sound/toast toggles, auto-start

---

## Quick Start

### 1. Install
```bash
cd claude-notch
pip install -r requirements.txt
python claude_notch.py
```

### 2. Install the hooks
Right-click the **system tray icon** (Clawd) → **Settings** → **Install Claude Code Hooks**

This does two things:
- Creates hook scripts at `~/.claude-notch/hooks/`
- Adds hook entries to `~/.claude/settings.json` so Claude Code fires events to the notch

### 3. Restart Claude Code
Any running Claude Code sessions need to be restarted for hooks to take effect.

### 4. That's it
Open Claude Code and start working. The notch will light up as sessions start, show real-time status, and notify you when tasks complete.

---

## How It Works

### Architecture
```
┌──────────────────────────────────────────────────────────┐
│                    Claude Notch (UI)                     │
│  PyQt6 frameless transparent always-on-top window        │
│  Collapsed: 220x34 notch pill with Clawd + status        │
│  Expanded: 340x460 dashboard with sessions + tasks       │
├──────────────────────────────────────────────────────────┤
│                 HookServer (TCP :19748)                   │
│  Receives JSON events from Claude Code hook scripts      │
│  Each hook fires a PowerShell script → TCP → here        │
├──────────────────────────────────────────────────────────┤
│                   SessionManager                          │
│  State machine per session                                │
│  idle → working → waiting → completed → idle              │
│  Tracks tool calls, project names, timestamps            │
├──────────────────────────────────────────────────────────┤
│                 NotificationManager                       │
│  winsound.Beep() for completion chimes                   │
│  plyer toast notifications for fullscreen games          │
├──────────────────────────────────────────────────────────┤
│                   ConfigManager                           │
│  ~/.claude-notch/config.json                             │
│  API key, preferences, auto-start toggle                 │
└──────────────────────────────────────────────────────────┘
```

### Hook Flow
```
Claude Code session
  ├── PreToolUse event fires
  │   └── hook script runs: sends JSON to localhost:19748
  │       └── HookServer receives → SessionManager.handle_event()
  │           └── Session state → "working"
  │               └── UI updates: Clawd pulses amber
  ├── PostToolUse event fires
  │   └── same flow → logs tool completion
  ├── Notification event fires
  │   └── Session state → "waiting" 
  │       └── Sound plays + toast notification
  └── Stop event fires
      └── Session state → "completed"
          └── Chime plays + toast + Clawd turns green
```

### Events We Track
| Event | What happens in the notch |
|-------|--------------------------|
| `SessionStart` | New session appears in dashboard |
| `PreToolUse` | Session shows "working", Clawd pulses |
| `PostToolUse` | Tool logged in activity feed |
| `Notification` | "Waiting" state + sound + toast |
| `Stop` | "Completed" + chime + toast |
| `SessionEnd` | Session marked as done |
| `UserPromptSubmit` | Session shows "working" |

---

## Configuration

Config lives at `~/.claude-notch/config.json`:

```json
{
  "anthropic_api_key": "",
  "hook_server_port": 19748,
  "sound_enabled": true,
  "toast_enabled": true,
  "auto_start": false,
  "poll_interval_seconds": 30,
  "max_sessions_shown": 6
}
```

---

## Running Without a Console Window

To run Claude Notch silently (no CMD window):

```bash
pythonw claude_notch.py
```

Or enable **Start with Windows** in Settings — it uses `pythonw.exe` automatically.

---

## Troubleshooting

**Hooks not firing?**
- Make sure you clicked "Install Claude Code Hooks" in Settings
- Restart Claude Code after installing hooks
- Check `~/.claude/settings.json` has the hook entries
- Run `/hooks` inside Claude Code to verify they're registered

**Port conflict?**
- Change `hook_server_port` in config.json and reinstall hooks

**No sound?**
- Make sure `sound_enabled` is true in Settings
- Windows volume must be on

**Toast notifications not showing?**
- Install `plyer`: `pip install plyer`
- Make sure Windows notification settings allow them

---

## Credits

Inspired by:
- [Notchy](https://github.com/adamlyttleapps/notchy) by Adam Lyttle — macOS notch terminal
- [Notchi](https://github.com/sk-ruban/notchi) by sk-ruban — macOS notch companion with sprites
- [AgentNotch](https://github.com/AppGram/agentnotch) — macOS telemetry overlay

Built by **@ReelDad**

---

## License

MIT
