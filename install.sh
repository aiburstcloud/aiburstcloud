#!/usr/bin/env bash
set -euo pipefail

# AI Burst Cloud — one-line installer
# curl -fsSL https://raw.githubusercontent.com/aiburstcloud/aiburstcloud/main/install.sh | bash

REPO="https://github.com/aiburstcloud/aiburstcloud.git"
MIN_PYTHON="3.10"
CONFIG_DIR="$HOME/.aiburstcloud"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  AI Burst Cloud Installer"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# --- Find Python ---
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [ -n "$ver" ]; then
            major=${ver%%.*}
            minor=${ver#*.}
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                PYTHON="$cmd"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "Error: Python >= $MIN_PYTHON is required but not found."
    echo "Install Python from https://python.org and try again."
    exit 1
fi

echo "Found $PYTHON ($($PYTHON --version 2>&1))"

# --- Find pip ---
PIP=""
for cmd in pip3 pip; do
    if command -v "$cmd" &>/dev/null; then
        PIP="$cmd"
        break
    fi
done

if [ -z "$PIP" ]; then
    echo "pip not found, using $PYTHON -m pip"
    PIP="$PYTHON -m pip"
fi

# --- Install ---
echo ""
echo "Installing aiburstcloud..."
$PIP install "aiburstcloud @ git+${REPO}" --quiet 2>/dev/null || \
$PIP install "aiburstcloud @ git+${REPO}"

# --- Create config directory ---
if [ ! -d "$CONFIG_DIR" ]; then
    mkdir -p "$CONFIG_DIR"
    echo "Created config directory: $CONFIG_DIR"
fi

# --- Download .env.example if no config exists ---
if [ ! -f "$CONFIG_DIR/.env" ]; then
    curl -fsSL "https://raw.githubusercontent.com/aiburstcloud/aiburstcloud/main/.env.example" \
        -o "$CONFIG_DIR/.env" 2>/dev/null || true
    if [ -f "$CONFIG_DIR/.env" ]; then
        echo "Created default config: $CONFIG_DIR/.env"
        echo "  Edit this file to add your cloud endpoint and API key."
    fi
fi

# --- Done ---
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Installed successfully!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Start the router:"
echo "    aiburstcloud"
echo ""
echo "  Options:"
echo "    aiburstcloud --port 9000"
echo "    aiburstcloud --burst-mode cloud_burst"
echo "    aiburstcloud --help"
echo ""
echo "  Config: $CONFIG_DIR/.env"
echo "  Docs:   https://github.com/aiburstcloud/aiburstcloud"
echo ""
