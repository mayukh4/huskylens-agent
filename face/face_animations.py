"""
TARS face animation state machine.
Matrix aesthetic with actual face features (eyes, mouth).
"""

import time
import math
import random
from enum import Enum
from dataclasses import dataclass


class FaceState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    HAPPY = "happy"
    CURIOUS = "curious"
    SURPRISED = "surprised"
    SLEEPING = "sleeping"
    BOOTING = "booting"
    RECORDING = "recording"


STATE_LABELS = {
    FaceState.IDLE:      "STANDBY",
    FaceState.LISTENING: "LISTENING",
    FaceState.THINKING:  "PROCESSING",
    FaceState.SPEAKING:  "TRANSMITTING",
    FaceState.HAPPY:     "PLEASED",
    FaceState.CURIOUS:   "ANALYZING",
    FaceState.SURPRISED: "ALERT",
    FaceState.SLEEPING:  "LOW POWER",
    FaceState.BOOTING:   "INITIALIZING",
    FaceState.RECORDING: "RECORDING",
}


@dataclass
class FaceParams:
    # Global
    glow_intensity: float = 0.6
    rain_speed: float = 1.0
    rain_density: float = 0.3
    glitch_chance: float = 0.02
    glitch_intensity: float = 0.3
    scanline_opacity: float = 0.15
    char_scramble_rate: float = 0.02
    status_text: str = "STANDBY"
    # Eyes
    eye_openness: float = 1.0       # 0=closed, 1=normal, 1.3=wide
    eye_glow: float = 0.8           # brightness of eye region
    pupil_x: float = 0.0            # -1 to 1
    pupil_y: float = 0.0            # -1 to 1
    pupil_size: float = 0.35        # relative size
    left_eye_scale: float = 1.0     # asymmetry for curious
    right_eye_scale: float = 1.0
    # Mouth
    mouth_openness: float = 0.0     # 0=closed, 1=fully open
    mouth_smile: float = 0.1        # -1 to 1
    mouth_width: float = 1.0        # relative


def lerp(a, b, t):
    return a + (b - a) * min(1.0, max(0.0, t))


class FaceAnimator:
    def __init__(self):
        self.state = FaceState.BOOTING
        self.params = FaceParams()
        self._target = self._get_target(FaceState.BOOTING)
        self._state_start = time.time()
        self._blink_next = time.time() + random.uniform(3, 6)
        self._blink_phase = -1.0
        self._pupil_drift = (0.0, 0.0)
        self._pupil_timer = time.time() + 2.0
        # Vision router gaze override
        self.vision_pupil_x = None  # Set by vision router; None = use default drift
        self.vision_pupil_y = None

    def set_state(self, state: FaceState):
        if state != self.state:
            self.state = state
            self._target = self._get_target(state)
            self._state_start = time.time()

    def _get_target(self, state: FaceState) -> FaceParams:
        p = FaceParams()
        p.status_text = STATE_LABELS.get(state, "STANDBY")

        if state == FaceState.IDLE:
            p.glow_intensity = 0.55
            p.rain_speed = 0.8
            p.rain_density = 0.2
            p.eye_glow = 0.7
            p.glitch_chance = 0.01
        elif state == FaceState.LISTENING:
            p.glow_intensity = 0.7
            p.rain_speed = 1.0
            p.rain_density = 0.3
            p.eye_openness = 1.1
            p.eye_glow = 0.9
            p.mouth_openness = 0.05
            p.glitch_chance = 0.01
        elif state == FaceState.RECORDING:
            p.glow_intensity = 0.85
            p.rain_speed = 1.5
            p.rain_density = 0.4
            p.eye_openness = 1.15
            p.eye_glow = 1.0
            p.mouth_openness = 0.1
            p.glitch_chance = 0.01
            p.status_text = "● RECORDING"
        elif state == FaceState.THINKING:
            p.glow_intensity = 0.65
            p.rain_speed = 2.0
            p.rain_density = 0.5
            p.eye_glow = 0.75
            p.pupil_x = -0.3
            p.pupil_y = -0.3
            p.glitch_chance = 0.03
            p.char_scramble_rate = 0.05
        elif state == FaceState.SPEAKING:
            p.glow_intensity = 0.8
            p.rain_speed = 1.2
            p.rain_density = 0.3
            p.eye_glow = 0.85
            p.glitch_chance = 0.01
        elif state == FaceState.HAPPY:
            p.glow_intensity = 0.85
            p.rain_speed = 0.8
            p.rain_density = 0.35
            p.eye_openness = 0.6
            p.eye_glow = 0.9
            p.mouth_smile = 0.7
            p.mouth_openness = 0.05
            p.glitch_chance = 0.005
        elif state == FaceState.CURIOUS:
            p.glow_intensity = 0.7
            p.rain_speed = 1.5
            p.rain_density = 0.4
            p.eye_glow = 0.85
            p.left_eye_scale = 1.2
            p.right_eye_scale = 0.85
            p.pupil_size = 0.4
            p.mouth_openness = 0.1
            p.mouth_width = 0.7
            p.glitch_chance = 0.03
        elif state == FaceState.SURPRISED:
            p.glow_intensity = 1.0
            p.rain_speed = 2.5
            p.rain_density = 0.5
            p.eye_openness = 1.4
            p.eye_glow = 1.0
            p.pupil_size = 0.2
            p.mouth_openness = 0.5
            p.mouth_width = 0.6
            p.glitch_chance = 0.07
            p.glitch_intensity = 0.5
        elif state == FaceState.SLEEPING:
            p.glow_intensity = 0.15
            p.rain_speed = 0.2
            p.rain_density = 0.08
            p.eye_openness = 0.05
            p.eye_glow = 0.2
            p.scanline_opacity = 0.05
            p.glitch_chance = 0.0
        elif state == FaceState.BOOTING:
            p.glow_intensity = 0.4
            p.rain_speed = 2.5
            p.rain_density = 0.6
            p.eye_glow = 0.5
            p.glitch_chance = 0.06
            p.char_scramble_rate = 0.08
        return p

    def update(self, dt: float):
        now = time.time()
        t = dt * 4.0  # transition speed

        # Lerp all params
        p, tgt = self.params, self._target
        p.glow_intensity = lerp(p.glow_intensity, tgt.glow_intensity, t)
        p.rain_speed = lerp(p.rain_speed, tgt.rain_speed, t)
        p.rain_density = lerp(p.rain_density, tgt.rain_density, t)
        p.glitch_chance = lerp(p.glitch_chance, tgt.glitch_chance, t)
        p.glitch_intensity = lerp(p.glitch_intensity, tgt.glitch_intensity, t)
        p.scanline_opacity = lerp(p.scanline_opacity, tgt.scanline_opacity, t)
        p.char_scramble_rate = lerp(p.char_scramble_rate, tgt.char_scramble_rate, t)
        p.eye_openness = lerp(p.eye_openness, tgt.eye_openness, t)
        p.eye_glow = lerp(p.eye_glow, tgt.eye_glow, t)
        p.pupil_x = lerp(p.pupil_x, tgt.pupil_x, t)
        p.pupil_y = lerp(p.pupil_y, tgt.pupil_y, t)
        p.pupil_size = lerp(p.pupil_size, tgt.pupil_size, t)
        p.left_eye_scale = lerp(p.left_eye_scale, tgt.left_eye_scale, t)
        p.right_eye_scale = lerp(p.right_eye_scale, tgt.right_eye_scale, t)
        p.mouth_openness = lerp(p.mouth_openness, tgt.mouth_openness, t)
        p.mouth_smile = lerp(p.mouth_smile, tgt.mouth_smile, t)
        p.mouth_width = lerp(p.mouth_width, tgt.mouth_width, t)
        p.status_text = tgt.status_text

        # Breathing pulse
        elapsed = now - self._state_start
        pulse = math.sin(elapsed * 1.5 * math.pi)
        p.glow_intensity = max(0.05, min(1.0, p.glow_intensity + pulse * 0.08))

        # Blinking
        if self.state not in (FaceState.SLEEPING, FaceState.HAPPY):
            if self._blink_phase < 0 and now >= self._blink_next:
                self._blink_phase = 0.0
            if self._blink_phase >= 0:
                self._blink_phase += dt / 0.15
                if self._blink_phase < 0.5:
                    p.eye_openness *= (1.0 - self._blink_phase * 2)
                elif self._blink_phase < 1.0:
                    p.eye_openness *= ((self._blink_phase - 0.5) * 2)
                else:
                    self._blink_phase = -1.0
                    self._blink_next = now + random.uniform(3, 6)

        # Speaking mouth animation
        if self.state == FaceState.SPEAKING:
            p.mouth_openness = 0.1 + 0.35 * abs(math.sin(elapsed * 4.5 * math.pi))

        # Idle pupil drift (overridden by vision router gaze when available)
        if self.state in (FaceState.IDLE, FaceState.LISTENING):
            if self.vision_pupil_x is not None and self.vision_pupil_y is not None:
                # Vision router gaze tracking — smooth lerp toward gaze target
                p.pupil_x = lerp(p.pupil_x, self.vision_pupil_x, t * 0.5)
                p.pupil_y = lerp(p.pupil_y, self.vision_pupil_y, t * 0.5)
            else:
                if now >= self._pupil_timer:
                    self._pupil_drift = (random.uniform(-0.2, 0.2), random.uniform(-0.15, 0.15))
                    self._pupil_timer = now + random.uniform(2, 5)
                p.pupil_x = lerp(p.pupil_x, self._pupil_drift[0], t * 0.3)
                p.pupil_y = lerp(p.pupil_y, self._pupil_drift[1], t * 0.3)

        # Thinking pupil movement
        if self.state == FaceState.THINKING:
            p.pupil_x = -0.3 + 0.2 * math.sin(elapsed * 0.8)
            p.pupil_y = -0.2 + 0.15 * math.cos(elapsed * 0.6)
