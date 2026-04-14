---
name: tars-vision
description: Matrix-style AI face display for Raspberry Pi 5 that gives Hermes Agent a physical body. HuskyLens V2 camera over I2C for face, emotion, and gesture recognition. Animated Three.js holographic face on a DSI touchscreen. OpenAI Whisper plus TTS voice pipeline. Optional Home Assistant smart-home gestures. TARS (Interstellar) personality with 75% humor.
license: MIT
compatibility: Raspberry Pi 5 with Raspberry Pi OS (Bookworm). HuskyLens V2 (firmware v1.2.2+) set to I2C mode. 800x480 DSI touchscreen. USB microphone and speaker. PipeWire audio server. Requires OPENAI_API_KEY. Home Assistant is optional — palm/fist gestures silently no-op when unconfigured.
metadata:
  author: MayukhBuilds
  version: "3.0.0"
  homepage: https://github.com/MayukhBuilds/huskylens-agent
  category: hardware
  tags: [hardware, vision, huskylens, raspberry-pi, face-display, voice, home-automation, tars]
---

# tars-vision

Physical embodiment for Hermes Agent. The Pi drives three independent loops that share a single HuskyLens camera over I2C:

- **Always-on gesture control** — open palm, fist, and victory sign trigger Home Assistant switches and Hermes web-search queries.
- **Heartbeat (every 5 min)** — sequentially runs face recognition then emotion recognition, feeds `"<name> is here, they seem <mood>"` to Hermes, and speaks the reply.
- **Tap-to-speak voice** — touch the screen to record, transcribe with Whisper, route through Hermes, speak the reply with OpenAI TTS (Onyx voice).

The face is rendered in the browser (Chromium kiosk) from `assets/static/` and driven by a Flask API on `localhost:5555`. Hermes can push face state with `POST /state` from any skill.

## Install

```bash
git clone https://github.com/MayukhBuilds/huskylens-agent.git
cd huskylens-agent
bash scripts/install.sh
# edit .env with your OPENAI_API_KEY
bash scripts/start.sh
```

Full hardware wiring, HuskyLens I2C setup, and optional Home Assistant config: see [references/SETUP.md](references/SETUP.md).

Architecture deep-dive (threading model, heartbeat rationale, why I2C won over UART/USB-MCP): see [references/ARCHITECTURE.md](references/ARCHITECTURE.md).

TARS personality prompt (copied to `~/.hermes/SOUL.md` by `install.sh`): [references/SOUL.md](references/SOUL.md).

## Face API

```bash
curl -X POST localhost:5555/state      -d '{"state":"happy"}'
curl -X POST localhost:5555/expression -d '{"expression":"surprised","duration":3}'
curl       localhost:5555/health
```

States: `idle`, `listening`, `recording`, `thinking`, `speaking`, `happy`, `curious`, `surprised`, `sleeping`.
