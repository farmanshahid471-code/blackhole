#!/usr/bin/env bash
# ===========================================================================
#  AutoVideoBot - START THE WEB INTERFACE (macOS / Linux)
# ===========================================================================
#  Windows users: use START-WINDOWS.bat instead.
#
#  Run it:      bash START-WEB.sh
#  Or make it double-clickable on macOS:
#               chmod +x START-WEB.sh
#
#  If anything is missing this script fixes it: it creates the environment,
#  downloads the web packages and the private FFmpeg, and then opens the
#  interface in your browser.
# ===========================================================================
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

VENV=".venv"
PORT="${PORT:-8765}"
PY="python3"

echo
echo "  ======================================================================"
echo "    AutoVideoBot  -  web interface"
echo "  ======================================================================"
echo

# ---- 1. python present? ---------------------------------------------------
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "  Python 3 was not found."
  echo
  echo "    macOS : brew install python3        (or https://www.python.org/downloads/)"
  echo "    Ubuntu: sudo apt update && sudo apt install python3 python3-venv python3-pip"
  echo "    Fedora: sudo dnf install python3 python3-pip"
  echo
  exit 1
fi

# ---- 2. environment -------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  echo "  First run: creating the private environment ..."
  if ! "$PY" -m venv "$VENV" 2>/dev/null; then
    echo
    echo "  Could not create a virtual environment."
    echo "    Ubuntu/Debian users:  sudo apt install python3-venv"
    echo "  Then run this script again."
    exit 1
  fi
fi
VPY="$VENV/bin/python"

# ---- 3. dependencies ------------------------------------------------------
if ! "$VPY" -c "import fastapi, uvicorn, requests, yaml, PIL" >/dev/null 2>&1; then
  echo "  Downloading what the bot needs (one time, a few minutes) ..."
  "$VPY" -m pip install --upgrade pip --quiet || true
  if ! "$VPY" -m pip install --quiet -r requirements.txt; then
    echo "  (requirements.txt failed - installing the essentials only)"
    "$VPY" -m pip install --quiet requests PyYAML python-dotenv Pillow rich tqdm \
        edge-tts pydub imageio-ffmpeg fastapi "uvicorn[standard]" python-multipart psutil
  fi
fi

# ---- 4. folders and .env --------------------------------------------------
mkdir -p workspace/projects workspace/tmp assets/background_music assets/fonts assets/piper
[ -f .env ] || { [ -f .env.example ] && cp .env.example .env; }

# ---- 5. a friendly warning if ffmpeg is missing ---------------------------
"$VPY" - <<'PY' || true
import sys
try:
    from bot.utils import resolve_ffmpeg
    exe = resolve_ffmpeg("ffmpeg")
    print(f"  video engine: {exe}")
except Exception as e:
    print(f"  (could not locate ffmpeg yet: {e})")
PY

# ---- 6. free the port if an old copy is running ---------------------------
if command -v lsof >/dev/null 2>&1; then
  OLD=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
  if [ -n "${OLD:-}" ]; then
    echo "  Closing an earlier copy on port $PORT ..."
    kill $OLD 2>/dev/null || true
    sleep 1
  fi
fi

# ---- 7. go ----------------------------------------------------------------
echo
echo "  Starting on http://127.0.0.1:$PORT"
echo "  Keep this terminal window open while you use the bot."
echo
exec "$VPY" main.py web --port "$PORT"
