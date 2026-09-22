"""
bot/providers/image_colab.py
============================
Google Colab free GPU as your image generator.

HOW THIS WORKS (the honest version)
-----------------------------------
Colab cannot host a permanent website, so you run the notebook in
`deploy/colab/colab_image_server.ipynb` and it prints a temporary public link
(an ngrok/cloudflare tunnel). Paste that link into .env:

    IMAGE_ENDPOINT_URL=https://abcd-1234.ngrok-free.app

Then the bot posts ALL of your scene prompts to that link in one request and
gets all the images back. Your PC does the thinking; the free T4 does the
diffusion.

GOOD TO KNOW
------------
  * The link DIES when the Colab runtime disconnects (about 90 minutes idle,
    or 12 hours maximum). When that happens you just re-run the notebook and
    paste the new link. The bot tells you clearly when a link is dead.
  * We ping /health every 25 seconds while working (`keepalive_seconds`) so
    Colab does not decide you are idle and kill the runtime mid-batch.
  * Every request has a long timeout: a free T4 takes 20-60 s per image and
    throttling happens. Patience here is normal.

SETUP: see docs/07-COLAB-KAGGLE.md (it is a copy-paste, 5 minute job).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from ..registry import register
from ..utils import debug, info
from . import _wire
from .base import ImageProvider


@register("image", "colab",
          cost="free (Google's GPU, your notebook)",
          needs_key=False, quality="excellent (SDXL / FLUX)",
          setup_time="15 minutes per session",
          doc="Posts your prompts to the Stable Diffusion server running in "
              "deploy/colab/colab_image_server.ipynb. Free T4 GPU. Paste the "
              "printed link into .env as IMAGE_ENDPOINT_URL.")
class ColabProvider(ImageProvider):
    """Batch-generates through a Colab-hosted server."""

    supports_batch = True
    supports_parallel = False     # one request carries every job

    def __init__(self, cfg, project=None):
        super().__init__(cfg, project)
        self._keepalive: threading.Thread | None = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    def _endpoint(self) -> str:
        url = self.secret("image.colab.endpoint_env") or self.setting("image.colab.endpoint")
        if not url:
            from ..utils import die
            die(
                "Colab mode needs the link your notebook printed.\n"
                "  1. open deploy/colab/colab_image_server.ipynb in Google Colab\n"
                "  2. Runtime -> Change runtime type -> T4 GPU, then Run all\n"
                "  3. the last cell prints a link like https://xxxx.ngrok-free.app\n"
                "  4. put it in .env ->  IMAGE_ENDPOINT_URL=https://xxxx.ngrok-free.app\n"
                "     (or pass it for one run:  --endpoint https://xxxx.ngrok-free.app)\n"
                "  Free alternative with no notebook:  --set image.provider=pollinations"
            )
        return str(url).rstrip("/")

    def _api_path(self) -> str:
        return str(self.setting("image.colab.api_path", "/generate"))

    def _headers(self) -> dict[str, str]:
        h = self.setting("image.colab.ngrok_header")
        return {"ngrok-skip-browser-warning": str(h)} if h else {}

    # ------------------------------------------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        try:
            url = self._endpoint()
        except SystemExit:
            return False, "no Colab link configured (IMAGE_ENDPOINT_URL is empty)"
        ok, payload = _wire.health(url, timeout=20)
        if ok:
            gpu = payload.get("gpu") or "GPU"
            model = payload.get("model") or "model"
            return True, f"Colab server alive at {url} ({gpu}, {model})"
        return False, (
            f"the Colab server at {url} is not answering "
            f"({payload.get('error', 'no reason given')}).\n"
            "  * Colab links expire - re-run the notebook and paste the NEW link.\n"
            "  * Check the link ends with the tunnel host, e.g. https://xxxx.ngrok-free.app\n"
            "  * Make sure the notebook's last cell said 'server ready'."
        )

    # ------------------------------------------------------------------
    def _start_keepalive(self) -> None:
        """Ping /health in the background so Colab does not fall asleep."""
        if self._keepalive and self._keepalive.is_alive():
            return
        every = max(10.0, float(self.setting("image.colab.keepalive_seconds", 25) or 25))
        try:
            url = self._endpoint()
        except SystemExit:
            return

        def loop() -> None:
            while not self._stop.wait(every):
                try:
                    _wire.health(url, timeout=15)
                    debug("colab keepalive ping sent")
                except Exception:
                    pass

        self._stop.clear()
        self._keepalive = threading.Thread(target=loop, daemon=True)
        self._keepalive.start()
        info(f"  keepalive: pinging the Colab server every {every:.0f}s so it stays awake")

    # ------------------------------------------------------------------
    def generate_many(self, jobs: list[dict[str, Any]]) -> list[Path | None]:
        url = self._endpoint()
        timeout = int(self.setting("image.colab.timeout", 300))
        # One long request carrying every scene needs a lot more time than a
        # single image, so scale the timeout with the batch size.
        total_timeout = max(timeout, 120 * max(1, len(jobs)))

        self._start_keepalive()
        payload = _wire.jobs_from(jobs, style_suffix=self.style_suffix())
        info(f"  sending {len(payload)} prompt(s) to the Colab GPU "
             f"(up to {total_timeout // 60} minutes)...")
        t0 = time.time()

        try:
            results = _wire.send_jobs(url, payload, api_path=self._api_path(),
                                      timeout=total_timeout, extra_headers=self._headers())
        except Exception as e:
            msg = str(e)
            if "timed out" in msg.lower() or "Timeout" in msg:
                raise RuntimeError(
                    f"the Colab server did not answer within {total_timeout // 60} minutes.\n"
                    f"  A free T4 with a big model can be slow. Options:\n"
                    f"   * lower config.yaml -> image.steps (20 instead of 30)\n"
                    f"   * lower image.width/height (1280x720 renders ~2x faster)\n"
                    f"   * split the work: render a few scenes at a time with --only\n"
                    f"  ({msg[:160]})"
                ) from e
            raise

        ok_count = sum(1 for r in results if r.get("ok") is not False and
                       (r.get("image_b64") or r.get("url")))
        info(f"  Colab returned {len(results)} result(s), {ok_count} usable, "
             f"in {time.time() - t0:.0f}s")

        by_id = {str(r.get("id")): r for r in results if r.get("id")}
        out: list[Path | None] = []
        for job in jobs:
            res = by_id.get(str(job.get("scene_id")))
            if not res:
                out.append(None)
                continue
            out.append(_wire.save_result(res, Path(job["out_path"]), self.save_image_bytes))
        return out

    # ------------------------------------------------------------------
    def generate(self, prompt: str, out_path: Path, **kwargs: Any) -> Path | None:
        job = {"prompt": prompt, "out_path": out_path, **kwargs,
               "scene_id": kwargs.get("scene_id") or "single"}
        res = self.generate_many([job])
        return res[0] if res else None

    def teardown(self) -> None:
        self._stop.set()
        self._keepalive = None
