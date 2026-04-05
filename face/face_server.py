#!/usr/bin/env python3
"""
TARS Face Display — Matrix AI face with conversation panel.

Left 60%: Matrix-style face with eyes/mouth
Right 40%: Conversation log + status
Touch anywhere: tap-to-speak (record -> STT -> Hermes -> TTS -> speaker)
Top-right X button: exit

Hermes can drive face state via:
  curl -X POST localhost:5555/state -d '{"state":"thinking"}'
"""

import os
import sys
import time
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
from vision_router import VisionRouter
from huskylens_uart import (HuskyLensI2C, ALGORITHM_FACE_RECOGNITION,
                            ALGORITHM_HAND_RECOGNITION, ALGORITHM_EMOTION_RECOGNITION,
                            EMOTION_NAMES)

# --- Config ---
HUSKYLENS_I2C_BUS = 1
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
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")


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


# --- HuskyLens UART Client ---
uart_client = None   # Initialized in main()
vision_router = None  # Initialized in main()


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
    # Pause vision router during voice interaction
    if vision_router:
        vision_router.pause()
    try:
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
    finally:
        # Always resume vision router
        if vision_router:
            vision_router.resume()


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

    # Start HuskyLens I2C client
    global uart_client
    uart_client = HuskyLensI2C(bus=HUSKYLENS_I2C_BUS)

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
    if uart_client and uart_client.connected:
        app_state.log(f"HuskyLens I2C: bus {HUSKYLENS_I2C_BUS}", "green")
    else:
        app_state.log("HuskyLens I2C: not connected", "red")


    # --- Hermes Heartbeat (every ~5 min) ---
    def hermes_heartbeat_loop():
        """Periodic face + mood check via I2C, then Hermes greeting."""
        time.sleep(90)  # Wait 1.5 min after boot
        while True:
            time.sleep(300)  # Every 5 minutes
            if app_state.is_processing or app_state.is_recording:
                continue
            if app_state.get_face() == "sleeping":
                continue
            if not uart_client or not uart_client.connected:
                continue
            try:
                # Pause gesture detection
                if vision_router:
                    vision_router.pause()

                app_state.set_face("curious")
                app_state.log("[heartbeat] Checking...", "dim")

                # --- Sequential: Face recognition, then Emotion ---
                face_info = "Nobody is around."
                mood_info = ""

                # Step 1: Face recognition
                try:
                    uart_client.switch_algorithm_safe(ALGORITHM_FACE_RECOGNITION)
                    time.sleep(3)
                    for _ in range(3):
                        faces = uart_client.get_face_data()
                        if faces:
                            f = faces[0]
                            if f["name"]:
                                face_info = f"{f['name']} is here."
                            else:
                                face_info = "Someone unfamiliar is here."
                            break
                        time.sleep(0.5)
                except Exception as e:
                    app_state.log(f"[heartbeat] Face err: {str(e)[:30]}", "red")

                # Step 2: Emotion detection (only if someone was found)
                if "here" in face_info:
                    try:
                        uart_client.switch_algorithm_safe(ALGORITHM_EMOTION_RECOGNITION)
                        time.sleep(3)
                        for _ in range(3):
                            emotions = uart_client.get_emotion_data()
                            if emotions:
                                mood = emotions[0]["emotion"]
                                if mood != "neutral":
                                    mood_info = f"They seem {mood}."
                                break
                            time.sleep(0.5)
                    except Exception as e:
                        app_state.log(f"[heartbeat] Mood err: {str(e)[:30]}", "red")

                context = f"{face_info} {mood_info}".strip()
                app_state.log(f"[heartbeat] {context}", "dim")

                # Ask Hermes with face + mood context
                obs = ask_hermes(
                    f"Quick status: {context} "
                    "React naturally — if someone's here, say something to them "
                    "(acknowledge their mood if relevant). If nobody's around, "
                    "mutter something to yourself. One sentence, stay in character."
                )

                if obs and len(obs) > 5:
                    m = re.match(r'\[(happy|curious|surprised|neutral|thinking)\]', obs)
                    if m and m.group(1) != "neutral":
                        app_state.set_expression(m.group(1), 3.0)
                    clean = re.sub(r'\[(?:happy|curious|surprised|neutral|thinking)\]\s*', '', obs)

                    for line in textwrap.wrap(clean, width=36):
                        app_state.log(f"  {line}", "green")
                    app_state.set_face("speaking")
                    speak_openai(obs)

                app_state.set_face("idle")
            except Exception as e:
                app_state.log(f"[heartbeat] Error: {str(e)[:40]}", "red")
                app_state.set_face("idle")
            finally:
                # ALWAYS switch back to hand recognition and resume
                try:
                    uart_client.switch_algorithm_safe(ALGORITHM_HAND_RECOGNITION)
                    time.sleep(3)  # Give firmware time to stabilize
                except Exception:
                    pass
                if vision_router:
                    vision_router.resume()

    threading.Thread(target=hermes_heartbeat_loop, daemon=True).start()
    app_state.log("Hermes heartbeat: every 5 min", "dim")

    # --- Vision Router (gesture control via I2C) ---
    global vision_router
    vision_router = VisionRouter(
        uart_client=uart_client,
        app_state=app_state,
        log_fn=app_state.log,
        hermes_fn=ask_hermes,
        speak_fn=speak_openai,
    )
    vision_router.start()

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
