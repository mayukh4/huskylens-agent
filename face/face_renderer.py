"""
Matrix/terminal AI face renderer with actual face features.
Left 60% of 800x480 screen = face area (480x480).
"""

import math
import random
import datetime
import pygame

SCREEN_W = 800
SCREEN_H = 480
FACE_W = 480  # 60% of 800
PANEL_W = 320  # 40%
PANEL_X = FACE_W

# Colors
BLACK = (0, 0, 0)
GREEN_BRIGHT = (0, 255, 70)
GREEN_MID = (0, 180, 50)
GREEN_DIM = (0, 100, 30)
GREEN_FAINT = (0, 40, 12)
GREEN_GLOW = (0, 255, 70)
DARK_BG = (3, 8, 3)
PANEL_BG = (5, 12, 5)
BORDER_COLOR = (0, 80, 25)
RED_DIM = (180, 30, 30)

MATRIX_CHARS = "01"
KANJI = "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモ"
ALL_CHARS = MATRIX_CHARS + KANJI + "abcdef0123456789@#$%&"

# Head silhouette for the face area (480x480 region)
# (y_ratio, left_ratio, right_ratio) relative to face area
SILHOUETTE = [
    (0.02, 0.38, 0.62), (0.05, 0.30, 0.70), (0.08, 0.26, 0.74),
    (0.11, 0.23, 0.77), (0.14, 0.21, 0.79), (0.17, 0.20, 0.80),
    (0.20, 0.19, 0.81), (0.23, 0.19, 0.81), (0.26, 0.19, 0.81),
    (0.29, 0.19, 0.81), (0.32, 0.20, 0.80), (0.35, 0.20, 0.80),
    (0.38, 0.21, 0.79), (0.41, 0.22, 0.78), (0.44, 0.24, 0.76),
    (0.47, 0.27, 0.73), (0.50, 0.30, 0.70),
    # Neck
    (0.53, 0.38, 0.62), (0.55, 0.39, 0.61), (0.57, 0.38, 0.62),
    # Shoulders
    (0.60, 0.30, 0.70), (0.63, 0.22, 0.78), (0.66, 0.15, 0.85),
    (0.70, 0.10, 0.90), (0.74, 0.07, 0.93), (0.78, 0.05, 0.95),
    (0.82, 0.03, 0.97), (0.86, 0.02, 0.98), (0.90, 0.01, 0.99),
    (0.95, 0.00, 1.00), (1.00, 0.00, 1.00),
]

# Eye positions (relative to face area)
LEFT_EYE = (0.35, 0.24)   # (x_ratio, y_ratio)
RIGHT_EYE = (0.65, 0.24)
EYE_W_RATIO = 0.10  # width of each eye as ratio of face_w
EYE_H_RATIO = 0.06  # height
PUPIL_RATIO = 0.035

# Mouth position
MOUTH_CENTER = (0.50, 0.40)
MOUTH_W_RATIO = 0.16
MOUTH_H_RATIO = 0.04


class MatrixRain:
    def __init__(self, font, cols, rows, region_w):
        self.font = font
        self.cols = cols
        self.rows = rows
        self.char_w = font.size("A")[0]
        self.char_h = font.get_linesize()
        self.columns = []
        for _ in range(cols):
            self.columns.append({
                'y': random.uniform(-rows, 0),
                'speed': random.uniform(3, 10),
                'chars': [random.choice(ALL_CHARS) for _ in range(rows)],
                'trail': random.randint(4, 12),
                'active': random.random() < 0.2,
            })

    def update(self, dt, density, speed_mult):
        for col in self.columns:
            if not col['active']:
                if random.random() < density * dt * 0.5:
                    col['active'] = True
                    col['y'] = -col['trail']
                    col['speed'] = random.uniform(3, 10) * speed_mult
                continue
            col['y'] += col['speed'] * dt
            if col['y'] > self.rows + col['trail']:
                col['active'] = False
            if random.random() < 0.08:
                col['chars'][random.randint(0, self.rows-1)] = random.choice(ALL_CHARS)

    def render(self, surface, opacity=0.15):
        for i, col in enumerate(self.columns):
            if not col['active']:
                continue
            x = i * self.char_w
            head = int(col['y'])
            for j in range(col['trail']):
                row = head - j
                if 0 <= row < self.rows:
                    fade = 1.0 - j / col['trail']
                    alpha = int(180 * fade * opacity)
                    color = GREEN_BRIGHT if j == 0 else (GREEN_MID if j < 3 else GREEN_DIM)
                    cs = self.font.render(col['chars'][row], True, color)
                    cs.set_alpha(alpha)
                    surface.blit(cs, (x, row * self.char_h))


class FaceRenderer:
    def __init__(self):
        self.font_size = 11
        self.font = pygame.font.SysFont("monospace", self.font_size)
        self.label_font = pygame.font.SysFont("monospace", 16, bold=True)
        self.status_font = pygame.font.SysFont("monospace", 11)

        self.char_w = self.font.size("W")[0]
        self.char_h = self.font.get_linesize()
        self.face_cols = FACE_W // self.char_w
        self.face_rows = SCREEN_H // self.char_h

        self.sil_mask = self._build_mask()
        self.char_grid = [[random.choice(ALL_CHARS) for _ in range(self.face_cols)] for _ in range(self.face_rows)]
        self.rain = MatrixRain(self.font, self.face_cols, self.face_rows, FACE_W)

        # Eye regions (in grid coordinates)
        self.left_eye_rect = self._eye_rect(LEFT_EYE)
        self.right_eye_rect = self._eye_rect(RIGHT_EYE)
        self.mouth_rect = self._mouth_rect()

        self.scanline_y = 0
        self.glitch_offsets = {}

    def _eye_rect(self, pos):
        cx = int(pos[0] * self.face_cols)
        cy = int(pos[1] * self.face_rows)
        hw = int(EYE_W_RATIO * self.face_cols / 2)
        hh = int(EYE_H_RATIO * self.face_rows / 2)
        return (cx - hw, cy - hh, hw * 2, hh * 2)

    def _mouth_rect(self):
        cx = int(MOUTH_CENTER[0] * self.face_cols)
        cy = int(MOUTH_CENTER[1] * self.face_rows)
        hw = int(MOUTH_W_RATIO * self.face_cols / 2)
        hh = int(MOUTH_H_RATIO * self.face_rows / 2)
        return (cx - hw, cy - hh, hw * 2, hh * 2)

    def _build_mask(self):
        mask = [[False] * self.face_cols for _ in range(self.face_rows)]
        for i in range(len(SILHOUETTE) - 1):
            y0, l0, r0 = SILHOUETTE[i]
            y1, l1, r1 = SILHOUETTE[i+1]
            row_s = int(y0 * self.face_rows)
            row_e = int(y1 * self.face_rows)
            for row in range(row_s, min(row_e + 1, self.face_rows)):
                t = (row - row_s) / max(1, row_e - row_s)
                left = int((l0 + (l1 - l0) * t) * self.face_cols)
                right = int((r0 + (r1 - r0) * t) * self.face_cols)
                for col in range(max(0, left), min(self.face_cols, right)):
                    mask[row][col] = True
        return mask

    def _in_eye(self, row, col, params):
        """Check if (row, col) is inside an eye ellipse. Returns (True, is_pupil, intensity)."""
        for eye_rect, scale in [(self.left_eye_rect, params.left_eye_scale),
                                 (self.right_eye_rect, params.right_eye_scale)]:
            ex, ey, ew, eh = eye_rect
            # Scale eye height by openness
            eh_scaled = int(eh * params.eye_openness * scale)
            ew_scaled = int(ew * scale)
            cy = ey + eh // 2
            cx = ex + ew // 2

            # Ellipse test
            dx = (col - cx) / max(1, ew_scaled / 2)
            dy = (row - cy) / max(1, eh_scaled / 2)
            if dx * dx + dy * dy <= 1.0:
                # Inside eye — check if pupil
                pupil_r = params.pupil_size * min(ew_scaled, eh_scaled)
                px = cx + int(params.pupil_x * ew_scaled * 0.3)
                py = cy + int(params.pupil_y * eh_scaled * 0.3)
                pdx = (col - px)
                pdy = (row - py)
                if pdx * pdx + pdy * pdy <= pupil_r * pupil_r:
                    return True, True, 1.0
                # Eye border (brighter at edges)
                dist = math.sqrt(dx * dx + dy * dy)
                edge_factor = 0.4 + 0.6 * dist  # brighter at edge
                return True, False, edge_factor
        return False, False, 0

    def _in_mouth(self, row, col, params):
        """Check if (row, col) is in the mouth region."""
        mx, my, mw, mh = self.mouth_rect
        mw_scaled = int(mw * params.mouth_width)
        mh_open = max(1, int(mh * (0.3 + params.mouth_openness * 2)))
        cx = mx + mw // 2
        cy = my + mh // 2

        # Smile curve: offset y based on x position and smile amount
        dx_norm = (col - cx) / max(1, mw_scaled / 2)
        if abs(dx_norm) > 1.0:
            return False, 0
        smile_offset = params.mouth_smile * 2 * (dx_norm * dx_norm)
        adjusted_cy = cy + int(smile_offset)

        dy = (row - adjusted_cy) / max(1, mh_open / 2)
        if abs(dy) <= 1.0 and abs(dx_norm) <= 1.0:
            dist = abs(dy)
            # Mouth border is bright, inside is dim
            if dist > 0.7:
                return True, 1.0  # border
            elif params.mouth_openness > 0.05:
                return True, 0.3  # inside open mouth
            return True, 0.6
        return False, 0

    def render(self, surface, params, dt):
        # Fill face area
        face_surface = surface.subsurface((0, 0, FACE_W, SCREEN_H))
        face_surface.fill(BLACK)

        now = pygame.time.get_ticks() / 1000.0

        # Matrix rain (background)
        self.rain.update(dt, params.rain_density, params.rain_speed)
        self.rain.render(face_surface, opacity=0.10)

        # Scramble chars
        scramble_count = int(self.face_rows * self.face_cols * params.char_scramble_rate * dt * 30)
        for _ in range(scramble_count):
            r = random.randint(0, self.face_rows - 1)
            c = random.randint(0, self.face_cols - 1)
            self.char_grid[r][c] = random.choice(ALL_CHARS)

        # Glitch
        self.glitch_offsets = {}
        if random.random() < params.glitch_chance:
            for _ in range(random.randint(1, 5)):
                r = random.randint(0, self.face_rows - 1)
                for dr in range(random.randint(1, 3)):
                    if r + dr < self.face_rows:
                        self.glitch_offsets[r + dr] = random.randint(-6, 6) * int(params.glitch_intensity * 8)

        # Render silhouette with face features
        center_row = self.face_rows * 0.30
        center_col = self.face_cols * 0.50
        max_dist = math.sqrt((self.face_rows * 0.4) ** 2 + (self.face_cols * 0.4) ** 2)

        for row in range(self.face_rows):
            x_off = self.glitch_offsets.get(row, 0)
            for col in range(self.face_cols):
                if not self.sil_mask[row][col]:
                    continue

                char = self.char_grid[row][col]

                # Base intensity from distance to center
                dist = math.sqrt((row - center_row) ** 2 + (col - center_col) ** 2)
                base_intensity = params.glow_intensity * (0.25 + 0.75 * (1.0 - min(1, dist / max_dist)))

                # Edge detection (silhouette border is brighter)
                is_edge = False
                for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    nr, nc = row + dr, col + dc
                    if 0 <= nr < self.face_rows and 0 <= nc < self.face_cols:
                        if not self.sil_mask[nr][nc]:
                            is_edge = True
                            break

                # Check face features
                in_eye, is_pupil, eye_intensity = self._in_eye(row, col, params)
                in_mouth, mouth_intensity = self._in_mouth(row, col, params)

                if is_pupil:
                    # Pupil: very bright, use bright chars
                    g = int(min(255, params.eye_glow * 255))
                    color = (g // 8, g, g // 3)
                    char = random.choice("░▒▓█") if random.random() < 0.3 else random.choice("01@#")
                elif in_eye:
                    # Eye region: hollow/dark inside, bright border
                    g = int(min(255, params.eye_glow * eye_intensity * 200))
                    color = (g // 10, g, g // 4)
                    if eye_intensity > 0.7:  # border
                        char = random.choice("()[]{}|/\\") if random.random() < 0.15 else char
                    else:  # inside eye, darker
                        g = max(15, g // 3)
                        color = (0, g, g // 4)
                elif in_mouth:
                    g = int(min(255, params.glow_intensity * mouth_intensity * 200))
                    color = (g // 10, g, g // 4)
                    if mouth_intensity > 0.7:  # border
                        char = random.choice("-=~_") if random.random() < 0.2 else char
                    else:
                        g = max(10, g // 3)
                        color = (0, g, g // 5)
                elif is_edge:
                    g = int(min(255, base_intensity * 1.5 * 255))
                    color = (g // 12, g, g // 3)
                else:
                    g = int(min(255, base_intensity * 180))
                    color = (g // 15, g, g // 4)

                cs = self.font.render(char, True, color)
                px = col * self.char_w + x_off
                py = row * self.char_h
                if 0 <= px < FACE_W - self.char_w:
                    face_surface.blit(cs, (px, py))

        # Scanlines
        self.scanline_y = (self.scanline_y + params.scanline_opacity * dt * 200) % SCREEN_H
        if params.scanline_opacity > 0.01:
            sl = pygame.Surface((FACE_W, 1), pygame.SRCALPHA)
            sl.fill((0, 0, 0, int(params.scanline_opacity * 60)))
            for y in range(0, SCREEN_H, 3):
                face_surface.blit(sl, (0, y))
            # Moving scanline
            bright = pygame.Surface((FACE_W, 2), pygame.SRCALPHA)
            bright.fill((*GREEN_GLOW, int(params.scanline_opacity * 100)))
            face_surface.blit(bright, (0, int(self.scanline_y)))

        # Status label centered on face
        label = f"[ {params.status_text} ]"
        ls = self.label_font.render(label, True, GREEN_BRIGHT)
        lw = ls.get_width()
        lx = (FACE_W - lw) // 2
        ly = int(SCREEN_H * 0.56)
        # Dark bg behind label
        bg = pygame.Surface((lw + 16, ls.get_height() + 8), pygame.SRCALPHA)
        bg.fill((0, 0, 0, 180))
        face_surface.blit(bg, (lx - 8, ly - 4))
        pygame.draw.rect(face_surface, GREEN_DIM, (lx - 8, ly - 4, lw + 16, ls.get_height() + 8), 1)
        face_surface.blit(ls, (lx, ly))

        # Bottom bar on face area
        bar_y = SCREEN_H - self.char_h - 4
        pygame.draw.line(face_surface, BORDER_COLOR, (0, bar_y), (FACE_W, bar_y))
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        info = f" TARS v1.0 | MCP:10 TOOLS | {ts}"
        face_surface.blit(self.status_font.render(info, True, GREEN_DIM), (4, bar_y + 2))

        # Vertical divider between face and panel
        pygame.draw.line(surface, BORDER_COLOR, (FACE_W, 0), (FACE_W, SCREEN_H), 2)
