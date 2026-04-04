---
name: tars-vision
description: TARS face display for HuskyLens V2 — matrix-style AI face on DSI touchscreen with tap-to-speak voice interface and proactive vision. Gives Hermes a physical face, eyes (HuskyLens camera), voice (OpenAI Onyx), and a TARS personality.
version: 2.0.0
author: MayukhBuilds
license: MIT
metadata:
  hermes:
    tags: [Hardware, Vision, HuskyLens, Raspberry-Pi, Face-Display, Voice, TTS, STT, TARS]
    homepage: https://github.com/MayukhBuilds/huskylens-agent
prerequisites:
  commands: [python3, ffmpeg, pw-play]
  python: [pygame, flask, sounddevice, numpy, mcp]
---

# TARS Vision — HuskyLens Face Display

Gives Hermes Agent a physical body on a Raspberry Pi 5 with a TARS (Interstellar) personality.

## Features

- **Eyes**: HuskyLens V2 AI camera (10 MCP vision tools via SSE)
- **Face**: Matrix/terminal-style animated display with eyes and mouth (800x480 DSI touchscreen)
- **Voice**: OpenAI Whisper STT + TTS (Onyx voice) via PipeWire
- **Brain**: Hermes Agent handles all reasoning, memory, and tool calling
- **Proactive**: Every ~2 min, TARS looks through the camera and comments on what it sees
- **Tap-to-speak**: Touch the screen to talk, 1.2s silence detection

## Setup

1. Connect HuskyLens V2 via USB (creates network at 192.168.88.1)
2. Enable MCP Service on HuskyLens (requires firmware v1.1.6+)
3. Apply the SSE transport patch to Hermes (see `patches/hermes_sse_transport.md`)
4. Add to `~/.hermes/config.yaml`:
   ```yaml
   mcp_servers:
     huskylens:
       url: "http://192.168.88.1:3000/sse"
       transport: sse
       timeout: 30
   ```
5. Copy `soul/SOUL.md` to `~/.hermes/SOUL.md`
6. Run: `python3 face/face_server.py`

## Face API

Hermes can drive the face state from any platform (CLI, Telegram, etc.):

```bash
curl -X POST localhost:5555/state -H 'Content-Type: application/json' -d '{"state":"happy"}'
```

States: `idle`, `listening`, `recording`, `thinking`, `speaking`, `happy`, `curious`, `surprised`, `sleeping`
