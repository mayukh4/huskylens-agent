# TARS — HuskyLens V2 + Hermes Agent Face Display

A matrix-style AI face display for Raspberry Pi that gives [Hermes Agent](https://github.com/NousResearch/hermes-agent) a physical presence — eyes (HuskyLens V2 camera), a voice (OpenAI TTS/STT), and a face (LCD touchscreen). TARS personality from Interstellar. Humor setting at 75%.

Built for the [@MayukhBuilds](https://www.youtube.com/@MayukhBuilds) YouTube channel.

## What It Does

- **Matrix-style AI face** on a DSI touchscreen — ASCII humanoid silhouette with animated eyes/mouth, scanlines, glitch effects, matrix rain
- **Split screen**: 60% face (left), 40% conversation log (right)
- **Tap-to-speak**: Touch anywhere on the touchscreen to talk to the agent
- **Voice pipeline**: Record → OpenAI Whisper STT → Hermes Agent (with HuskyLens MCP vision tools) → OpenAI TTS (Onyx voice) → Speaker
- **Proactive vision**: Every ~2 minutes, TARS looks through the camera and comments on what it sees in its signature dry, witty style
- **HuskyLens V2 MCP**: 10 vision tools — face recognition, object detection, hand/pose tracking, OCR, QR codes, and more
- **TARS personality**: Dry wit, deadpan humor, self-aware about being a camera on a Pi
- **Hermes-driven**: The actual [Hermes Agent](https://github.com/NousResearch/hermes-agent) is the brain — this display is a voice/visual frontend. Hermes can also drive the face state remotely via Telegram, CLI, or HTTP API.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    DSI Touchscreen (800x480)             │
│  ┌──────────────────────┐ ┌───────────────────────────┐ │
│  │   Matrix Face         │ │  TARS // COMMS LOG        │ │
│  │   ASCII silhouette    │ │  > what do you see?       │ │
│  │   with eyes & mouth   │ │  Sending to Hermes...     │ │
│  │                       │ │  [tool] get_recognition   │ │
│  │   [ PROCESSING ]      │ │    Face ID 1 detected.    │ │
│  │                       │ │    That's you, Mayukh.    │ │
│  └──────────────────────┘ │                           │ │
│              [X]          │  TAP SCREEN TO SPEAK       │ │
│                           └───────────────────────────┘ │
└─────────────────────────────────────────────────────────┘

Tap screen ──► Record (USB Mic, 44100Hz)
                 │
                 ▼
           OpenAI Whisper STT
                 │
                 ▼
          ┌─────────────┐     ┌──────────────────┐
          │ Hermes Agent │◄───►│ HuskyLens V2 MCP │
          │ (the brain)  │     │ 10 vision tools  │
          │ TARS persona │     │ via SSE transport│
          └──────┬──────┘     └──────────────────┘
                 │
                 ▼
           OpenAI TTS (Onyx voice)
                 │
                 ▼
           PipeWire ──► USB Speaker

  ┌──────────────────────────────────────┐
  │  Proactive Vision Loop (every 2 min) │
  │  TARS looks through camera and       │
  │  comments on what it sees            │
  └──────────────────────────────────────┘
```

## Hardware

| Component | Details |
|-----------|---------|
| Computer | Raspberry Pi 5 |
| Camera | [HuskyLens V2](https://www.dfrobot.com/product-2995.html) (SEN0638) via USB |
| Display | DSI touchscreen (800×480) |
| Microphone | USB mic (PCM2902 Audio Codec) |
| Speaker | USB speaker (via HuskyLens USB audio / Jieli UACDemo) |

## Prerequisites

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) v0.7+ installed and configured
- HuskyLens V2 with MCP Service enabled (firmware v1.1.6+), WiFi module connected, plugged in via USB
- OpenAI API key (for Whisper STT and TTS)
- OpenRouter API key (for Hermes LLM backend)
- PipeWire audio server (default on Raspberry Pi OS)
- `ffmpeg` installed

## Quick Start

### 1. Install Python dependencies

```bash
pip install --break-system-packages pygame flask sounddevice numpy requests mcp
```

### 2. Patch Hermes for SSE transport

The HuskyLens V2 MCP server uses SSE transport, but Hermes only supports StreamableHTTP. Apply the patch documented in `patches/hermes_sse_transport.md`.

### 3. Configure HuskyLens MCP in Hermes

The HuskyLens creates a USB network when connected (Pi: `192.168.88.2`, HuskyLens: `192.168.88.1`).

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  huskylens:
    url: "http://192.168.88.1:3000/sse"
    transport: sse
    timeout: 30
    connect_timeout: 15
```

Verify with: `hermes mcp test huskylens` — should show 10 tools.

### 4. Install TARS personality

```bash
cp soul/SOUL.md ~/.hermes/SOUL.md
```

### 5. Set API keys

The face server reads `OPENROUTER_API_KEY` from `~/.hermes/.env`. Set your OpenAI API key in the `face/face_server.py` `_OPENAI_API_KEY` constant (or via environment).

### 6. Run

```bash
# Desktop: tap the TARS icon on the Pi desktop
# Or terminal:
./scripts/start_all.sh
```

### 7. Desktop shortcut (optional)

```bash
cp tars.desktop ~/Desktop/TARS.desktop
chmod +x ~/Desktop/TARS.desktop
```

## Usage

- **Tap anywhere** on the touchscreen to start speaking. TARS listens until you stop talking (1.2s silence threshold), transcribes, sends to Hermes, and responds through the speaker.
- **Proactive vision**: Every ~2 minutes, TARS looks through the camera and makes a witty observation about what it sees — even if it's just you sitting there.
- **Exit**: Tap the [X] button in the top-right corner, or press Escape/Q.
- **Remote control**: Hermes can drive the face from Telegram or CLI:
  ```bash
  curl -X POST localhost:5555/state -H 'Content-Type: application/json' \
    -d '{"state":"happy"}'
  ```

## Face States

| State | Visual Effect | Trigger |
|-------|--------------|---------|
| `idle` | Calm glow, slow rain, gentle blink | Default standby |
| `listening` | Brighter eyes, wider | User tapped screen |
| `recording` | Bright glow, red "RECORDING" label | Recording audio |
| `thinking` | Fast rain, glitches, pupils drift | Processing query |
| `speaking` | Pulsing mouth, moderate glow | TTS playing |
| `curious` | Asymmetric eyes, wave distortion | Using vision tools |
| `happy` | Squinted eyes, bright | Recognized someone |
| `surprised` | Wide eyes, heavy glitch | Unexpected input |
| `sleeping` | Dim, minimal rain | Low power mode |

## Hermes Skill

Install as a Hermes Agent skill:

```bash
mkdir -p ~/.hermes/skills/hardware/tars-vision
cp skill/SKILL.md ~/.hermes/skills/hardware/tars-vision/
```

## File Structure

```
huskylens-agent/
├── face/
│   ├── face_server.py          # Main app: pygame + Flask + voice + proactive vision
│   ├── face_renderer.py        # Matrix face renderer with eyes/mouth
│   └── face_animations.py      # State machine and animation parameters
├── soul/
│   └── SOUL.md                 # TARS personality for Hermes Agent
├── skill/
│   └── SKILL.md                # Hermes Agent skill definition
├── patches/
│   └── hermes_sse_transport.md # SSE transport patch for Hermes MCP client
├── scripts/
│   ├── start_all.sh            # Launch TARS face display
│   ├── stop_all.sh             # Stop all processes
│   ├── test_mcp.py             # Test HuskyLens MCP connectivity
│   └── test_face.py            # Cycle through face animation states
├── tars.desktop                # Desktop shortcut for Raspberry Pi
├── requirements.txt
└── README.md
```

## How It Works

1. **Face Display** (`face_server.py`) runs as the main process on the Pi, rendering the matrix face on the DSI touchscreen and exposing a Flask API on port 5555.

2. **Voice input** is triggered by touching the screen. Audio is recorded from the USB mic at its native 44100Hz, resampled to 16kHz, and sent to OpenAI Whisper for transcription.

3. **Hermes Agent** receives the transcribed text via `hermes chat -q "text" -Q` (single-query quiet mode). Hermes uses its TARS personality (from SOUL.md), calls HuskyLens MCP tools to see through the camera, and returns a response.

4. **TTS** converts the response to speech via OpenAI's Onyx voice, boosted +4dB via ffmpeg, and played through PipeWire to the USB speaker.

5. **Proactive vision** runs in a background thread. Every ~2 minutes, it asks Hermes to look through the camera and comment on what it sees — keeping TARS feeling alive and observant even when you're not talking to it.

6. **Remote control**: Since Hermes runs independently (gateway, Telegram, CLI), it can also drive the face state via the Flask API — e.g., setting the face to "happy" when it recognizes you via Telegram.

## License

MIT

## Credits

Built by [Mayukh Bagchi](https://www.youtube.com/@MayukhBuilds) with [Claude Code](https://claude.ai/code).

[HuskyLens V2](https://www.dfrobot.com/product-2995.html) by DFRobot. [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research.
