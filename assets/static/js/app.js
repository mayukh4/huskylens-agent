/**
 * TARS App — main entry point.
 * Polls backend for state, drives animator + renderer + panel.
 */

(function () {
  'use strict';

  const STATE_MAP = {
    idle: 'idle', listening: 'listening', thinking: 'thinking',
    speaking: 'speaking', happy: 'happy', curious: 'curious',
    surprised: 'surprised', sleeping: 'sleeping', booting: 'booting',
    recording: 'recording', neutral: 'idle'
  };

  const canvas = document.getElementById('face-canvas');
  canvas.width = 480;
  canvas.height = 480;

  const faceRenderer = new FaceRenderer(canvas);
  const animator = new FaceAnimator();
  const panel = new PanelManager();
  const statusLabel = document.getElementById('status-label');

  let lastTime = performance.now() / 1000;

  // ── State polling ────────────────────────────────────

  async function pollState() {
    try {
      const resp = await fetch('/api/state');
      if (!resp.ok) return;
      const state = await resp.json();

      const mapped = STATE_MAP[state.face] || 'idle';
      animator.setState(mapped);

      panel.update(state);

      statusLabel.textContent = animator.params.status_text;
    } catch (e) {
      // Server unreachable — ignore, retry next cycle
    }
  }

  setInterval(pollState, 200);
  pollState();

  // ── Render loop (60fps) ──────────────────────────────

  function animate() {
    const now = performance.now() / 1000;
    const dt = Math.min(now - lastTime, 0.1);
    lastTime = now;

    animator.update(dt);
    faceRenderer.update(animator.params, dt);

    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);

  // ── Touch / Click ────────────────────────────────────

  document.getElementById('exit-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    fetch('/api/exit', { method: 'POST' });
  });

  document.getElementById('container').addEventListener('click', (e) => {
    if (e.target.id === 'exit-btn') return;
    fetch('/api/speak', { method: 'POST' });
  });

})();
