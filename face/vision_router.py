"""
Vision Router — Always-on hand gesture detection via HuskyLens V2 I2C.

Polls HuskyLens over I2C binary protocol, classifies open_palm / fist / victory,
triggers Home Assistant actions or Hermes queries with stability-based debounce.
"""

import time
import logging
import threading

from gesture_classifier import classify_gesture
from ha_controller import HAController
from huskylens_uart import ALGORITHM_HAND_RECOGNITION

logger = logging.getLogger(__name__)


# Gesture -> action mapping
GESTURE_ACTIONS = {
    "open_palm": {
        "type": "ha",
        "entities": ["switch.fan_socket_1"],
        "label": "Fan toggled",
        "expression": "happy",
    },
    "fist": {
        "type": "ha",
        "entities": ["switch.room_led_socket_1"],
        "label": "Room LED toggled",
        "expression": "curious",
    },
    "victory": {
        "type": "hermes",
        "prompt": (
            "Give me one fascinating latest development or discovery in "
            "astronomy, astrophysics, or cosmology. Something from the last "
            "few weeks if possible. One concise paragraph, make it exciting."
        ),
        "label": "Astronomy briefing",
        "expression": "curious",
    },
}


class VisionRouter:
    """Always-on hand gesture pipeline using HuskyLens I2C."""

    def __init__(self, uart_client, app_state, log_fn=None, hermes_fn=None, speak_fn=None):
        """
        Args:
            uart_client: HuskyLensI2C instance.
            app_state: The shared AppState instance.
            log_fn: Callable(text, color) for LCD logging.
            hermes_fn: Callable(text) -> str for Hermes queries.
            speak_fn: Callable(text) for TTS output.
        """
        self.uart = uart_client
        self.ha = HAController()
        self.app_state = app_state
        self.log_fn = log_fn
        self.hermes_fn = hermes_fn
        self.speak_fn = speak_fn

        self._thread = None
        self.running = False
        self.paused = False

        # --- Gesture detection config ---
        self.GESTURE_STABILITY = 3       # consecutive frames of same gesture
        self.GESTURE_COOLDOWN = 3.0      # seconds between actions
        self.HISTORY_DECAY_TIME = 2.0    # seconds before clearing stale history

        # --- Gesture state ---
        self.gesture_history = []        # list of (gesture, timestamp)
        self.last_action_time = 0.0

        # --- Adaptive polling ---
        self._base_interval = 1.0        # default 1Hz
        self._fast_interval = 0.8        # ~1.2Hz when hand detected (I2C needs breathing room)
        self._slow_interval = 2.0        # 0.5Hz when idle
        self._current_interval = self._base_interval
        self._last_hand_seen = 0.0

        # --- Stats & error tracking ---
        self._poll_count = 0
        self._last_debug_log = 0.0
        self._consecutive_errors = 0
        self._consecutive_empty = 0
        self._last_reset_time = 0.0
        self.RESET_COOLDOWN = 120.0
        self.ERROR_THRESHOLD = 10
        self.EMPTY_THRESHOLD = 120       # ~120s at 1Hz = camera stuck

    def _log(self, text, color="dim"):
        if self.log_fn:
            self.log_fn(text, color)
        logger.info(text)

    def start(self):
        """Start the vision router polling thread."""
        if not self.uart.connected:
            self._log("[vision] Waiting for I2C...", "dim")
            for _ in range(10):
                time.sleep(1)
                if self.uart.connected:
                    break

        if not self.uart.connected:
            self._log("[vision] I2C not available - gestures disabled", "red")
            return

        # Handshake with retries
        knocked = False
        for attempt in range(5):
            if self.uart.knock_safe():
                knocked = True
                break
            self._log(f"[vision] Knock attempt {attempt + 1}/5...", "dim")
            time.sleep(2)

        if not knocked:
            self._log("[vision] HuskyLens handshake failed - starting anyway", "red")

        # Switch to hand recognition
        self._switch_to_hand()

        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        self._log("[vision] Gesture control online (I2C)", "green")

    def _poll_loop(self):
        """Main polling loop — runs in its own thread."""
        while self.running:
            if self.paused:
                time.sleep(0.5)
                continue

            if not self.uart.connected:
                time.sleep(2)
                continue

            try:
                self._poll_once()
                self._consecutive_errors = 0
            except Exception as e:
                self._consecutive_errors += 1
                logger.warning(f"Poll error ({self._consecutive_errors}): {e}")
                if self._consecutive_errors >= self.ERROR_THRESHOLD:
                    self._try_reset()
                time.sleep(1)
                continue

            time.sleep(self._current_interval)

    def _try_reset(self):
        """Reset HuskyLens via serial port reopen."""
        now = time.time()
        if now - self._last_reset_time < self.RESET_COOLDOWN:
            return

        self._last_reset_time = now
        self._consecutive_errors = 0
        self._consecutive_empty = 0
        self._log("[vision] HuskyLens stuck — resetting serial...", "red")

        try:
            self.uart.reopen()
            time.sleep(2)

            if self.uart.connected and self.uart.knock_safe():
                self._switch_to_hand()
                # Start slow after reset, ramp up
                self._current_interval = 3.0
                self._log("[vision] Reset OK — ramping up", "green")
            else:
                self._log("[vision] Reset failed — no handshake", "red")
        except Exception as e:
            self._log(f"[vision] Reset error: {e}", "red")

    def _switch_to_hand(self):
        """Switch to Hand Recognition algorithm."""
        try:
            ok = self.uart.switch_algorithm_safe(ALGORITHM_HAND_RECOGNITION)
            if ok:
                time.sleep(1)
                self._log("[vision] Hand Recognition active!", "green")
            else:
                self._log("[vision] Switch to hand failed", "red")
            return ok
        except Exception as e:
            self._log(f"[vision] Switch failed: {e}", "red")
            return False

    def _poll_once(self):
        """Single poll: get hand result, classify, maybe fire action."""
        now = time.time()

        # Get hand keypoints via UART
        results = self.uart.get_hand_data()

        if results:
            self._consecutive_empty = 0
            self._last_hand_seen = now
            # Ramp up to fast polling when hand visible
            self._current_interval = self._fast_interval

            gesture = classify_gesture(results[0])
            self._update_gesture_history(gesture, now)
        else:
            self._consecutive_empty += 1
            # Slow down when no hand visible
            if now - self._last_hand_seen > 10.0:
                self._current_interval = self._slow_interval
            elif now - self._last_hand_seen > 3.0:
                self._current_interval = self._base_interval

            # Decay stale gesture history
            if self.gesture_history:
                last_ts = self.gesture_history[-1][1]
                if now - last_ts > self.HISTORY_DECAY_TIME:
                    self.gesture_history.clear()

            # Stuck camera detection
            if self._consecutive_empty >= self.EMPTY_THRESHOLD:
                self._consecutive_empty = 0
                self._log("[vision] No detections for 2min — camera may be stuck", "red")
                self._try_reset()

        # Check if we should fire an action
        self._check_and_fire(now)

        # Periodic debug log (every 10s)
        self._poll_count += 1
        if now - self._last_debug_log > 10.0:
            self._last_debug_log = now
            hand_count = len(results) if results else 0
            hist = [g for g, _ in self.gesture_history[-3:]]
            self._log(f"[vision] hand={hand_count} hist={hist} poll={self._current_interval:.1f}s", "dim")
            self._poll_count = 0

        # Gradual ramp-up after reset
        if self._current_interval > self._base_interval and self._consecutive_errors == 0:
            self._current_interval = max(self._base_interval, self._current_interval - 0.1)

    def _update_gesture_history(self, gesture, now):
        """Add gesture to history, keeping only recent entries."""
        if gesture == "unknown":
            return

        self.gesture_history.append((gesture, now))

        max_history = self.GESTURE_STABILITY + 2
        if len(self.gesture_history) > max_history:
            self.gesture_history = self.gesture_history[-max_history:]

    def _check_and_fire(self, now):
        """Check if gesture history meets stability and fire action."""
        if len(self.gesture_history) < self.GESTURE_STABILITY:
            return
        if now - self.last_action_time < self.GESTURE_COOLDOWN:
            return

        recent = self.gesture_history[-self.GESTURE_STABILITY:]
        gestures = [g for g, _ in recent]
        timestamps = [t for _, t in recent]

        if len(set(gestures)) != 1:
            return

        gesture = gestures[0]
        if gesture not in GESTURE_ACTIONS:
            return

        time_span = timestamps[-1] - timestamps[0]
        if time_span < 0.3:
            return

        # Fire!
        self.last_action_time = now
        self.gesture_history.clear()
        action = GESTURE_ACTIONS[gesture]
        self._execute_gesture(gesture, action)

    def _execute_gesture(self, gesture, action):
        """Execute gesture action (HA toggle or Hermes query)."""
        label = action["label"]
        expression = action["expression"]
        action_type = action.get("type", "ha")

        self._log(f"[gesture] {gesture} -> {label}", "green")

        if action_type == "ha":
            entities = action["entities"]
            ok = all(self.ha.toggle(eid) for eid in entities)
            if ok:
                self._log(f"  {label}", "bright")
                if self.app_state:
                    self.app_state.set_expression(expression, 2.0)
            else:
                self._log(f"  HA action failed!", "red")

        elif action_type == "hermes" and self.hermes_fn:
            if self.app_state:
                self.app_state.set_expression(expression, 2.0)
            # Run Hermes query in a separate thread to not block polling
            def _run_hermes():
                import textwrap, re
                try:
                    self.app_state.set_face("thinking")
                    response = self.hermes_fn(action["prompt"])
                    if response and len(response) > 5:
                        m = re.match(r'\[(happy|curious|surprised|neutral|thinking)\]', response)
                        if m and m.group(1) != "neutral":
                            self.app_state.set_expression(m.group(1), 3.0)
                        clean = re.sub(r'\[(?:happy|curious|surprised|neutral|thinking)\]\s*', '', response)
                        for line in textwrap.wrap(clean, width=36):
                            self._log(f"  {line}", "green")
                        self.app_state.set_face("speaking")
                        if self.speak_fn:
                            self.speak_fn(response)
                    self.app_state.set_face("idle")
                except Exception as e:
                    self._log(f"  Hermes error: {str(e)[:30]}", "red")
                    self.app_state.set_face("idle")
            threading.Thread(target=_run_hermes, daemon=True).start()

    def pause(self):
        """Pause vision polling (during voice interaction or heartbeat)."""
        self.paused = True

    def resume(self):
        """Resume vision polling. Re-switch to hand recognition."""
        self.paused = False
        if self.uart.connected:
            try:
                self._switch_to_hand()
            except Exception:
                pass

    def stop(self):
        self.running = False
