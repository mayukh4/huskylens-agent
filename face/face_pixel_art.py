"""
Pixel art particle face renderer for TARS.
Renders face as thousands of flowing white dots on black background.
Inspired by LILYGO particle face displays.
"""

import math
import random
import datetime
import numpy as np
import pygame

from face_renderer import SCREEN_W, SCREEN_H, FACE_W
from face_renderer import BLACK, GREEN_BRIGHT, GREEN_DIM, BORDER_COLOR


class PixelArtFaceRenderer:
    """Renders an AI face as a cloud of animated particles."""

    def __init__(self):
        self.face_w = FACE_W   # 480
        self.face_h = SCREEN_H  # 480
        self.t = 0.0

        # Face center
        self.fcx = self.face_w // 2
        self.fcy = int(self.face_h * 0.40)

        # Scale factors from reference 160x200 design
        self.sx = self.face_w / 160.0
        self.sy = self.face_h / 200.0

        # Fonts for status overlay
        self.label_font = pygame.font.SysFont("monospace", 16, bold=True)
        self.status_font = pygame.font.SysFont("monospace", 11)

        # Particle counts
        self.num_particles = 4500
        self.num_dust = 80

        # Face brightness map and candidate arrays
        self.face_map = None
        self.candidates_x = None
        self.candidates_y = None
        self.candidates_w = None
        self.cum_weights = None
        self.total_weight = 0.0

        # Build initial face map
        self._build_face_map()

        # Initialize particles
        self._init_particles()
        self._init_dust()

        # Frame buffer with trail decay
        self.fbuf = np.zeros((self.face_h, self.face_w), dtype=np.float32)

        # Track last params to detect when face map needs rebuild
        self._last_eye_openness = 1.0
        self._last_pupil_x = 0.0
        self._last_pupil_y = 0.0
        self._last_mouth_openness = 0.0
        self._last_mouth_smile = 0.1

    # ── Face map construction ────────────────────────────────────────

    def _ell(self, surf, cx, cy, rx, ry, gray):
        """Draw filled ellipse at center (cx,cy) with radii (rx,ry)."""
        w = max(1, int(rx * 2))
        h = max(1, int(ry * 2))
        rect = pygame.Rect(int(cx - rx), int(cy - ry), w, h)
        pygame.draw.ellipse(surf, (gray, gray, gray), rect)

    def _lin(self, surf, x0, y0, x1, y1, w, gray):
        """Draw line segment."""
        pygame.draw.line(surf, (gray, gray, gray),
                         (int(x0), int(y0)), (int(x1), int(y1)), max(1, int(w)))

    def _build_face_map(self, params=None):
        """Build a brightness map of the face.  Higher values attract more
        particles, producing density-based shading."""
        surf = pygame.Surface((self.face_w, self.face_h))
        surf.fill((0, 0, 0))

        fcx, fcy = self.fcx, self.fcy
        sx, sy = self.sx, self.sy

        # Expression params (defaults for initial build)
        eo = 1.0 if params is None else params.eye_openness
        px = 0.0 if params is None else params.pupil_x
        py = 0.0 if params is None else params.pupil_y
        mo = 0.0 if params is None else params.mouth_openness
        ms = 0.1 if params is None else params.mouth_smile

        # ── Hair / top of head ───────────────────────────────────────
        self._ell(surf, fcx, fcy - 24 * sy, 42 * sx, 32 * sy, 0x60)
        self._ell(surf, fcx - 10 * sx, fcy - 32 * sy, 32 * sx, 24 * sy, 0x50)
        self._ell(surf, fcx + 6 * sx, fcy - 28 * sy, 34 * sx, 22 * sy, 0x48)

        # ── Head shape ───────────────────────────────────────────────
        self._ell(surf, fcx, fcy + 5 * sy, 38 * sx, 50 * sy, 0x78)

        # Face inner (lighter)
        self._ell(surf, fcx, fcy + 2 * sy, 34 * sx, 44 * sy, 0x90)

        # Forehead highlight
        self._ell(surf, fcx, fcy - 18 * sy, 24 * sx, 13 * sy, 0xA8)

        # Temples
        self._ell(surf, fcx - 30 * sx, fcy - 5 * sy, 8 * sx, 18 * sy, 0x60)
        self._ell(surf, fcx + 30 * sx, fcy - 5 * sy, 8 * sx, 18 * sy, 0x60)

        # Cheeks
        self._ell(surf, fcx - 20 * sx, fcy + 10 * sy, 14 * sx, 12 * sy, 0x80)
        self._ell(surf, fcx + 20 * sx, fcy + 10 * sy, 14 * sx, 12 * sy, 0x80)

        # ── Eyes ─────────────────────────────────────────────────────
        eye_h = max(1.0, 6 * sy * eo)

        # Eye sockets (dark depressions)
        self._ell(surf, fcx - 14 * sx, fcy - 2 * sy, 11 * sx, eye_h, 0x30)
        self._ell(surf, fcx + 14 * sx, fcy - 2 * sy, 11 * sx, eye_h, 0x30)

        if eo > 0.15:
            eb_h = max(1.0, 5 * sy * min(1.0, eo))

            # Eyeballs (sclera)
            self._ell(surf, fcx - 14 * sx, fcy - 2 * sy, 8 * sx, eb_h, 0xC0)
            self._ell(surf, fcx + 14 * sx, fcy - 2 * sy, 8 * sx, eb_h, 0xC0)

            # Pupil offset
            pox = px * 4 * sx
            poy = py * 3 * sy

            # Iris
            self._ell(surf, fcx - 13 * sx + pox, fcy - 2 * sy + poy,
                       4 * sx, 4 * sy, 0xE0)
            self._ell(surf, fcx + 15 * sx + pox, fcy - 2 * sy + poy,
                       4 * sx, 4 * sy, 0xE0)

            # Pupils (brightest)
            self._ell(surf, fcx - 13 * sx + pox, fcy - 2 * sy + poy,
                       2.2 * sx, 2.2 * sy, 0xFF)
            self._ell(surf, fcx + 15 * sx + pox, fcy - 2 * sy + poy,
                       2.2 * sx, 2.2 * sy, 0xFF)

            # Specular highlights
            self._ell(surf, fcx - 11.5 * sx + pox, fcy - 4 * sy + poy,
                       1.2 * sx, 1.2 * sy, 0xFF)
            self._ell(surf, fcx + 16.5 * sx + pox, fcy - 4 * sy + poy,
                       1.2 * sx, 1.2 * sy, 0xFF)

        # Eyebrows
        self._lin(surf, fcx - 24 * sx, fcy - 12 * sy,
                  fcx - 6 * sx, fcy - 11 * sy, 3 * sx, 0x90)
        self._lin(surf, fcx + 6 * sx, fcy - 11 * sy,
                  fcx + 24 * sx, fcy - 12 * sy, 3 * sx, 0x90)

        # ── Nose ─────────────────────────────────────────────────────
        self._lin(surf, fcx, fcy + 1 * sy,
                  fcx - 1 * sx, fcy + 13 * sy, 2 * sx, 0x80)
        self._ell(surf, fcx, fcy + 15 * sy, 6 * sx, 4 * sy, 0x8A)
        # Nostrils
        self._ell(surf, fcx - 4 * sx, fcy + 15.5 * sy, 2.5 * sx, 1.8 * sy, 0x48)
        self._ell(surf, fcx + 4 * sx, fcy + 15.5 * sy, 2.5 * sx, 1.8 * sy, 0x48)

        # ── Mouth ────────────────────────────────────────────────────
        mouth_y = fcy + 24 * sy
        mouth_hw = 11 * sx
        open_off = mo * 5 * sy
        smile_off = ms * 3 * sy

        # Approximate quadratic curve with line segments
        pts_upper = []
        pts_lower = []
        for i in range(13):
            t = i / 12.0
            x = fcx - mouth_hw + 2 * mouth_hw * t
            dn = (t - 0.5) * 2  # -1..1
            curve = smile_off * dn * dn
            pts_upper.append((int(x), int(mouth_y + curve - open_off * 0.4)))
            pts_lower.append((int(x), int(mouth_y + curve + open_off * 0.6 + 3 * sy)))

        if len(pts_upper) > 1:
            pygame.draw.lines(surf, (0xB0, 0xB0, 0xB0), False,
                              pts_upper, max(1, int(2 * sx)))
        if mo > 0.05 and len(pts_lower) > 1:
            pygame.draw.lines(surf, (0x88, 0x88, 0x88), False,
                              pts_lower, max(1, int(1.5 * sx)))
            # Mouth interior
            if mo > 0.08:
                self._ell(surf, fcx, mouth_y + 1.5 * sy,
                          mouth_hw * 0.6, max(1, open_off * 1.8), 0x40)

        # ── Chin / jaw / neck ────────────────────────────────────────
        self._ell(surf, fcx, fcy + 36 * sy, 16 * sx, 10 * sy, 0x78)
        self._ell(surf, fcx, fcy + 44 * sy, 32 * sx, 8 * sy, 0x40)

        # Neck
        pygame.draw.rect(surf, (0x50, 0x50, 0x50),
                         pygame.Rect(int(fcx - 15 * sx), int(fcy + 46 * sy),
                                     int(30 * sx), int(28 * sy)))
        self._ell(surf, fcx, fcy + 46 * sy, 17 * sx, 4 * sy, 0x38)

        # Shoulders
        self._ell(surf, fcx, fcy + 70 * sy, 55 * sx, 18 * sy, 0x44)
        self._ell(surf, fcx, fcy + 78 * sy, 65 * sx, 14 * sy, 0x38)

        # Face contour highlights
        self._lin(surf, fcx - 36 * sx, fcy - 12 * sy,
                  fcx - 32 * sx, fcy + 32 * sy, max(1, sx), 0x80)
        self._lin(surf, fcx + 36 * sx, fcy - 12 * sy,
                  fcx + 32 * sx, fcy + 32 * sy, max(1, sx), 0x80)

        # ── Extract brightness ───────────────────────────────────────
        arr = pygame.surfarray.array3d(surf)           # (w, h, 3)
        self.face_map = arr[:, :, 0].T.astype(np.float32) / 255.0  # (h, w)

        # Build candidate arrays for fast weighted sampling
        ys, xs = np.where(self.face_map > 0.04)
        if len(xs) > 0:
            self.candidates_x = xs.astype(np.float32)
            self.candidates_y = ys.astype(np.float32)
            self.candidates_w = self.face_map[ys, xs]
            self.cum_weights = np.cumsum(self.candidates_w)
            self.total_weight = self.cum_weights[-1]

        del surf

    # ── Weighted sampling ────────────────────────────────────────────

    def _weighted_sample(self, n):
        """Return (xs, ys, weights) for n particles sampled by brightness."""
        if self.total_weight <= 0 or self.candidates_x is None:
            return (np.random.random(n).astype(np.float32) * self.face_w,
                    np.random.random(n).astype(np.float32) * self.face_h,
                    np.full(n, 0.1, dtype=np.float32))

        r = np.random.random(n) * self.total_weight
        idx = np.searchsorted(self.cum_weights, r)
        idx = np.clip(idx, 0, len(self.candidates_x) - 1)

        return (self.candidates_x[idx].copy(),
                self.candidates_y[idx].copy(),
                self.candidates_w[idx].copy())

    # ── Particle initialisation ──────────────────────────────────────

    def _init_particles(self):
        n = self.num_particles
        hx, hy, w = self._weighted_sample(n)

        self.p_hx = hx
        self.p_hy = hy
        self.p_x = hx + (np.random.random(n).astype(np.float32) - 0.5) * 2
        self.p_y = hy + (np.random.random(n).astype(np.float32) - 0.5) * 2
        self.p_brightness = w * (0.6 + np.random.random(n).astype(np.float32) * 0.4)
        self.p_speed = (0.15 + np.random.random(n) * 0.5).astype(np.float32)
        self.p_life = (np.random.random(n) * 150).astype(np.int32)
        self.p_max_life = (50 + np.random.random(n) * 160).astype(np.int32)
        self.p_phase = (np.random.random(n) * np.pi * 2).astype(np.float32)

    def _init_dust(self):
        n = self.num_dust
        self.d_x = (np.random.random(n) * self.face_w).astype(np.float32)
        self.d_y = (np.random.random(n) * self.face_h).astype(np.float32)
        self.d_speed = (0.04 + np.random.random(n) * 0.10).astype(np.float32)
        self.d_brightness = (0.015 + np.random.random(n) * 0.04).astype(np.float32)
        self.d_phase = (np.random.random(n) * np.pi * 2).astype(np.float32)
        self.d_life = (np.random.random(n) * 500).astype(np.int32)
        self.d_max_life = (250 + np.random.random(n) * 500).astype(np.int32)

    # ── Flow field ───────────────────────────────────────────────────

    def _flow_angles(self, px, py, t):
        """Vectorised flow-field angle computation."""
        s = 0.01
        a1 = np.sin(px * s + t * 0.35) + np.cos(py * s * 1.2 + t * 0.25)
        a2 = np.sin(px * s * 1.8 - t * 0.18) * 0.35

        dx = px - self.fcx
        dy = py - self.fcy
        dist = np.sqrt(dx * dx + dy * dy)
        swirl = np.arctan2(dy, dx) + np.pi * 0.5
        sw = np.maximum(0.0, 1.0 - dist / 165.0) * 0.8

        return a1 + a2 + swirl * sw

    # ── Respawn ──────────────────────────────────────────────────────

    def _respawn(self, mask):
        n = int(np.sum(mask))
        if n == 0:
            return
        hx, hy, w = self._weighted_sample(n)
        self.p_hx[mask] = hx
        self.p_hy[mask] = hy
        self.p_x[mask] = hx + (np.random.random(n).astype(np.float32) - 0.5) * 2
        self.p_y[mask] = hy + (np.random.random(n).astype(np.float32) - 0.5) * 2
        self.p_life[mask] = 0
        self.p_max_life[mask] = (50 + np.random.random(n) * 160).astype(np.int32)
        self.p_brightness[mask] = w * (0.6 + np.random.random(n).astype(np.float32) * 0.4)

    # ── Main render ──────────────────────────────────────────────────

    def render(self, surface, params, dt):
        self.t += dt
        t = self.t

        # Rebuild face map when expression changes noticeably
        if (abs(params.eye_openness - self._last_eye_openness) > 0.08 or
                abs(params.pupil_x - self._last_pupil_x) > 0.12 or
                abs(params.pupil_y - self._last_pupil_y) > 0.12 or
                abs(params.mouth_openness - self._last_mouth_openness) > 0.06 or
                abs(params.mouth_smile - self._last_mouth_smile) > 0.12):
            self._build_face_map(params)
            self._last_eye_openness = params.eye_openness
            self._last_pupil_x = params.pupil_x
            self._last_pupil_y = params.pupil_y
            self._last_mouth_openness = params.mouth_openness
            self._last_mouth_smile = params.mouth_smile

        face_surface = surface.subsurface((0, 0, FACE_W, SCREEN_H))

        # ── Trail decay ──────────────────────────────────────────────
        self.fbuf *= 0.84

        # ── Update main particles ────────────────────────────────────
        speed_mult = 0.4 + params.rain_speed * 0.6

        angles = self._flow_angles(self.p_x, self.p_y, t)

        self.p_x += np.cos(angles) * self.p_speed * speed_mult
        self.p_y += np.sin(angles) * self.p_speed * speed_mult

        # Pull towards home position
        self.p_x += (self.p_hx - self.p_x) * 0.018
        self.p_y += (self.p_hy - self.p_y) * 0.018

        # Lifecycle
        self.p_life += 1
        self._respawn(self.p_life > self.p_max_life)

        # Fade envelope (clamp to 0..1 for safety)
        lf = self.p_life.astype(np.float32) / np.maximum(1, self.p_max_life).astype(np.float32)
        fade = np.clip(
            np.where(lf < 0.08, lf / 0.08,
                     np.where(lf > 0.85, (1.0 - lf) / 0.15, 1.0)),
            0.0, 1.0)

        # Flicker
        flicker = 0.5 + 0.5 * np.sin(t * 2.0 + self.p_phase)

        # Final brightness per particle, modulated by face state
        glow = max(0.3, params.glow_intensity * 1.6)
        br = self.p_brightness * fade * flicker * glow

        # Write particles to frame buffer
        ix = np.clip(self.p_x.astype(np.int32), 0, self.face_w - 1)
        iy = np.clip(self.p_y.astype(np.int32), 0, self.face_h - 1)
        np.add.at(self.fbuf, (iy, ix), br)

        # Short stroke tail along flow direction for motion feel
        dx = np.cos(angles)
        dy = np.sin(angles)
        ix2 = np.clip((self.p_x + dx).astype(np.int32), 0, self.face_w - 1)
        iy2 = np.clip((self.p_y + dy).astype(np.int32), 0, self.face_h - 1)
        np.add.at(self.fbuf, (iy2, ix2), br * 0.45)

        # ── Dust particles ───────────────────────────────────────────
        da = self._flow_angles(self.d_x, self.d_y, t * 0.3)
        self.d_x += np.cos(da) * self.d_speed
        self.d_y += np.sin(da) * self.d_speed
        self.d_x %= self.face_w
        self.d_y %= self.face_h

        self.d_life += 1
        dexp = self.d_life > self.d_max_life
        nd = int(np.sum(dexp))
        if nd:
            self.d_x[dexp] = np.random.random(nd).astype(np.float32) * self.face_w
            self.d_y[dexp] = np.random.random(nd).astype(np.float32) * self.face_h
            self.d_life[dexp] = 0

        dbr = self.d_brightness * (0.4 + 0.6 * np.sin(t + self.d_phase))
        dix = np.clip(self.d_x.astype(np.int32), 0, self.face_w - 1)
        diy = np.clip(self.d_y.astype(np.int32), 0, self.face_h - 1)
        np.add.at(self.fbuf, (diy, dix), dbr)

        # ── Glitch effect ────────────────────────────────────────────
        if random.random() < params.glitch_chance:
            n_rows = random.randint(1, max(1, int(6 * params.glitch_intensity)))
            for _ in range(n_rows):
                gy = random.randint(0, self.face_h - 1)
                shift = random.randint(
                    -int(15 * params.glitch_intensity),
                    int(15 * params.glitch_intensity))
                if shift:
                    self.fbuf[gy] = np.roll(self.fbuf[gy], shift)

        # ── Rasterise to surface ─────────────────────────────────────
        v = np.clip(self.fbuf * 255, 0, 255).astype(np.uint8)
        # surfarray expects (width, height, 3) — transpose from (h,w) to (w,h)
        vt = v.T
        rgb = np.stack([vt, vt, vt], axis=2)
        pygame.surfarray.blit_array(face_surface, rgb)

        # ── Subtle scanlines ─────────────────────────────────────────
        if params.scanline_opacity > 0.01:
            sl = pygame.Surface((FACE_W, 1), pygame.SRCALPHA)
            sl.fill((0, 0, 0, int(params.scanline_opacity * 35)))
            for y in range(0, SCREEN_H, 3):
                face_surface.blit(sl, (0, y))

        # ── Status label ─────────────────────────────────────────────
        label = f"[ {params.status_text} ]"
        ls = self.label_font.render(label, True, GREEN_BRIGHT)
        lw = ls.get_width()
        lx = (FACE_W - lw) // 2
        ly = int(SCREEN_H * 0.58)
        bg = pygame.Surface((lw + 16, ls.get_height() + 8), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        face_surface.blit(bg, (lx - 8, ly - 4))
        pygame.draw.rect(face_surface, GREEN_DIM,
                         (lx - 8, ly - 4, lw + 16, ls.get_height() + 8), 1)
        face_surface.blit(ls, (lx, ly))

        # ── Bottom bar ───────────────────────────────────────────────
        bar_y = SCREEN_H - 14
        pygame.draw.line(face_surface, BORDER_COLOR, (0, bar_y), (FACE_W, bar_y))
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        info = f" TARS v1.0 | MCP:10 TOOLS | {ts}"
        face_surface.blit(self.status_font.render(info, True, GREEN_DIM),
                          (4, bar_y + 2))

        # Divider (also drawn by main loop, but consistent with original renderer)
        pygame.draw.line(surface, BORDER_COLOR,
                         (FACE_W, 0), (FACE_W, SCREEN_H), 2)
