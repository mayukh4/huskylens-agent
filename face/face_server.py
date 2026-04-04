#!/usr/bin/env python3
"""
TARS Face Display — Matrix AI face with conversation panel.

Left 60%: Matrix-style face with eyes/mouth
Right 40%: Conversation log + status
Touch anywhere: tap-to-speak (record -> STT -> LLM+MCP -> TTS -> speaker)
Top-right X button: exit

Hermes can drive face state via:
  curl -X POST localhost:5555/state -d '{"state":"thinking"}'
"""

import os
import sys
import time
import json
import re
import wave
import tempfile
import subprocess
import threading
import textwrap
import collections

os.environ.setdefault('DISPLAY', ':0')
os.environ.setdefault('SDL_VIDEODRIVER', 'x11')

import pygame
from flask import Flask, request, jsonify
import requests as http_requests
import numpy as np
import sounddevice as sd

sys.path.insert(0, os.path.dirname(__file__))
from face_animations import FaceAnimator, FaceState
from face_renderer import FaceRenderer, SCREEN_W, SCREEN_H, FACE_W, PANEL_W, PANEL_X
from face_renderer import BLACK, GREEN_BRIGHT, GREEN_MID, GREEN_DIM, GREEN_FAINT, BORDER_COLOR, PANEL_BG, RED_DIM

# --- Config ---
HUSKYLENS_MCP_URL = "http://192.168.88.1:3000/sse"
LLM_MODEL = "qwen/qwen3.6-plus:free"
OPENROUTER_API_KEY = ""
OPENAI_API_KEY = ""
TTS_VOICE = "onyx"
SOUL_PATH = os.path.expanduser("~/.hermes/SOUL.md")

# Audio — mic is card 2 (USB PnP Sound Device), native rate 44100Hz
# Speaker is card 3 (UACDemoV1.0 / HuskyLens), use aplay
MIC_DEVICE = None  # Will auto-detect
MIC_SAMPLE_RATE = 44100  # Native rate for USB mic
WHISPER_SAMPLE_RATE = 16000  # What Whisper expects
SPEAKER_CARD = "plughw:3,0"
SILENCE_THRESHOLD = 500  # int16 RMS threshold
SILENCE_DURATION = 1.2  # seconds of silence to stop
VOLUME_BOOST_DB = 4  # dB boost for speaker output

# Exit button
EXIT_BUTTON_SIZE = 32
EXIT_BUTTON_MARGIN = 6


def _read_env_file(path):
    """Read key=value pairs from an env file."""
    result = {}
    if not os.path.exists(path):
        return result
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            result[key.strip()] = val.strip().strip('"').strip("'")
    return result


def load_env():
    global OPENROUTER_API_KEY, OPENAI_API_KEY
    # Load from Hermes .env
    hermes = _read_env_file(os.path.expanduser("~/.hermes/.env"))
    OPENROUTER_API_KEY = hermes.get("OPENROUTER_API_KEY", "")
    OPENAI_API_KEY = "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"


def load_system_prompt():
    try:
        with open(SOUL_PATH) as f:
            return f.read()
    except FileNotFoundError:
        return "You are TARS, a dry-witted AI assistant."


def detect_mic():
    """Find the USB microphone sounddevice index and its native sample rate."""
    global MIC_DEVICE, MIC_SAMPLE_RATE
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d['max_input_channels'] > 0:
            name = d['name'].lower()
            if 'usb' in name and 'pnp' in name:
                MIC_DEVICE = i
                MIC_SAMPLE_RATE = int(d['default_samplerate'])
                return
            if 'usb' in name:
                MIC_DEVICE = i
                MIC_SAMPLE_RATE = int(d['default_samplerate'])
    # Fallback: first input device
    if MIC_DEVICE is None:
        for i, d in enumerate(devices):
            if d['max_input_channels'] > 0:
                MIC_DEVICE = i
                MIC_SAMPLE_RATE = int(d['default_samplerate'])
                return


def detect_speaker():
    """Find the correct speaker ALSA device."""
    global SPEAKER_CARD
    # Check which cards have playback
    try:
        result = subprocess.run(['aplay', '-l'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.split('\n'):
            if 'UACDemo' in line or 'USB Audio' in line:
                # Extract card number
                if 'card' in line:
                    card = line.split('card')[1].strip().split(':')[0].strip()
                    SPEAKER_CARD = f"plughw:{card},0"
                    return
    except Exception:
        pass


# --- State ---
class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self.face_state = "booting"
        self.expression_override = None
        self.expression_until = 0.0
        self.log_lines = collections.deque(maxlen=200)
        self.is_recording = False
        self.is_processing = False
        self.conversation = []
        self.should_quit = False

    def set_face(self, state):
        with self._lock:
            self.face_state = state

    def set_expression(self, expr, dur=2.0):
        with self._lock:
            self.expression_override = expr
            self.expression_until = time.time() + dur

    def get_face(self):
        with self._lock:
            now = time.time()
            if self.expression_override and now < self.expression_until:
                return self.expression_override
            if self.expression_override:
                self.expression_override = None
            return self.face_state

    def log(self, text, color="green"):
        with self._lock:
            self.log_lines.append((text, color))

    def get_log(self):
        with self._lock:
            return list(self.log_lines)


app_state = AppState()

# --- Flask API ---
flask_app = Flask(__name__)
flask_app.logger.disabled = True
import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

@flask_app.route('/state', methods=['POST'])
def api_set_state():
    data = request.get_json(force=True)
    state = data.get('state', 'idle')
    app_state.set_face(state)
    app_state.log(f"[hermes] state -> {state}", "dim")
    return jsonify({"ok": True, "state": state})

@flask_app.route('/expression', methods=['POST'])
def api_set_expression():
    data = request.get_json(force=True)
    app_state.set_expression(data.get('expression', 'idle'), data.get('duration', 2.0))
    return jsonify({"ok": True})

@flask_app.route('/health', methods=['GET'])
def api_health():
    return jsonify({"status": "running", "face": app_state.get_face()})

@flask_app.route('/log', methods=['POST'])
def api_log():
    data = request.get_json(force=True)
    app_state.log(data.get('text', ''), data.get('color', 'green'))
    return jsonify({"ok": True})

def run_flask():
    flask_app.run(host='0.0.0.0', port=5555, threaded=True)


# --- MCP Client ---
class HuskyLensMCP:
    def __init__(self):
        self._session = None
        self._tools = []
        self._loop = None
        self._thread = None
        self._ready = threading.Event()

    def start(self):
        import asyncio
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if self._ready.wait(timeout=15):
            app_state.log(f"MCP: {len(self._tools)} vision tools online", "green")
        else:
            app_state.log("MCP: connection timeout", "red")

    def _run(self):
        import asyncio
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect())
        except Exception as e:
            app_state.log(f"MCP error: {e}", "red")

    async def _connect(self):
        from mcp.client.sse import sse_client
        from mcp import ClientSession
        async with sse_client(HUSKYLENS_MCP_URL) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                self._tools = (await session.list_tools()).tools
                self._session = session
                self._ready.set()
                import asyncio
                while True:
                    await asyncio.sleep(1)

    def get_tools_for_llm(self):
        return [{
            "type": "function",
            "function": {
                "name": f"mcp_huskylens_{t.name}",
                "description": (t.description or "")[:400],
                "parameters": t.inputSchema if hasattr(t, 'inputSchema') else {"type": "object", "properties": {}},
            },
        } for t in self._tools]

    def call_tool(self, name, args):
        import asyncio
        real = name.replace("mcp_huskylens_", "")
        fut = asyncio.run_coroutine_threadsafe(self._session.call_tool(real, args), self._loop)
        result = fut.result(timeout=30)
        return "\n".join(it.text if hasattr(it, "text") else str(it) for it in result.content)

    @property
    def connected(self):
        return self._ready.is_set()


mcp_client = HuskyLensMCP()


# --- Voice Pipeline ---

def record_audio_blocking():
    """Record from USB mic until silence after speech."""
    if MIC_DEVICE is None:
        app_state.log("No microphone found", "red")
        return None

    block_dur = 0.1
    block_size = int(MIC_SAMPLE_RATE * block_dur)
    silence_blocks = int(SILENCE_DURATION / block_dur)

    frames = []
    silent = 0
    has_speech = False

    try:
        with sd.InputStream(samplerate=MIC_SAMPLE_RATE, channels=1, dtype='int16',
                            device=MIC_DEVICE, blocksize=block_size) as stream:
            while True:
                data, overflowed = stream.read(block_size)
                frames.append(data.copy())
                rms = int(np.sqrt(np.mean(data.astype(np.float32) ** 2)))
                if rms > SILENCE_THRESHOLD:
                    has_speech = True
                    silent = 0
                else:
                    silent += 1
                if has_speech and silent >= silence_blocks:
                    break
                if len(frames) * block_dur > 20:  # max 20s
                    break
    except Exception as e:
        app_state.log(f"Mic error: {e}", "red")
        return None

    if not has_speech:
        return None

    audio = np.concatenate(frames, axis=0)

    # Resample from MIC_SAMPLE_RATE to 16000 for Whisper if needed
    if MIC_SAMPLE_RATE != WHISPER_SAMPLE_RATE:
        ratio = WHISPER_SAMPLE_RATE / MIC_SAMPLE_RATE
        new_len = int(len(audio) * ratio)
        indices = np.linspace(0, len(audio) - 1, new_len).astype(int)
        audio = audio[indices]

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    with wave.open(tmp.name, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(WHISPER_SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return tmp.name


def transcribe_openai(wav_path):
    """Transcribe via OpenAI Whisper API."""
    if not OPENAI_API_KEY:
        app_state.log("No OpenAI key for STT", "red")
        return None
    try:
        with open(wav_path, 'rb') as f:
            resp = http_requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                files={"file": ("audio.wav", f, "audio/wav")},
                data={"model": "whisper-1", "language": "en"},
                timeout=15,
            )
        resp.raise_for_status()
        text = resp.json().get("text", "").strip()
        os.unlink(wav_path)
        return text if len(text) > 1 else None
    except Exception as e:
        app_state.log(f"STT error: {e}", "red")
        if os.path.exists(wav_path):
            os.unlink(wav_path)
        return None


# Session name for persistent Hermes conversations
HERMES_SESSION = "tars-lcd"
HERMES_BIN = os.path.expanduser("~/.local/bin/hermes")


def ask_hermes(text):
    """Send a message to Hermes Agent and get the response.
    Uses hermes chat -q for single-query mode with session continuity."""
    try:
        cmd = [
            HERMES_BIN, "chat",
            "-q", text,
            "-Q",  # Quiet mode — just the response
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")},
        )
        output = result.stdout.strip()
        # Parse out the response — it's between the Hermes box markers
        lines = output.split("\n")
        response_lines = []
        in_response = False
        for line in lines:
            # Skip box drawing and tool progress lines
            if line.startswith("\u256d") or line.startswith("\u2570") or "\u250a" in line:
                continue
            if "\u2695 Hermes" in line or "Hermes \u2500" in line:
                in_response = True
                continue
            if line.startswith("session_id:"):
                continue
            if in_response:
                response_lines.append(line.strip())
        
        response = " ".join(response_lines).strip()
        if not response:
            # Fallback: just grab non-empty lines that aren't tool progress
            for line in lines:
                clean = line.strip()
                if clean and not clean.startswith(("\u250a", "\u256d", "\u2570", "session_id")):
                    if "Hermes" not in clean and "\u2500" not in clean:
                        response_lines.append(clean)
            response = " ".join(response_lines).strip()
        
        return response if response else "Signal lost. No response from Hermes."
    except subprocess.TimeoutExpired:
        return "Hermes took too long to respond. The signal-to-noise ratio was unfavorable."
    except Exception as e:
        app_state.log(f"Hermes error: {e}", "red")
        return f"Error reaching Hermes: {e}"


def speak_openai(text):
    """TTS via OpenAI Onyx voice, with volume boost."""
    clean = re.sub(r'\[(?:happy|curious|surprised|neutral|thinking)\]\s*', '', text).strip()
    if not clean or not OPENAI_API_KEY:
        return
    try:
        resp = http_requests.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "tts-1", "input": clean, "voice": TTS_VOICE, "response_format": "mp3"},
            timeout=30,
        )
        resp.raise_for_status()
        tmp_in = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_in.write(resp.content)
        tmp_in.close()

        # Convert to wav with volume boost, then play via PipeWire
        tmp_out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_out.close()
        subprocess.run([
            "ffmpeg", "-y", "-i", tmp_in.name,
            "-filter:a", f"volume={VOLUME_BOOST_DB}dB",
            "-ar", "48000", "-ac", "2",
            tmp_out.name
        ], capture_output=True, timeout=10)
        os.unlink(tmp_in.name)

        # Play via PipeWire (which routes to USB speaker)
        subprocess.run(["pw-play", tmp_out.name],
                       capture_output=True, timeout=60)
        os.unlink(tmp_out.name)
    except Exception as e:
        app_state.log(f"TTS error: {e}", "red")


def handle_voice_input():
    """Full voice pipeline: record -> STT -> LLM -> TTS."""
    app_state.is_processing = True
    app_state.is_recording = True
    app_state.set_face("recording")
    app_state.log("Recording...", "bright")

    wav = record_audio_blocking()
    app_state.is_recording = False

    if not wav:
        app_state.log("No speech detected.", "dim")
        app_state.set_face("idle")
        app_state.is_processing = False
        return

    app_state.set_face("thinking")
    app_state.log("Transcribing...", "dim")
    text = transcribe_openai(wav)
    if not text:
        app_state.log("Couldn't transcribe.", "dim")
        app_state.set_face("idle")
        app_state.is_processing = False
        return

    app_state.log(f"> {text}", "bright")
    app_state.set_face("thinking")
    app_state.log("Sending to Hermes...", "dim")

    response = ask_hermes(text)

    # Parse emotion tag
    m = re.match(r'\[(happy|curious|surprised|neutral|thinking)\]', response)
    if m and m.group(1) != "neutral":
        app_state.set_expression(m.group(1), 3.0)

    clean = re.sub(r'\[(?:happy|curious|surprised|neutral|thinking)\]\s*', '', response)
    for line in textwrap.wrap(clean, width=36):
        app_state.log(f"  {line}", "green")

    app_state.set_face("speaking")
    speak_openai(response)
    app_state.set_face("idle")

    app_state.is_processing = False


# --- Panel Renderer ---

class PanelRenderer:
    def __init__(self):
        self.font = pygame.font.SysFont("monospace", 12)
        self.title_font = pygame.font.SysFont("monospace", 13, bold=True)
        self.char_h = self.font.get_linesize()

    def render(self, surface, state):
        panel = surface.subsurface((PANEL_X + 2, 0, PANEL_W - 2, SCREEN_H))
        panel.fill(PANEL_BG)

        y = 6
        header = self.title_font.render(" TARS // COMMS LOG", True, GREEN_BRIGHT)
        panel.blit(header, (4, y))
        y += self.char_h + 2
        pygame.draw.line(panel, BORDER_COLOR, (4, y), (PANEL_W - 10, y))
        y += 6

        log = state.get_log()
        max_lines = (SCREEN_H - y - 40) // self.char_h
        visible = log[-max_lines:] if len(log) > max_lines else log

        for text, color_name in visible:
            if color_name == "bright":
                color = GREEN_BRIGHT
            elif color_name == "dim":
                color = GREEN_DIM
            elif color_name == "red":
                color = RED_DIM
            else:
                color = GREEN_MID
            if text.startswith("> "):
                color = GREEN_BRIGHT
            line_surf = self.font.render(text[:38], True, color)
            panel.blit(line_surf, (6, y))
            y += self.char_h

        # Bottom hint
        hint_y = SCREEN_H - self.char_h - 8
        pygame.draw.line(panel, BORDER_COLOR, (4, hint_y - 4), (PANEL_W - 10, hint_y - 4))
        if state.is_recording:
            hint_text = "REC — speak now..."
            hint_color = RED_DIM
        elif state.is_processing:
            hint_text = "Processing..."
            hint_color = GREEN_DIM
        else:
            hint_text = "TAP SCREEN TO SPEAK"
            hint_color = GREEN_DIM
        panel.blit(self.font.render(hint_text, True, hint_color), (6, hint_y))


# --- Exit Button ---

def draw_exit_button(surface):
    """Draw a small X button in the top-right corner."""
    bx = SCREEN_W - EXIT_BUTTON_SIZE - EXIT_BUTTON_MARGIN
    by = EXIT_BUTTON_MARGIN
    rect = pygame.Rect(bx, by, EXIT_BUTTON_SIZE, EXIT_BUTTON_SIZE)
    # Dark background
    bg = pygame.Surface((EXIT_BUTTON_SIZE, EXIT_BUTTON_SIZE), pygame.SRCALPHA)
    bg.fill((0, 0, 0, 160))
    surface.blit(bg, (bx, by))
    # Border
    pygame.draw.rect(surface, GREEN_DIM, rect, 1)
    # X
    margin = 8
    pygame.draw.line(surface, RED_DIM, (bx + margin, by + margin),
                     (bx + EXIT_BUTTON_SIZE - margin, by + EXIT_BUTTON_SIZE - margin), 2)
    pygame.draw.line(surface, RED_DIM, (bx + EXIT_BUTTON_SIZE - margin, by + margin),
                     (bx + margin, by + EXIT_BUTTON_SIZE - margin), 2)
    return rect


def is_exit_click(pos):
    """Check if a click/touch is on the exit button."""
    bx = SCREEN_W - EXIT_BUTTON_SIZE - EXIT_BUTTON_MARGIN
    by = EXIT_BUTTON_MARGIN
    rect = pygame.Rect(bx, by, EXIT_BUTTON_SIZE, EXIT_BUTTON_SIZE)
    return rect.collidepoint(pos)


# --- Main ---

STATE_MAP = {
    "idle": FaceState.IDLE, "listening": FaceState.LISTENING,
    "thinking": FaceState.THINKING, "speaking": FaceState.SPEAKING,
    "happy": FaceState.HAPPY, "curious": FaceState.CURIOUS,
    "surprised": FaceState.SURPRISED, "sleeping": FaceState.SLEEPING,
    "booting": FaceState.BOOTING, "recording": FaceState.RECORDING,
    "neutral": FaceState.IDLE,
}


def main():
    load_env()

    # Detect audio devices
    detect_mic()
    detect_speaker()

    # MCP is handled by Hermes Agent directly
    app_state.log("MCP: managed by Hermes", "dim")

    # Start Flask
    threading.Thread(target=run_flask, daemon=True).start()

    pygame.init()
    try:
        screen = pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.FULLSCREEN | pygame.NOFRAME)
    except pygame.error:
        screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
    pygame.display.set_caption("TARS")
    pygame.mouse.set_visible(False)

    clock = pygame.time.Clock()
    face_renderer = FaceRenderer()
    panel_renderer = PanelRenderer()
    animator = FaceAnimator()

    app_state.log("TARS v1.0 booting...", "dim")
    app_state.log(f"Mic: device {MIC_DEVICE} @ {MIC_SAMPLE_RATE}Hz", "dim")
    app_state.log(f"Speaker: {SPEAKER_CARD}", "dim")
    app_state.log(f"LLM: {LLM_MODEL}", "dim")
    app_state.log(f"Voice: OpenAI / {TTS_VOICE}", "dim")
    app_state.log("Connecting to HuskyLens...", "dim")


    # --- Proactive Vision (every ~5 min) ---
    def proactive_vision_loop():
        time.sleep(60)  # Wait 1 min after boot
        while True:
            time.sleep(120)  # Every 2 minutes
            if app_state.is_processing or app_state.is_recording:
                continue
            if app_state.get_face() == "sleeping":
                continue
            try:
                app_state.set_face("curious")
                app_state.log("[proactive] Scanning...", "dim")
                app_state.log("[proactive] Asking Hermes...", "dim")
                obs = ask_hermes("Look through your HuskyLens camera right now. Describe what you see in one witty sentence — your usual TARS style. Even if it is the same person sitting there, comment on it. Be observational, dry, funny.")
                app_state.log(f"[proactive] Got: {obs[:50]}...", "dim")
                if obs and len(obs) > 5:
                    for line in textwrap.wrap(obs, width=36):
                        app_state.log(f"  {line}", "green")
                    app_state.set_face("speaking")
                    speak_openai(obs)
                app_state.set_face("idle")
            except Exception:
                app_state.set_face("idle")

    threading.Thread(target=proactive_vision_loop, daemon=True).start()
    app_state.log("Proactive vision: every 5 min", "dim")


    boot_start = time.time()
    last_time = time.time()
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                # Get position
                if event.type == pygame.FINGERDOWN:
                    pos = (int(event.x * SCREEN_W), int(event.y * SCREEN_H))
                else:
                    pos = event.pos

                # Check exit button
                if is_exit_click(pos):
                    running = False
                    continue

                # Tap to speak
                if not app_state.is_processing and not app_state.is_recording:
                    threading.Thread(target=handle_voice_input, daemon=True).start()

        # Boot -> idle transition
        if animator.state == FaceState.BOOTING and time.time() - boot_start > 3.0:
            app_state.set_face("idle")
            app_state.log("Systems nominal.", "green")
            app_state.log("Tap anywhere to speak.", "dim")

        current = app_state.get_face()
        animator.set_state(STATE_MAP.get(current, FaceState.IDLE))

        now = time.time()
        dt = min(now - last_time, 0.1)
        last_time = now

        animator.update(dt)

        screen.fill(BLACK)
        face_renderer.render(screen, animator.params, dt)
        panel_renderer.render(screen, app_state)
        # Vertical divider
        pygame.draw.line(screen, BORDER_COLOR, (FACE_W, 0), (FACE_W, SCREEN_H), 2)
        # Exit button (always on top)
        draw_exit_button(screen)
        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    sys.exit(0)


if __name__ == '__main__':
    main()
