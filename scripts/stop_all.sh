#!/bin/bash
# Stop TARS face display
echo "Stopping TARS..."
pkill -f face_server.py 2>/dev/null && echo "  Stopped." || echo "  Not running."
