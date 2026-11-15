#!/usr/bin/env bash
# ==============================================================================
# Control Hub - Standalone Native Launcher
# Sets up virtual environment, installs requirements, and boots server.py
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo "  🚀 Starting Control Hub Standalone Launcher..."
echo "============================================================"

# Ensure Python 3 is installed
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

# Ensure python3-venv / venv is available
VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating isolated Python virtual environment at $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# Install / update requirements
echo "📦 Verifying dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Create default .env if missing
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "⚙️ Creating initial .env from template..."
    cp .env.example .env
fi

# Launch Control Hub
echo "✨ Booting Control Hub daemon on port ${CONTROL_HUB_PORT:-7575}..."
exec python3 server.py "$@"
