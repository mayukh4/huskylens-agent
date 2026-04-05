"""Classify hand gestures from HuskyLens V2 hand recognition keypoints (21 points).

MCP returns keypoints as arrays: "index_finger_tip": [x, y]
"""

import math


def _dist(x1, y1, x2, y2):
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def _point(data, key):
    """Extract (x, y) from a result dict.

    Handles both formats:
      - MCP format: "wrist": [x, y]
      - Flat format: "wrist_x": x, "wrist_y": y
    """
    val = data.get(key)
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        return (val[0], val[1])
    # Fallback to _x/_y format
    return (data.get(f"{key}_x", 0), data.get(f"{key}_y", 0))


def _valid(pt):
    return pt[0] != 0 or pt[1] != 0


def _is_extended(hand_data, finger_name, wrist, threshold=1.05):
    """Check if a finger is extended (tip farther from wrist than MCP)."""
    tip = _point(hand_data, f"{finger_name}_tip")
    mcp = _point(hand_data, f"{finger_name}_mcp")
    if not _valid(tip) or not _valid(mcp):
        return None  # Can't determine
    tip_d = _dist(tip[0], tip[1], wrist[0], wrist[1])
    mcp_d = _dist(mcp[0], mcp[1], wrist[0], wrist[1])
    if mcp_d == 0:
        return None
    return tip_d > mcp_d * threshold


def classify_gesture(hand_data: dict) -> str:
    """Classify a hand gesture from 21 keypoints.

    Returns: "open_palm", "fist", "victory", or "unknown".

    Algorithm: Check which fingers are extended relative to the wrist.
    - Open palm: 3-4 fingers extended
    - Fist: 0-1 fingers extended
    - Victory: index + middle extended, ring + pinky folded
    """
    wrist = _point(hand_data, "wrist")
    if not _valid(wrist):
        return "unknown"

    finger_names = ["index_finger", "middle_finger", "ring_finger", "pinky_finger"]
    states = {}
    valid_count = 0

    for name in finger_names:
        ext = _is_extended(hand_data, name, wrist)
        if ext is not None:
            states[name] = ext
            valid_count += 1

    if valid_count < 3:
        return "unknown"

    extended = sum(1 for v in states.values() if v)

    # Victory: index + middle up, ring + pinky down
    index_up = states.get("index_finger", False)
    middle_up = states.get("middle_finger", False)
    ring_down = not states.get("ring_finger", True)
    pinky_down = not states.get("pinky_finger", True)

    if index_up and middle_up and ring_down and pinky_down:
        return "victory"

    if extended >= 3:
        return "open_palm"
    elif extended <= 1:
        return "fist"
    else:
        return "unknown"
