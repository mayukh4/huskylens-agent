"""
TARS Holographic Face Renderer — 2D scan-line approach.

Pre-computes a human head depth map, renders as dense horizontal
scan lines with brightness varying by depth.  Eyes and mouth are
dynamic overlays.  Pure pygame, targets 30 FPS on Pi 5.
"""

import math
import random
import pygame
import numpy as np

# ── Layout ──────────────────────────────────────────────────────────────
SCREEN_W, SCREEN_H = 800, 480
FACE_W = 480
PANEL_W = 320
PANEL_X = 480

# ── Exported (green — panel) ────────────────────────────────────────────
BLACK        = (0, 0, 0)
GREEN_BRIGHT = (0, 255, 65)
GREEN_MID    = (0, 180, 40)
GREEN_DIM    = (0, 100, 25)
GREEN_FAINT  = (0, 50, 15)
BORDER_COLOR = (0, 120, 30)
PANEL_BG     = (2, 8, 2)
RED_DIM      = (180, 40, 40)

# ── Internal palette ────────────────────────────────────────────────────
_CB = np.array([0, 200, 245], dtype=np.float32)   # bright cyan
_CM = (0, 140, 180)
_CD = (0, 55, 80)
_CF = (0, 22, 35)
_CG = (100, 210, 255)

_RAIN_CHARS = "アイウエオカキクケコサシスセソ012345"

# ── Head geometry ───────────────────────────────────────────────────────
# Center of head in face area
_HCX = FACE_W // 2       # 240
_HCY = SCREEN_H // 2 - 8 # 232

# Half-width control points: (norm_y, half_width_px)
# norm_y: -1 = top of skull, 0 ≈ eye level, +1 = bottom of neck
_OUTLINE = [
    (-1.00,   0),
    (-0.90,  42),
    (-0.78,  66),
    (-0.65,  78),
    (-0.52,  86),
    (-0.42,  90),   # temples
    (-0.34,  92),   # brow — widest
    (-0.25,  88),   # eye level
    (-0.15,  90),   # below eyes
    (-0.05,  92),   # cheekbones
    ( 0.05,  88),
    ( 0.15,  80),   # below cheeks
    ( 0.25,  72),   # mouth
    ( 0.35,  60),   # chin sides
    ( 0.42,  48),   # chin tip
    ( 0.50,  38),   # under chin
    ( 0.60,  32),   # jaw-neck
    ( 0.72,  28),   # neck
    ( 0.85,  26),
    ( 1.00,  24),
]

# Head vertical span in pixels (from center)
_HEAD_TOP = -190    # pixels above _HCY
_HEAD_BOT =  190    # pixels below _HCY
_HEAD_H   = _HEAD_BOT - _HEAD_TOP


def _interp_outline(ny):
    """Interpolate half-width at normalised y."""
    pts = _OUTLINE
    if ny <= pts[0][0]:
        return pts[0][1]
    if ny >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        y0, w0 = pts[i]
        y1, w1 = pts[i + 1]
        if y0 <= ny <= y1:
            t = (ny - y0) / (y1 - y0)
            # smoothstep for smoother curves
            t = t * t * (3 - 2 * t)
            return w0 + (w1 - w0) * t
    return 0


def _depth_at(rx, ny):
    """
    Compute depth (brightness) at relative-x (-1..1) and norm-y (-1..1).
    Returns 0.0 (invisible) to 1.0 (brightest).
    """
    # Base: smooth falloff from center to edge
    edge = 1.0 - abs(rx)
    d = max(0, edge) ** 0.65

    # ── Nose (bright vertical ridge at center) ──
    if abs(rx) < 0.10 and -0.20 < ny < 0.20:
        nose_x = max(0, 1.0 - abs(rx) / 0.10)
        nose_y = max(0, 1.0 - abs(ny - 0.02) / 0.20)
        d = min(1.0, d + 0.35 * nose_x * nose_y)

    # Nose tip (wider at bottom)
    if abs(rx) < 0.16 and 0.05 < ny < 0.18:
        tip_x = max(0, 1.0 - abs(rx) / 0.16)
        tip_y = max(0, 1.0 - abs(ny - 0.12) / 0.07)
        d = min(1.0, d + 0.2 * tip_x * tip_y)

    # Nose bridge (thin ridge above)
    if abs(rx) < 0.06 and -0.32 < ny < -0.05:
        br_x = max(0, 1.0 - abs(rx) / 0.06)
        br_y = max(0, 1.0 - abs(ny + 0.15) / 0.18)
        d = min(1.0, d + 0.15 * br_x * br_y)

    # ── Eye sockets (darker depressions) ──
    for ex in [-0.32, 0.32]:
        dx = (rx - ex) / 0.14
        dy = (ny - (-0.24)) / 0.07
        dist2 = dx * dx + dy * dy
        if dist2 < 1.0:
            d *= (0.25 + 0.75 * dist2)

    # ── Brow ridge (slightly brighter band) ──
    if -0.36 < ny < -0.30 and abs(rx) < 0.55:
        brow = max(0, 1.0 - abs(ny + 0.33) / 0.04) * max(0, 1.0 - abs(rx) / 0.55)
        d = min(1.0, d + 0.12 * brow)

    # ── Cheekbones (subtle bright) ──
    for cx_c in [-0.45, 0.45]:
        dx = (rx - cx_c) / 0.12
        dy = (ny - (-0.05)) / 0.08
        dist2 = dx * dx + dy * dy
        if dist2 < 1.0:
            d = min(1.0, d + 0.08 * (1.0 - dist2))

    # ── Mouth area (subtle depression) ──
    if abs(rx) < 0.20 and 0.22 < ny < 0.32:
        m_x = max(0, 1.0 - abs(rx) / 0.20)
        m_y = max(0, 1.0 - abs(ny - 0.27) / 0.06)
        d *= (1.0 - 0.25 * m_x * m_y)

    # ── Chin (slightly brighter at center) ──
    if abs(rx) < 0.18 and 0.35 < ny < 0.45:
        ch_x = max(0, 1.0 - abs(rx) / 0.18)
        ch_y = max(0, 1.0 - abs(ny - 0.40) / 0.06)
        d = min(1.0, d + 0.10 * ch_x * ch_y)

    # ── Temples (slight depression) ──
    if abs(rx) > 0.55 and -0.45 < ny < -0.25:
        d *= 0.85

    # ── Forehead (medium brightness, slight roundness) ──
    if ny < -0.38 and abs(rx) < 0.4:
        fh = max(0, 1.0 - abs(rx) / 0.4) * max(0, (-0.38 - ny) / 0.5)
        d = min(1.0, d + 0.06 * fh)

    return max(0.0, min(1.0, d))


# ────────────────────────────────────────────────────────────────────────

def _sc(base, f):
    return (max(0, min(255, int(base[0]*f))),
            max(0, min(255, int(base[1]*f))),
            max(0, min(255, int(base[2]*f))))


class FaceRenderer:

    def __init__(self):
        self._t = 0.0
        self._frame = 0
        self._rfont = pygame.font.SysFont("monospace", 10)
        self._sfont = pygame.font.SysFont("monospace", 13, bold=True)

        # Pre-render the static head scan-line image
        self._head_surf = self._build_head()

        # Feature lines overlay (nose ridge, brow, jaw)
        self._feature_surf = self._build_features()

        # Eye glow
        self._glow = self._make_glow(16)

        # Rain
        self._atlas = {}
        self._atlas_br = {}
        self._build_atlas()
        self._rain = []
        self._init_rain()

        # Particles
        self._parts = []
        self._init_parts()

        # Scanline overlay
        self._scanline_surf = self._make_scanlines()

        # Eye positions in screen coords
        self._eye_ly = int(_HCY + (-0.24) * (_HEAD_H / 2))
        self._eye_lx = int(_HCX + (-0.32) * _interp_outline(-0.24))
        self._eye_ry = self._eye_ly
        self._eye_rx = int(_HCX + (0.32) * _interp_outline(-0.24))

        # Mouth position
        self._mouth_y = int(_HCY + 0.27 * (_HEAD_H / 2))
        self._mouth_x = _HCX

    # ── pre-build head ──────────────────────────────────────────────────

    def _build_head(self):
        """Pre-render the head as dense scan lines with depth-based brightness."""
        surf = pygame.Surface((FACE_W, SCREEN_H))
        surf.fill(BLACK)
        surf.set_colorkey(BLACK)

        arr = np.zeros((FACE_W, SCREEN_H, 3), dtype=np.uint8)

        half_h = _HEAD_H / 2

        for y in range(SCREEN_H):
            # Normalised y
            ny = (y - _HCY) / half_h
            if ny < -1.05 or ny > 1.05:
                continue

            hw = _interp_outline(ny)
            if hw < 2:
                continue

            # Scan-line brightness modulation
            scan = 1.0 if y % 2 == 0 else 0.22

            x_left = max(0, int(_HCX - hw))
            x_right = min(FACE_W - 1, int(_HCX + hw))

            for x in range(x_left, x_right + 1):
                rx = (x - _HCX) / max(1, hw)
                depth = _depth_at(rx, ny)

                if depth < 0.02:
                    continue

                # Edge dissolution: randomly skip pixels near edges
                if depth < 0.12 and random.random() > depth / 0.12:
                    continue

                br = depth * scan
                r = int(_CB[0] * br)
                g = int(_CB[1] * br)
                b = int(_CB[2] * br)

                if r > 0 or g > 0 or b > 0:
                    arr[x, y, 0] = min(255, r)
                    arr[x, y, 1] = min(255, g)
                    arr[x, y, 2] = min(255, b)

        pygame.surfarray.blit_array(surf, arr)
        return surf

    # ── feature lines ───────────────────────────────────────────────────

    def _build_features(self):
        """Pre-render subtle facial feature contour lines."""
        surf = pygame.Surface((FACE_W, SCREEN_H), pygame.SRCALPHA)

        half_h = _HEAD_H / 2
        col_bright = (*_CM, 140)
        col_mid = (*_CD, 100)

        # Nose ridge (vertical line)
        for y in range(int(_HCY - 0.30 * half_h), int(_HCY + 0.16 * half_h)):
            ny = (y - _HCY) / half_h
            # Width varies: thin at bridge, wider at tip
            width = 1 if ny < 0.05 else 2
            pygame.draw.line(surf, col_bright, (_HCX - width, y), (_HCX + width, y))

        # Brow line (horizontal arc)
        for x in range(_HCX - 58, _HCX + 58):
            t = (x - _HCX) / 58.0
            y = int(_HCY + (-0.33) * half_h - 2 * (1.0 - t * t))
            if 0 <= x < FACE_W and 0 <= y < SCREEN_H:
                surf.set_at((x, y), col_mid)

        # Eye socket outlines (elliptical arcs)
        for ecx in [self._eye_lx if hasattr(self, '_eye_lx') else _HCX - 30,
                     self._eye_rx if hasattr(self, '_eye_rx') else _HCX + 30]:
            ecy = int(_HCY + (-0.24) * half_h)
            for k in range(20):
                a = 2 * math.pi * k / 20
                px = int(ecx + 13 * math.cos(a))
                py = int(ecy + 7 * math.sin(a))
                if 0 <= px < FACE_W and 0 <= py < SCREEN_H:
                    surf.set_at((px, py), col_mid)

        # Jaw line (from ear to chin, both sides)
        for side in [-1, 1]:
            pts = []
            for i in range(15):
                t = i / 14
                ny = -0.05 + t * 0.48
                hw = _interp_outline(ny)
                # Jaw line is at ~90% of width
                jx = int(_HCX + side * hw * (0.92 - t * 0.45))
                jy = int(_HCY + ny * half_h)
                pts.append((jx, jy))
            for i in range(len(pts) - 1):
                pygame.draw.line(surf, col_mid, pts[i], pts[i + 1])

        # Mouth line (subtle horizontal)
        my = int(_HCY + 0.27 * half_h)
        for x in range(_HCX - 18, _HCX + 18):
            t = (x - _HCX) / 18.0
            y_off = int(1.5 * (1 - t * t))
            if 0 <= x < FACE_W:
                surf.set_at((x, my + y_off), col_mid)

        return surf

    # ── glow / scanlines ────────────────────────────────────────────────

    def _make_glow(self, radius):
        size = radius * 2
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        for r in range(radius, 0, -1):
            t = r / radius
            a = int(90 * (1.0 - t) ** 1.6)
            if a > 0:
                pygame.draw.circle(s, (_CG[0], _CG[1], _CG[2], min(255, a)),
                                   (radius, radius), r)
        return s

    def _make_scanlines(self):
        s = pygame.Surface((FACE_W, SCREEN_H), pygame.SRCALPHA)
        for y in range(0, SCREEN_H, 3):
            pygame.draw.line(s, (0, 0, 0, 20), (0, y), (FACE_W, y))
        return s

    # ── rain ────────────────────────────────────────────────────────────

    def _build_atlas(self):
        for ch in set(_RAIN_CHARS):
            self._atlas[ch] = self._rfont.render(ch, True, _CF)
            self._atlas_br[ch] = self._rfont.render(ch, True, _CD)

    def _init_rain(self):
        self._rain = []
        for x in range(0, FACE_W, 14):
            self._rain.append({
                "x": x, "y": random.uniform(-SCREEN_H, SCREEN_H),
                "spd": random.uniform(30, 80),
                "ch": [random.choice(_RAIN_CHARS) for _ in range(random.randint(3, 10))],
                "on": random.random() < 0.18,
            })

    def _draw_rain(self, surf, p, dt):
        den = p.rain_density
        spd = p.rain_speed
        for c in self._rain:
            if not c["on"]:
                if random.random() < den * 0.01:
                    c["on"] = True
                    c["y"] = -len(c["ch"]) * 12
                continue
            c["y"] += c["spd"] * spd * dt
            if c["y"] > SCREEN_H + 10:
                c["on"] = random.random() < den
                c["y"] = -len(c["ch"]) * 12
                c["ch"] = [random.choice(_RAIN_CHARS) for _ in range(random.randint(3, 10))]
            x = c["x"]
            for k, ch in enumerate(c["ch"]):
                cy = int(c["y"] + k * 12)
                if cy < -12 or cy > SCREEN_H:
                    continue
                s = self._atlas_br.get(ch) if k == len(c["ch"]) - 1 else self._atlas.get(ch)
                if s:
                    surf.blit(s, (x, cy))

    # ── particles ───────────────────────────────────────────────────────

    def _init_parts(self):
        self._parts = []
        for _ in range(70):
            self._parts.append([
                random.uniform(30, FACE_W - 30),
                random.uniform(30, SCREEN_H - 30),
                random.uniform(-4, 4),
                random.uniform(-4, 4),
                random.uniform(0.2, 1.0),
            ])

    def _draw_parts(self, surf, p, dt):
        col = _sc(_CD, 0.2 + p.glow_intensity * 0.3)
        for pt in self._parts:
            pt[0] += pt[2] * dt
            pt[1] += pt[3] * dt
            pt[4] -= dt * 0.08
            if pt[4] <= 0 or pt[0] < 10 or pt[0] > FACE_W - 10 or pt[1] < 10 or pt[1] > SCREEN_H - 10:
                pt[0] = random.uniform(50, FACE_W - 50)
                pt[1] = random.uniform(50, SCREEN_H - 50)
                pt[2] = random.uniform(-4, 4)
                pt[3] = random.uniform(-4, 4)
                pt[4] = 1.0
            pygame.draw.circle(surf, _sc(col, max(0.15, pt[4])),
                               (int(pt[0]), int(pt[1])), 1)

    # ── eyes (dynamic) ──────────────────────────────────────────────────

    def _draw_eyes(self, surf, p):
        openness = p.eye_openness
        eg = p.eye_glow
        psx, psy = p.pupil_x, p.pupil_y
        ps = p.pupil_size

        for ecx, ecy, escale in [
            (self._eye_lx, self._eye_ly, p.left_eye_scale),
            (self._eye_rx, self._eye_ry, p.right_eye_scale),
        ]:
            ew = int(11 * escale)
            eh = int(6 * openness)

            if openness < 0.08:
                pygame.draw.line(surf, _sc(_CM, eg * 0.3),
                                 (ecx - ew, ecy), (ecx + ew, ecy), 1)
                continue

            # Pupil offset
            pcx = int(ecx + psx * ew * 0.3)
            pcy = int(ecy + psy * eh * 0.3)
            pr = max(2, min(4, int(ps * 10)))

            # Glow (subtle)
            if eg > 0.15:
                gs = self._glow.copy()
                gs.set_alpha(int(eg * 70))
                r = 16
                surf.blit(gs, (pcx - r, pcy - r), special_flags=pygame.BLEND_ADD)

            # Bright pupil
            pygame.draw.circle(surf, _sc((0, 220, 255), eg), (pcx, pcy), pr)
            pygame.draw.circle(surf, _sc(_CG, eg * 0.5), (pcx, pcy), pr + 2, 1)

            # Eye outline (small ellipse)
            oc = _sc(_CM, 0.3 + eg * 0.3)
            for k in range(12):
                a = 2 * math.pi * k / 12
                px = int(ecx + ew * math.cos(a))
                py = int(ecy + eh * math.sin(a))
                pygame.draw.circle(surf, oc, (px, py), 1)

    # ── mouth (dynamic) ─────────────────────────────────────────────────

    def _draw_mouth(self, surf, p):
        op = p.mouth_openness
        sm = p.mouth_smile
        w = p.mouth_width
        gl = p.glow_intensity
        col = _sc(_CM, 0.3 + gl * 0.35)

        mx, my = self._mouth_x, self._mouth_y
        mw = int(16 * w)

        pts_u, pts_l = [], []
        n = 14
        for k in range(n):
            t = k / (n - 1)
            x_off = int(-mw + 2 * mw * t)
            norm = (t - 0.5) * 2
            curve = sm * 3 * (1.0 - norm * norm)
            y_open = op * 5

            pts_u.append((mx + x_off, int(my - y_open - curve)))
            pts_l.append((mx + x_off, int(my + y_open - curve)))

        for pts in [pts_u] + ([pts_l] if op > 0.04 else []):
            for k in range(len(pts)):
                pygame.draw.circle(surf, col, pts[k], 1)
                if k > 0:
                    pygame.draw.line(surf, col, pts[k - 1], pts[k], 1)

    # ── glitch ──────────────────────────────────────────────────────────

    def _draw_glitch(self, surf, p):
        if p.glitch_chance < 0.02 or random.random() > p.glitch_chance * 2:
            return
        for _ in range(random.randint(1, 2)):
            y = random.randint(0, SCREEN_H - 6)
            h = random.randint(2, 5)
            off = int(random.uniform(-10, 10) * p.glitch_intensity)
            if off == 0:
                continue
            try:
                band = surf.subsurface(pygame.Rect(
                    max(0, -off), y,
                    min(FACE_W, FACE_W - abs(off)), min(h, SCREEN_H - y)
                )).copy()
                surf.blit(band, (max(0, off), y))
            except ValueError:
                pass

    # ── status ──────────────────────────────────────────────────────────

    def _draw_status(self, surf, p):
        if not p.status_text:
            return
        col = _sc(_CM, 0.35 + p.glow_intensity * 0.35)
        ts = self._sfont.render(p.status_text, True, col)
        surf.blit(ts, (_HCX - ts.get_width() // 2, SCREEN_H - 22))

    # ── main render ─────────────────────────────────────────────────────

    def render(self, surface, params, dt):
        self._t += dt
        self._frame += 1

        surface.set_clip(pygame.Rect(0, 0, FACE_W, SCREEN_H))

        # Rain behind head
        self._draw_rain(surface, params, dt)
        self._draw_parts(surface, params, dt)

        # Head (pre-rendered, modulated by glow)
        alpha = max(30, min(255, int(params.glow_intensity * 280)))
        self._head_surf.set_alpha(alpha)
        surface.blit(self._head_surf, (0, 0))

        # Feature lines
        feat_alpha = max(20, min(200, int(params.glow_intensity * 220)))
        self._feature_surf.set_alpha(feat_alpha)
        surface.blit(self._feature_surf, (0, 0))

        # Dynamic face elements
        self._draw_mouth(surface, params)
        self._draw_eyes(surface, params)

        # Effects
        self._draw_glitch(surface, params)

        op = params.scanline_opacity
        if op > 0.01:
            self._scanline_surf.set_alpha(int(op * 255))
            surface.blit(self._scanline_surf, (0, 0))

        self._draw_status(surface, params)

        surface.set_clip(None)
