# tars-vision — HuskyLens V2 AI Face Display

A matrix-style AI face for Raspberry Pi 5 that gives [Hermes Agent](https://github.com/NousResearch/hermes-agent) a physical presence — eyes (HuskyLens V2 camera over I2C), a voice (OpenAI Whisper + TTS), and a face (Three.js holographic render on a DSI touchscreen). TARS personality from *Interstellar*. Humour setting at 75%.

 <img width="765" height="574" alt="Screenshot 2026-04-16 at 8 57 12 AM" src="https://github.com/user-attachments/assets/3f0a72e9-c29c-4e9e-9ca5-218bd9099c51" />


Packaged as a [Hermes skill](https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills/) — drop it in `~/.hermes/skills/hardware/tars-vision/` and Hermes discovers it on startup.

Built for [@MayukhBuilds](https://www.youtube.com/@MayukhBuilds).

## What it does

- **Holographic face** on an 800x480 DSI touchscreen — animated eyes and mouth rendered with Three.js in Chromium kiosk mode.
- **Tap-to-speak**: touch screen → record → Whisper STT → Hermes Agent → OpenAI TTS → speaker.
- **Always-on gesture control**: open palm toggles a fan, fist toggles a room LED, victory sign asks Hermes for astronomy news. All via HuskyLens hand recognition and Home Assistant. Home Assistant is optional — if unconfigured, palm and fist silently no-op; victory sign still works.
- **Heartbeat**: every 5 min, TARS briefly runs face recognition then emotion recognition, tells Hermes who is around and how they seem, and speaks a response in character.

## Architecture

```
HuskyLens V2 --(I2C)--> Raspberry Pi 5
                            |
              +-------------+-------------+
              |             |             |
         Hand Gestures  Face/Mood    Voice Pipeline
         (always-on)    (heartbeat)  (tap-to-speak)
              |             |             |
              v             v             v
        Home Assistant  Hermes Agent  Hermes Agent
        (toggle fan,    (greet user,  (full conversation)
         toggle LED)    mood react)       |
                            |             v
                            +--> OpenAI TTS (Onyx) --> Speaker
```

Deep-dive: [references/ARCHITECTURE.md](references/ARCHITECTURE.md).

## Hardware

| Component | Details |
|-----------|---------|
| Computer | Raspberry Pi 5 (4GB+) |
| Camera | HuskyLens V2 (SEN0638) via I2C |
| Display | DSI touchscreen (800x480) |
| Microphone | USB mic (e.g. C-Media PCM2902) |
| Speaker | USB speaker (e.g. Jieli UACDemo) |
| Power for HuskyLens | Separate 5V/2A+ USB-C brick (**do not** power from the Pi) |

Full wiring table, I2C firmware setup, and PipeWire audio setup: [references/SETUP.md](references/SETUP.md).

## Quick start

```bash
git clone https://github.com/MayukhBuilds/huskylens-agent.git
cd huskylens-agent

# Install Python deps, copy SOUL.md to ~/.hermes/, create .env from template
bash scripts/install.sh

# Put your OpenAI key in .env (and HA_URL/HA_TOKEN/TARS_LOCATION if you want them)
$EDITOR .env

# Wire HuskyLens via I2C, power it from the separate USB-C brick, set its
# Protocol Type to "I2C" in device settings.

# Run
bash scripts/start.sh
```

To register as a Hermes skill so it auto-loads:

```bash
mkdir -p ~/.hermes/skills/hardware
ln -s "$(pwd)" ~/.hermes/skills/hardware/tars-vision
```

## Configuration

All configuration is via `.env` (template in `.env.example`):

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes | Whisper STT and TTS |
| `TARS_LOCATION` | no | City for the weather widget (e.g. `"Kingston, Ontario"`). Empty disables it. |
| `HA_URL` | no | Home Assistant base URL (e.g. `http://homeassistant.local:8123`). Empty disables HA gestures. |
| `HA_TOKEN` | no | Home Assistant long-lived access token |

Smart-home entity IDs are hardcoded in [assets/vision_router.py](assets/vision_router.py) (`switch.fan_socket_1`, `switch.room_led_socket_1`). Edit `GESTURE_ACTIONS` at the top of that file to match your HA setup.

## Gestures

| Gesture | Action | Requires |
|---------|--------|----------|
| Open palm | Toggle fan switch | Home Assistant |
| Fist | Toggle room LED switch | Home Assistant |
| Victory sign | Astronomy/astrophysics news briefing | Hermes Agent |

## Face API

Hermes (or anything else) can drive the face by POSTing to `localhost:5555`:

```bash
curl -X POST localhost:5555/state      -d '{"state":"happy"}'
curl -X POST localhost:5555/expression -d '{"expression":"surprised","duration":3}'
curl       localhost:5555/health
```

States: `idle`, `listening`, `recording`, `thinking`, `speaking`, `happy`, `curious`, `surprised`, `sleeping`.

## Key files

| File | Purpose |
|------|---------|
| [SKILL.md](SKILL.md) | Hermes skill manifest |
| [assets/face_server.py](assets/face_server.py) | Main process: Flask API + voice pipeline + heartbeat |
| [assets/vision_router.py](assets/vision_router.py) | Always-on gesture polling loop |
| [assets/huskylens_uart.py](assets/huskylens_uart.py) | Standalone I2C binary-protocol driver |
| [assets/gesture_classifier.py](assets/gesture_classifier.py) | Classify palm/fist/victory from 21 hand keypoints |
| [assets/ha_controller.py](assets/ha_controller.py) | Home Assistant REST wrapper (optional) |
| [assets/static/](assets/static/) | Three.js holographic face frontend |
| [references/SOUL.md](references/SOUL.md) | TARS personality prompt |
| [references/SETUP.md](references/SETUP.md) | Hardware + firmware setup guide |
| [references/ARCHITECTURE.md](references/ARCHITECTURE.md) | Threading model and design rationale |

## License

MIT — see [LICENSE](LICENSE).
