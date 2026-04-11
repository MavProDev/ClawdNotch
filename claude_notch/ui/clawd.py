"""
claude_notch.ui.clawd — Clawd mascot renderer & color utilities
================================================================
CLAWD pixel grid, emotion styles, draw_clawd(), and shared color helpers
used by every other ui sub-module.
"""

import math
import time

from PySide6.QtCore import QRectF
from PySide6.QtGui import QPainter, QColor, QBrush

from claude_notch.config import C

# ═══════════════════════════════════════════════════════════════════════════════
# CLAWD PIXEL GRID & EMOTION STYLES
# ═══════════════════════════════════════════════════════════════════════════════

CLAWD = [
    [0, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0],
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],
    [0, 1, 2, 2, 1, 1, 1, 2, 2, 1, 0],
    [0, 1, 2, 2, 1, 1, 1, 2, 2, 1, 0],
    [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0],
    [0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0],
    [0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0],
    [0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0],
    [0, 0, 1, 0, 1, 0, 1, 0, 1, 0, 0],
]

EMOTION_STYLES = {
    "neutral": {"bounce_mult": 1.0, "tint": None, "leg_droop": 0, "tremble": False, "eye_droop": 0},
    "happy":   {"bounce_mult": 1.5, "tint": QColor(235, 155, 120), "leg_droop": 0, "tremble": False, "eye_droop": 0},
    "sad":     {"bounce_mult": 0.5, "tint": QColor(180, 130, 120), "leg_droop": 1, "tremble": False, "eye_droop": 0.5},
    "sob":     {"bounce_mult": 0.3, "tint": QColor(200, 100, 90),  "leg_droop": 2, "tremble": True, "eye_droop": 0.5},
}


# ═══════════════════════════════════════════════════════════════════════════════
# COLOR HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _with_alpha(color, alpha):
    """Return a copy of a QColor with the given alpha (0-255)."""
    return QColor(color.red(), color.green(), color.blue(), alpha)


def _status_colors():
    """Build status colors from current theme. Called at paint time so theme changes apply."""
    return {
        "idle": C["text_lo"],
        "working": C["amber"],
        "waiting": C["coral"],
        "completed": C["green"],
        "error": C["red"],
    }


def _lerp_color(c1, c2, f):
    """Linearly interpolate between two QColors. f is clamped to [0, 1]."""
    f = max(0, min(1, f))
    return QColor(
        int(c1.red() + (c2.red() - c1.red()) * f),
        int(c1.green() + (c2.green() - c1.green()) * f),
        int(c1.blue() + (c2.blue() - c1.blue()) * f),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# draw_clawd()
# ═══════════════════════════════════════════════════════════════════════════════

def draw_clawd(painter, x, y, ps, bounce=0, tint=None, ex=0, ey=0,
               emotion="neutral", eye_glow=False, glow_phase=0.0):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    style = EMOTION_STYLES.get(emotion, EMOTION_STYLES["neutral"])
    body = tint or style["tint"] or C["coral"]
    eye = QColor(35, 25, 22)
    # Matrix green eye color when coding is active
    if eye_glow:
        glow_intensity = 0.5 + 0.5 * math.sin(glow_phase * 1.8)
        eye_r = int(0 + 35 * (1 - glow_intensity))
        eye_g = int(200 + 55 * glow_intensity)
        eye_b = int(40 + 25 * glow_intensity)
        eye = QColor(eye_r, eye_g, eye_b)
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
            if ri >= 7:
                py += math.sin(adj_bounce * 0.5 + ci * 0.8) * 0.5
                py += style["leg_droop"]
            if cell == 2:
                px += ex
                py += ey + style["eye_droop"]
                # Draw green glow halo behind eyes when coding
                if eye_glow:
                    glow_a = int(40 + 30 * math.sin(glow_phase * 1.8))
                    glow_c = QColor(0, 255, 65, glow_a)
                    gs = ps * 2.2
                    painter.fillRect(QRectF(px - ps * 0.6, py - ps * 0.6, gs, gs), QBrush(glow_c))
            painter.fillRect(QRectF(px, py, ps + 0.5, ps + 0.5), QBrush(color))
    painter.restore()
