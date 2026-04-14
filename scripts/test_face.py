#!/usr/bin/env python3
"""
Test script: cycles through all face states.
Also useful for recording B-roll footage.
"""

import time
import requests

API = "http://localhost:5555"

states = [
    ("idle", 3),
    ("listening", 3),
    ("thinking", 3),
    ("speaking", 4),
    ("happy", 3),
    ("curious", 3),
    ("surprised", 2),
    ("sleeping", 3),
    ("idle", 2),
]

print("Face state cycle test")
print("Make sure face_server.py is running first!")
print()

for state, duration in states:
    print(f"  -> {state} ({duration}s)")
    try:
        r = requests.post(f"{API}/state", json={"state": state})
        print(f"     {r.json()}")
    except Exception as e:
        print(f"     ERROR: {e}")
        break
    time.sleep(duration)

# Test expression overlay
print("\n  -> expression: surprised (2s overlay on idle)")
requests.post(f"{API}/state", json={"state": "idle"})
time.sleep(0.5)
requests.post(f"{API}/expression", json={"expression": "surprised", "duration": 2.0})
time.sleep(3)

print("\nDone!")
