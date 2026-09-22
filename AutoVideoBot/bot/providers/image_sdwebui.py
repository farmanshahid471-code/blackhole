"""
bot/providers/image_sdwebui.py
==============================
Any Stable Diffusion WebUI with its API switched on.

ONE PROVIDER, MANY PLACES
-------------------------
The WebUI API is the same everywhere, so this single provider covers:

    * AUTOMATIC1111 on your own PC        --api --listen --port 7860
    * Forge / reForge / SD.Next           (same API)
    * a Stable Diffusion running in Colab (paste the ngrok link)
    * a Stable Diffusion on a Vast.ai GPU (paste the public address)
    * a friend's machine on your network

Just point SDWEBUI_URL at it in .env:
        SDWEBUI_URL=http://127.0.0.1:7860

WHY PEOPLE LOVE IT
------------------
  * you control the model, the sampler, the steps, the LoRAs - everything
  * it is free forever once it runs on your own GPU
  * no rate limits, so you can generate a 200-scene video in one go

The API call (for the curious):
    POST /sdapi/v1/txt2img
    {"prompt": "...", "negative_prompt": "...", "width": 1920, "height": 1080,
     "steps": 30, "cfg_scale": 7.0, "sampler_name": "DPM++ 2M Karras", "seed": -1}
    -> {"images": ["<base64 png>", ...]}
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from ..registry import register
from ..utils import debug, ensure_dir, info
from .base import ImageProvider

DEFAULT_URL = "http://127.0.0.1:7860"


@register("image", "sdwebui",
          cost="free (your own GPU)",
          needs_key=False, quality="excellent",
          setup_time="30-60 minutes first time, then zero",
          doc="Stable Diffusion WebUI (AUTOMATIC1111/Forge), local or remote. "
              "Full control over model, sampler and steps. No limits, no fees.")
class SDWebUIProvider(ImageProvider):
    """Talks to the standard /sdapi/v1/txt2img endpoint."""

    def _url(self) -> str:
        url = self.secret("image.sdwebui.url_env", DEFAULT_URL) or DEFAULT_URL
        return str(url).rstrip("/")

    def _api(self) -> str:
        return self._url() + str(self.setting("image.sdwebui.api_path", "/sdapi/v1/txt2img"))

    # ------------------------------------------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        import requests
        try:
            r = requests.get(self._url() + "/sdapi/v1/sd-models", timeout=15)
        except Exception as e:
            return False, (
                f"Stable Diffusion WebUI is not answering at {self._url()} "
                f"({e.__class__.__name__}).\n"
                "  * Start it with the API flag:\n"
                "       python launch.py --api --listen --port 7860\n"
                "       (webui-user.bat users: add  --api  to COMMANDLINE_ARGS)\n"
                "  * On Colab/Vast: paste the public link into .env -> SDWEBUI_URL=\n"
                "  * Nothing running yet? Free cloud option:  --set image.provider=pollinations"
            )
        if r.status_code == 200:
            try:
                models = [m.get("model_name", "") for m in r.json()]
            except Exception:
                models = []
            current = models[0] if models else "unknown"
            return True, (f"Stable Diffusion WebUI ready at {self._url()} "
                          f"({len(models)} model(s); loaded: {current})")
        return False, f"WebUI answered HTTP {r.status_code} at {self._url()}"

    # ------------------------------------------------------------------
    def generate(self, prompt: str, out_path: Path, **kwargs: Any) -> Path | None:
        import requests

        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        width, height = self.resolved_size(kwargs.get("width"), kwargs.get("height"))
        negative = str(kwargs.get("negative_prompt") or
                       self.setting("image.negative_prompt", "") or "")
        steps = int(kwargs.get("steps") or self.setting("image.steps", 30))
        cfg = float(kwargs.get("cfg_scale") or self.setting("image.cfg", 7.0))
        seed = kwargs.get("seed")
        sampler = str(self.setting("image.sampler", "DPM++ 2M Karras"))
        model = str(self.setting("image.sdwebui.model", "") or "")
        timeout = int(self.setting("image.sdwebui.timeout", 600))

        payload: dict[str, Any] = {
            "prompt": self.build_prompt(prompt),
            "negative_prompt": negative,
            "width": width,
            "height": height,
            "steps": steps,
            "cfg_scale": cfg,
            "sampler_name": sampler,
            "seed": int(seed) if seed is not None else -1,
            "batch_size": 1,
            "send_images": True,
            "save_images": False,
        }
        if model:
            payload["override_settings"] = {"sd_model_checkpoint": model}
            payload["override_settings_restore_afterwards"] = False
        if self.setting("image.sdwebui.hires_fix", False):
            payload["enable_hr"] = True
            payload["hr_scale"] = float(self.setting("image.sdwebui.hires_scale", 1.5))
            payload["hr_upscaler"] = "R-ESRGAN 4x+"
            payload["denoising_strength"] = 0.35

        debug(f"sdwebui: POST {self._api()} {width}x{height} steps={steps}")
        r = requests.post(self._api(), json=payload, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(
                f"WebUI HTTP {r.status_code}: {r.text[:300]}\n"
                f"  Common causes: the '--api' flag is missing, wrong port, or the\n"
                f"  machine ran out of VRAM (try a smaller image.width/height in config.yaml)."
            )
        try:
            images = r.json().get("images") or []
        except Exception as e:
            raise RuntimeError(f"WebUI sent an unreadable reply: {e}") from e
        if not images:
            raise RuntimeError("WebUI returned no image (check its console for the reason)")

        # The reply is base64 PNG (sometimes with a "data:image/png;base64," prefix)
        data = images[0].split(",", 1)[-1] if images[0].startswith("data:") else images[0]
        return self.save_image_bytes(base64.b64decode(data), out_path)

    # ------------------------------------------------------------------
    def generate_many(self, jobs: list[dict[str, Any]]) -> list[Path | None]:
        """
        No batch endpoint is used on purpose: one request per image means a
        single failure never loses the whole batch, and the progress messages
        in the terminal stay meaningful.
        """
        out: list[Path | None] = []
        for i, job in enumerate(jobs, 1):
            try:
                out.append(self.generate(job["prompt"], job["out_path"], **{
                    k: v for k, v in job.items()
                    if k in ("width", "height", "negative_prompt", "steps", "cfg_scale", "seed")
                }))
            except Exception as e:
                info(f"  [{i}/{len(jobs)}] {job.get('scene_id', '?')}: {str(e)[:150]}")
                out.append(None)
        return out
