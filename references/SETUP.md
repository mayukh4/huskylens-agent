# Setup guide

Complete hardware, firmware, and software setup for tars-vision on a Raspberry Pi 5.

## Hardware bill of materials

| Component | Notes |
|---|---|
| Raspberry Pi 5 | 4GB or better. Pi 4 untested. |
| HuskyLens V2 | SEN0638, firmware v1.2.2 or newer. Older firmware has broken `set_algorithm` over I2C. |
| DSI touchscreen | 800x480 official Pi display or compatible. Higher resolutions work but the Three.js face is laid out for 800x480. |
| USB microphone | Any USB audio-class mic. Tested with C-Media PCM2902. |
| USB speaker | Any USB audio-class speaker. Tested with Jieli UACDemo. |
| 5V/2A+ USB-C power brick | **Dedicated** supply for the HuskyLens. Powering it from the Pi's 5V rail causes brown-outs under load. |
| Gravity 4-pin I2C cable | Comes with the HuskyLens. |

## Wiring (HuskyLens → Pi via I2C)

| Gravity wire | Signal | Pi header pin |
|---|---|---|
| Green | SDA | Pin 3 (GPIO 2) |
| Blue | SCL | Pin 5 (GPIO 3) |
| Black | GND | Any GND pin |
| Red | VCC | Pin 1 (3.3V) |

Power the HuskyLens from the separate USB-C brick via its USB-C port. Do not jumper the Pi's 5V rail to the HuskyLens.

## HuskyLens firmware

1. Boot the HuskyLens, long-press the function button to enter settings.
2. Open **General Settings → Protocol Type**.
3. Set it to **I2C** or **Auto Detect**.
4. Confirm the firmware shows **v1.2.2** or newer in **General Settings → About**. If older, upgrade via the DFRobot USB utility before continuing — older firmware has a bug where `set_algorithm` messages are silently dropped over I2C.

## Pi system setup

### Enable I2C

```bash
sudo raspi-config      # Interface Options → I2C → Enable
sudo reboot
```

Confirm the device is visible:

```bash
sudo i2cdetect -y 1    # expect "32" (0x32) in the grid
```

### Audio (PipeWire)

Raspberry Pi OS Bookworm ships with PipeWire by default. Plug in the USB mic and speaker before running `start.sh`; the face server auto-detects them at boot by name (`USB Audio` / `UACDemo`). If detection misses your hardware, edit the device-matching strings in [`assets/face_server.py`](../assets/face_server.py) (`detect_mic()` and `detect_speaker()`).

### Python dependencies

`scripts/install.sh` runs `pip install -r requirements.txt` for you. The packages: `pygame`, `flask`, `sounddevice`, `numpy`, `requests`, `pyserial`, `smbus2`.

If you are on a fresh Bookworm image you may also need `sudo apt install -y python3-smbus ffmpeg`.

## Configuration

`bash scripts/install.sh` copies `.env.example` to `.env` on first run. Edit `.env`:

```
OPENAI_API_KEY=sk-proj-...        # required
TARS_LOCATION=                    # optional, e.g. "Kingston, Ontario"
HA_URL=                           # optional
HA_TOKEN=                         # optional
```

### Optional: Home Assistant

If you want the palm/fist gestures to toggle real switches:

1. In Home Assistant, go to **Profile → Security → Long-Lived Access Tokens**, create one, and copy the JWT.
2. Put the base URL (e.g. `http://homeassistant.local:8123`) into `HA_URL` and the JWT into `HA_TOKEN`.
3. Edit `GESTURE_ACTIONS` at the top of [`assets/vision_router.py`](../assets/vision_router.py) and change the entity IDs from the defaults (`switch.fan_socket_1`, `switch.room_led_socket_1`) to match your HA entities.

If `HA_URL` or `HA_TOKEN` is empty, the controller is disabled at init and the palm/fist gestures log a one-time `HA not configured` notice and become no-ops. The victory-sign astronomy briefing still works because that path goes through Hermes, not HA.

### Optional: Hermes SOUL

`install.sh` copies `references/SOUL.md` to `~/.hermes/SOUL.md`, which Hermes loads as the system prompt. Edit either file and re-run `install.sh`, or symlink them.

## Running

```bash
bash scripts/start.sh        # launches Flask on :5555, opens face in kiosk browser
bash scripts/stop.sh         # pkill face_server.py
python3 scripts/test_face.py # cycles through every face state (server must be running)
```

## Pi 5 caveats

- **UART is unusable** on Pi 5 kernel 6.6.51 and later due to a serial-driver regression. tars-vision uses I2C exclusively — do not try to wire the HuskyLens over UART.
- **USB MCP was abandoned**: the HuskyLens MCP firmware crashes (green screen) after 15–20 minutes of continuous polling. I2C is the stable transport.
