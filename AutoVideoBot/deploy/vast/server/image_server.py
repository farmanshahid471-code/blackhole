#!/usr/bin/env python3
"""
deploy/vast/server/image_server.py
==================================
The image server that runs ON the rented GPU.

It is a tiny FastAPI app with exactly two routes, and both of them speak the
protocol in bot/providers/_wire.py:

    GET  /health    -> {"ok": true, "gpu": "RTX 4090", "model": "sdxl", ...}
    POST /generate  -> body {"jobs": [...]}   ->  {"results": [...]}

WHY SO SMALL
------------
Every line of code on the GPU costs money to debug. So this file does exactly
one thing: load a diffusion model, keep it in VRAM, and paint pictures on
demand. All the intelligence (what prompts, which scenes, what to do with the
images) stays on your PC.

WHAT HAPPENS ON STARTUP
-----------------------
   1. check that a CUDA GPU is really visible (and fail loudly if not)
   2. load the model ONCE and move it to the GPU
   3. enable the memory-saving tricks:
        * float16  - half the VRAM, no visible quality loss
        * attention slicing / VAE slicing - avoids spikes on big images
        * optional CPU offload for very large models
   4. serve requests until the bot destroys the machine

MEMORY HONESTY
--------------
SDXL at 1920x1080 in one pass needs more VRAM than most cards have. Instead
of crashing, this server generates at a sane internal size (default 1024x1024
area scaled to your aspect ratio) and then UPSCALES with Lanczos to the exact
size you asked for. That is exactly what a human would do, and it is what
makes a 16 GB 4090 handle a 1080p documentary.
"""
from __future__ import annotations

import base64
import io
import os
import time
import traceback
from typing import Any

# ---------------------------------------------------------------------------
# Configuration (all overridable with environment variables)
# ---------------------------------------------------------------------------
MODEL_ID = os.environ.get("MODEL_ID", "stabilityai/stable-diffusion-xl-base-1.0")
PORT = int(os.environ.get("PORT", "7860"))
DTYPE = os.environ.get("DTYPE", "float16")          # float16 | bfloat16 | float32
MAX_INTERNAL_PIXELS = int(os.environ.get("MAX_INTERNAL_PIXELS", str(1024 * 1024)))
ENABLE_CPU_OFFLOAD = os.environ.get("ENABLE_CPU_OFFLOAD", "0") == "1"
DEFAULT_STEPS = int(os.environ.get("DEFAULT_STEPS", "30"))
USE_TURBO = os.environ.get("USE_TURBO", "0") == "1"   # SDXL-Turbo: 1-4 steps

print("=" * 70)
print("  AutoVideoBot image server  (runs on the rented GPU)")
print("=" * 70)

# ---------------------------------------------------------------------------
# 1. Is there really a GPU here?
# ---------------------------------------------------------------------------
try:
    import torch
except Exception as e:                                             # pragma: no cover
    raise SystemExit(
        f"PyTorch is not installed on this machine ({e}).\n"
        f"Pick the pytorch/pytorch image in config.yaml -> image.vast.search.image"
    )

if not torch.cuda.is_available():
    raise SystemExit(
        "NO GPU VISIBLE to PyTorch. The bot is paying for a GPU it cannot use, "
        "so it is stopping now.\n"
        "  * check the machine reports a GPU:  nvidia-smi\n"
        "  * make sure the image you rented is a CUDA image"
    )

GPU_NAME = torch.cuda.get_device_name(0)
VRAM_GB = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
print(f"  GPU   : {GPU_NAME}")
print(f"  VRAM  : {VRAM_GB:.1f} GB")
print(f"  torch : {torch.__version__}  (cuda {torch.version.cuda})")

# ---------------------------------------------------------------------------
# 2. Load the model
# ---------------------------------------------------------------------------
print(f"  model : {MODEL_ID}")
print("  loading (the first run downloads several GB - this is the slow part) ...")
t0 = time.time()

from diffusers import AutoPipelineForText2Image                       # noqa: E402

dtype = {"float16": torch.float16, "bfloat16": torch.bfloat16,
         "float32": torch.float32}.get(DTYPE, torch.float16)

pipe = AutoPipelineForText2Image.from_pretrained(MODEL_ID, torch_dtype=dtype)
pipe = pipe.to("cuda")

# ---- memory helpers ------------------------------------------------------
try:
    pipe.enable_attention_slicing()
except Exception:
    pass
try:
    pipe.enable_vae_slicing()
except Exception:
    pass
if ENABLE_CPU_OFFLOAD:
    try:
        pipe.enable_model_cpu_offload()
        print("  cpu offload: ON (slower, but works on small cards)")
    except Exception as e:
        print(f"  cpu offload unavailable: {e}")
try:
    pipe.set_progress_bar_config(disable=True)
except Exception:
    pass

# SDXL-Turbo wants almost no steps and no guidance
if USE_TURBO or "turbo" in MODEL_ID.lower():
    DEFAULT_STEPS = min(DEFAULT_STEPS, 4)

print(f"  model ready in {time.time() - t0:.0f}s "
      f"({VRAM_GB - torch.cuda.memory_allocated() / (1024 ** 3):.1f} GB still free)")
print("=" * 70)


# ---------------------------------------------------------------------------
# 3. The API
# ---------------------------------------------------------------------------
from fastapi import FastAPI                                          # noqa: E402
from fastapi.responses import JSONResponse                           # noqa: E402
from pydantic import BaseModel                                       # noqa: E402

app = FastAPI(title="AutoVideoBot image server")
STARTED = time.time()


class Job(BaseModel):
    id: str | None = None
    prompt: str
    negative_prompt: str | None = ""
    width: int | None = 1024
    height: int | None = 1024
    steps: int | None = None
    guidance_scale: float | None = 7.0
    seed: int | None = None


class JobBatch(BaseModel):
    jobs: list[Job]


@app.get("/health")
def health() -> dict[str, Any]:
    """The bot pings this to know when the GPU is ready (and to keep it awake)."""
    free = 0.0
    try:
        free = (torch.cuda.get_device_properties(0).total_memory -
                torch.cuda.memory_reserved(0)) / (1024 ** 3)
    except Exception:
        pass
    return {
        "ok": True,
        "gpu": GPU_NAME,
        "vram_gb": round(VRAM_GB, 1),
        "vram_free_gb": round(free, 1),
        "model": MODEL_ID,
        "steps_default": DEFAULT_STEPS,
        "uptime_s": round(time.time() - STARTED, 1),
    }


def _fit_internal(width: int, height: int) -> tuple[int, int]:
    """
    Keep the generation inside the pixel budget, preserving the aspect ratio.

    Upscaling afterwards is nearly free and looks better than an out-of-memory
    crash. Multiples of 8 are required by the VAE.
    """
    width = max(256, int(width))
    height = max(256, int(height))
    area = width * height
    if area > MAX_INTERNAL_PIXELS:
        k = (MAX_INTERNAL_PIXELS / area) ** 0.5
        width, height = int(width * k), int(height * k)
    width -= width % 8
    height -= height % 8
    return max(256, width), max(256, height)


def _round8(v: int) -> int:
    return max(8, int(round(v / 8.0)) * 8)


@app.post("/generate")
def generate(batch: JobBatch):
    """
    Paint every job in the request and return base64 JPEGs.

    One bad job never fails the batch: it comes back with ok:false and an
    error message, and the bot decides what to do (usually a placeholder card).
    """
    results: list[dict[str, Any]] = []
    print(f"-> {len(batch.jobs)} job(s) received")

    for job in batch.jobs:
        t0 = time.time()
        try:
            target_w = _round8(int(job.width or 1024))
            target_h = _round8(int(job.height or 1024))
            gen_w, gen_h = _fit_internal(target_w, target_h)
            steps = int(job.steps or DEFAULT_STEPS)
            guidance = float(job.guidance_scale if job.guidance_scale is not None else 7.0)
            if USE_TURBO or "turbo" in MODEL_ID.lower():
                steps = min(steps, 4)
                guidance = 0.0

            generator = None
            if job.seed is not None:
                generator = torch.Generator(device="cuda").manual_seed(int(job.seed))

            with torch.inference_mode():
                out = pipe(
                    prompt=job.prompt,
                    negative_prompt=job.negative_prompt or None,
                    width=gen_w, height=gen_h,
                    num_inference_steps=max(1, steps),
                    guidance_scale=guidance,
                    generator=generator,
                )
            image = out.images[0]

            # ---- upscale to exactly what the bot asked for ---------------
            if (image.width, image.height) != (target_w, target_h):
                image = image.resize((target_w, target_h), 1)   # 1 = LANCZOS

            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG", quality=94)
            payload = base64.b64encode(buf.getvalue()).decode("ascii")

            took = time.time() - t0
            print(f"   ok  {job.id}: {gen_w}x{gen_h} -> {target_w}x{target_h}, "
                  f"{steps} steps, {took:.1f}s")
            results.append({"id": job.id, "ok": True, "image_b64": payload,
                            "width": target_w, "height": target_h,
                            "seconds": round(took, 2), "seed": job.seed})

        except torch.cuda.OutOfMemoryError as e:                    # pragma: no cover
            torch.cuda.empty_cache()
            print(f"   OOM {job.id}: {e}")
            results.append({"id": job.id, "ok": False,
                            "error": "out of VRAM - lower image.width/height in config.yaml "
                                     "or set MAX_INTERNAL_PIXELS lower on the server"})
        except Exception as e:                                      # pragma: no cover
            print(f"   FAIL {job.id}: {e}")
            traceback.print_exc()
            results.append({"id": job.id, "ok": False, "error": str(e)[:400]})

    torch.cuda.empty_cache()
    return JSONResponse({"results": results})


if __name__ == "__main__":
    import uvicorn
    print(f"  listening on 0.0.0.0:{PORT}   (health: /health)")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
