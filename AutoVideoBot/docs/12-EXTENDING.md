# Extending the bot - add your own provider in ~40 lines

The core never needs editing. Providers plug into one of four sockets:
`llm`, `tts`, `image`, `assembly`.

## Recipe: a new IMAGE provider ("mycloud")

**1.** Create `bot/providers/image_mycloud.py`:

```python
from pathlib import Path
import requests
from ..registry import register
from ..utils import ensure_dir
from .base import ImageProvider

@register("image", "mycloud", needs_key=True, cost="$0.001/img", quality="high")
class MyCloudProvider(ImageProvider):
    """One paragraph: what it is, who should use it."""

    def setup(self):
        # read config + secrets. cfg.section() gives you image.mycloud.*
        s = self.section()
        self.api_key = self.cfg.env("image.mycloud.api_key_env") or ""
        self.url = s.get("url", "https://api.mycloud.example")

    def healthcheck(self):
        try:
            r = requests.get(f"{self.url}/ping",
                             headers={"Authorization": self.api_key}, timeout=15)
            return (r.status_code == 200, f"mycloud {r.status_code}")
        except Exception as e:
            return False, str(e)

    def generate(self, prompt, out_path, *, width=None, height=None,
                 negative_prompt=None, seed=None, steps=None,
                 cfg_scale=None, **extra) -> Path:
        out_path = Path(out_path); ensure_dir(out_path.parent)
        r = requests.post(f"{self.url}/v1/images", json={
            "prompt": prompt,
            "width": width or 1920, "height": height or 1080,
            "negative": negative_prompt or "",
            "seed": seed, "steps": steps or 30,
        }, headers={"Authorization": self.api_key}, timeout=300)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return out_path

    # OPTIONAL but valuable for GPU-style services: send everything at once.
    # Set supports_batch = True and the pipeline will call this with all jobs.
    supports_batch = False
```

**2.** Import it in `bot/providers/__init__.py`:
```python
from . import image_mycloud   # noqa: F401
```

**3.** (optional) Add a friendly alias in `bot/registry.py` -> `_ALIASES["image"]`.

**4.** Add its config block + secret name to `config.yaml` / `.env.example`.

**5.** Use it:
```bash
python main.py providers                  # it appears
python main.py run vid --script s.txt --set image.provider=mycloud
```

That is genuinely the whole procedure. `generate_many`, `teardown`
(shut your machine down here), and `setup` are the only optional hooks you
will ever need.

## Recipe: a new TTS provider

Implement `synthesize(text, out_path, *, voice, rate, pitch, target_duration)
-> {"path":..., "words": [...]|None}`. Return word timings if your engine can
(`{"w": "Black", "s": 0.12, "e": 0.44}` in seconds) and captions become
word-accurate for free. If it can produce exact-length audio, honour
`target_duration` and the timing stage skips tempo stretching.

## Recipe: a new LLM provider

Implement `chat(messages, *, temperature, max_tokens, json_mode) -> str`.
Return RAW text; `bot.utils.extract_json` already forgives fences, chatty
preambles and trailing commas.

## Changing pipeline behaviour (not tools)

* **New motion preset** - add an entry to `MOTION_PRESETS` in `bot/filters.py`:
  three lambdas of normalised progress (crop scale, focus x, focus y).
* **New colour grade** - add an ffmpeg filter string to `COLOR_GRADES`.
* **New transition** - add a name to `XFADE_MAP` (any ffmpeg xfade transition
  works: `circlecrop`, `squeezeh`, `pixelize`, ...).
* **New caption rule** - `bot/subtitles.py` is small and commented.
* **Rewrite the bot's voice** - edit `prompts/*.txt`; no python at all.

## Rules that keep the bot honest (please keep them in your code)

1. Never write outside `workspace/` and the project folder.
2. Hash every input into your manifest key, or caching will lie.
3. Raise loud, specific errors ("key missing: get it at ...") instead of
   returning None silently.
4. Respect `self.cfg` for every tunable - hard-coded numbers become
   someone's 2 a.m. bug.
