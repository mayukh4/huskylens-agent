#!/bin/bash
# Start TARS face display
set -e
PROJECT_DIR="$HOME/huskylens-agent"

echo ""
echo "  TARS — Face Display v3.0"
echo ""

pkill -f face_server.py 2>/dev/null && sleep 1 || true

# Load environment variables
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    source "$PROJECT_DIR/.env"
    set +a
fi

echo "  Starting..."
DISPLAY=:0 /usr/bin/python3 "$PROJECT_DIR/face/face_server.py" 2>&1
