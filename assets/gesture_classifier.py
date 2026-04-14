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


def _is_extended(hand_data, finger_name, wrist, threshold=1.15):
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

    Returns: "open_palm", "fist", "thumbs_up", or "unknown".

    Algorithm: Check which fingers are extended relative to the wrist.
    - Thumbs up: only thumb extended, thumb tip visibly above the wrist
    - Open palm: 3-4 non-thumb fingers extended
    - Fist: 0-1 non-thumb fingers extended
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

    # Thumbs-up: thumb extended + ALL four non-thumb fingers explicitly folded +
    # thumb tip is the highest point of the hand (above every fingertip) AND
    # meaningfully above the wrist. Strict enough to reject a tilted closed fist,
    # where the thumb tip typically sits level with or below the folded knuckles.
    thumb_ext = _is_extended(hand_data, "thumb", wrist)
    others_folded = all(n in states and states[n] is False for n in finger_names)
    if thumb_ext and others_folded:
        thumb_tip = _point(hand_data, "thumb_tip")
        middle_mcp = _point(hand_data, "middle_finger_mcp")
        tips = [_point(hand_data, f"{n}_tip") for n in finger_names]
        if _valid(thumb_tip) and _valid(middle_mcp) and all(_valid(t) for t in tips):
            hand_scale = abs(wrist[1] - middle_mcp[1])
            min_finger_tip_y = min(t[1] for t in tips)
            if (
                hand_scale > 0
                and thumb_tip[1] < wrist[1] - 0.35 * hand_scale
                and thumb_tip[1] < min_finger_tip_y - 0.15 * hand_scale
            ):
                return "thumbs_up"

    if extended >= 3:
        return "open_palm"
    elif extended <= 1:
        return "fist"
    else:
        return "unknown"
