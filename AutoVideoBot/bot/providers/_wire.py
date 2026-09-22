"""
bot/providers/_wire.py
======================
The tiny protocol that our OWN image servers speak (Colab, Kaggle, Vast).

WHY A SHARED PROTOCOL
---------------------
Three different providers (colab, vast, and anything you write yourself) all
need to say the same thing to a remote GPU:

    POST /generate
    {"jobs": [{"id": "s01", "prompt": "...", "width": 1920, "height": 1080,
               "steps": 30, "guidance_scale": 7.0, "seed": null}, ...]}

    <- {"results": [{"id": "s01", "ok": true, "image_b64": "..."} ,
                    {"id": "s02", "ok": false, "error": "CUDA OOM"}]}

    GET /health   <- {"ok": true, "gpu": "Tesla T4", "model": "SDXL"}

Because the protocol is fixed, the SERVER can be swapped just as easily as the
provider: the notebook in deploy/colab, the notebook in deploy/kaggle and the
script in deploy/vast/server all implement exactly these two routes.

The file name starts with "_" so the registry does not try to load it as a
provider - it is a helper, not a tool.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from ..utils import debug, info


def health(url: str, timeout: int = 20) -> tuple[bool, dict[str, Any]]:
    """Call GET /health. Returns (ok, payload)."""
    import requests
    try:
        r = requests.get(url.rstrip("/") + "/health", timeout=timeout)
    except Exception as e:
        return False, {"error": f"{e.__class__.__name__}: {e}"}
    if r.status_code != 200:
        return False, {"error": f"HTTP {r.status_code}: {r.text[:160]}"}
    try:
        return True, r.json()
    except Exception:
        return True, {"raw": r.text[:200]}


def send_jobs(url: str, jobs: list[dict[str, Any]], *, api_path: str = "/generate",
              timeout: int = 1800, extra_headers: dict[str, str] | None = None
              ) -> list[dict[str, Any]]:
    """
    Send every job in one request and return the list of result dicts.

    Long timeouts on purpose: a Colab T4 can take 30-60 seconds per image and a
    free tier can throttle, so 30 minutes for a whole batch is normal, not a bug.
    """
    import requests
    payload = {"jobs": jobs}
    endpoint = url.rstrip("/") + api_path
    debug(f"wire: POST {endpoint} ({len(jobs)} job(s))")
    r = requests.post(endpoint, json=payload, timeout=timeout,
                      headers={"Content-Type": "application/json", **(extra_headers or {})})
    if r.status_code != 200:
        raise RuntimeError(
            f"the image server answered HTTP {r.status_code}: {r.text[:300]}\n"
            f"  URL: {endpoint}"
        )
    data = r.json()
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise RuntimeError(f"unexpected reply from the image server: {str(data)[:300]}")
    return results


def save_result(result: dict[str, Any], out_path: Path, saver) -> Path | None:
    """
    Turn one result dict into a file on disk.

    Accepts either inline base64 (`image_b64`) or a URL to download, because
    Colab servers usually inline the bytes while a cloud GPU might prefer to
    hand back a link.

    `saver` is provider.save_image_bytes (passed in so this helper never has to
    import the provider classes).
    """
    out_path = Path(out_path)
    if result.get("ok") is False:
        info(f"  server said: {str(result.get('error'))[:160]}")
        return None

    b64 = result.get("image_b64") or result.get("b64") or result.get("image")
    url = result.get("url") or result.get("image_url")

    if b64:
        if isinstance(b64, str) and b64.startswith("data:"):
            b64 = b64.split(",", 1)[-1]
        try:
            return saver(base64.b64decode(b64), out_path)
        except Exception as e:
            info(f"  could not decode the returned image: {e}")
            return None

    if url:
        import requests
        try:
            r = requests.get(str(url), timeout=180)
            if r.status_code == 200:
                return saver(r.content, out_path)
            info(f"  could not download the image: HTTP {r.status_code}")
        except Exception as e:
            info(f"  could not download the image: {e}")
    return None


def jobs_from(jobs: list[dict[str, Any]], *, style_suffix: str = "") -> list[dict[str, Any]]:
    """Convert the pipeline's job dicts into the wire format."""
    out = []
    for j in jobs:
        prompt = str(j.get("prompt") or "")
        if style_suffix and style_suffix.lower() not in prompt.lower():
            prompt = f"{prompt.rstrip().rstrip(',')}, {style_suffix}"
        out.append({
            "id": j.get("scene_id"),
            "prompt": prompt,
            "negative_prompt": j.get("negative_prompt") or "",
            "width": int(j.get("width") or 1024),
            "height": int(j.get("height") or 1024),
            "steps": int(j.get("steps") or 30),
            "guidance_scale": float(j.get("cfg_scale") or 7.0),
            "seed": j.get("seed"),
        })
    return out
