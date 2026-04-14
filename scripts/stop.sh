#!/bin/bash
# Stop tars-vision face display.
echo "Stopping tars-vision..."
pkill -f face_server.py 2>/dev/null && echo "  Stopped." || echo "  Not running."
