# Architecture

tars-vision is a single Python process (`assets/face_server.py`) that fans out into worker threads sharing one HuskyLens camera over I2C. The face is a browser UI served from Flask. Hermes Agent is an out-of-process peer that the skill talks to via HTTP.

## Process map

```
  face_server.py  (one process, several threads)
  ├── Flask HTTP server on :5555
  │     ├─ / and /static/*  → serves assets/static/ (Three.js face UI)
  │     ├─ POST /state, /expression, /log  → drive the face (used by Hermes)
  │     ├─ GET  /health, /api/state        → frontend polls for status
  │     └─ POST /api/speak                 → tap-to-speak entrypoint
  │
  ├── Vision router thread  (assets/vision_router.py)
  │     polls HuskyLens at 0.5–1.2 Hz over I2C in ALGORITHM_HAND_RECOGNITION,
  │     classifies palm / fist / victory from 21 keypoints,
  │     dispatches via GESTURE_ACTIONS → HAController or Hermes HTTP.
  │
  ├── Heartbeat thread  (in face_server.py)
  │     every 5 min: pauses vision router →
  │     switches HuskyLens to ALGORITHM_FACE_RECOGNITION →
  │     reads the name →
  │     switches to ALGORITHM_EMOTION_RECOGNITION →
  │     reads the mood →
  │     switches back to ALGORITHM_HAND_RECOGNITION →
  │     resumes vision router.
  │     Then asks Hermes "<name> is here, they seem <mood>" and speaks the reply.
  │
  ├── Weather thread
  │     every 15 min, GETs wttr.in for TARS_LOCATION. No-op if the env var is empty.
  │
  └── Voice pipeline  (invoked synchronously from /api/speak)
        sounddevice records from USB mic with silence detection →
        Whisper STT (OpenAI) →
        Hermes Agent (HTTP) →
        OpenAI TTS (Onyx voice) →
        pw-play via PipeWire.
```

`AppState` in `face_server.py` is the threading.Lock-guarded shared state: face state, temporary expression override (time-bounded), recording flags, conversation log. Every thread reads and writes through its accessors.

## Frontend

The face itself is `assets/static/index.html` + `assets/static/js/*`, rendered by Chromium in kiosk mode. It:

- Polls `GET /api/state` for the current face state and log lines.
- Sends `POST /api/speak` when the user taps the screen.
- Does the Three.js holographic render entirely client-side.

The left 60 % of the screen is the face; the right 40 % is a scrolling conversation log with weather and status.

The repo also contains a legacy pygame renderer (`assets/face_renderer.py`, `assets/face_animations.py`). It is not used by the current `face_server.py` — it is retained for reference and in case someone wants to revive the pure-pygame path.

## HuskyLens transport

`assets/huskylens_uart.py` is a standalone I2C binary-protocol driver with no external dependency on `pinpong` or the DFRobot SDK. The name keeps `uart` for historical reasons; the wire is I2C on Pi 5. It speaks the HuskyLens command protocol directly over `smbus2`, with a write-then-poll-read pattern that matches the firmware's I2C state machine.

Three algorithms are exercised at runtime:

- `ALGORITHM_HAND_RECOGNITION` — default mode, used for gesture polling.
- `ALGORITHM_FACE_RECOGNITION` — heartbeat step 1.
- `ALGORITHM_EMOTION_RECOGNITION` — heartbeat step 2.

## Why the heartbeat runs face then emotion sequentially

An earlier design attempted to enable face and emotion recognition concurrently (`multi-algorithm` mode). HuskyLens firmware v1.2.2 is unstable in that mode — it drops frames and occasionally hangs the I2C bus. Commit `4aa189b` (*"sequential face then emotion in heartbeat, drop multi-algo"*) switched to running the algorithms one after the other. Each runs for about 2 s, which is long enough to get a stable classification and short enough to feel like a single "who is here" check.

## Transport history: why I2C won

Three transports were tried before landing on I2C:

1. **UART** — blocked by a Raspberry Pi 5 kernel regression starting in 6.6.51 that broke the `/dev/serial0` driver under load. No official fix at time of writing.
2. **USB + MCP** — a Hermes MCP server talking to HuskyLens over USB. HuskyLens firmware crashes with a green screen after 15–20 minutes of continuous polling, regardless of poll rate. Also, firmware v1.2.2 has broken `set_algorithm` over MCP.
3. **I2C binary protocol (current)** — direct binary writes over I2C, lightweight, stable across multi-day runs. The cost is needing a separate 5 V USB-C brick for the HuskyLens because its I2C lines can't be shared with its power under load.

### Legacy: Hermes SSE transport patch

When the skill briefly used MCP over SSE, a patch to Hermes Agent was required: Hermes v0.7.0 only supported StreamableHTTP for URL-based MCP servers, while HuskyLens's MCP server used Server-Sent Events. A small patch added SSE fallback to Hermes. That patch is no longer relevant for tars-vision v3.0+ and is intentionally not included in this repo — the direct I2C path removes the MCP server entirely.
