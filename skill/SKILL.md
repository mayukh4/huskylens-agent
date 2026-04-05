---
name: tars-vision
description: TARS face display for HuskyLens V2 — matrix-style AI face on DSI touchscreen with gesture control, mood tracking, and tap-to-speak voice interface.
version: 3.0.0
author: MayukhBuilds
license: MIT
metadata:
  hermes:
    tags: [Hardware, Vision, HuskyLens, Raspberry-Pi, Face-Display, Voice, TTS, STT, TARS, I2C, Gestures]
    homepage: https://github.com/MayukhBuilds/huskylens-agent
prerequisites:
  commands: [python3, ffmpeg, pw-play]
  python: [pygame, flask, sounddevice, numpy, pyserial, smbus2]
---

# TARS Vision — HuskyLens Face Display

Gives Hermes Agent a physical body on a Raspberry Pi 5 with a TARS (Interstellar) personality.

## Features

- **Eyes**: HuskyLens V2 AI camera via I2C binary protocol (face recognition, emotion detection, hand gestures)
- **Face**: Matrix/terminal-style animated display with eyes and mouth (800x480 DSI touchscreen)
- **Voice**: OpenAI Whisper STT + TTS (Onyx voice) via PipeWire
- **Gestures**: Open palm = toggle fan, fist = toggle LED, victory = astronomy news (via Home Assistant + Hermes)
- **Heartbeat**: Every 5 min, face + mood check, Hermes reacts in character
- **Brain**: Hermes Agent handles all reasoning, memory, and conversation

## Setup

1. Connect HuskyLens V2 via I2C Gravity cable (Green=SDA->Pin3, Blue=SCL->Pin5, Black=GND, Red=3.3V->Pin1)
2. Power HuskyLens with separate USB-C brick (NOT from Pi)
3. Set HuskyLens Protocol Type to "I2C" or "Auto Detect"
4. Copy `soul/SOUL.md` to `~/.hermes/SOUL.md`
5. Run: `./scripts/start_all.sh`

## Face API

```bash
curl -X POST localhost:5555/state -d '{"state":"happy"}'
curl http://localhost:5555/health
```

States: idle, listening, recording, thinking, speaking, happy, curious, surprised, sleeping
