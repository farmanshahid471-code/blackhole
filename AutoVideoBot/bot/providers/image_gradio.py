"""
bot/providers/image_gradio.py
=============================
Talk to ANY Gradio app that generates images.

WHY THIS PROVIDER EXISTS
------------------------
Thousands of image generators are published as Gradio apps on Hugging Face
Spaces, and every Colab/Kaggle notebook that uses `gr.Interface` is one too.
They all speak the same protocol, so ONE provider can drive all of them.

SETUP
-----
Put the app's address in .env:
    IMAGE_ENDPOINT_URL=https://your-space.hf.space
or pass it per run:
    python main.py run myvideo --topic "..." --endpoint https://xxxx.gradio.live

needs `pip install gradio_client` (in requirements.txt, optional tier).

IF THE APP USES DIFFERENT INPUT NAMES
-------------------------------------
Gradio apps each name their inputs differently ("prompt", "text", "instruction"...).
The provider inspects the app's API signature and maps them for you. If it gets
confused, you can force the names in config.yaml:

    image:
      gradio:
        api_name: "/predict"
        prompt_param: "prompt"        # the box the text goes in
        width_param: "width"
        height_param: "height"
        seed_param: "seed"
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ..registry import register
from ..utils import debug, ensure_dir, info
from .base import ImageProvider

PROMPT_NAMES = ("prompt", "text", "instruction", "describe", "input", "query", "caption")
NEG_NAMES = ("negative_prompt", "negative", "neg_prompt")
STEPS_NAMES = ("steps", "num_inference_steps", "num_steps", "iterations")
SCALE_NAMES = ("guidance_scale", "cfg_scale", "scale", "gs")
SEED_NAMES = ("seed", "random_seed")
WIDTH_NAMES = ("width", "w")
HEIGHT_NAMES = ("height", "h")


@register("image", "gradio",
          cost="free to cheap",
          needs_key=False, quality="depends on the app you point it at",
          setup_time="5 minutes (paste a link)",
          doc="Talks to any Gradio image app: Hugging Face Spaces, Colab share "
              "links, Kaggle notebooks. Works out the input names by itself.")
class GradioProvider(ImageProvider):
    """Drives a Gradio app through the gradio_client library."""

    def _endpoint(self) -> str:
        url = self.secret("image.gradio.endpoint_env") or self.setting("image.gradio.endpoint")
        if not url:
            from ..utils import die
            die(
                "No Gradio address configured.\n"
                "  Put the app link in .env ->  IMAGE_ENDPOINT_URL=https://...  \n"
                "  or pass it for one run:      --endpoint https://xxxx.gradio.live\n"
                "  (Hugging Face Spaces links look like https://user-space.hf.space)"
            )
        return str(url).rstrip("/")

    def _client(self):
        if self._client is not None:
            return self._client
        try:
            from gradio_client import Client                  # type: ignore
        except ImportError:
            from ..utils import die
            die("gradio_client is not installed.\n  Run:  pip install gradio_client")
        info(f"  connecting to the Gradio app at {self._endpoint()} ...")
        self._client = Client(self._endpoint())
        return self._client

    # ------------------------------------------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        try:
            url = self._endpoint()
        except SystemExit:
            return False, "no Gradio endpoint configured (see docs/07-COLAB-KAGGLE.md)"
        try:
            client = self._client()
            api = getattr(client, "endpoints", None) or []
            names = [e for e in api if "predict" in str(e).lower()]
            return True, (f"Gradio app reachable at {url} "
                          f"({len(api)} endpoint(s){', predict' if names else ''})")
        except Exception as e:
            return False, (
                f"could not connect to the Gradio app at {url}\n"
                f"  ({e.__class__.__name__}: {str(e)[:140]})\n"
                "  * Free Colab links EXPIRE after ~90 minutes - get a fresh one.\n"
                "  * Hugging Face Spaces: make sure the Space is 'Running', not sleeping.\n"
                "  * No app yet? Use the free default:  --set image.provider=pollinations"
            )

    # ------------------------------------------------------------------
    def _input_map(self, client) -> dict[str, str]:
        """Work out which parameter names this particular app uses."""
        forced = {k: self.setting(f"image.gradio.{k}_param") for k in
                  ("prompt", "negative", "steps", "scale", "seed", "width", "height")}
        found: dict[str, str] = {}

        # Try the app's published API info first
        try:
            client.view_api(return_format="dict")
        except Exception:
            pass
        try:
            info_dict = client.view_api(return_format="dict") or {}
            params = (((info_dict.get("named_endpoints") or {}).get(
                str(self.setting("image.gradio.api_name", "/predict"))) or {}).get("parameters")) or []
            labels = [str(p.get("parameter_name") or p.get("label") or "").lower() for p in params]
            debug(f"gradio parameters: {labels}")
            for key, candidates in (("prompt", PROMPT_NAMES), ("negative", NEG_NAMES),
                                    ("steps", STEPS_NAMES), ("scale", SCALE_NAMES),
                                    ("seed", SEED_NAMES), ("width", WIDTH_NAMES),
                                    ("height", HEIGHT_NAMES)):
                for cand in candidates:
                    if cand in labels:
                        found[key] = cand
                        break
        except Exception as e:
            debug(f"could not read the gradio api description: {e}")

        for key, val in forced.items():
            if val:
                found[key] = str(val)
        return found

    # ------------------------------------------------------------------
    def generate(self, prompt: str, out_path: Path, **kwargs: Any) -> Path | None:
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        client = self._client()
        api_name = str(self.setting("image.gradio.api_name", "/predict"))

        width, height = self.resolved_size(kwargs.get("width"), kwargs.get("height"))
        names = self._input_map(client)

        # Build the arguments in the ORDER the app expects (positional API)
        try:
            info_dict = client.view_api(return_format="dict") or {}
            params = (((info_dict.get("named_endpoints") or {}).get(api_name)) or {}).get("parameters") or []
        except Exception:
            params = []

        desired = {
            "prompt": self.build_prompt(prompt),
            "negative": str(kwargs.get("negative_prompt") or self.setting("image.negative_prompt", "")),
            "steps": int(kwargs.get("steps") or self.setting("image.steps", 30)),
            "scale": float(kwargs.get("cfg_scale") or self.setting("image.cfg", 7.0)),
            "seed": int(kwargs["seed"]) if kwargs.get("seed") is not None else 0,
            "width": width,
            "height": height,
        }

        args: list[Any] = []
        if params:
            for p in params:
                label = str(p.get("parameter_name") or p.get("label") or "").lower()
                matched = False
                for key, cand in names.items():
                    if cand == label:
                        args.append(desired[key])
                        matched = True
                        break
                if matched:
                    continue
                # Unknown input: guess from its type so the call still works
                ptype = str((p.get("type") or {}).get("type", "string"))
                if "number" in ptype:
                    args.append(desired["steps"])
                elif "bool" in ptype:
                    args.append(False)
                elif "file" in ptype or "image" in ptype:
                    args.append(None)
                else:
                    args.append("")
        else:
            # No API description available: assume the classic (prompt, negative, steps...)
            args = [desired["prompt"], desired["negative"], desired["steps"],
                    desired["scale"], desired["seed"]]

        debug(f"gradio: calling {api_name} with {len(args)} argument(s)")
        result = client.predict(*args, api_name=api_name)

        # The app returns a file path, a URL, a tuple, or a dict. Handle all.
        path = self._extract_file(result)
        if not path:
            raise RuntimeError(
                f"the Gradio app replied but no image was found in the answer "
                f"({str(result)[:180]})\n"
                f"  Tip: check the app names its outputs differently, or try\n"
                f"       image.gradio.api_name in config.yaml"
            )
        return self.save_image_bytes(Path(path).read_bytes(), out_path)

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_file(result: Any) -> Path | None:
        """Gradio can hand back a path, a URL, a tuple, a list or a dict."""
        if result is None:
            return None
        if isinstance(result, (list, tuple)):
            for item in result:
                found = GradioProvider._extract_file(item)
                if found:
                    return found
            return None
        if isinstance(result, dict):
            for key in ("path", "name", "image", "url", "value"):
                if result.get(key):
                    found = GradioProvider._extract_file(result[key])
                    if found:
                        return found
            return None
        if isinstance(result, str):
            if result.startswith("http"):
                import requests
                r = requests.get(result, timeout=180)
                if r.status_code != 200:
                    return None
                from ..paths import ROOT
                tmp = ensure_dir(ROOT / "workspace" / "tmp") / "gradio_download.img"
                tmp.write_bytes(r.content)
                return tmp
            p = Path(result)
            if p.exists():
                return p
        return None

    def teardown(self) -> None:
        try:
            if self._client is not None:
                close = getattr(self._client, "close", None)
                if callable(close):
                    close()
        except Exception:
            pass
        self._client = None
