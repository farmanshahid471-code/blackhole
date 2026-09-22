"""
bot/providers/image_replicate.py
================================
Replicate - hosted FLUX/SDXL images, paid per image, zero GPU management.

WHEN TO CHOOSE THIS
-------------------
You want near-Vast.ai quality without ever seeing a terminal full of CUDA
errors. You pay a few tenths of a cent per image and Replicate worries about
the GPUs. For a 40-scene video that is usually well under a dollar.

SETUP (3 minutes)
-----------------
  1. https://replicate.com/account/api-tokens  -> copy the token
  2. .env ->  REPLICATE_API_TOKEN=r8_...
  3. config.yaml -> image:
                       provider: "replicate"
     (optionally change the model: black-forest-labs/flux-schnell is fast and
      cheap; black-forest-labs/flux-1.1-pro is the best-looking and pricier)

HOW IT WORKS
------------
Replicate is asynchronous by design:
    POST /v1/predictions            -> {"id": "...", "status": "starting"}
    GET  /v1/predictions/<id>       -> poll until status is succeeded/failed
The polling loop below waits patiently and explains itself in the log, because
"nothing is happening" is the most confusing part of any hosted service.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..registry import register
from ..utils import debug, ensure_dir, info
from .base import ImageProvider

API = "https://api.replicate.com/v1"


@register("image", "replicate",
          cost="~$0.003 per image (flux-schnell)",
          needs_key=True, quality="excellent",
          setup_time="3 minutes",
          doc="Hosted FLUX / SDXL through the Replicate API. Best quality for "
              "the least effort: no GPU to rent, boot or babysit.")
class ReplicateProvider(ImageProvider):
    """Runs FLUX on Replicate's machines, one prediction per image."""

    supports_batch = True          # we send every prediction at once, then poll

    # ------------------------------------------------------------------
    def _token(self) -> str:
        tok = self.secret("image.replicate.api_token_env") or self.setting("image.replicate.api_token")
        if not tok:
            from ..utils import die
            die(
                "Replicate needs an API token.\n"
                "  1. https://replicate.com/account/api-tokens\n"
                "  2. .env ->  REPLICATE_API_TOKEN=r8_...\n"
                "  Free alternative with no account:  --set image.provider=pollinations"
            )
        return str(tok)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
                "Prefer": "wait"}          # ask Replicate to hold the request open

    def _model(self) -> str:
        return str(self.setting("image.replicate.model", "black-forest-labs/flux-schnell"))

    # ------------------------------------------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        import requests
        try:
            headers = self._headers()
        except SystemExit:
            return False, "REPLICATE_API_TOKEN is empty in .env"
        try:
            r = requests.get(f"{API}/account", headers=headers, timeout=25)
        except Exception as e:
            return False, f"could not reach Replicate ({e.__class__.__name__})"
        if r.status_code == 200:
            who = r.json().get("username", "?")
            return True, f"Replicate ready as '{who}' (model: {self._model()})"
        if r.status_code == 401:
            return False, "Replicate rejected the token (401) - check REPLICATE_API_TOKEN in .env"
        return False, f"Replicate HTTP {r.status_code}: {r.text[:160]}"

    # ------------------------------------------------------------------
    def _payload(self, job: dict[str, Any]) -> dict[str, Any]:
        width, height = self.resolved_size(job.get("width"), job.get("height"))
        model = self._model().lower()
        prompt = self.build_prompt(job["prompt"])

        # Different models take differently-named inputs - this maps the
        # common ones so you can swap the model without touching the code.
        if "flux-schnell" in model:
            p: dict[str, Any] = {
                "prompt": prompt,
                "num_inference_steps": min(4, max(1, int(job.get("steps") or 4))),
                "output_format": "jpg",
                "aspect_ratio": self._aspect(width, height),
            }
        elif "flux" in model:
            p = {"prompt": prompt, "output_format": "jpg",
                 "aspect_ratio": self._aspect(width, height)}
            if job.get("seed") is not None:
                p["seed"] = int(job["seed"])
        else:                                   # SDXL and friends
            p = {
                "prompt": prompt,
                "negative_prompt": job.get("negative_prompt") or "",
                "width": width, "height": height,
                "num_inference_steps": int(job.get("steps") or 30),
                "guidance_scale": float(job.get("cfg_scale") or 7.0),
            }
            if job.get("seed") is not None:
                p["seed"] = int(job["seed"])
        return {"input": p}

    @staticmethod
    def _aspect(w: int, h: int) -> str:
        table = {(1, 1): "1:1", (16, 9): "16:9", (9, 16): "9:16",
                 (4, 3): "4:3", (3, 4): "3:4", (3, 2): "3:2", (2, 3): "2:3"}
        from math import gcd
        g = gcd(w, h) or 1
        return table.get((w // g, h // g), "16:9")

    # ------------------------------------------------------------------
    def _create(self, job: dict[str, Any]) -> str | None:
        """Start one prediction, return its id (or None if it failed)."""
        import requests
        r = requests.post(f"{API}/models/{self._model()}/predictions",
                          headers=self._headers(), json=self._payload(job), timeout=120)
        if r.status_code not in (200, 201):
            info(f"  {job.get('scene_id')}: replicate refused the job "
                 f"HTTP {r.status_code}: {r.text[:180]}")
            return None
        data = r.json()
        # With Prefer: wait, fast models are already finished here
        if data.get("status") == "succeeded":
            return data.get("id")
        return data.get("id")

    def _collect(self, pred_id: str, timeout: float = 600.0) -> bytes | None:
        """Poll one prediction until it produces a URL, then download it."""
        import requests
        t0 = time.time()
        looked = False
        while time.time() - t0 < timeout:
            r = requests.get(f"{API}/predictions/{pred_id}", headers=self._headers(), timeout=60)
            if r.status_code != 200:
                info(f"  waiting on prediction {pred_id[:8]}... (HTTP {r.status_code})")
            else:
                data = r.json()
                status = data.get("status")
                if status == "succeeded":
                    out = data.get("output")
                    url = (out[0] if isinstance(out, list) and out else out)
                    if not url:
                        return None
                    rr = requests.get(str(url), timeout=180)
                    return rr.content if rr.status_code == 200 else None
                if status in ("failed", "canceled"):
                    info(f"  prediction {pred_id[:8]} {status}: {str(data.get('error'))[:160]}")
                    return None
                if not looked:
                    info(f"  generating on Replicate ({status}) ...")
                    looked = True
            time.sleep(2.0)
        return None

    # ------------------------------------------------------------------
    def generate(self, prompt: str, out_path: Path, **kwargs: Any) -> Path | None:
        job = {"prompt": prompt, "out_path": out_path, **kwargs}
        pid = self._create(job)
        if not pid:
            return None
        data = self._collect(pid)
        if not data:
            return None
        return self.save_image_bytes(data, Path(out_path))

    def generate_many(self, jobs: list[dict[str, Any]]) -> list[Path | None]:
        """
        Start EVERY prediction first, then wait for them all.

        This is the whole reason Replicate is fast: 40 scenes generate in
        parallel on their side instead of one after another. It is also why
        this provider sets supports_batch = True.
        """
        ids: list[str | None] = []
        for job in jobs:
            ids.append(self._create(job))
        ready = sum(1 for i in ids if i)
        if ready:
            info(f"  {ready} image(s) queued on Replicate - collecting as they finish")

        results: list[Path | None] = []
        for job, pid in zip(jobs, ids):
            if not pid:
                results.append(None)
                continue
            data = self._collect(pid)
            if not data:
                results.append(None)
                continue
            try:
                results.append(self.save_image_bytes(data, Path(job["out_path"])))
            except Exception as e:
                info(f"  {job.get('scene_id')}: could not save the image ({str(e)[:100]})")
                results.append(None)
        return results

    def teardown(self) -> None:
        return None
