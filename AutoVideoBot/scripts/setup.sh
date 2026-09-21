#!/usr/bin/env bash
# ============================================================================
#  AutoVideoBot - one-command setup for macOS / Linux / WSL
#
#  WHAT IT DOES
#    1. checks you have python 3.10+ and ffmpeg (installs ffmpeg if missing)
#    2. creates a virtual environment in .venv
#    3. installs the python packages
#    4. copies .env.example to .env if you do not have one
#    5. creates the folder structure
#    6. runs the doctor so you see exactly what is ready
#
#  Run it once. Then edit .env and config.yaml and start making videos.
# ============================================================================
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
echo "=============================================="
echo "  AutoVideoBot setup   ($ROOT)"
echo "=============================================="

# ---------------------------------------------------------------------------
# 1. python
# ---------------------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Install Python 3.10+ first."
  echo "  macOS:  brew install python"
  echo "  Ubuntu: sudo apt install python3 python3-venv python3-pip"
  exit 1
fi
PYV=$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  python detected : $PYV"
if python3 -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)'; then :; else
  echo "  WARNING: Python $PYV is old. 3.10+ strongly recommended."
fi

# ---------------------------------------------------------------------------
# 2. ffmpeg
# ---------------------------------------------------------------------------
if command -v ffmpeg >/dev/null 2>&1; then
  echo "  ffmpeg detected : $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f3)"
else
  echo "  ffmpeg NOT found - trying to install it ..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg
  elif command -v brew >/dev/null 2>&1; then
    brew install ffmpeg
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y ffmpeg
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -S --noconfirm ffmpeg
  else
    echo "  Could not install ffmpeg automatically."
    echo "  Download a static build from https://johnvansickle.com/ffmpeg/ ,"
    echo "  put ffmpeg + ffprobe somewhere on your PATH, then re-run this script."
  fi
fi

# ---------------------------------------------------------------------------
# 3. virtual environment + packages
# ---------------------------------------------------------------------------
if [ ! -d .venv ]; then
  echo "  creating virtual environment .venv ..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
echo "  installing python packages (1-3 minutes) ..."
python -m pip install --quiet -r requirements.txt

# ---------------------------------------------------------------------------
# 4. secrets file
# ---------------------------------------------------------------------------
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  created .env from .env.example  ->  EDIT IT and add your API keys"
else
  echo "  .env already exists - leaving it alone"
fi

# ---------------------------------------------------------------------------
# 5. folders
# ---------------------------------------------------------------------------
mkdir -p assets/background_music assets/fonts workspace/projects workspace/tmp
echo "  folder structure ready"

# ---------------------------------------------------------------------------
# 6. verify
# ---------------------------------------------------------------------------
echo
echo "  running the system doctor ..."
python main.py doctor || true

echo
echo "=============================================="
echo "  SETUP COMPLETE. Two commands to remember:"
echo
echo "    source .venv/bin/activate"
echo "    python main.py run \"my first video\" --topic \"why the sky is blue\" --duration 60"
echo
echo "  Or with YOUR OWN script:"
echo "    python main.py run \"my video\" --script examples/black_holes_script.txt"
echo "=============================================="
