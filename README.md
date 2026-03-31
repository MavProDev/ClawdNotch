# ClawdNotch

**The Windows notch for Claude Code. Track sessions, get notified, look cool.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Windows 10/11](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6.svg)](https://www.microsoft.com/windows)

<!-- GIF goes here -->

---

## What is this?

You know those slick macOS notch apps — [Notchy](https://github.com/adamlyttleapps/notchy), [Notchi](https://github.com/sk-ruban/notchi), [AgentNotch](https://github.com/AppGram/agentnotch) — that turn the MacBook notch into something actually useful? Yeah, Windows didn't have that. Now it does.

ClawdNotch is a desktop overlay that lives at the top of your screen and tracks your Claude Code sessions in real time. It comes with **Clawd**, a pixel mascot who reacts to your coding — bouncing when idle, thinking when you're deep in it, and celebrating when stuff works. He's got feelings. Respect them.

---

## Quick Start

**1.** Download `ClawdNotch.exe` from [Releases](https://github.com/MavProDev/ClawdNotch/releases)

**2.** Double-click to run. That's it. No installer, no setup wizard, no 47-step onboarding.

**3.** When prompted, install the Claude Code hooks and restart Claude Code. ClawdNotch will handle the rest.

> **Windows SmartScreen warning:** On first run, Windows may say "Windows protected your PC." This is normal for unsigned open-source software. Click **"More info"** then **"Run anyway."** ClawdNotch is fully open-source — read every line of code right here in this repo.

---

## Features

- **Multi-session tracking** — Monitor 4+ simultaneous Claude Code sessions without losing your mind
- **Real-time status with Clawd** — Animated mascot + thinking spinner (yes, he says things like "Booping...")
- **8 color themes** — Because everyone has opinions about dark mode
- **Usage stats & sparkline graphs** — Coding streaks, token counts, session history at a glance
- **Git snapshots** — One-tap save points with `Ctrl+Shift+S`, because trust issues are valid
- **System resource monitoring** — CPU and RAM usage, right there in the overlay
- **Smart notifications** — Toast alerts that respect your flow, plus DND mode for when you mean business
- **Keyboard shortcuts** — `Ctrl+Shift+C` (toggle), `Ctrl+Shift+E` (expand), `Ctrl+Shift+S` (snapshot), `Ctrl+Shift+D` (dashboard)
- **Mini mode** — Shrink it down when screen real estate gets tight
- **Export usage reports** — Markdown or CSV, for the data nerds and the managers who love them
- **Clawd's emotion engine** — He reacts to your prompts. Long debug session? He feels that. Mass refactor? He's hyped. He's basically your rubber duck with a personality.

---

## Building from Source

```bash
git clone https://github.com/MavProDev/ClawdNotch.git
cd ClawdNotch
pip install -r requirements.txt
python -m claude_notch
```

---

## Configuration

Settings live at `~/.claude-notch/config.json`. You can edit it by hand if you're into that, but the **Settings dialog** (right-click tray icon) covers everything — themes, notifications, shortcuts, auto-start, all of it.

---

## Credits

Built by [@ReelDad](https://x.com/ReelDad).

Inspired by [Notchy](https://github.com/adamlyttleapps/notchy) by Adam Lyttle, [Notchi](https://github.com/sk-ruban/notchi) by sk-ruban, and [AgentNotch](https://github.com/AppGram/agentnotch) by AppGram. They made it cool on Mac. We brought it to Windows.

Clawd is the best pixel mascot in the dev tools space. Fight me.

---

## Contact

- [@ReelDad](https://x.com/ReelDad) on X
- [MavProGroup@gmail.com](mailto:MavProGroup@gmail.com)
- Bugs, ideas, business inquiries — seriously, don't hesitate to [reach out](https://github.com/MavProDev/ClawdNotch/issues)

---

## License

[MIT](LICENSE) — do whatever you want with it.
