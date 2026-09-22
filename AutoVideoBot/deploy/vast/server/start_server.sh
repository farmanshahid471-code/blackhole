#!/usr/bin/env bash
# ============================================================================
#  deploy/vast/server/start_server.sh
#  Runs ON the rented Vast.ai GPU. The bot uploads this folder and calls this
#  script. Everything it prints goes into server.log on the GPU machine.
#
#  Order of work (each step is slow the first time, instant afterwards):
#     1. install the Python packages the image server needs
#     2. start the server on port 7860
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")"

echo "=============================================================="
echo " AutoVideoBot GPU server boot   $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=============================================================="

# ---- 1. what hardware did we get? -----------------------------------------
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version \
             --format=csv,noheader || true
else
  echo "WARNING: nvidia-smi not found - is this really a GPU machine?"
fi

python - <<'PY' || true
try:
    import torch
    print(f"torch {torch.__version__} | cuda available: {torch.cuda.is_available()}")
except Exception as e:
    print(f"torch not importable: {e}")
PY

# ---- 2. dependencies -------------------------------------------------------
# A marker file means we install once per machine, not once per start.
MARKER=".deps_installed"
if [ ! -f "$MARKER" ]; then
  echo "installing python packages (2-4 minutes) ..."
  pip install --no-input --quiet --upgrade pip || true
  pip install --no-input --quiet \
      "diffusers>=0.31.0" \
      "transformers>=4.44.0" \
      "accelerate>=0.33.0" \
      "safetensors>=0.4.0" \
      "fastapi>=0.110" \
      "uvicorn[standard]>=0.29" \
      "pillow>=10.0.0" \
      "sentencepiece>=0.2.0" \
      "protobuf>=4.25.0"
  touch "$MARKER"
  echo "packages installed"
else
  echo "packages already installed on this machine"
fi

# ---- 3. run it -------------------------------------------------------------
# These environment variables are the knobs you can change without editing
# python: MODEL_ID, DTYPE, MAX_INTERNAL_PIXELS, ENABLE_CPU_OFFLOAD, USE_TURBO.
export MODEL_ID="${MODEL_ID:-stabilityai/stable-diffusion-xl-base-1.0}"
export PORT="${PORT:-7860}"
export DTYPE="${DTYPE:-float16}"

# On a card with 12 GB or less, let the model spill to system RAM.
VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo 0)
if [ "${VRAM_MB:-0}" -lt 12288 ]; then
  export ENABLE_CPU_OFFLOAD=1
  echo "low VRAM detected (${VRAM_MB} MB) -> enabling CPU offload"
fi

echo "starting the image server on port $PORT ..."
exec python -u image_server.py
