"""
HuskyLens V2 — Standalone UART communication module.

Extracted from DFRobot's pinpong library (dfrobot_huskylensv2.py),
with pinpong dependency replaced by pyserial.

Binary protocol: [0x55][0xAA][cmd][algo_id][data_length][data...][checksum]
"""

import time
import queue
import logging
import threading

import serial

logger = logging.getLogger(__name__)

# --- Protocol constants ---
HEADER_0_INDEX = 0
HEADER_1_INDEX = 1
COMMAND_INDEX = 2
ALGO_INDEX = 3
CONTENT_SIZE_INDEX = 4
CONTENT_INDEX = 5
PROTOCOL_SIZE = 6

# Commands
COMMAND_KNOCK = 0x00
COMMAND_GET_RESULT = 0x01
COMMAND_SET_ALGORITHM = 0x0A
COMMAND_SET_MULTI_ALGORITHM = 0x0C
COMMAND_SET_MULTI_ALGORITHM_RATIO = 0x0D
COMMAND_RETURN_ARGS = 0x1A
COMMAND_RETURN_INFO = 0x1B
COMMAND_RETURN_BLOCK = 0x1C
COMMAND_RETURN_ARROW = 0x1D

# Algorithm IDs
ALGORITHM_ANY = 0
ALGORITHM_FACE_RECOGNITION = 1
ALGORITHM_OBJECT_RECOGNITION = 2
ALGORITHM_OBJECT_TRACKING = 3
ALGORITHM_HAND_RECOGNITION = 8
ALGORITHM_POSE_RECOGNITION = 9
ALGORITHM_EMOTION_RECOGNITION = 13
ALGORITHM_GAZE_RECOGNITION = 14

# Emotion IDs returned by emotion recognition
EMOTION_NAMES = {
    1: "angry", 2: "disgust", 3: "fear", 4: "happy",
    5: "neutral", 6: "sad", 7: "surprise",
}


def _read_u16(buf, idx):
    """Read little-endian uint16."""
    return buf[idx] | (buf[idx + 1] << 8)


# --- Result classes ---

class Result:
    """Base result parsed from a RETURN_BLOCK packet."""

    def __init__(self, buf):
        self.data = buf
        self.algo = buf[ALGO_INDEX]
        self.dataLength = buf[CONTENT_SIZE_INDEX]
        base = CONTENT_INDEX

        self.nameLength = 0
        self.contentLength = 0
        if self.dataLength > 10:
            if len(buf) > base + 10:
                self.nameLength = buf[base + 10]
            if len(buf) > base + 10 + 1 + self.nameLength:
                self.contentLength = buf[base + 10 + 1 + self.nameLength]

        self.ID = buf[base]
        self.level = buf[base + 1]
        self.xCenter = _read_u16(buf, base + 2)
        self.yCenter = _read_u16(buf, base + 4)
        self.width = _read_u16(buf, base + 6)
        self.height = _read_u16(buf, base + 8)
        self.used = False

        self.name = ""
        self.content = ""
        str_idx = base + 10
        if self.nameLength > 0:
            self.name = buf[str_idx + 1:str_idx + 1 + self.nameLength].decode("utf-8", "replace")
        str_idx += 1 + self.nameLength
        if self.contentLength > 0:
            self.content = buf[str_idx + 1:str_idx + 1 + self.contentLength].decode("utf-8", "replace")

        # For RETURN_INFO packets
        self.total_results = self.xCenter
        self.total_results_learned = self.yCenter
        self.total_blocks = self.width
        self.total_blocks_learned = self.height
        self.maxID = self.ID


class FaceResult(Result):
    """Face recognition result with 5 facial keypoints."""

    def __init__(self, buf):
        super().__init__(buf)
        FACE_FIELDS = [
            ("leye_x", 0), ("leye_y", 2),
            ("reye_x", 4), ("reye_y", 6),
            ("nose_x", 8), ("nose_y", 10),
            ("lmouth_x", 12), ("lmouth_y", 14),
            ("rmouth_x", 16), ("rmouth_y", 18),
        ]
        base = CONTENT_INDEX + 12 + self.nameLength + self.contentLength
        for name, offset in FACE_FIELDS:
            val = _read_u16(buf, base + offset) if base + offset + 1 < len(buf) else 0
            setattr(self, name, val)


class HandResult(Result):
    """Hand recognition result with 21 keypoints."""

    HAND_FIELDS = [
        ("wrist_x", 0), ("wrist_y", 2),
        ("thumb_cmc_x", 4), ("thumb_cmc_y", 6),
        ("thumb_mcp_x", 8), ("thumb_mcp_y", 10),
        ("thumb_ip_x", 12), ("thumb_ip_y", 14),
        ("thumb_tip_x", 16), ("thumb_tip_y", 18),
        ("index_finger_mcp_x", 20), ("index_finger_mcp_y", 22),
        ("index_finger_pip_x", 24), ("index_finger_pip_y", 26),
        ("index_finger_dip_x", 28), ("index_finger_dip_y", 30),
        ("index_finger_tip_x", 32), ("index_finger_tip_y", 34),
        ("middle_finger_mcp_x", 36), ("middle_finger_mcp_y", 38),
        ("middle_finger_pip_x", 40), ("middle_finger_pip_y", 42),
        ("middle_finger_dip_x", 44), ("middle_finger_dip_y", 46),
        ("middle_finger_tip_x", 48), ("middle_finger_tip_y", 50),
        ("ring_finger_mcp_x", 52), ("ring_finger_mcp_y", 54),
        ("ring_finger_pip_x", 56), ("ring_finger_pip_y", 58),
        ("ring_finger_dip_x", 60), ("ring_finger_dip_y", 62),
        ("ring_finger_tip_x", 64), ("ring_finger_tip_y", 66),
        ("pinky_finger_mcp_x", 68), ("pinky_finger_mcp_y", 70),
        ("pinky_finger_pip_x", 72), ("pinky_finger_pip_y", 74),
        ("pinky_finger_dip_x", 76), ("pinky_finger_dip_y", 78),
        ("pinky_finger_tip_x", 80), ("pinky_finger_tip_y", 82),
    ]

    # Keypoint names for dict conversion (without _x/_y suffix)
    KEYPOINT_NAMES = [
        "wrist", "thumb_cmc", "thumb_mcp", "thumb_ip", "thumb_tip",
        "index_finger_mcp", "index_finger_pip", "index_finger_dip", "index_finger_tip",
        "middle_finger_mcp", "middle_finger_pip", "middle_finger_dip", "middle_finger_tip",
        "ring_finger_mcp", "ring_finger_pip", "ring_finger_dip", "ring_finger_tip",
        "pinky_finger_mcp", "pinky_finger_pip", "pinky_finger_dip", "pinky_finger_tip",
    ]

    def __init__(self, buf):
        super().__init__(buf)
        base = CONTENT_INDEX + 12 + self.nameLength + self.contentLength
        for name, offset in self.HAND_FIELDS:
            val = _read_u16(buf, base + offset) if base + offset + 1 < len(buf) else 0
            setattr(self, name, val)

    def to_dict(self):
        """Convert to dict format expected by gesture_classifier.

        Returns: {"wrist": [x, y], "index_finger_tip": [x, y], ...}
        """
        d = {}
        for kp in self.KEYPOINT_NAMES:
            d[kp] = [getattr(self, f"{kp}_x", 0), getattr(self, f"{kp}_y", 0)]
        return d


# --- Protocol layer ---

class _Protocol:
    """Binary protocol framing — handles packet construction, parsing, checksum."""

    FRAME_BUFFER_SIZE = 1024
    MAX_RETRIES = 3
    WAIT_TIMEOUT_MS = 8000

    def __init__(self):
        self.receive_index = HEADER_0_INDEX
        self.receive_buffer = bytearray(self.FRAME_BUFFER_SIZE)
        self.send_buffer = bytearray(512)
        self.send_index = CONTENT_INDEX
        self._result_store = {}
        for i in range(256):
            self._result_store[i] = {"info": None, "blocks": []}

    def _checksum(self, cmd):
        cs = 0
        for x in cmd:
            cs += x
        return cs & 0xFF

    def _write_begin(self, algo, command):
        self.send_buffer = bytearray(512)
        self.send_buffer[HEADER_0_INDEX] = 0x55
        self.send_buffer[HEADER_1_INDEX] = 0xAA
        self.send_buffer[COMMAND_INDEX] = command
        self.send_buffer[ALGO_INDEX] = algo
        self.send_index = CONTENT_INDEX

    def _write_uint8(self, val):
        self.send_buffer[self.send_index] = val & 0xFF
        self.send_index += 1

    def _write_int16(self, val):
        self.send_buffer[self.send_index] = val & 0xFF
        self.send_buffer[self.send_index + 1] = (val >> 8) & 0xFF
        self.send_index += 2

    def _write_zero(self, count):
        end = self.send_index + count
        self.send_buffer[self.send_index:end] = b'\x00' * count
        self.send_index = end

    def _write_end(self):
        self.send_buffer[CONTENT_SIZE_INDEX] = self.send_index - CONTENT_INDEX
        cs = 0
        for i in range(self.send_index):
            cs += self.send_buffer[i]
        self.send_buffer[self.send_index] = cs & 0xFF
        self.send_index += 1

    def _receive_byte(self, data):
        """State machine: feed one byte, return True when complete valid packet."""
        if self.receive_index == HEADER_0_INDEX:
            if data != 0x55:
                self.receive_index = HEADER_0_INDEX
                return False
            self.receive_buffer[self.receive_index] = 0x55
        elif self.receive_index == HEADER_1_INDEX:
            if data != 0xAA:
                self.receive_index = HEADER_0_INDEX
                return False
            self.receive_buffer[self.receive_index] = 0xAA
        elif self.receive_index == COMMAND_INDEX:
            self.receive_buffer[self.receive_index] = data
        elif self.receive_index == ALGO_INDEX:
            self.receive_buffer[self.receive_index] = data
        elif self.receive_index == CONTENT_SIZE_INDEX:
            if self.receive_index >= self.FRAME_BUFFER_SIZE - PROTOCOL_SIZE:
                self.receive_index = 0
                return False
            self.receive_buffer[self.receive_index] = data
        else:
            self.receive_buffer[self.receive_index] = data
            if self.receive_index == self.receive_buffer[CONTENT_SIZE_INDEX] + CONTENT_INDEX:
                cs = self._checksum(self.receive_buffer[0:self.receive_index])
                return cs == self.receive_buffer[self.receive_index]
        self.receive_index += 1
        return False

    def _wait_for(self, expected_cmd):
        """Read bytes until we get a complete packet matching expected_cmd.

        Returns: (success, retInt_list, retStr_list)
        """
        self.receive_buffer = bytearray(self.FRAME_BUFFER_SIZE)
        self.receive_index = HEADER_0_INDEX
        start_ms = time.time_ns() // 1_000_000

        while True:
            now_ms = time.time_ns() // 1_000_000
            if now_ms - start_ms > self.WAIT_TIMEOUT_MS:
                break
            c = self._read_byte()
            if c is None:
                time.sleep(0.01)
                continue
            if self._receive_byte(c):
                # Packet complete
                if expected_cmd != self.receive_buffer[COMMAND_INDEX]:
                    return False, [], []

                if expected_cmd != COMMAND_RETURN_ARGS:
                    return True, [], []

                # Parse RETURN_ARGS payload
                retInt = []
                retStr = []
                totalIntArgs = self.receive_buffer[CONTENT_INDEX]
                contentSize = self.receive_buffer[CONTENT_SIZE_INDEX]
                contentEnd = CONTENT_INDEX + contentSize
                retValue = self.receive_buffer[CONTENT_INDEX + 1]
                offset = CONTENT_INDEX + 2
                for _ in range(totalIntArgs):
                    v = self.receive_buffer[offset] | (self.receive_buffer[offset + 1] << 8)
                    retInt.append(v)
                    offset += 2

                offset = CONTENT_INDEX + 10
                while offset < contentEnd:
                    length = self.receive_buffer[offset]
                    if length == 0:
                        break
                    offset += 1
                    if offset + length > contentEnd:
                        break
                    s = bytes(self.receive_buffer[offset:offset + length]).decode("utf-8", "replace")
                    retStr.append(s)
                    offset += length
                return retValue == 0, retInt, retStr

        return False, [], []

    def _execute(self, wait_cmd):
        """Send command and wait for response, with retries."""
        for _ in range(self.MAX_RETRIES):
            self._write_bytes()
            ok, retInt, retStr = self._wait_for(wait_cmd)
            if ok:
                return ok, retInt, retStr
        return False, [], []

    # --- Abstract transport methods (implemented by subclass) ---

    def _write_bytes(self):
        raise NotImplementedError

    def _read_byte(self):
        raise NotImplementedError

    # --- High-level commands ---

    def knock(self):
        self._write_begin(ALGORITHM_ANY, COMMAND_KNOCK)
        self._write_uint8(1)
        self._write_zero(9)
        self._write_end()
        ok, _, _ = self._execute(COMMAND_RETURN_ARGS)
        return ok

    def get_result(self, algo):
        """Get recognition results. Returns count or None on failure."""
        self._write_begin(algo, COMMAND_GET_RESULT)
        self._write_end()

        ok, _, _ = self._execute(COMMAND_RETURN_INFO)
        if not ok:
            return None
        if self.receive_index != CONTENT_INDEX + 10:
            return None

        info = Result(self.receive_buffer[0:self.receive_index + 1])
        info.total_arrows = info.total_results - info.total_blocks
        info.total_arrows_learned = info.total_results_learned - info.total_blocks_learned

        self._result_store[algo]["info"] = info
        self._result_store[algo]["blocks"] = []

        for _ in range(info.total_blocks):
            ok, _, _ = self._wait_for(COMMAND_RETURN_BLOCK)
            if not ok:
                return None
            L = self.receive_buffer[CONTENT_SIZE_INDEX] + PROTOCOL_SIZE
            if algo == ALGORITHM_FACE_RECOGNITION:
                block = FaceResult(self.receive_buffer[0:L])
            elif algo == ALGORITHM_HAND_RECOGNITION:
                block = HandResult(self.receive_buffer[0:L])
            else:
                block = Result(self.receive_buffer[0:L])
            self._result_store[algo]["blocks"].append(block)

        for _ in range(info.total_arrows):
            ok, _, _ = self._wait_for(COMMAND_RETURN_ARROW)
            if not ok:
                return None
            L = self.receive_buffer[CONTENT_SIZE_INDEX] + PROTOCOL_SIZE
            self._result_store[algo]["blocks"].append(
                Result(self.receive_buffer[0:L])
            )

        return info.total_results

    def switch_algorithm(self, algo):
        self._write_begin(ALGORITHM_ANY, COMMAND_SET_ALGORITHM)
        self._write_uint8(algo)
        self._write_zero(9)
        self._write_end()
        ok, _, _ = self._execute(COMMAND_RETURN_ARGS)
        return ok

    def set_multi_algorithm(self, algos):
        if len(algos) < 2 or len(algos) > 3:
            return False
        self._write_begin(ALGORITHM_ANY, COMMAND_SET_MULTI_ALGORITHM)
        self._write_uint8(len(algos))
        self._write_uint8(0)
        for a in algos:
            self._write_int16(a)
        for _ in range(4 - len(algos)):
            self._write_int16(0)
        self._write_end()
        ok, _, _ = self._execute(COMMAND_RETURN_ARGS)
        return ok

    def set_multi_algorithm_ratio(self, ratios):
        if len(ratios) < 2 or len(ratios) > 3:
            return False
        self._write_begin(ALGORITHM_ANY, COMMAND_SET_MULTI_ALGORITHM_RATIO)
        self._write_uint8(len(ratios))
        self._write_uint8(0)
        for r in ratios:
            self._write_int16(r)
        for _ in range(4 - len(ratios)):
            self._write_int16(0xFFFF)
        self._write_end()
        ok, _, _ = self._execute(COMMAND_RETURN_ARGS)
        return ok

    def get_cached_result(self, algo, index):
        blocks = self._result_store[algo]["blocks"]
        if index >= len(blocks):
            return None
        return blocks[index]

    def get_cached_count(self, algo):
        return len(self._result_store[algo]["blocks"])


# --- UART transport ---

class HuskyLensUART(_Protocol):
    """HuskyLens V2 communication over UART using pyserial."""

    def __init__(self, port="/dev/ttyAMA0", baudrate=115200):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self._ser = None
        self._rx_queue = queue.Queue()
        self._lock = threading.Lock()
        self._open()

    def _open(self):
        try:
            self._ser = serial.Serial(
                self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1,
            )
            # Flush any stale data
            self._ser.reset_input_buffer()
            self._rx_queue = queue.Queue()
            logger.info(f"UART opened: {self.port} @ {self.baudrate}")
        except Exception as e:
            logger.error(f"Failed to open {self.port}: {e}")
            self._ser = None

    @property
    def connected(self):
        return self._ser is not None and self._ser.is_open

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()
            logger.info("UART closed")

    def reopen(self):
        """Close and reopen serial port (recovery after crash)."""
        self.close()
        self._rx_queue = queue.Queue()
        time.sleep(0.5)
        self._open()

    def _write_bytes(self):
        if not self.connected:
            return
        cmd = bytes(self.send_buffer[0:self.send_index])
        self._ser.write(cmd)
        time.sleep(0.1)  # Give device time to process

    def _read_byte(self):
        if self._rx_queue.empty():
            if not self.connected:
                return None
            data = self._ser.read(32)
            if data:
                for b in data:
                    self._rx_queue.put(b)
        if self._rx_queue.empty():
            return None
        return self._rx_queue.get()

    # --- Thread-safe high-level API ---

    def knock_safe(self):
        with self._lock:
            return self.knock()

    def switch_algorithm_safe(self, algo):
        with self._lock:
            return self.switch_algorithm(algo)

    def get_result_safe(self, algo):
        with self._lock:
            return self.get_result(algo)

    def get_hand_data(self, algo=ALGORITHM_HAND_RECOGNITION):
        """Get hand recognition results as list of dicts for gesture_classifier.

        Thread-safe. Returns list of {"wrist": [x, y], ...} dicts.
        """
        with self._lock:
            count = self.get_result(algo)
            if not count or count <= 0:
                return []
            results = []
            for i in range(count):
                block = self.get_cached_result(algo, i)
                if block and isinstance(block, HandResult):
                    results.append(block.to_dict())
            return results

    def get_face_data(self, algo=ALGORITHM_FACE_RECOGNITION):
        """Get face recognition results. Thread-safe.

        Returns list of dicts with keys: ID, name, xCenter, yCenter.
        """
        with self._lock:
            count = self.get_result(algo)
            if not count or count <= 0:
                return []
            results = []
            for i in range(count):
                block = self.get_cached_result(algo, i)
                if block:
                    results.append({
                        "ID": block.ID,
                        "name": block.name,
                        "xCenter": block.xCenter,
                        "yCenter": block.yCenter,
                    })
            return results


# --- I2C transport ---

class HuskyLensI2C(_Protocol):
    """HuskyLens V2 communication over I2C using smbus2."""

    I2C_ADDR = 0x50
    CHUNK_SIZE = 32  # Max I2C transfer size

    def __init__(self, bus=1):
        super().__init__()
        self.bus_num = bus
        self._i2c = None
        self._rx_queue = queue.Queue()
        self._lock = threading.Lock()
        self._open()

    def _open(self):
        try:
            import smbus2
            self._i2c = smbus2.SMBus(self.bus_num)
            logger.info(f"I2C opened: bus {self.bus_num}, addr 0x{self.I2C_ADDR:02x}")
        except Exception as e:
            logger.error(f"Failed to open I2C bus {self.bus_num}: {e}")
            self._i2c = None

    @property
    def connected(self):
        return self._i2c is not None

    def close(self):
        if self._i2c:
            self._i2c.close()
            self._i2c = None
            logger.info("I2C closed")

    def reopen(self):
        """Close and reopen I2C bus (recovery after crash)."""
        self.close()
        self._rx_queue = queue.Queue()
        time.sleep(0.5)
        self._open()

    def _write_bytes(self):
        if not self.connected:
            return
        cmd = list(self.send_buffer[0:self.send_index])
        # Send in chunks (I2C has transfer size limits)
        for offset in range(0, len(cmd), self.CHUNK_SIZE):
            chunk = cmd[offset:offset + self.CHUNK_SIZE]
            try:
                self._i2c.write_i2c_block_data(self.I2C_ADDR, chunk[0], chunk[1:])
            except Exception as e:
                logger.warning(f"I2C write error: {e}")
                return
        time.sleep(0.5)  # I2C needs more processing time than UART

    def _read_byte(self):
        if self._rx_queue.empty():
            if not self.connected:
                return None
            try:
                data = self._i2c.read_i2c_block_data(self.I2C_ADDR, 0, self.CHUNK_SIZE)
                for b in data:
                    self._rx_queue.put(b)
            except Exception:
                return None
        if self._rx_queue.empty():
            return None
        return self._rx_queue.get()

    # --- Thread-safe high-level API (same as UART) ---

    def knock_safe(self):
        with self._lock:
            return self.knock()

    def switch_algorithm_safe(self, algo):
        with self._lock:
            return self.switch_algorithm(algo)

    def get_result_safe(self, algo):
        with self._lock:
            return self.get_result(algo)

    def set_multi_algorithm_safe(self, algos):
        with self._lock:
            return self.set_multi_algorithm(algos)

    def get_hand_data(self, algo=ALGORITHM_HAND_RECOGNITION):
        """Get hand recognition results as list of dicts for gesture_classifier."""
        with self._lock:
            count = self.get_result(algo)
            if not count or count <= 0:
                return []
            results = []
            for i in range(count):
                block = self.get_cached_result(algo, i)
                if block and isinstance(block, HandResult):
                    results.append(block.to_dict())
            return results

    def get_face_data(self, algo=ALGORITHM_FACE_RECOGNITION):
        """Get face recognition results. Thread-safe."""
        with self._lock:
            count = self.get_result(algo)
            if not count or count <= 0:
                return []
            results = []
            for i in range(count):
                block = self.get_cached_result(algo, i)
                if block:
                    results.append({
                        "ID": block.ID,
                        "name": block.name,
                        "xCenter": block.xCenter,
                        "yCenter": block.yCenter,
                    })
            return results

    def get_emotion_data(self, algo=ALGORITHM_EMOTION_RECOGNITION):
        """Get emotion recognition results. Thread-safe.

        Returns list of dicts: {"ID": 4, "emotion": "happy", "name": "Happy"}
        Emotion IDs: 1=angry 2=disgust 3=fear 4=happy 5=neutral 6=sad 7=surprise
        """
        with self._lock:
            count = self.get_result(algo)
            if not count or count <= 0:
                return []
            results = []
            for i in range(count):
                block = self.get_cached_result(algo, i)
                if block:
                    results.append({
                        "ID": block.ID,
                        "emotion": EMOTION_NAMES.get(block.ID, "unknown"),
                        "name": block.name,
                    })
            return results
