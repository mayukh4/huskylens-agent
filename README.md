# TARS — HuskyLens V2 + Hermes Agent Face Display

A matrix-style AI face display for Raspberry Pi that gives [Hermes Agent](https://github.com/NousResearch/hermes-agent) a physical presence — eyes (HuskyLens V2 camera), a voice (OpenAI TTS), ears (OpenAI Whisper STT), and a face (LCD touchscreen).

Built for the [@MayukhBuilds](https://www.youtube.com/@MayukhBuilds) YouTube channel.

![TARS Face](https://img.shields.io/badge/TARS-Online-00ff46?style=flat-square)

## What It Does

- **Matrix-style AI face** on a DSI touchscreen — ASCII humanoid silhouette with eyes, mouth, scanlines, glitch effects, and matrix rain
- **Split screen**: 60% face (left), 40% conversation log (right)
- **Tap-to-speak**: Touch anywhere on the screen to talk to the agent
- **Voice pipeline**: Record → OpenAI Whisper STT → Hermes Agent (with HuskyLens vision) → OpenAI TTS (Onyx voice) → Speaker
- **HuskyLens V2 MCP integration**: Hermes sees through the camera — face recognition, object detection, hand/pose tracking, OCR, and more
- **TARS personality**: Dry wit, deadpan humor at 75%, inspired by TARS from Interstellar
- **Hermes-driven**: The actual Hermes Agent is the brain — this display is a voice/visual frontend

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    DSI Touchscreen                       │
│  ┌────────────────────┐  ┌───────────────────────────┐  │
│  │   Matrix Face       │  │   TARS // COMMS LOG       │  │
│  │   (ASCII silhouette │  │   > user messages         │  │
│  │    with eyes/mouth) │  │     agent responses       │  │
│  │                     │  │   [tool] vision calls     │  │
│  │   [ PROCESSING ]    │  │                           │  │
│  │                     │  │   TAP SCREEN TO SPEAK     │  │
│  └────────────────────┘  └───────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
         │                         │
    Tap to speak              Flask API :5555
         │                    (Hermes can drive
         ▼                     face state too)
   ┌───────────┐
   │ Record    │──► OpenAI Whisper STT
   │ (USB Mic) │
   └───────────┘
         │
         ▼
   ┌───────────┐    ┌──────────────────┐
   │  Hermes   │◄──►│  HuskyLens V2    │
   │  Agent    │    │  MCP Server      │
   │  (brain)  │    │  (10 vision      │
   │           │    │   tools via SSE) │
   └───────────┘    └──────────────────┘
         │
         ▼
   ┌───────────┐
   │ OpenAI    │──► PipeWire ──► USB Speaker
   │ TTS Onyx  │
   └───────────┘
```

## Hardware

- Raspberry Pi 5
- [HuskyLens V2](https://www.dfrobot.com/product-2995.html) (SEN0638) — connected via USB
- DSI touchscreen (800x480)
- USB microphone
- USB speaker

## Prerequisites

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed and configured
- HuskyLens V2 with MCP Service enabled and connected via USB
- OpenAI API key (for Whisper STT and TTS)
- OpenRouter API key (for Hermes LLM)
- Python 3.11+ with: `pygame`, `flask`, `sounddevice`, `numpy`, `requests`, `mcp`
- PipeWire audio server (default on Raspberry Pi OS)
- `ffmpeg` installed

## Setup

### 1. Install dependencies

```bash
pip install --break-system-packages pygame flask sounddevice numpy requests mcp
```

### 2. Configure HuskyLens MCP in Hermes

The HuskyLens V2 creates a USB network (Pi: 192.168.88.2, HuskyLens: 192.168.88.1). Its MCP server runs at `http://192.168.88.1:3000/sse`.

Hermes Agent uses StreamableHTTP transport by default, but HuskyLens uses SSE. A patch to `~/.hermes/hermes-agent/tools/mcp_tool.py` adds SSE fallback support. See `patches/hermes_sse_transport.md` for details.

Add to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  huskylens:
    url: "http://192.168.88.1:3000/sse"
    transport: sse
    timeout: 30
    connect_timeout: 15
```

Verify: `hermes mcp test huskylens`

### 3. Install the SOUL.md personality

```bash
cp soul/SOUL.md ~/.hermes/SOUL.md
```

### 4. Set up API keys

The app reads keys from:
- `~/.hermes/.env` → `OPENROUTER_API_KEY`
- OpenAI key from your environment (or configure in `.env`)

### 5. Run

```bash
# From the Pi desktop — tap the TARS icon
# Or from terminal:
./scripts/start_all.sh
```

### 6. Desktop shortcut

```bash
cp tars.desktop ~/Desktop/TARS.desktop
chmod +x ~/Desktop/TARS.desktop
```

## Hermes Skill Installation

To install as a Hermes Agent skill:

```bash
cp -r skill ~/.hermes/skills/hardware/tars-vision
hermes skills list  # should show tars-vision
```

## Face States

The face display responds to state changes via HTTP:

```bash
curl -X POST localhost:5555/state -H 'Content-Type: application/json' \
  -d '{"state":"thinking"}'
```

| State | Visual | When |
|-------|--------|------|
| `idle` | Calm glow, slow rain, gentle blink | Standby |
| `listening` | Brighter, wider eyes | User speaking |
| `recording` | Bright glow, red status | Recording audio |
| `thinking` | Fast rain, glitches, pupils move | Processing |
| `speaking` | Pulsing mouth, moderate glow | TTS playing |
| `curious` | Asymmetric eyes, wave distortion | Using vision tools |
| `happy` | Squinted eyes, bright glow | Recognized someone |
| `surprised` | Wide eyes, heavy glitch | Unexpected input |
| `sleeping` | Dim, minimal rain | Low power |

## File Structure

```
huskylens-agent/
├── face/
│   ├── face_server.py        # Main app: pygame + Flask + voice pipeline
│   ├── face_renderer.py      # Matrix face renderer with eyes/mouth
│   └── face_animations.py    # State machine and animation params
├── soul/
│   └── SOUL.md               # TARS personality for Hermes
├── skill/
│   └── SKILL.md              # Hermes Agent skill definition
├── patches/
│   └── hermes_sse_transport.md  # SSE transport patch for Hermes MCP
├── scripts/
│   ├── start_all.sh          # Launch the face display
│   ├── stop_all.sh           # Stop all processes
│   ├── test_mcp.py           # Test HuskyLens MCP connection
│   └── test_face.py          # Cycle through face states
├── tars.desktop              # Desktop shortcut for Pi
├── requirements.txt
└── README.md
```

## License

MIT

## Credits

Built by [Mayukh Bagchi](https://www.youtube.com/@MayukhBuilds) with Claude Code.

HuskyLens V2 by [DFRobot](https://www.dfrobot.com/). Hermes Agent by [Nous Research](https://github.com/NousResearch/hermes-agent).
