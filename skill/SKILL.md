---
name: tars-vision
description: TARS face display for HuskyLens V2 — matrix-style AI face on DSI touchscreen with tap-to-speak voice interface. Gives Hermes a physical face, eyes (HuskyLens camera), and voice.
version: 1.0.0
author: MayukhBuilds
license: MIT
metadata:
  hermes:
    tags: [Hardware, Vision, HuskyLens, Raspberry-Pi, Face-Display, Voice, TTS, STT]
    homepage: https://github.com/MayukhBuilds/huskylens-agent
prerequisites:
  commands: [python3, ffmpeg, pw-play]
  python: [pygame, flask, sounddevice, numpy, mcp]
---

# TARS Vision — HuskyLens Face Display

Gives Hermes Agent a physical body on a Raspberry Pi 5:
- **Eyes**: HuskyLens V2 AI camera (10 MCP vision tools)
- **Face**: Matrix-style animated display on DSI touchscreen
- **Voice**: OpenAI Whisper STT + TTS (Onyx voice)
- **Personality**: TARS from Interstellar (humor setting 75%)

## Setup

1. Connect HuskyLens V2 via USB (creates network at 192.168.88.1)
2. Enable MCP Service on HuskyLens
3. Add to `~/.hermes/config.yaml`:
   ```yaml
   mcp_servers:
     huskylens:
       url: "http://192.168.88.1:3000/sse"
       transport: sse
       timeout: 30
   ```
4. Apply the SSE transport patch (see `patches/hermes_sse_transport.md`)
5. Copy `soul/SOUL.md` to `~/.hermes/SOUL.md`
6. Run: `python3 face/face_server.py`

## Face API

Hermes can drive the face state from any session (CLI, Telegram, etc.):

```bash
# From Hermes terminal tool:
curl -X POST localhost:5555/state -H 'Content-Type: application/json' -d '{"state":"happy"}'
```

States: `idle`, `listening`, `recording`, `thinking`, `speaking`, `happy`, `curious`, `surprised`, `sleeping`

## Tap-to-Speak

Touch the DSI screen to record audio. Speech is transcribed, sent to Hermes, and the response is spoken aloud through the USB speaker. The face animates through each phase of the conversation.
