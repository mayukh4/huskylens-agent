#!/bin/bash
# Start TARS face display
set -e
PROJECT_DIR="$HOME/huskylens-agent"

echo ""
echo "  TARS — Face Display"
echo ""

pkill -f face_server.py 2>/dev/null && sleep 1 || true

echo "  Starting..."
DISPLAY=:0 /usr/bin/python3 "$PROJECT_DIR/face/face_server.py" 2>&1
