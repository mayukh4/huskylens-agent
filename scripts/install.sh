#!/bin/bash
# One-shot installer for tars-vision.
set -e

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ""
echo "  Installing tars-vision..."
echo ""

pip install -r "$SKILL_DIR/requirements.txt"

mkdir -p "$HOME/.hermes"
cp "$SKILL_DIR/references/SOUL.md" "$HOME/.hermes/SOUL.md"
echo "  [+] Copied SOUL.md to ~/.hermes/SOUL.md"

if [ ! -f "$SKILL_DIR/.env" ]; then
    cp "$SKILL_DIR/.env.example" "$SKILL_DIR/.env"
    echo "  [+] Created .env from template"
    echo ""
    echo "  -> Edit $SKILL_DIR/.env and set OPENAI_API_KEY (required)."
    echo "     Set HA_URL / HA_TOKEN / TARS_LOCATION if you want them (all optional)."
fi

echo ""
echo "  Done. Wire HuskyLens via I2C, then run: $SKILL_DIR/scripts/start.sh"
echo ""
