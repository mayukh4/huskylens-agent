#!/bin/bash
# Start tars-vision face display.
set -e

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ""
echo "  tars-vision — Face Display v3.0"
echo ""

pkill -f face_server.py 2>/dev/null && sleep 1 || true

if [ -f "$SKILL_DIR/.env" ]; then
    set -a
    . "$SKILL_DIR/.env"
    set +a
fi

echo "  Starting..."
DISPLAY=:0 /usr/bin/python3 "$SKILL_DIR/assets/face_server.py" 2>&1
