# TARS — HuskyLens V2 AI Face Display

A matrix-style AI face display for Raspberry Pi 5 that gives [Hermes Agent](https://github.com/NousResearch/hermes-agent) a physical presence — eyes (HuskyLens V2 camera), a voice (OpenAI TTS/STT), and a face (DSI touchscreen). TARS personality from Interstellar. Humor setting at 75%.

Built for [@MayukhBuilds](https://www.youtube.com/@MayukhBuilds).

## What It Does

- **Matrix face** on 800x480 DSI touchscreen — ASCII silhouette with animated eyes/mouth, scanlines, glitch effects, matrix rain
- **Tap-to-speak**: Touch screen -> Record -> Whisper STT -> Hermes Agent -> OpenAI TTS -> Speaker
- **Gesture control**: Open palm toggles fan, fist toggles room LED, victory sign gets astronomy news — all via HuskyLens hand recognition + Home Assistant
- **Heartbeat**: Every 5 min, TARS checks who is around (face recognition) and their mood (emotion recognition), then comments in character
- **TARS personality**: Dry wit, deadpan humor, slightly existential. Powered by Hermes Agent with custom SOUL.md

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

## Hardware

| Component | Details |
|-----------|---------|
| Computer | Raspberry Pi 5 (4GB+) |
| Camera | HuskyLens V2 (SEN0638) via I2C |
| Display | DSI touchscreen (800x480) |
| Microphone | USB mic (C-Media PCM2902) |
| Speaker | USB speaker (Jieli UACDemo) |
| Power | Separate 5V/2A+ USB-C brick for HuskyLens |

## Wiring (I2C via Gravity 4-pin cable)

| Gravity Wire | Signal | Pi Pin |
|-------------|--------|--------|
| Green | SDA | Pin 3 (GPIO 2) |
| Blue | SCL | Pin 5 (GPIO 3) |
| Black | GND | Any GND pin |
| Red | VCC | Pin 1 (3.3V) |

HuskyLens Protocol Type must be set to **I2C** or **Auto Detect** in device settings.

> **Note**: UART does not work on Pi 5 due to a known kernel regression (6.6.51+). USB MCP was abandoned due to firmware crashes after 15-20 min of continuous polling. I2C is the stable solution.

## Gesture Map

| Gesture | Action |
|---------|--------|
| Open palm (5 fingers) | Toggle fan (Home Assistant) |
| Fist | Toggle room LED (Home Assistant) |
| Victory sign (2 fingers) | Astronomy/astrophysics briefing from Hermes |

## Prerequisites

- Hermes Agent installed and configured
- HuskyLens V2 (firmware v1.2.2+) set to I2C mode
- OpenAI API key (for Whisper STT and TTS)
- Home Assistant instance (for gesture smart home control)
- PipeWire audio server (default on Raspberry Pi OS)

## Quick Start

```bash
# 1. Install dependencies
pip install pygame flask sounddevice numpy requests pyserial smbus2

# 2. Copy SOUL personality to Hermes
cp soul/SOUL.md ~/.hermes/SOUL.md

# 3. Wire HuskyLens via I2C (see wiring table above)
# 4. Power HuskyLens with separate USB-C brick
# 5. Set HuskyLens to I2C mode in device settings

# 6. Run
./scripts/start_all.sh
```

## Key Files

| File | Purpose |
|------|---------|
| face/face_server.py | Main app: pygame + Flask API + voice pipeline + heartbeat |
| face/face_renderer.py | Matrix face with ASCII silhouette, eyes, mouth |
| face/face_animations.py | State machine (idle, thinking, speaking, happy, etc.) |
| face/huskylens_uart.py | I2C/UART binary protocol driver (standalone, no pinpong) |
| face/vision_router.py | Gesture detection loop with adaptive polling |
| face/gesture_classifier.py | Classify palm/fist/victory from 21 hand keypoints |
| face/ha_controller.py | Home Assistant REST API wrapper |
| soul/SOUL.md | TARS personality definition |

## Face API

Control TARS face state from anywhere:

```bash
# Set face state
curl -X POST localhost:5555/state -d '{"state":"happy"}'

# Temporary expression (3 seconds)
curl -X POST localhost:5555/expression -d '{"expression":"surprised","duration":3}'

# Health check
curl http://localhost:5555/health
```

States: idle, listening, recording, thinking, speaking, happy, curious, surprised, sleeping

## How the Heartbeat Works

Every 5 minutes, TARS:
1. Pauses gesture detection
2. Enters multi-algorithm mode (Face Recognition + Emotion Recognition)
3. Identifies who is there and their mood
4. Switches back to Hand Recognition
5. Passes context to Hermes: "Mayukh is here. They seem happy."
6. Hermes responds in character, TARS speaks it aloud

## License

MIT
