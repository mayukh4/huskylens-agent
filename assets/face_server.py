#!/usr/bin/env python3
"""
TARS Face Display — HTML/JS frontend served by Flask.

Left 60%: Three.js holographic face (rendered in Chromium)
Right 40%: Conversation log + status (HTML/CSS)
Touch anywhere: tap-to-speak (POST /api/speak -> record -> STT -> Hermes -> TTS)

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
import signal

from flask import Flask, request, jsonify, send_from_directory
import requests as http_requests
import numpy as np
import sounddevice as sd

sys.path.insert(0, os.path.dirname(__file__))
from vision_router import VisionRouter
from huskylens_uart import (HuskyLensI2C, ALGORITHM_FACE_RECOGNITION,
                            ALGORITHM_HAND_RECOGNITION, ALGORITHM_EMOTION_RECOGNITION,
                            EMOTION_NAMES)

# --- Config ---
LOCATION = os.environ.get("TARS_LOCATION", "")
HUSKYLENS_I2C_BUS = 1
LLM_MODEL = "qwen/qwen3.6-plus:free"
OPENROUTER_API_KEY = ""
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
TTS_VOICE = "onyx"
SOUL_PATH = os.path.expanduser("~/.hermes/SOUL.md")

# Audio
MIC_DEVICE = None
MIC_SAMPLE_RATE = 44100
WHISPER_SAMPLE_RATE = 16000
SPEAKER_CARD = "plughw:3,0"
SILENCE_THRESHOLD = 500
SILENCE_DURATION = 1.2
VOLUME_BOOST_DB = 4

# Static files
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')


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
    global OPENROUTER_API_KEY, OPENAI_API_KEY, LOCATION
    hermes = _read_env_file(os.path.expanduser("~/.hermes/.env"))
    OPENROUTER_API_KEY = hermes.get("OPENROUTER_API_KEY", "")
    env_key = os.environ.get("OPENAI_API_KEY", "")
    if env_key:
        OPENAI_API_KEY = env_key
    env_location = os.environ.get("TARS_LOCATION", "")
    if env_location:
        LOCATION = env_location


def load_system_prompt():
    try:
        with open(SOUL_PATH) as f:
            return f.read()
    except FileNotFoundError:
        return "You are TARS, a dry-witted AI assistant."


def detect_mic():
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
    if MIC_DEVICE is None:
        for i, d in enumerate(devices):
            if d['max_input_channels'] > 0:
                MIC_DEVICE = i
                MIC_SAMPLE_RATE = int(d['default_samplerate'])
                return


def detect_speaker():
    global SPEAKER_CARD
    try:
        result = subprocess.run(['aplay', '-l'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.split('\n'):
            if 'UACDemo' in line or 'USB Audio' in line:
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
        self.weather_temp = "--"
        self.weather_desc = ""
        self.weather_location = ""

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


def fetch_weather_loop():
    """Background thread: fetch weather every 15 minutes. No-op if TARS_LOCATION unset."""
    import urllib.parse
    if not LOCATION:
        return
    while True:
        try:
            loc = urllib.parse.quote(LOCATION)
            resp = http_requests.get(
                f"https://wttr.in/{loc}?format=j1", timeout=10,
                headers={"User-Agent": "TARS/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            current = data.get("current_condition", [{}])[0]
            temp_c = current.get("temp_C", "--")
            desc = current.get("weatherDesc", [{}])[0].get("value", "")
            app_state.weather_temp = f"{temp_c}\u00b0C"
            app_state.weather_desc = desc
            app_state.weather_location = LOCATION
        except Exception:
            pass
        time.sleep(900)


# --- Flask API ---
flask_app = Flask(__name__)
flask_app.logger.disabled = True
import logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)


# Serve frontend
@flask_app.route('/')
def serve_index():
    return send_from_directory(STATIC_DIR, 'index.html')


@flask_app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(STATIC_DIR, path)


# Existing API endpoints (keep for Hermes/external use)
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


# New API endpoints for frontend
@flask_app.route('/api/state', methods=['GET'])
def api_get_state():
    logs = app_state.get_log()
    recent = [{"text": t, "color": c} for t, c in logs[-50:]]
    return jsonify({
        "face": app_state.get_face(),
        "is_recording": app_state.is_recording,
        "is_processing": app_state.is_processing,
        "weather": {
            "temp": app_state.weather_temp,
            "desc": app_state.weather_desc,
            "location": app_state.weather_location,
        },
        "logs": recent,
    })


@flask_app.route('/api/speak', methods=['POST'])
def api_speak():
    if app_state.is_processing or app_state.is_recording:
        return jsonify({"ok": False, "reason": "busy"})
    threading.Thread(target=handle_voice_input, daemon=True).start()
    return jsonify({"ok": True})


@flask_app.route('/api/exit', methods=['POST'])
def api_exit():
    app_state.should_quit = True
    threading.Thread(target=_shutdown, daemon=True).start()
    return jsonify({"ok": True})


def _shutdown():
    time.sleep(0.3)
    # Kill chromium first
    subprocess.run(['pkill', '-9', 'chromium'], capture_output=True)
    time.sleep(0.3)
    # Then kill ourselves
    os._exit(0)


def run_flask():
    flask_app.run(host='0.0.0.0', port=5555, threaded=True)


# --- HuskyLens ---
uart_client = None
vision_router = None


# --- Voice Pipeline ---

def record_audio_blocking():
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
                if len(frames) * block_dur > 20:
                    break
    except Exception as e:
        app_state.log(f"Mic error: {e}", "red")
        return None

    if not has_speech:
        return None

    audio = np.concatenate(frames, axis=0)
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


HERMES_SESSION = "tars-lcd"
HERMES_BIN = os.path.expanduser("~/.local/bin/hermes")


def ask_hermes(text):
    try:
        cmd = [HERMES_BIN, "chat", "-q", text, "-Q"]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=240,
            env={**os.environ, "PATH": os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", "")},
        )
        output = result.stdout.strip()
        # Hermes streams with \r rewrites; keep only the final segment of each line.
        # Also reset the buffer at each new Hermes header so intermediate tool-prep
        # messages don't pile up with the final answer.
        lines = [l.split("\r")[-1] for l in output.split("\n")]
        response_lines = []
        in_response = False
        for line in lines:
            if line.startswith("\u256d") or line.startswith("\u2570") or "\u250a" in line:
                continue
            if "\u2695 Hermes" in line or "Hermes \u2500" in line:
                in_response = True
                response_lines = []
                continue
            if line.startswith("session_id:"):
                continue
            if in_response:
                response_lines.append(line.strip())

        response = " ".join(response_lines).strip()
        if not response:
            for line in lines:
                clean = line.strip()
                if clean and not clean.startswith(("\u250a", "\u256d", "\u2570", "session_id")):
                    if "Hermes" not in clean and "\u2500" not in clean:
                        response_lines.append(clean)
            response = " ".join(response_lines).strip()

        return response if response else "Signal lost. No response from Hermes."
    except subprocess.TimeoutExpired:
        return "Hermes took too long to respond."
    except Exception as e:
        app_state.log(f"Hermes error: {e}", "red")
        return f"Error reaching Hermes: {e}"


def speak_openai(text):
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

        tmp_out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_out.close()
        subprocess.run([
            "ffmpeg", "-y", "-i", tmp_in.name,
            "-filter:a", f"volume={VOLUME_BOOST_DB}dB",
            "-ar", "48000", "-ac", "2",
            tmp_out.name
        ], capture_output=True, timeout=10)
        os.unlink(tmp_in.name)

        subprocess.run(["pw-play", tmp_out.name], capture_output=True, timeout=60)
        os.unlink(tmp_out.name)
    except Exception as e:
        app_state.log(f"TTS error: {e}", "red")


def handle_voice_input():
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
        if vision_router:
            vision_router.resume()


# --- Chromium Kiosk ---

def launch_chromium():
    """Launch Chromium in kiosk mode after Flask is ready."""
    try:
        time.sleep(2.0)

        # Fix crash flag to prevent "restore session" dialog
        prefs_file = os.path.expanduser("~/.config/chromium/Default/Preferences")
        if os.path.exists(prefs_file):
            try:
                with open(prefs_file, 'r') as f:
                    prefs = f.read()
                prefs = prefs.replace('"exited_cleanly":false', '"exited_cleanly":true')
                prefs = prefs.replace('"exit_type":"Crashed"', '"exit_type":"Normal"')
                with open(prefs_file, 'w') as f:
                    f.write(prefs)
            except Exception:
                pass

        # Kill any lingering chromium (ignore errors if none running)
        try:
            subprocess.run(['pkill', 'chromium'], capture_output=True, timeout=3)
        except Exception:
            pass
        time.sleep(1)

        print("Launching chromium...", flush=True)
        subprocess.Popen([
            'chromium',
            '--kiosk',
            '--noerrdialogs',
            '--disable-infobars',
            '--no-first-run',
            '--start-fullscreen',
            '--disable-session-crashed-bubble',
            '--disable-restore-session-state',
            '--use-fake-ui-for-media-stream',
            '--autoplay-policy=no-user-gesture-required',
            '--disable-features=TranslateUI',
            '--check-for-update-interval=31536000',
            '--disable-component-update',
            '--disable-breakpad',
            '--disable-crash-reporter',
            '--disable-pinch',
            '--overscroll-history-navigation=0',
            'http://localhost:5555/'
        ])
        print("Chromium launched.", flush=True)
    except Exception as e:
        print(f"Chromium launch error: {e}", flush=True)


# --- Main ---

def main():
    load_env()
    print("=== TARS face_server starting (HTML/JS mode) ===", flush=True)

    detect_mic()
    detect_speaker()

    # HuskyLens I2C (non-fatal)
    global uart_client
    try:
        uart_client = HuskyLensI2C(bus=HUSKYLENS_I2C_BUS)
        print(f"HuskyLens I2C: connected={getattr(uart_client, 'connected', '?')}", flush=True)
    except Exception as e:
        print(f"HuskyLens I2C init failed: {e}", flush=True)
        uart_client = None

    # Start Flask
    threading.Thread(target=run_flask, daemon=True).start()
    print("Flask started on port 5555", flush=True)

    # Start weather fetcher
    threading.Thread(target=fetch_weather_loop, daemon=True).start()

    # Boot logs
    app_state.log("TARS v2.0 booting...", "dim")
    app_state.log(f"Mic: device {MIC_DEVICE} @ {MIC_SAMPLE_RATE}Hz", "dim")
    app_state.log(f"Speaker: {SPEAKER_CARD}", "dim")
    app_state.log(f"LLM: {LLM_MODEL}", "dim")
    app_state.log(f"Voice: OpenAI / {TTS_VOICE}", "dim")
    if uart_client and getattr(uart_client, 'connected', False):
        app_state.log(f"HuskyLens I2C: bus {HUSKYLENS_I2C_BUS}", "green")
    else:
        app_state.log("HuskyLens I2C: not connected", "red")

    # Hermes heartbeat
    def hermes_heartbeat_loop():
        time.sleep(90)
        while True:
            time.sleep(300)
            if app_state.is_processing or app_state.is_recording:
                continue
            if app_state.get_face() == "sleeping":
                continue
            if not uart_client or not getattr(uart_client, 'connected', False):
                continue
            try:
                if vision_router:
                    vision_router.pause()
                app_state.set_face("curious")
                app_state.log("[heartbeat] Checking...", "dim")

                face_info = "Nobody is around."
                mood_info = ""

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
                try:
                    uart_client.switch_algorithm_safe(ALGORITHM_HAND_RECOGNITION)
                    time.sleep(3)
                except Exception:
                    pass
                if vision_router:
                    vision_router.resume()

    threading.Thread(target=hermes_heartbeat_loop, daemon=True).start()
    app_state.log("Hermes heartbeat: every 5 min", "dim")

    # Vision Router (run in thread so it doesn't block Chromium launch)
    global vision_router
    def _start_vision():
        global vision_router
        if uart_client and getattr(uart_client, 'connected', False):
            try:
                vision_router = VisionRouter(
                    uart_client=uart_client,
                    app_state=app_state,
                    log_fn=app_state.log,
                    hermes_fn=ask_hermes,
                    speak_fn=speak_openai,
                )
                vision_router.start()
            except Exception as e:
                print(f"Vision router init failed: {e}", flush=True)
                app_state.log("[vision] Not available", "red")
        else:
            app_state.log("[vision] HuskyLens not connected", "dim")
    threading.Thread(target=_start_vision, daemon=True).start()

    # Boot → idle after 3 seconds
    def boot_transition():
        time.sleep(3.0)
        app_state.set_face("idle")
        app_state.log("Systems nominal.", "green")
        app_state.log("Tap anywhere to speak.", "dim")
    threading.Thread(target=boot_transition, daemon=True).start()

    # Launch Chromium
    threading.Thread(target=launch_chromium, daemon=True).start()
    print("Chromium kiosk launching...", flush=True)

    # Block main thread until quit
    try:
        while not app_state.should_quit:
            time.sleep(1)
    except KeyboardInterrupt:
        pass

    print("TARS shutting down.", flush=True)
    sys.exit(0)


if __name__ == '__main__':
    main()
