# The Clawd Character Bible

> **Purpose:** This document is the complete specification for recreating the "Clawd" mascot character — originally built for the ClawdNotch desktop pet app — in any new PyQt6 project. It contains both the creative intent (what Clawd *is* and *why*) and the exact technical reproduction guide (every pixel, color, formula, and animation constant). Treat this as the single source of truth for Clawd's visual identity.

---

# PART A: CREATIVE BRIEF

## What Is Clawd?

Clawd is a tiny pixel-art robot mascot. He's the visual embodiment of Claude AI activity on your desktop — a little creature who comes alive when Claude Code sessions are running, watches you with glowing green eyes when he's working, bounces happily when things go well, and slumps sadly when things go wrong.

He was originally created for **ClawdNotch**, a desktop companion app (built in Python/PyQt6) that docks to the edge of your screen and monitors active Claude Code sessions. Clawd lives in that dock — a small, always-visible character rendered entirely in code (no image assets), drawn pixel-by-pixel using QPainter on a canvas.

## Design Philosophy

1. **Procedurally drawn, not image-based.** Clawd is defined as an 11x10 pixel grid and rendered at runtime using filled rectangles. No sprites, no PNGs. This means he scales to any pixel size, can be tinted dynamically, and lives entirely in code.

2. **Always alive.** Even with no active sessions, Clawd never goes static. He always bounces gently, his body always pulses with a warm coral glow, and his eyes always glow green. He feels like a living thing on your screen.

3. **Personality through motion.** Clawd's emotional state comes through in his animations — faster bouncing when happy, drooping legs when sad, trembling when sobbing. Floating hearts appear when he's happy; rain drops fall when he's sad. His eyes track your cursor. Small details that make him feel aware.

4. **Dark theme native.** Clawd lives on near-black backgrounds (RGB 12, 12, 14). His warm coral body stands out against the dark UI. All colors were chosen for contrast and readability on dark surfaces.

5. **Themeable.** The default coral palette can be swapped to 7 other color themes (blue, green, purple, cyan, amber, pink, red). The theme changes Clawd's body color and all accent elements.

## What The Creator Asked For (Original Brief)

The creator (@ReelDad) wanted a "desktop pet that monitors Claude Code sessions." The character needed to be:
- Small enough to fit in a 34px-tall dock on the screen edge
- Recognizable at tiny sizes (hence the chunky pixel art style)
- Expressive despite being simple (hence the emotion system + particle effects)
- Visually warm and approachable (hence the coral/salmon default palette)
- "Always alive" — never static or lifeless, even when idle

The design evolved through iteration: eyes were added for personality, then eye-glow was added to show "working" state, then cursor tracking was added for awareness, then emotions and particles were added for richer feedback. Each feature serves a purpose — communicating Claude's state through a character rather than text or icons.

## Visual Identity Summary

**Shape:** Blocky pixel robot. Two pointy ears on top, wide rectangular head, two large 2x2 square eyes, tapered body, four dangling legs (like a spider or octopus). The silhouette is immediately recognizable even at 2.5px cell size.

**Default Color:** Warm coral/salmon — RGB(217, 119, 87). Not orange, not red, not pink. A specific warm tone that pops on dark backgrounds without being aggressive.

**Eyes:** Dark brown normally, shifting to bright matrix-green when active. The green glow pulses with a halo effect behind each eye. Eyes follow the user's cursor for an "aware" feeling.

**Motion:** Constant gentle vertical bobbing via a sine wave. Legs have independent wave motion. The body color pulses between coral and a brighter warm tone. Everything breathes.

---

# PART B: TECHNICAL SPECIFICATION

## 1. The Pixel Grid

Clawd is defined as a 2D array of integers. Each cell is rendered as a filled square of `ps` (pixel size) dimensions.

```python
# Cell values: 0 = transparent, 1 = body, 2 = eye
CLAWD = [
    [0, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0],  # row 0: ears
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 1: head top
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 2: head
    [0, 1, 2, 2, 1, 1, 1, 2, 2, 1, 0],  # row 3: eyes top
    [0, 1, 2, 2, 1, 1, 1, 2, 2, 1, 0],  # row 4: eyes bottom
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],  # row 5: chest
    [0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0],  # row 6: waist (tapers)
    [0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0],  # row 7: legs
    [0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0],  # row 8: legs
    [0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0],  # row 9: legs (feet)
]
# Grid dimensions: 11 columns x 10 rows
# Character width on screen: 11 * ps
# Character height on screen: 10 * ps
# Eye positions: left eye at columns 2-3, rows 3-4
#                right eye at columns 7-8, rows 3-4
# Legs: 4 legs at columns 2, 4, 6, 8 (rows 7-9)
```

**How it's rendered:**
```python
# Iterate every cell, skip zeros, fill rectangles for body (1) and eyes (2)
for ri, row in enumerate(CLAWD):
    for ci, cell in enumerate(row):
        if cell == 0:
            continue
        color = body_color if cell == 1 else eye_color
        px = x + ci * ps  # + any horizontal offsets (tremble, eye shift)
        py = y + ri * ps   # + any vertical offsets (bounce, leg droop)
        painter.fillRect(QRectF(px, py, ps + 0.5, ps + 0.5), QBrush(color))
```

The `+ 0.5` on width/height prevents sub-pixel gaps between adjacent cells.

---

## 2. Color System

### 2.1 Core UI Palette (Background & Text)

```python
# CONFIGURABLE: These define the dark UI Clawd lives on
C = {
    "notch_bg":     QColor(12, 12, 14),      # #0C0C0E — near-black background
    "notch_border": QColor(40, 40, 48),       # #282830 — subtle border
    "card_bg":      QColor(28, 28, 34),       # #1C1C22 — card/panel background
    "divider":      QColor(44, 44, 52),       # #2C2C34 — divider lines
    "text_hi":      QColor(240, 236, 232),    # #F0ECE8 — primary text (bright)
    "text_md":      QColor(155, 148, 142),    # #9B948E — secondary text (medium)
    "text_lo":      QColor(85, 80, 76),       # #55504C — tertiary text (dim)
    "coral":        QColor(217, 119, 87),     # #D97757 — primary accent (theme-dependent)
    "coral_light":  QColor(235, 155, 120),    # #EB9B78 — lighter accent (theme-dependent)
    "green":        QColor(72, 199, 132),     # #48C784 — success/active
    "amber":        QColor(240, 185, 55),     # #F0B937 — working/warning
    "red":          QColor(230, 72, 72),      # #E64848 — error/danger/DND
}
```

### 2.2 Color Themes (8 Options)

The `coral` and `coral_light` entries in the palette are replaced when a theme is applied. All other colors stay constant.

```python
# CONFIGURABLE: Each theme has an accent (body color) and accent_light (glow/highlight)
THEMES = {
    "coral":   {"accent": (217, 119, 87),  "accent_light": (235, 155, 120)},  # default
    "blue":    {"accent": (88, 166, 255),  "accent_light": (130, 190, 255)},
    "green":   {"accent": (72, 199, 132),  "accent_light": (110, 220, 160)},
    "purple":  {"accent": (180, 130, 220), "accent_light": (200, 160, 235)},
    "cyan":    {"accent": (80, 200, 220),  "accent_light": (120, 220, 235)},
    "amber":   {"accent": (240, 185, 55),  "accent_light": (250, 205, 100)},
    "pink":    {"accent": (220, 100, 160), "accent_light": (240, 140, 185)},
    "red":     {"accent": (230, 72, 72),   "accent_light": (245, 110, 110)},
}

def apply_theme(name):
    t = THEMES.get(name, THEMES["coral"])
    C["coral"] = QColor(*t["accent"])
    C["coral_light"] = QColor(*t["accent_light"])
```

### 2.3 Session Tint Colors

When multiple sessions are displayed, each gets a unique tint to distinguish them visually:

```python
# CONFIGURABLE: Tints cycle through these for multi-session display
SESSION_TINTS = [
    QColor(217, 119, 87),   # coral
    QColor(88, 166, 255),   # blue
    QColor(72, 199, 132),   # green
    QColor(180, 130, 220),  # purple
    QColor(240, 185, 55),   # amber
    QColor(220, 100, 160),  # pink
]
```

### 2.4 Status Colors

State-dependent colors used for status dots, border intensity, etc.:

```python
STATUS_COLORS = {
    "idle":      C["text_lo"],   # dim gray — (85, 80, 76)
    "working":   C["amber"],     # amber — (240, 185, 55)
    "waiting":   C["coral"],     # coral — (217, 119, 87)
    "completed": C["green"],     # green — (72, 199, 132)
    "error":     C["red"],       # red — (230, 72, 72)
}
```

### 2.5 Utility: Color Interpolation

Used throughout for smooth transitions between colors:

```python
def _lerp_color(c1, c2, f):
    """Linearly interpolate between two QColors. f clamped to [0, 1]."""
    f = max(0, min(1, f))
    return QColor(
        int(c1.red()   + (c2.red()   - c1.red())   * f),
        int(c1.green() + (c2.green() - c1.green()) * f),
        int(c1.blue()  + (c2.blue()  - c1.blue())  * f),
    )

def _with_alpha(color, alpha):
    """Return a copy of a QColor with the given alpha (0-255)."""
    return QColor(color.red(), color.green(), color.blue(), alpha)
```

---

## 3. Body Rendering — The Warm Coral Pulse

Clawd's body color is never static. It continuously pulses between the base coral and a brighter, warmer tone — like a heartbeat or breathing.

```python
# CONFIGURABLE: The warm pulse formula
# _pulse increments by 0.1 every frame (at 30fps = ~3.0 per second)
q = 0.5 + 0.5 * math.sin(self._pulse * 2)

# q oscillates smoothly between 0.0 and 1.0
# When q=0: body is base coral (217, 119, 87)
# When q=1: body shifts to (240, 185, 55) — warmer, brighter

tint = QColor(
    int(217 + 23 * q),   # R: 217 → 240  (CONFIGURABLE: 23 = range)
    int(119 + 66 * q),   # G: 119 → 185  (CONFIGURABLE: 66 = range)
    int(87 - 32 * q),    # B: 87  → 55   (CONFIGURABLE: 32 = range)
)
```

This tint is passed as the body color every frame. The effect is a subtle warm breathing glow that never stops, even with no sessions active.

**Why:** Without this, Clawd looks like a static sprite. The pulse makes him feel alive. The color shift goes from coral toward amber/gold, giving a warm "glowing embers" effect.

---

## 4. Eye System

### 4.1 Base Eye Color

```python
# CONFIGURABLE: Eyes when NOT glowing
eye_color = QColor(35, 25, 22)  # #231916 — very dark brown, almost black
```

### 4.2 Matrix Green Glow (Active State)

When Clawd's eyes should glow (sessions active, working, etc.), the eye color shifts to a pulsing bright green:

```python
# CONFIGURABLE: Eye glow parameters
glow_intensity = 0.5 + 0.5 * math.sin(glow_phase * 1.8)
# glow_phase = self._pulse (shared animation counter)
# 1.8 = frequency multiplier (CONFIGURABLE — higher = faster pulse)

eye_r = int(0   + 35 * (1 - glow_intensity))  # 0-35: mostly black to faint red
eye_g = int(200 + 55 * glow_intensity)         # 200-255: bright green channel
eye_b = int(40  + 25 * glow_intensity)         # 40-65: slight cyan tint

eye_color = QColor(eye_r, eye_g, eye_b)
# At max glow: approximately (0, 255, 65) — vivid matrix green
# At min glow: approximately (35, 200, 40) — dimmer olive green
```

### 4.3 Eye Glow Halo

Behind each eye pixel, a larger semi-transparent green square creates a "halo" glow effect:

```python
# CONFIGURABLE: Halo effect behind each eye cell (cell value == 2)
glow_alpha = int(40 + 30 * math.sin(glow_phase * 1.8))
# Alpha oscillates between 40 and 70 (CONFIGURABLE: 40=base, 30=range)

glow_color = QColor(0, 255, 65, glow_alpha)  # bright green, semi-transparent

halo_size = ps * 2.2     # CONFIGURABLE: 2.2 = halo size multiplier
halo_offset = ps * 0.6   # CONFIGURABLE: 0.6 = offset from eye cell corner

# Drawn as a filled rectangle BEHIND the eye pixel
painter.fillRect(
    QRectF(px - halo_offset, py - halo_offset, halo_size, halo_size),
    QBrush(glow_color)
)
# Then the eye pixel is drawn on top of this halo
```

**Why halos are rectangles, not circles:** Anti-aliasing is turned OFF for Clawd's rendering (`QPainter.RenderHint.Antialiasing, False`) to preserve the pixel-art crispness. Rectangles fit the aesthetic.

### 4.4 Eye Cursor Tracking

Clawd's eyes shift slightly toward the user's mouse cursor, making him feel aware:

```python
# CONFIGURABLE: Eye tracking parameters
def _eye_shift(self):
    cursor = QCursor.pos()
    # Center point of Clawd on screen
    center_x = self.pos().x() + 14 + 5 * 2.5   # approximate head center X
    center_y = self.pos().y() + self.nh // 2     # vertical center of notch

    dx = cursor.x() - center_x
    dy = cursor.y() - center_y
    distance = max(1, math.sqrt(dx * dx + dy * dy))

    eye_shift_x = dx / distance * 1.2   # CONFIGURABLE: 1.2 = max horizontal shift in pixels
    eye_shift_y = dy / distance * 1.0   # CONFIGURABLE: 1.0 = max vertical shift in pixels

    return eye_shift_x, eye_shift_y

# These shifts (ex, ey) are added to every eye cell's position during rendering:
# px += ex  (for cell == 2 only)
# py += ey  (for cell == 2 only)
```

**Why the shift is small:** At 2.5px cell size, even 1 pixel of shift is noticeable. Larger shifts make the eyes "fall out" of the head.

---

## 5. Animation System

### 5.1 Animation Counters

Two counters drive all animations. They increment every frame and never reset:

```python
# CONFIGURABLE: Animation speed constants
self._bounce += 0.08   # per frame — controls body bobbing (CONFIGURABLE)
self._pulse  += 0.10   # per frame — controls glow, particles, effects (CONFIGURABLE)

# At 30fps (33ms timer):
# _bounce advances ~2.4 per second
# _pulse  advances ~3.0 per second
```

### 5.2 Body Bounce (Vertical Bobbing)

```python
# Every cell's Y position includes this sine-wave offset:
py = y + math.sin(adj_bounce) * 1.2 + ri * ps
#                                ^^^
#                    CONFIGURABLE: 1.2 = bounce amplitude in pixels

# adj_bounce is modified by emotion:
adj_bounce = bounce * emotion_style["bounce_mult"]
# bounce_mult values: neutral=1.0, happy=1.5, sad=0.5, sob=0.3
```

**Why sine:** Smooth, organic, endlessly looping. No keyframes needed.

### 5.3 Leg Wobble

Rows 7-9 (the legs) have an additional independent oscillation that creates a wave-like dangling motion:

```python
# For rows >= 7 (legs):
py += math.sin(adj_bounce * 0.5 + ci * 0.8) * 0.5
#              ^^^^^^^^^^^^   ^^^^^^^^   ^^^
#              half speed     per-column  CONFIGURABLE: 0.5 = wobble amplitude
#                             phase offset
#                             (each leg column wobbles at a different phase)

py += style["leg_droop"]
# leg_droop: neutral=0, happy=0, sad=1px down, sob=2px down
```

**Why per-column phase:** Without column-dependent phase, all four legs would move in unison (marching). The `ci * 0.8` offset creates a wave that ripples across the legs like dangling tentacles.

### 5.4 Tremble Effect (Sob Emotion Only)

```python
# CONFIGURABLE: Tremble frequency and amplitude
tremble_x = math.sin(time.time() * 47) * 0.3  # high-frequency horizontal jitter
tremble_y = math.cos(time.time() * 53) * 0.3  # slightly different vertical jitter
# 47 and 53 are coprime → the two axes rarely sync → chaotic shaking
# 0.3 = amplitude in pixels (CONFIGURABLE — keep small or it looks broken)
# Only active when emotion_style["tremble"] is True (only "sob" state)
```

### 5.5 Animation Timer Intervals

```python
# CONFIGURABLE: Frame rates
ACTIVE_INTERVAL = 33    # ms → ~30fps (when sessions active or animating)
IDLE_INTERVAL   = 100   # ms → ~10fps (when no sessions, saves CPU)

# Toast animation: 16ms → ~60fps (smoother for slide-in/out)
# Splash animation: 33ms → ~30fps
# Expand/collapse: 16ms → ~63fps (smooth panel resize)
```

### 5.6 Expand/Collapse Panel Animation

```python
# CONFIGURABLE: Panel expand/collapse easing
self._anim_p += 0.08   # progress per tick (0→1)
# Easing: cubic ease-out
t = 1 - (1 - self._anim_p) ** 3
# t=0: fully collapsed, t=1: fully expanded
```

---

## 6. Emotion States

Four emotion states modify Clawd's appearance. Each state is a bundle of visual modifiers:

```python
# CONFIGURABLE: All values in this dict
EMOTION_STYLES = {
    "neutral": {
        "bounce_mult": 1.0,            # normal bounce speed
        "tint": None,                  # use default coral pulse
        "leg_droop": 0,                # no droop
        "tremble": False,             # no shaking
        "eye_droop": 0,               # eyes centered
    },
    "happy": {
        "bounce_mult": 1.5,            # 50% more energetic bouncing
        "tint": QColor(235, 155, 120), # #EB9B78 — lighter, warmer coral
        "leg_droop": 0,
        "tremble": False,
        "eye_droop": 0,
    },
    "sad": {
        "bounce_mult": 0.5,            # half-energy bounce (sluggish)
        "tint": QColor(180, 130, 120), # #B48278 — muted, desaturated coral
        "leg_droop": 1,                # legs droop 1px down
        "tremble": False,
        "eye_droop": 0.5,             # eyes droop 0.5px (slight sadness)
    },
    "sob": {
        "bounce_mult": 0.3,            # minimal bounce (listless)
        "tint": QColor(200, 100, 90),  # #C8645A — darker, reddish
        "leg_droop": 2,                # legs droop 2px (heavy/defeated)
        "tremble": True,              # high-frequency shaking
        "eye_droop": 0.5,
    },
}

# How eye_droop is applied:
# For eye cells (cell == 2):
py += ey + style["eye_droop"]   # ey = cursor tracking, eye_droop = emotion offset
```

---

## 7. Particle Effects

### 7.1 Floating Hearts (Happy Emotion)

Three small hearts float upward from Clawd when he's happy:

```python
# CONFIGURABLE: Heart particle parameters
NUM_PARTICLES = 3

for i in range(NUM_PARTICLES):
    seed = self._pulse * 0.8 + i * 2.1      # staggered phase per particle
    phase = (seed % 3.0) / 3.0               # 0→1 cycle, repeating

    # Position
    px = clawd_center_x + math.sin(seed * 1.7 + i) * 6   # horizontal drift (CONFIGURABLE: 6 = spread)
    py = clawd_top - phase * 18 - 2                        # rises upward (CONFIGURABLE: 18 = travel distance)

    # Fade
    alpha = int(180 * (1 - phase))  # 180→0 as it rises (CONFIGURABLE: 180 = max alpha)

    # Heart shape: two overlapping circles + downward triangle
    sz = 1.5 + (1 - phase) * 0.5   # shrinks as it rises (CONFIGURABLE)
    color = QColor(235, 100, 120, alpha)  # #EB6478 — soft pink/red (CONFIGURABLE)

    # Left bump
    painter.drawEllipse(QRectF(px - sz, py - sz * 0.5, sz, sz))
    # Right bump
    painter.drawEllipse(QRectF(px, py - sz * 0.5, sz, sz))
    # Bottom point (triangle)
    tri = QPainterPath()
    tri.moveTo(px - sz, py)
    tri.lineTo(px + sz, py)
    tri.lineTo(px, py + sz)
    tri.closeSubpath()
    painter.drawPath(tri)
```

### 7.2 Falling Rain Drops (Sad / Sob Emotions)

Three drops fall downward from above Clawd when sad or sobbing:

```python
# CONFIGURABLE: Rain drop parameters
for i in range(NUM_PARTICLES):
    seed = self._pulse * 0.8 + i * 2.1
    phase = (seed % 3.0) / 3.0

    px = clawd_center_x + math.sin(seed * 1.7 + i) * 6
    py = clawd_top + phase * 14 + 2   # falls downward (CONFIGURABLE: 14 = travel distance)

    alpha = int(140 * (1 - phase))  # (CONFIGURABLE: 140 = max alpha, dimmer than hearts)
    color = QColor(120, 160, 220, alpha)  # #78A0DC — soft blue (CONFIGURABLE)

    # Simple vertical line, 3px tall
    painter.setPen(QPen(color, 1.2))   # CONFIGURABLE: 1.2 = line width
    painter.drawLine(int(px), int(py), int(px), int(py + 3))
```

---

## 8. Border Glow System

The container Clawd lives in has an animated glowing border — a rotating conical gradient that pulses brighter or dimmer based on activity state.

### 8.1 Glow Alpha (Brightness by State)

```python
# CONFIGURABLE: Alpha ranges per state (base + range * sin)
if any_working:
    glow_alpha = int(120 + 60 * math.sin(self._pulse * 2))      # 60-180 — brightest
elif any_waiting:
    glow_alpha = int(90 + 50 * math.sin(self._pulse * 2.5))     # 40-140
elif total_active > 0:
    glow_alpha = int(50 + 20 * math.sin(self._pulse * 1.5))     # 30-70
else:  # idle / no sessions
    glow_alpha = int(40 + 15 * math.sin(self._pulse * 1.5))     # 25-55 — dimmest

# During expand/collapse animation, alpha fades in:
if t < 0.5:
    glow_alpha = int(glow_alpha * (0.5 + t))
else:
    glow_alpha = int(glow_alpha * min(1.0, (t - 0.3) * 2))
```

### 8.2 Rotating Conical Gradient

```python
# The glow uses a conical (rotating) gradient for a "scanning" effect
gradient = QConicalGradient(center_x, center_y, (self._pulse * 20) % 360)
#                                                ^^^^^^^^^^^^^^^^^^^^^^
#                                    Rotation angle: 20 degrees per _pulse unit
#                                    At _pulse += 0.1/frame: ~60 degrees/sec (CONFIGURABLE)

gc1 = _with_alpha(C["coral"], glow_alpha)
gc2 = _with_alpha(C["coral_light"], glow_alpha)
gradient.setColorAt(0.0,  gc1)
gradient.setColorAt(0.25, gc2)
gradient.setColorAt(0.5,  gc1)
gradient.setColorAt(0.75, gc2)
gradient.setColorAt(1.0,  gc1)

# Drawn as a stroked path around the container border
glow_width = 1.5 + t * 0.5   # CONFIGURABLE: grows slightly during expand
painter.setPen(QPen(QBrush(gradient), glow_width))
painter.drawPath(glow_path)
```

### 8.3 Edge Accent Gradient

When the panel is partially expanded, a gradient line appears along the docked edge:

```python
# Three color stops along the edge: c1 (dim) → c2 (bright accent) → c3 (light accent) → c1
c1 = _with_alpha(C["coral"], 0)           # transparent at edges
c2 = _with_alpha(C["coral"], 120)         # accent color mid-brightness
c3 = _with_alpha(C["coral_light"], 80)    # lighter accent
# Applied as a QLinearGradient along the relevant screen edge
```

---

## 9. Rendering Contexts & Pixel Sizes

Clawd is drawn at different sizes depending on where he appears:

```python
# CONFIGURABLE: Pixel sizes for each context
CONTEXTS = {
    "collapsed_notch": {
        "ps": 2.5,          # pixel size — main dock view
        "position": "x=14 from left edge, y=centered vertically",
        "container": "300x34 (horizontal) or 34x200 (vertical)",
    },
    "expanded_panel": {
        "ps": 2.0,          # slightly smaller in the panel header
        "position": "x=20, y=top+12 (top-left of panel)",
        "container": "560x500 (resizable: min 440x400, max 900x900)",
    },
    "expanded_empty": {
        "ps": 2.2,          # shown in panel when no sessions active
        "position": "centered in session area",
    },
    "toast_notification": {
        "ps": 2.8,          # larger for notification popup
        "position": "x=12, y=centered in 340x88 toast",
    },
    "splash_screen": {
        "ps": 4.0,          # largest — hero display on boot
        "position": "centered horizontally, y=30 from top of 480x360 splash",
    },
    "mini_mode": {
        "ps": None,          # Clawd is NOT drawn in mini mode
        "indicator": "7px pulsing status dot centered in 28x28 container",
    },
}
```

---

## 10. Toast Notification Spec

A branded popup that slides in from the bottom-right corner with Clawd inside:

```python
# CONFIGURABLE: Toast visual parameters
TOAST = {
    "size": (340, 88),
    "corner_radius": 12,
    "background": QColor(12, 12, 14, 245),   # near-black, 96% opaque
    "border_width_inner": 1.2,
    "border_width_glow": 3.0,
    "glow_alpha_formula": "30 + 20 * sin(pulse * 2)",  # 10-50 range

    # Border color depends on notification type:
    "border_colors": {
        "completion": QColor(72, 199, 132),    # green — task finished
        "attention":  QColor(217, 119, 87),    # coral — needs input
        "budget":     QColor(240, 185, 55),    # amber — budget warning
        "info":       QColor(217, 119, 87),    # coral — default
    },

    # Slide-in animation
    "slide_distance": 40,         # pixels from below target
    "slide_speed": 0.06,          # progress per 16ms tick
    "fade_in_speed": 0.08,        # opacity per tick
    "easing": "cubic_ease_out",   # t = 1 - (1-p)^3
    "visible_duration": 8,        # seconds before auto-dismiss
    "fade_out_speed": 0.04,       # opacity per tick

    # Clawd inside toast
    "clawd_ps": 2.8,
    "clawd_x": 12,
    "clawd_emotion": "happy (if completion), neutral (otherwise)",
    "clawd_eye_glow": "True if attention type",

    # Text
    "title_font": ("Segoe UI", 10, "DemiBold"),
    "title_color": "matches border color",
    "message_font": ("Segoe UI", 9, "Normal"),
    "message_color": QColor(155, 148, 142),   # text_md
    "hint_font": ("Segoe UI", 8, "Normal"),
    "hint_color": QColor(85, 80, 76),         # text_lo

    # Type indicator dot (top-right corner)
    "dot_size": 6,
    "dot_position": "(w-16, 8)",
    "dot_color": "matches border color",
}
```

### Toast Stacking

Multiple toasts stack vertically from the bottom-right:

```python
stack_offset = len(active_toasts) * 96   # 88px toast + 8px gap
target_y = screen_height - 88 - 16 - stack_offset
# When a toast is dismissed, all above it smoothly slide down:
# new_y = current_y + (target_y - current_y) * 0.15  (per tick, smooth spring)
```

---

## 11. Splash Screen Spec

A centered boot screen shown on every launch:

```python
SPLASH = {
    "size": (480, 360),
    "corner_radius": 16,
    "background": QColor(12, 12, 14),
    "border_outer": "_with_alpha(C['coral'], 60), width 2.0",
    "border_inner": "C['coral'], width 1.0",

    # Clawd hero (largest rendering)
    "clawd_ps": 4.0,
    "clawd_position": "centered horizontally, y=30",
    "clawd_eye_glow": True,
    "clawd_emotion": "neutral",

    # Title
    "title": "ClawdNotch",   # (or your app name)
    "title_font": ("Segoe UI", 24, "Bold"),
    "title_color": "C['coral']",
    "title_y": 85,

    # Version subtitle
    "version_font": ("Segoe UI", 10, "Normal"),
    "version_color": "C['text_lo']",
    "version_y": 118,

    # Terminal-style loading lines
    "line_font": ("Consolas", 10),
    "line_spacing": 22,
    "line_start_y": 150,
    "line_delay": "250ms between lines (150ms if auto_start)",
    "bracket_color": "C['coral']",    # [spinner] prefix
    "text_color": "C['text_md']",     # line content

    # Spinner frames used in line prefixes
    "spinner_frames": ["·", "✻", "✽", "✶", "✳", "✢"],

    # Fade-out
    "post_load_delay": 500,   # ms before fade starts
    "fade_speed": 0.02,       # opacity per 33ms tick

    # Footer
    "footer_font": ("Segoe UI", 9),
    "footer_color": "C['text_lo']",
    "footer_y": "height - 28",
}
```

---

## 12. Speech Bubble (Empty State)

When no sessions are active, Clawd appears in the expanded panel with a thought bubble:

```python
SPEECH_BUBBLE = {
    # Three ascending thought dots
    "dot_sizes": [3, 4],            # two dots, ascending size
    "dot_color": "C['text_lo']",
    "dot_positions": [
        (clawd_x + 28, clawd_y + 14),  # small dot
        (clawd_x + 33, clawd_y + 9),   # medium dot
    ],

    # Main bubble
    "bubble_size": (120, 24),
    "bubble_radius": 10,
    "bubble_bg": QColor(40, 40, 48),    # #282830
    "bubble_offset": (clawd_x + 36, clawd_y - 4),

    # Text inside bubble
    "text": "Waiting for Claude...",
    "text_font": ("Segoe UI", 9),
    "text_color": "C['text_md']",
}
```

---

## 13. Mini Mode

When mini mode is enabled, Clawd is not rendered. Instead, a pulsing status dot represents him:

```python
MINI_MODE = {
    "container": (28, 28),

    # Status dot (always visible)
    "dot_size": 7,             # diameter in pixels
    "dot_position": "centered",
    "dot_color": "STATUS_COLORS[current_state]",

    # Pulsing glow (only when working or waiting)
    "glow_formula": "q = 0.5 + 0.5 * sin(pulse * 2.5)",
    "glow_radius": "3 + q * 2.5",              # 3-5.5px radius
    "glow_alpha": "int(40 + q * 40)",           # 40-80 alpha
    "glow_color": "_with_alpha(status_color, glow_alpha)",
}
```

---

## 14. Status Dot (Collapsed View, Non-Mini)

In the collapsed notch (not mini), a status dot appears alongside text:

```python
STATUS_DOT = {
    "size": 7,               # diameter
    "position_horizontal": (48, notch_height // 2),   # centered vertically
    "position_vertical": (notch_width // 2, 38),       # centered horizontally

    # Pulsing glow (when working or waiting)
    "glow_formula": "q = 0.5 + 0.5 * sin(pulse * 2.5)",
    "glow_radius": "3.5 + q * 3",              # 3.5-6.5px
    "glow_alpha": "int(40 + q * 40)",
}
```

---

## 15. Context Bar (Token Usage Visualization)

A thin progress bar under each session showing token/context usage:

```python
CONTEXT_BAR = {
    "height": 4,
    "border_radius": 2,
    "background": "C['card_bg']",  # (28, 28, 34)

    # Color interpolation based on usage percentage:
    # 0-50%:  green → amber
    # 50-80%: amber → coral
    # 80-100%: coral → red
    "color_stops": [
        (0.00, "C['green']"),    # (72, 199, 132)
        (0.50, "C['amber']"),    # (240, 185, 55)
        (0.80, "C['coral']"),    # (217, 119, 87)
        (1.00, "C['red']"),      # (230, 72, 72)
    ],

    # Label below bar
    "label_font": ("Segoe UI", 7),  # very small
    "label_color": "C['text_lo']",
    "label_format": "~{tokens}k / {limit}k",  # prefix ~ for estimates
}
```

---

## 16. UI Element Details

### 16.1 Spinner Animation

```python
# CONFIGURABLE: Spinner frames (used in collapsed text, session rows, toast hints)
SPINNER_FRAMES = ["·", "✻", "✽", "✶", "✳", "✢"]
# Cycles based on: frame_idx = int(self._pulse) % len(SPINNER_FRAMES)
```

### 16.2 Thinking Words

Random verbs shown while Clawd is working (e.g., "Cogitating...", "Brewing..."):

```python
# CONFIGURABLE: Full list of thinking words
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

### 16.3 Bell Icon (DND Button)

```python
DND_BUTTON = {
    "size": (22, 22),
    "border_radius": 6,
    "bg_normal": "_with_alpha(C['coral'], 20)",
    "bg_active": "QColor(230, 72, 72, 40)",    # red tint when DND on
    "border_normal": "C['coral'], 1.0",
    "border_active": "C['red'], 1.0",

    # Bell icon construction (all relative to button center bcx, bcy):
    "bell_dome": "drawArc(bcx-5, bcy-6, 10, 10, 0, 180*16)",   # upper semicircle
    "bell_sides_left": "drawLine(bcx-5, bcy-1, bcx-5, bcy+3)",
    "bell_sides_right": "drawLine(bcx+5, bcy-1, bcx+5, bcy+3)",
    "bell_rim": "drawLine(bcx-6, bcy+3, bcx+6, bcy+3)",
    "bell_clapper": "drawEllipse(bcx-1.5, bcy+4, 3, 3)",       # small dot below
    "strike_through": "drawLine(bcx-7, bcy+6, bcx+7, bcy-8)",  # diagonal when DND
    "line_width": 1.5,
    "strike_width": 2.0,
}
```

### 16.4 Session Count Badge

```python
SESSION_BADGE = {
    "size": 16,                              # diameter
    "position": "(container_width - 28, vertical_center)",
    "bg_multiple": "C['coral']",             # coral when >1 session
    "bg_single": "C['text_lo']",             # dim when only 1
    "text_color": "QColor(255, 255, 255)",   # white
    "text_font": ("Segoe UI", 7, "Bold"),
}
```

### 16.5 Session Pill

```python
SESSION_PILL = {
    "border_radius": 10,
    "bg": "QColor(217, 119, 87, 35)",   # coral at 14% opacity
    "border": "C['coral'], 1.0",
    "text_color": "C['coral']",
    "text_font": ("Segoe UI", 9, "Bold"),
    "format": "{count} session(s)",
}
```

---

## 17. Font Stack

All text uses the Segoe UI family (Windows system font) with Consolas for monospaced content:

```python
# CONFIGURABLE: Replace with platform-appropriate fonts
FONTS = {
    "title_large":   ("Segoe UI", 24, "Bold"),      # splash title
    "title":         ("Segoe UI", 14, "Bold"),       # panel header
    "heading":       ("Segoe UI", 12, "Bold"),       # install button
    "body_bold":     ("Segoe UI", 10, "Bold"),       # session names
    "body":          ("Segoe UI", 10, "Normal"),     # version text
    "label_bold":    ("Segoe UI", 9, "Bold"),        # pill text, section headers
    "label":         ("Segoe UI", 9, "Normal"),      # messages, bubble text
    "caption":       ("Segoe UI", 8, "Normal"),      # hints
    "tiny":          ("Segoe UI", 7, "Normal"),      # context bar labels
    "tiny_bold":     ("Segoe UI", 7, "Bold"),        # badge text
    "mono":          ("Consolas", 10, "Normal"),      # terminal-style loading lines
}
```

---

## 18. Window Properties

The container Clawd lives in has these window flags (PyQt6):

```python
WINDOW_FLAGS = (
    Qt.WindowType.FramelessWindowHint |       # no title bar or border
    Qt.WindowType.WindowStaysOnTopHint |       # always on top
    Qt.WindowType.Tool                         # no taskbar entry
)

WINDOW_ATTRIBUTES = [
    Qt.WidgetAttribute.WA_TranslucentBackground,   # transparent canvas
]

# Dim when inactive (window loses focus):
DIM_OPACITY = 0.55   # CONFIGURABLE — snaps instantly, no fade
# Restores to 1.0 on focus
```

---

## 19. Complete draw_clawd() Function Reference

This is the full rendering function, copy-paste ready:

```python
import math
import time
from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush

def draw_clawd(painter, x, y, ps, bounce=0, tint=None, ex=0, ey=0,
               emotion="neutral", eye_glow=False, glow_phase=0.0):
    """
    Draw the Clawd character at position (x, y) with pixel size ps.

    Args:
        painter:    QPainter instance
        x, y:       top-left corner of the character
        ps:         pixel size (each cell is ps x ps pixels)
        bounce:     animation counter for vertical bobbing
        tint:       QColor override for body color (None = use emotion default)
        ex, ey:     eye shift from cursor tracking
        emotion:    "neutral", "happy", "sad", or "sob"
        eye_glow:   True to enable green matrix eye glow
        glow_phase: animation counter for glow effects (typically same as _pulse)
    """
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    style = EMOTION_STYLES.get(emotion, EMOTION_STYLES["neutral"])
    body = tint or style["tint"] or C["coral"]
    eye = QColor(35, 25, 22)

    if eye_glow:
        glow_intensity = 0.5 + 0.5 * math.sin(glow_phase * 1.8)
        eye = QColor(
            int(0 + 35 * (1 - glow_intensity)),
            int(200 + 55 * glow_intensity),
            int(40 + 25 * glow_intensity),
        )

    adj_bounce = bounce * style["bounce_mult"]
    tremble_x = (math.sin(time.time() * 47) * 0.3) if style["tremble"] else 0
    tremble_y = (math.cos(time.time() * 53) * 0.3) if style["tremble"] else 0

    for ri, row in enumerate(CLAWD):
        for ci, cell in enumerate(row):
            if cell == 0:
                continue
            color = body if cell == 1 else eye
            px = x + ci * ps + tremble_x
            py = y + math.sin(adj_bounce) * 1.2 + ri * ps + tremble_y

            if ri >= 7:  # legs
                py += math.sin(adj_bounce * 0.5 + ci * 0.8) * 0.5
                py += style["leg_droop"]

            if cell == 2:  # eyes
                px += ex
                py += ey + style["eye_droop"]
                if eye_glow:
                    glow_a = int(40 + 30 * math.sin(glow_phase * 1.8))
                    glow_c = QColor(0, 255, 65, glow_a)
                    gs = ps * 2.2
                    painter.fillRect(
                        QRectF(px - ps * 0.6, py - ps * 0.6, gs, gs),
                        QBrush(glow_c),
                    )

            painter.fillRect(QRectF(px, py, ps + 0.5, ps + 0.5), QBrush(color))

    painter.restore()
```

---

## 20. Quick-Reference: All Configurable Constants

| Constant | Default | Purpose |
|---|---|---|
| `_bounce` increment | `0.08` | Body bob speed |
| `_pulse` increment | `0.10` | Glow/particle speed |
| Bounce amplitude | `1.2` px | How much Clawd bobs |
| Leg wobble amplitude | `0.5` px | How much legs wave |
| Leg wobble phase offset | `ci * 0.8` | Per-column leg wave offset |
| Coral pulse R range | `217 + 23*q` | Red channel of body pulse |
| Coral pulse G range | `119 + 66*q` | Green channel of body pulse |
| Coral pulse B range | `87 - 32*q` | Blue channel of body pulse |
| Eye glow frequency | `1.8` | Glow pulse speed multiplier |
| Eye glow halo size | `ps * 2.2` | Halo rectangle size |
| Eye glow halo offset | `ps * 0.6` | Halo position offset |
| Eye glow halo color | `(0, 255, 65)` | Bright green |
| Eye glow halo alpha | `40 + 30*sin` | 40-70 range |
| Eye tracking max X | `1.2` px | Max horizontal eye shift |
| Eye tracking max Y | `1.0` px | Max vertical eye shift |
| Tremble frequency X | `47` | Horizontal shake speed |
| Tremble frequency Y | `53` | Vertical shake speed |
| Tremble amplitude | `0.3` px | Shake distance |
| Heart color | `(235, 100, 120)` | Pink-red |
| Heart travel distance | `18` px | How far hearts float |
| Heart max alpha | `180` | Starting opacity |
| Rain color | `(120, 160, 220)` | Soft blue |
| Rain travel distance | `14` px | How far drops fall |
| Rain max alpha | `140` | Starting opacity |
| Particle count | `3` | Hearts or drops |
| Particle phase stagger | `i * 2.1` | Offset between particles |
| Border glow rotation | `pulse * 20` deg | Conical gradient spin speed |
| Active fps | `30` (33ms) | Animation frame rate |
| Toast fps | `60` (16ms) | Toast animation frame rate |
| Idle fps | `10` (100ms) | CPU-saving idle rate |
| Dim opacity | `0.55` | Opacity when window unfocused |

---

*Generated from ClawdNotch v4.0.0 source code. Every value in this document was extracted directly from the working codebase — no approximations.*
