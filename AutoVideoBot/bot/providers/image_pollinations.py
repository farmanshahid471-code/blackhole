"""
bot/providers/image_pollinations.py
===================================
Pollinations - FREE images with NO account, NO key and NO GPU.

This is the default because it is the only option where a total beginner can
type one command and see a finished video five minutes later. It runs a FLUX
model on their servers and simply hands you the picture:

    https://image.pollinations.ai/prompt/<your prompt>?width=1920&height=1080

WHY THE CODE BELOW IS SO CAREFUL
--------------------------------
A free shared service is not a paid API:
  * it rate-limits, so we wait `image.pollinations.delay_seconds` between scenes
  * it sometimes returns a 429/500/502 for a second or two -> we retry with a
    growing pause (this alone fixes 90% of "image failed" reports)
  * it sometimes returns an HTML error page instead of an image -> we check the
    bytes actually decode as a picture before saving them
  * it is slow for big images -> we download with a generous timeout

If it is down or you have no internet, the bot keeps going: the scene gets a
clean placeholder card and the video still renders. Nothing here can kill a run.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..registry import register
from ..utils import debug, ensure_dir, info, warn
from .base import ImageProvider

DEFAULT_ENDPOINT = "https://image.pollinations.ai/prompt/{prompt}"

# Tried in order when the user has not pinned a model
MODEL_CHAIN = ("flux", "turbo")


@register("image", "pollinations",
          cost="free",
          needs_key=False, quality="good",
          setup_time="0 minutes",
          doc="Free public FLUX server. No key, no account, no GPU. The fastest "
              "way to see a complete video, and a fine fallback if your GPU is busy.")
class PollinationsProvider(ImageProvider):
    """Free hosted FLUX/turbo images."""

    supports_parallel = False        # be polite: this service is shared

    # ------------------------------------------------------------------
    def _endpoint(self) -> str:
        ep = self.setting("image.pollinations.endpoint") or DEFAULT_ENDPOINT
        return str(ep)

    def healthcheck(self) -> tuple[bool, str]:
        import requests
        url = self._endpoint().replace("{prompt}", quote("a black hole"))
        try:
            r = requests.get(url, params={"width": 256, "height": 256, "nologo": "true"},
                             timeout=25)
        except Exception as e:
            return False, (
                f"Pollinations unreachable: {e.__class__.__name__}: {str(e)[:120]}\n"
                "  This provider needs the internet. If you are offline, the bot will\n"
                "  draw placeholder cards instead (the video still finishes).\n"
                "  Local options with no internet:  image.provider: sdwebui (your GPU)"
            )
        if r.status_code == 200 and len(r.content) > 1024:
            return True, "Pollinations ready (free, no key needed)"
        if r.status_code in (402, 429):
            return False, (f"Pollinations is rate-limiting right now (HTTP {r.status_code}).\n"
                           "  It will usually work in a few minutes. Placeholders will be\n"
                           "  used for now - or switch provider:  --set image.provider=sdwebui")
        return False, f"Pollinations answered HTTP {r.status_code}: {r.text[:140]}"

    # ------------------------------------------------------------------
    def _url_for(self, prompt: str, model: str, width: int, height: int,
                 seed: Any, nologo: bool) -> str:
        # The endpoint is a template; {prompt} is URL-encoded for you here.
        ep = self._endpoint()
        if "{prompt}" in ep:
            url = ep.replace("{prompt}", quote(self.build_prompt(prompt), safe=""))
        else:
            url = f"{ep.rstrip('/')}/{quote(self.build_prompt(prompt), safe='')}"
        params = {
            "width": max(256, int(width)),
            "height": max(256, int(height)),
            "model": model,
            "nologo": "true" if nologo else "false",
        }
        if seed is not None:
            params["seed"] = int(seed)
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{url}{'&' if '?' in url else '?'}{query}"

    def generate(self, prompt: str, out_path: Path, **kwargs: Any) -> Path | None:
        import requests

        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        width, height = self.resolved_size(kwargs.get("width"), kwargs.get("height"))
        seed = kwargs.get("seed")
        model = str(self.setting("image.pollinations.model", "flux") or "flux")
        nologo = bool(self.setting("image.pollinations.nologo", True))
        delay = float(self.setting("image.pollinations.delay_seconds", 1.5) or 0)
        attempts = self.retries()
        models = [model] + [m for m in MODEL_CHAIN if m != model]

        last = ""
        for attempt in range(1, attempts + 1):
            for m in models:
                url = self._url_for(prompt, m, width, height, seed, nologo)
                debug(f"pollinations: GET {url[:180]}")
                try:
                    r = requests.get(url, timeout=180,
                                     headers={"User-Agent": "AutoVideoBot/1.0"})
                except Exception as e:
                    last = f"{e.__class__.__name__}: {e}"
                    continue

                if r.status_code == 200 and len(r.content) > 2048:
                    try:
                        return self.save_image_bytes(r.content, out_path)
                    except Exception as e:
                        # Not an image (HTML error page) - try again
                        last = f"bad image data: {e}"
                        continue
                last = f"HTTP {r.status_code}: {r.text[:120]}"
                if r.status_code in (429, 503):
                    break      # rate limited: wait longer, do not hammer every model

            if attempt < attempts:
                pause = min(20.0, 2.0 * attempt * attempt)
                info(f"  image attempt {attempt}/{attempts} failed ({str(last)[:90]}) - "
                     f"waiting {pause:.0f}s")
                time.sleep(pause)

        warn(f"  giving up on this image: {str(last)[:140]}")
        return None

    # ------------------------------------------------------------------
    def generate_many(self, jobs: list[dict[str, Any]]) -> list[Path | None]:
        """Pollinations has no batch endpoint: do them one at a time, politely."""
        results: list[Path | None] = []
        gap = float(self.setting("image.pollinations.delay_seconds", 1.5) or 0)
        for i, job in enumerate(jobs):
            results.append(self.generate(job["prompt"], job["out_path"], **{
                k: v for k, v in job.items()
                if k in ("width", "height", "negative_prompt", "steps", "cfg_scale", "seed")
            }))
            if i < len(jobs) - 1 and gap > 0:
                time.sleep(gap)
        return results
