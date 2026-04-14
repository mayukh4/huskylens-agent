/**
 * TARS Edge-Flow Portrait Renderer — Canvas2D.
 *
 * A high-contrast grayscale portrait (img/portrait.png) is converted
 * into a weighted anchor field using a Sobel edge magnitude blended
 * with raw luminance.  Thousands of tiny strokes are weighted-sampled
 * from that field, then flow along a gentle curl field while a spring
 * pulls each back to its home pixel.  Particles cluster on edges
 * (eyes, brow, nose, beard, jaw) and the aggregate reads as a sharp,
 * flowing portrait.
 *
 * Extras:
 *   - Human-cadence eye blinks (driven by animator eye_openness).
 *   - Subtle green matrix-rain background on its own canvas.
 *
 * Interface preserved so app.js keeps working unchanged:
 *   new FaceRenderer(canvas);  renderer.update(params, dt);
 */

(function () {
  'use strict';

  const PW = 480;
  const PH = 480;
  const FCX = PW / 2;
  const FCY = PH / 2;
  const PORTRAIT_PATH = 'img/portrait.png';

  // Tuning — dialed for definition and crispness over soft blobs.
  const N_STROKES      = 7200;
  const N_DUST         = 60;
  const TRAIL_DECAY    = 0.84;   // longer trails → denser / more opaque
  const ANCHOR_PULL    = 0.045;
  const EDGE_WEIGHT    = 0.80;
  const LUMA_WEIGHT    = 0.20;
  const MIN_WEIGHT     = 0.08;
  const FLOW_SCALE     = 0.012;
  // Pupil glow splats — drawn additively each frame, independent of
  // whatever strokes are near the eye.  Shape / position is controlled
  // fully here, so there are no bbox-shaped artefacts from boosting
  // existing strokes.
  const EYE_CENTERS = [
    { x: 199, y: 226 }, // left eye (viewer's left)
    { x: 298, y: 226 }, // right eye
  ];
  const EYE_RADIUS     = 5.5;    // pupil glow radius in pixels
  const EYE_PEAK       = 0.95;   // peak brightness at center (0..1)

  // Eye blink rectangles, in face-canvas pixel coordinates.  These
  // should cover each eye in the source portrait.  Update when the
  // portrait is replaced.  Default tuned for a front-facing 480×480
  // portrait with eyes roughly on the y=200 line.
  // Area the animation disturbs during a blink.  Kept small and
  // centered on the pupil so it looks like a flicker, not a wipe.
  const BLINK_RADIUS_X = 14;
  const BLINK_RADIUS_Y = 7;

  // ── Utilities ──────────────────────────────────────────────────────

  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }

  // ── Build the anchor weight field from a portrait image ───────────

  function buildWeightField(img) {
    const tmp = document.createElement('canvas');
    tmp.width = PW;
    tmp.height = PH;
    const tctx = tmp.getContext('2d', { willReadFrequently: true });
    tctx.fillStyle = '#000';
    tctx.fillRect(0, 0, PW, PH);

    // Fit-to-cover so any aspect ratio survives.
    const iw = img.naturalWidth || PW;
    const ih = img.naturalHeight || PH;
    const scale = Math.max(PW / iw, PH / ih);
    const dw = iw * scale, dh = ih * scale;
    tctx.drawImage(img, (PW - dw) / 2, (PH - dh) / 2, dw, dh);

    const data = tctx.getImageData(0, 0, PW, PH).data;

    // Luminance.
    const lum = new Float32Array(PW * PH);
    let lmax = 0;
    for (let i = 0, j = 0, L = PW * PH; i < L; i++, j += 4) {
      const l = 0.299 * data[j] + 0.587 * data[j + 1] + 0.114 * data[j + 2];
      lum[i] = l;
      if (l > lmax) lmax = l;
    }
    if (lmax < 1) lmax = 1;
    for (let i = 0, L = PW * PH; i < L; i++) lum[i] /= lmax;

    // Sobel magnitude.
    const edge = new Float32Array(PW * PH);
    let emax = 0;
    for (let y = 1; y < PH - 1; y++) {
      for (let x = 1; x < PW - 1; x++) {
        const i = y * PW + x;
        const tl = lum[i - PW - 1], tc = lum[i - PW], tr = lum[i - PW + 1];
        const ml = lum[i - 1],                            mr = lum[i + 1];
        const bl = lum[i + PW - 1], bc = lum[i + PW], br2 = lum[i + PW + 1];
        const gx = (tr + 2 * mr + br2) - (tl + 2 * ml + bl);
        const gy = (bl + 2 * bc + br2) - (tl + 2 * tc + tr);
        const m = Math.sqrt(gx * gx + gy * gy);
        edge[i] = m;
        if (m > emax) emax = m;
      }
    }
    if (emax < 0.0001) emax = 1;
    for (let i = 0, L = PW * PH; i < L; i++) edge[i] /= emax;

    // Combined weight + candidate list.
    const xs = new Int16Array(PW * PH);
    const ys = new Int16Array(PW * PH);
    const ws = new Float32Array(PW * PH);
    const cdf = new Float32Array(PW * PH);
    let n = 0;
    let total = 0;
    for (let y = 0; y < PH; y++) {
      for (let x = 0; x < PW; x++) {
        const i = y * PW + x;
        let w = LUMA_WEIGHT * lum[i] + EDGE_WEIGHT * edge[i];
        if (w < MIN_WEIGHT) continue;
        w = w * w;
        xs[n] = x;
        ys[n] = y;
        ws[n] = w;
        total += w;
        cdf[n] = total;
        n++;
      }
    }
    return { xs, ys, ws, cdf, n, total };
  }

  function sampleCandidate(cands) {
    const r = Math.random() * cands.total;
    let lo = 0, hi = cands.n - 1;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (cands.cdf[mid] < r) lo = mid + 1; else hi = mid;
    }
    return lo;
  }

  function fallbackField() {
    const n = 2000;
    const xs = new Int16Array(n);
    const ys = new Int16Array(n);
    const ws = new Float32Array(n);
    const cdf = new Float32Array(n);
    let total = 0;
    for (let i = 0; i < n; i++) {
      const ang = Math.random() * Math.PI * 2;
      const r = Math.random() * 140;
      xs[i] = Math.round(FCX + Math.cos(ang) * r);
      ys[i] = Math.round(FCY + Math.sin(ang) * r);
      ws[i] = 0.3;
      total += 0.3;
      cdf[i] = total;
    }
    return { xs, ys, ws, cdf, n, total };
  }

  // ── FaceRenderer ───────────────────────────────────────────────────

  class FaceRenderer {
    constructor(canvas) {
      this.canvas = canvas;
      this.canvas.width = PW;
      this.canvas.height = PH;
      this.ctx = canvas.getContext('2d');

      this.fbuf = new Float32Array(PW * PH);
      this.outImg = this.ctx.createImageData(PW, PH);

      this.cands = fallbackField();
      this.strokes = new Array(N_STROKES);
      for (let i = 0; i < N_STROKES; i++) this.strokes[i] = this._spawnStroke();
      this.dust = new Array(N_DUST);
      for (let i = 0; i < N_DUST; i++) {
        this.dust[i] = {
          x: Math.random() * PW, y: Math.random() * PH,
          speed: 0.04 + Math.random() * 0.10,
          brightness: 0.015 + Math.random() * 0.04,
          phase: Math.random() * Math.PI * 2,
          life: Math.floor(Math.random() * 500),
          maxLife: 300 + Math.floor(Math.random() * 500),
        };
      }

      this.t = 0;

      // Load portrait and rebuild the anchor field when ready.
      const img = new Image();
      img.onload = () => {
        try {
          this.cands = buildWeightField(img);
          for (const s of this.strokes) this._respawn(s);
        } catch (e) {
          console.error('buildWeightField failed', e);
        }
      };
      img.onerror = () => { console.warn('portrait.png failed to load'); };
      img.src = PORTRAIT_PATH;
    }

    _spawnStroke() {
      const idx = sampleCandidate(this.cands);
      const hx = this.cands.xs[idx];
      const hy = this.cands.ys[idx];
      return {
        hx, hy,
        x: hx + (Math.random() - 0.5) * 1.5,
        y: hy + (Math.random() - 0.5) * 1.5,
        speed: 0.10 + Math.random() * 0.45,
        brightness: this.cands.ws[idx] * (1.15 + Math.random() * 0.55),
        life: Math.floor(Math.random() * 150),
        maxLife: 70 + Math.floor(Math.random() * 170),
        phase: Math.random() * Math.PI * 2,
      };
    }

    _respawn(s) {
      const idx = sampleCandidate(this.cands);
      s.hx = this.cands.xs[idx];
      s.hy = this.cands.ys[idx];
      s.x = s.hx + (Math.random() - 0.5) * 1.5;
      s.y = s.hy + (Math.random() - 0.5) * 1.5;
      s.life = 0;
      s.maxLife = 70 + Math.floor(Math.random() * 170);
      s.brightness = this.cands.ws[idx] * (1.15 + Math.random() * 0.55);
    }

    _flowAngle(x, y, swirl) {
      const s = FLOW_SCALE;
      const a1 = Math.sin(x * s + this.t * 0.35)
               + Math.cos(y * s * 1.2 + this.t * 0.25);
      const a2 = Math.sin(x * s * 1.8 - this.t * 0.18) * 0.35;
      const dx = x - FCX, dy = y - FCY;
      const dist = Math.sqrt(dx * dx + dy * dy);
      const sw = Math.max(0, 1 - dist / 200) * swirl;
      const swAng = Math.atan2(dy, dx) + Math.PI * 0.5;
      return a1 + a2 + swAng * sw;
    }

    _setPx(x, y, v) {
      const ix = x | 0, iy = y | 0;
      if (ix < 0 || ix >= PW || iy < 0 || iy >= PH) return;
      const i = iy * PW + ix;
      const cur = this.fbuf[i] + v;
      this.fbuf[i] = cur > 1 ? 1 : cur;
    }

    // Eye handling, applied after all stroke drawing.
    //   - When open: additively splat a small round gaussian hotspot
    //     at each pupil center.  No bbox, no multiplier, no
    //     rectangular artefacts.
    //   - When blinking: fade the pupil splat, and also damp the
    //     strokes in a small ellipse around each eye so the blink is
    //     visible as a brief darkening flicker.
    _applyEyes(eyeOpenness) {
      const fb = this.fbuf;
      const openT = clamp(eyeOpenness / 0.6, 0, 1);
      const blinkT = 1 - openT;   // 0 open, 1 fully closed
      const peak = EYE_PEAK * openT;

      // Damp strokes in a small ellipse around each pupil during blink.
      if (blinkT > 0.05) {
        const keep = 1 - 0.9 * blinkT;
        for (let e = 0; e < EYE_CENTERS.length; e++) {
          const cx = EYE_CENTERS[e].x;
          const cy = EYE_CENTERS[e].y;
          const rx = BLINK_RADIUS_X;
          const ry = BLINK_RADIUS_Y;
          const x0 = Math.max(0, (cx - rx) | 0);
          const y0 = Math.max(0, (cy - ry) | 0);
          const x1 = Math.min(PW, (cx + rx) | 0);
          const y1 = Math.min(PH, (cy + ry) | 0);
          for (let y = y0; y < y1; y++) {
            const dy = (y - cy) / ry;
            const dy2 = dy * dy;
            const row = y * PW;
            for (let x = x0; x < x1; x++) {
              const dx = (x - cx) / rx;
              const d2 = dx * dx + dy2;
              if (d2 >= 1) continue;
              const fall = 1 - d2;
              const localKeep = 1 - (1 - keep) * fall;
              fb[row + x] *= localKeep;
            }
          }
        }
      }

      // Additive pupil splats — circular gaussian, small and bright.
      if (peak > 0.02) {
        const r = EYE_RADIUS;
        const r2 = r * r;
        for (let e = 0; e < EYE_CENTERS.length; e++) {
          const cx = EYE_CENTERS[e].x;
          const cy = EYE_CENTERS[e].y;
          const x0 = Math.max(0, Math.floor(cx - r - 1));
          const y0 = Math.max(0, Math.floor(cy - r - 1));
          const x1 = Math.min(PW, Math.ceil(cx + r + 1));
          const y1 = Math.min(PH, Math.ceil(cy + r + 1));
          for (let y = y0; y < y1; y++) {
            const dy = y - cy;
            const dy2 = dy * dy;
            const row = y * PW;
            for (let x = x0; x < x1; x++) {
              const dx = x - cx;
              const d2 = dx * dx + dy2;
              if (d2 >= r2) continue;
              // Smooth gaussian-ish falloff: 1 at center, 0 at edge.
              const fall = 1 - d2 / r2;
              const add = peak * fall * fall;
              const v = fb[row + x] + add;
              fb[row + x] = v > 1 ? 1 : v;
            }
          }
        }
      }
    }

    update(params, dt) {
      this.t += dt;

      const flowSpeed    = params.flow_speed      != null ? params.flow_speed      : 1.0;
      const swirl        = params.swirl_intensity != null ? params.swirl_intensity : 0.3;
      const glitchChance = params.glitch_chance || 0.01;
      const glow         = params.glow_intensity  != null ? params.glow_intensity  : 0.6;
      const eyeOpenness  = params.eye_openness    != null ? params.eye_openness    : 1.0;

      // Decay trails.
      const fb = this.fbuf;
      const decay = TRAIL_DECAY;
      for (let i = 0, L = fb.length; i < L; i++) fb[i] *= decay;

      // Integrate strokes.
      const sm = 0.35 + flowSpeed * 0.65;
      const glowK = Math.max(0.55, glow * 1.6);
      for (let i = 0; i < N_STROKES; i++) {
        const s = this.strokes[i];
        s.life++;
        if (s.life > s.maxLife ||
            s.x < -8 || s.x > PW + 8 || s.y < -8 || s.y > PH + 8) {
          this._respawn(s);
        }
        const a = this._flowAngle(s.x, s.y, swirl);
        s.x += Math.cos(a) * s.speed * sm;
        s.y += Math.sin(a) * s.speed * sm;
        s.x += (s.hx - s.x) * ANCHOR_PULL;
        s.y += (s.hy - s.y) * ANCHOR_PULL;

        const lf = s.life / s.maxLife;
        const fade = lf < 0.08 ? lf / 0.08 :
                     lf > 0.85 ? Math.max(0, (1 - lf) / 0.15) : 1;
        const fl = 0.55 + 0.45 * Math.sin(this.t * 2 + s.phase);
        const br = s.brightness * fade * fl * glowK;
        this._setPx(s.x, s.y, br);
        this._setPx(s.x + Math.cos(a), s.y + Math.sin(a), br * 0.55);
      }

      // Dust.
      for (let i = 0; i < N_DUST; i++) {
        const d = this.dust[i];
        d.life++;
        if (d.life > d.maxLife) {
          d.x = Math.random() * PW;
          d.y = Math.random() * PH;
          d.life = 0;
        }
        const a = this._flowAngle(d.x, d.y, swirl * 0.4) + 0.2;
        d.x += Math.cos(a) * d.speed * sm * 0.6;
        d.y += Math.sin(a) * d.speed * sm * 0.6;
        if (d.x < 0) d.x += PW; else if (d.x >= PW) d.x -= PW;
        if (d.y < 0) d.y += PH; else if (d.y >= PH) d.y -= PH;
        const fl = 0.4 + 0.6 * Math.sin(this.t + d.phase);
        this._setPx(d.x, d.y, d.brightness * fl * glowK);
      }

      // Occasional horizontal glitch row-shift.
      if (Math.random() < glitchChance) {
        const nRows = 1 + ((Math.random() * 5) | 0);
        for (let r = 0; r < nRows; r++) {
          const gy = (Math.random() * PH) | 0;
          const shift = ((Math.random() - 0.5) * 30) | 0;
          if (!shift) continue;
          const rowStart = gy * PW;
          const copy = new Float32Array(fb.subarray(rowStart, rowStart + PW));
          for (let x = 0; x < PW; x++) {
            const sx = ((x - shift) % PW + PW) % PW;
            fb[rowStart + x] = copy[sx];
          }
        }
      }

      // Eye region: boost brightness when open, fade when blinking.
      this._applyEyes(eyeOpenness);

      // Blit float buffer → canvas as fully opaque grayscale.  This is
      // the v1 look the user approved; anything alpha-blended gets
      // washed out against whatever sits behind the canvas.
      const out = this.outImg.data;
      for (let i = 0, L = fb.length; i < L; i++) {
        const v = fb[i];
        const q = v >= 1 ? 255 : (v * 255) | 0;
        const j = i << 2;
        out[j] = q; out[j + 1] = q; out[j + 2] = q; out[j + 3] = 255;
      }
      this.ctx.putImageData(this.outImg, 0, 0);
    }
  }

  window.FaceRenderer = FaceRenderer;
})();
