/**
 * TARS Face Animator — port of face_animations.py
 * State machine with smooth lerp transitions, blinking, breathing, pupil drift.
 */

const STATE_LABELS = {
  idle: 'STANDBY', listening: 'LISTENING', thinking: 'PROCESSING',
  speaking: 'TRANSMITTING', happy: 'PLEASED', curious: 'ANALYZING',
  surprised: 'ALERT', sleeping: 'LOW POWER', booting: 'INITIALIZING',
  recording: 'RECORDING'
};

function lerp(a, b, t) {
  return a + (b - a) * Math.min(1.0, Math.max(0.0, t));
}

function getTargetParams(state) {
  const p = {
    glow_intensity: 0.6, rain_speed: 1.0, rain_density: 0.3,
    glitch_chance: 0.02, glitch_intensity: 0.3,
    scanline_opacity: 0.15, status_text: STATE_LABELS[state] || 'STANDBY',
    eye_openness: 1.0, eye_glow: 0.8,
    pupil_x: 0.0, pupil_y: 0.0, pupil_size: 0.35,
    left_eye_scale: 1.0, right_eye_scale: 1.0,
    mouth_openness: 0.0, mouth_smile: 0.1, mouth_width: 1.0,
    flow_speed: 1.0, swirl_intensity: 0.4
  };

  switch (state) {
    case 'idle':
      p.glow_intensity = 0.55; p.rain_speed = 0.8; p.rain_density = 0.2;
      p.eye_glow = 0.7; p.glitch_chance = 0.01;
      p.flow_speed = 0.8; p.swirl_intensity = 0.35;
      break;
    case 'listening':
      p.glow_intensity = 0.7; p.rain_density = 0.3;
      p.eye_openness = 1.1; p.eye_glow = 0.9; p.mouth_openness = 0.05;
      p.glitch_chance = 0.01;
      p.flow_speed = 1.0; p.swirl_intensity = 0.5;
      break;
    case 'recording':
      p.glow_intensity = 0.85; p.rain_speed = 1.5; p.rain_density = 0.4;
      p.eye_openness = 1.15; p.eye_glow = 1.0; p.mouth_openness = 0.1;
      p.glitch_chance = 0.01; p.status_text = '\u25CF RECORDING';
      p.flow_speed = 1.1; p.swirl_intensity = 0.55;
      break;
    case 'thinking':
      p.glow_intensity = 0.65; p.rain_speed = 2.0; p.rain_density = 0.5;
      p.eye_glow = 0.75; p.pupil_x = -0.3; p.pupil_y = -0.3;
      p.glitch_chance = 0.03;
      p.flow_speed = 2.0; p.swirl_intensity = 1.0;
      break;
    case 'speaking':
      p.glow_intensity = 0.8; p.rain_speed = 1.2; p.rain_density = 0.3;
      p.eye_glow = 0.85; p.glitch_chance = 0.01;
      p.flow_speed = 1.3; p.swirl_intensity = 0.45;
      break;
    case 'happy':
      p.glow_intensity = 0.85; p.rain_speed = 0.8; p.rain_density = 0.35;
      p.eye_openness = 0.6; p.eye_glow = 0.9;
      p.mouth_smile = 0.7; p.mouth_openness = 0.05; p.glitch_chance = 0.005;
      p.flow_speed = 0.9; p.swirl_intensity = 0.3;
      break;
    case 'curious':
      p.glow_intensity = 0.7; p.rain_speed = 1.5; p.rain_density = 0.4;
      p.eye_glow = 0.85; p.left_eye_scale = 1.2; p.right_eye_scale = 0.85;
      p.pupil_size = 0.4; p.mouth_openness = 0.1; p.mouth_width = 0.7;
      p.glitch_chance = 0.03;
      p.flow_speed = 1.4; p.swirl_intensity = 0.7;
      break;
    case 'surprised':
      p.glow_intensity = 1.0; p.rain_speed = 2.5; p.rain_density = 0.5;
      p.eye_openness = 1.4; p.eye_glow = 1.0; p.pupil_size = 0.2;
      p.mouth_openness = 0.5; p.mouth_width = 0.6;
      p.glitch_chance = 0.07; p.glitch_intensity = 0.5;
      p.flow_speed = 2.5; p.swirl_intensity = 0.9;
      break;
    case 'sleeping':
      p.glow_intensity = 0.15; p.rain_speed = 0.2; p.rain_density = 0.08;
      p.eye_openness = 0.05; p.eye_glow = 0.2;
      p.scanline_opacity = 0.05; p.glitch_chance = 0.0;
      p.flow_speed = 0.3; p.swirl_intensity = 0.2;
      break;
    case 'booting':
      p.glow_intensity = 0.4; p.rain_speed = 2.5; p.rain_density = 0.6;
      p.eye_glow = 0.5; p.glitch_chance = 0.06;
      p.flow_speed = 1.8; p.swirl_intensity = 1.2;
      break;
  }
  return p;
}

const LERP_FIELDS = [
  'glow_intensity', 'rain_speed', 'rain_density', 'glitch_chance',
  'glitch_intensity', 'scanline_opacity', 'eye_openness', 'eye_glow',
  'pupil_x', 'pupil_y', 'pupil_size', 'left_eye_scale', 'right_eye_scale',
  'mouth_openness', 'mouth_smile', 'mouth_width',
  'flow_speed', 'swirl_intensity'
];

class FaceAnimator {
  constructor() {
    this.state = 'booting';
    this.params = getTargetParams('booting');
    this._target = getTargetParams('booting');
    this._stateStart = performance.now() / 1000;
    this._blinkNext = performance.now() / 1000 + 1.5 + Math.random() * 2.2;
    this._blinkPhase = -1;
    this._pupilDrift = [0, 0];
    this._pupilTimer = performance.now() / 1000 + 2;
  }

  setState(state) {
    if (state !== this.state) {
      this.state = state;
      this._target = getTargetParams(state);
      this._stateStart = performance.now() / 1000;
    }
  }

  update(dt) {
    const now = performance.now() / 1000;
    const t = dt * 4.0;
    const tgt = this._target;

    // Lerp all numeric params
    for (const f of LERP_FIELDS) {
      this.params[f] = lerp(this.params[f], tgt[f], t);
    }
    this.params.status_text = tgt.status_text;

    const elapsed = now - this._stateStart;

    // Blinking
    if (this.state !== 'sleeping' && this.state !== 'happy') {
      if (this._blinkPhase < 0 && now >= this._blinkNext) {
        this._blinkPhase = 0;
      }
      if (this._blinkPhase >= 0) {
        this._blinkPhase += dt / 0.15;
        if (this._blinkPhase < 0.5) {
          this.params.eye_openness *= (1.0 - this._blinkPhase * 2);
        } else if (this._blinkPhase < 1.0) {
          this.params.eye_openness *= ((this._blinkPhase - 0.5) * 2);
        } else {
          this._blinkPhase = -1;
          this._blinkNext = now + 1.5 + Math.random() * 2.2;
        }
      }
    }

    // Speaking mouth
    if (this.state === 'speaking') {
      this.params.mouth_openness = 0.1 + 0.35 * Math.abs(
        Math.sin(elapsed * 4.5 * Math.PI));
    }

    // Idle pupil drift
    if (this.state === 'idle' || this.state === 'listening') {
      if (now >= this._pupilTimer) {
        this._pupilDrift = [
          (Math.random() - 0.5) * 0.4,
          (Math.random() - 0.5) * 0.3
        ];
        this._pupilTimer = now + 2 + Math.random() * 3;
      }
      this.params.pupil_x = lerp(this.params.pupil_x, this._pupilDrift[0], t * 0.3);
      this.params.pupil_y = lerp(this.params.pupil_y, this._pupilDrift[1], t * 0.3);
    }

    // Thinking pupil motion
    if (this.state === 'thinking') {
      this.params.pupil_x = -0.3 + 0.2 * Math.sin(elapsed * 0.8);
      this.params.pupil_y = -0.2 + 0.15 * Math.cos(elapsed * 0.6);
    }
  }
}
