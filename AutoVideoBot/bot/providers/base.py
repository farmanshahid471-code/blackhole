"""
bot/providers/base.py
=====================
The four CONTRACTS a provider must satisfy, plus helpers everyone shares.

WHY CONTRACTS MATTER
--------------------
The pipeline calls the same handful of methods on every provider, no matter
which one you picked in config.yaml. Because all providers look identical from
the outside, you can swap a free web service for your own GPU at 3 a.m. and
nothing else in the bot needs to change.

THE FOUR KINDS
--------------
    LLMProvider      -> .chat(messages)                    writes text
    TTSProvider      -> .synthesize(text, out_path)         writes a .wav/.mp3
    ImageProvider    -> .generate(prompt, out_path)         writes a .jpg
    AssemblyProvider -> render/mix/mux with ffmpeg          writes video/audio

Every provider also has:
    .healthcheck()  -> (True, "what I checked") or (False, "what to fix")
    .teardown()     -> free anything that costs money (Vast GPUs, tunnels)

WHAT A TYPICAL PROVIDER LOOKS LIKE
----------------------------------
    from ..registry import register
    from .base import ImageProvider

    @register("image", "mything", cost="free", quality="good")
    class MyThing(ImageProvider):
        def generate(self, prompt, out_path, **kw):
            ...
            return Path(out_path)

That is the whole thing. Copy an existing provider, rename it, edit the middle.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..config import Config
from ..paths import Project
from ..utils import debug, ensure_dir


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------
def to_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def to_int(value: Any, fallback: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


class BaseProvider:
    """
    Common plumbing: config access, env access, a project that may be None.

    `project` is None when a provider is only being checked (doctor, voices,
    providers list). Never assume it exists - use self.project_dir if you need
    somewhere to write a scratch file.
    """

    kind: str = ""
    provider_name: str = ""
    provider_meta: dict[str, Any] = {}

    def __init__(self, cfg: Config, project: Project | None = None):
        self.cfg = cfg
        self.project = project
        self._client: Any = None
        self._notes: list[str] = []

    # ------------------------------------------------------------------
    # convenience -------------------------------------------------------
    @property
    def name(self) -> str:
        return self.provider_name or self.__class__.__name__

    def setting(self, dotted: str, default: Any = None) -> Any:
        """Read config value, e.g. self.setting('image.pollinations.model')."""
        return self.cfg.get(dotted, default)

    def secret(self, dotted: str, fallback: str = "") -> str:
        """Read the VALUE of an env var whose NAME is stored at `dotted`."""
        return str(self.cfg.env(dotted, fallback) or "")

    @property
    def project_dir(self) -> Path:
        if self.project is not None:
            return self.project.dir
        from ..paths import ROOT
        return ensure_dir(ROOT / "workspace" / "tmp")

    def ensure_parent(self, path: Path) -> Path:
        ensure_dir(Path(path).parent)
        return Path(path)

    # ------------------------------------------------------------------
    # the three methods every provider has -------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        """(ok, message). Say what you checked, and how to fix it if broken."""
        return True, f"{self.kind} provider '{self.name}' has no healthcheck"

    def teardown(self) -> None:
        """Release anything that costs money. Called after every run."""
        return None

    # ------------------------------------------------------------------
    def __repr__(self) -> str:                                    # pragma: no cover
        return f"<{self.__class__.__name__} name={self.name!r}>"


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
class LLMProvider(BaseProvider):
    """
    Writes text. Used for (a) writing whole scripts from a topic, (b) polish
    image prompts, (c) YouTube title/description/tags.

    MUST IMPLEMENT
        chat(messages, **kw) -> str
            messages = [{"role": "system"|"user"|"assistant", "content": "..."}]
            json_mode=True means "please answer with pure JSON"
            Return the assistant's text. Raise RuntimeError on failure.
    """

    kind = "llm"

    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False,
             temperature: float | None = None, max_tokens: int | None = None) -> str:
        raise NotImplementedError

    # Most LLMs return either markdown-fenced JSON or prose+JSON. Both of the
    # helpers below are already in bot/utils, so providers just call them.
    @staticmethod
    def parse_json(text: str) -> Any:
        from ..utils import extract_json
        return extract_json(text)


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------
class TTSProvider(BaseProvider):
    """
    Turns text into speech.

    MUST IMPLEMENT
        synthesize(text, out_path, *, voice=None, rate=None, pitch=None,
                   target_duration=None) -> dict

    RETURN VALUE (a dict with at least "path"):
        {
          "path":  Path,                      # the audio file you wrote
          "words": [{"w": "hello", "s": 0.12, "e": 0.46}, ...] or None,
          "voice": "en-US-GuyNeural",
          "duration": 3.4,
        }

    WHY target_duration IS PASSED
        If your service can render EXACTLY N seconds of speech (VoiceStudio
        can), use it - your sync will be perfect. Providers that cannot simply
        ignore it and the timing stage time-stretches the audio afterwards.

    WORD TIMINGS
        If you can return word start/end times the subtitles become word-perfect
        sentence-grouped captions. If you cannot, return words=None and the bot
        falls back to distributing words evenly across the scene.
    """

    kind = "tts"

    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None,
                   rate: str | None = None, pitch: str | None = None,
                   target_duration: float | None = None) -> dict:
        raise NotImplementedError

    def list_voices(self) -> list[str]:
        """Human-readable list for  python main.py voices  . Optional."""
        return []

    # Helpers shared by the audio providers ------------------------------
    @staticmethod
    def write_words_json(path: Path, words: list[dict[str, Any]] | None) -> None:
        from ..utils import write_json
        if words:
            write_json(path, words)

    def default_voice(self) -> str:
        return str(self.setting(f"tts.{self.name}.voice", "") or "")


# ---------------------------------------------------------------------------
# IMAGE
# ---------------------------------------------------------------------------
class ImageProvider(BaseProvider):
    """
    Turns a text prompt into a picture.

    MUST IMPLEMENT
        generate(prompt, out_path, **kw) -> Path | None

    kw contains (all optional, all already resolved from config.yaml):
        width, height, negative_prompt, steps, cfg_scale, seed

    OPTIONAL BUT POWERFUL
        supports_batch = True   -> the pipeline calls generate_many(jobs)
        generate_many(jobs)     -> [path|None, ...]   (one per job, same order)
        supports_parallel = False -> never run two requests at once
                                     (free services rate-limit; be polite)
        api_name / endpoint plumbing is entirely up to you.

    A job dict looks like:
        {"scene_id": "s01", "prompt": "...", "out_path": Path,
         "width": 1920, "height": 1080, "negative_prompt": "...",
         "steps": 30, "cfg_scale": 7.0, "seed": None}
    """

    kind = "image"
    supports_batch: bool = False
    supports_parallel: bool = True

    def generate(self, prompt: str, out_path: Path, **kwargs: Any) -> Path | None:
        raise NotImplementedError

    def generate_many(self, jobs: list[dict[str, Any]]) -> list[Path | None]:
        return [self.generate(j["prompt"], j["out_path"], **{
            k: v for k, v in j.items()
            if k in ("width", "height", "negative_prompt", "steps", "cfg_scale", "seed")
        }) for j in jobs]

    # ---- shared helpers ------------------------------------------------
    def style_suffix(self) -> str:
        return str(self.setting("image.style_suffix", "") or "")

    def build_prompt(self, prompt: str) -> str:
        """Append the global style suffix, unless the caller already did."""
        suffix = self.style_suffix().strip()
        if suffix and suffix.lower() not in prompt.lower():
            return f"{prompt.strip().rstrip(',')}, {suffix}"
        return prompt

    def resolved_size(self, width: Any = None, height: Any = None) -> tuple[int, int]:
        if width and height:
            return to_int(width, 1024), to_int(height, 1024)
        w, h = self.cfg.resolution()
        return (to_int(self.setting("image.width", w), w),
                to_int(self.setting("image.height", h), h))

    def retries(self) -> int:
        return max(1, to_int(self.setting("image.batch_retries", 3), 3))

    def save_image_bytes(self, data: bytes, out_path: Path) -> Path:
        """Write bytes, or convert to JPEG if the caller asked for .jpg."""
        from ..imaging import save_image_atomic
        return save_image_atomic(data, Path(out_path))


# ---------------------------------------------------------------------------
# ASSEMBLY (ffmpeg / moviepy)
# ---------------------------------------------------------------------------
class AssemblyProvider(BaseProvider):
    """
    Everything that touches video or audio files.

    This is the biggest contract in the bot, but every method is a small,
    single-purpose ffmpeg call. Implement the ones you need; the pipeline
    tells you (loudly) if one is missing.

    probe_duration(path)                 -> float seconds
    make_silence(out, seconds)           -> Path      silent wav
    concat_audio(parts, out, exact_duration=None) -> Path
    fit_audio(src, out, target_seconds, *, max_speedup, max_slowdown,
              strategy)                  -> {"tempo","natural","final","method"}
    render_scene_clip(image, audio, out_path, duration, motion) -> Path
    concatenate(clips, out, *, transition, transition_duration, vary, enabled)
                                         -> (path, real_duration)
    build_mix(voice, music, out_path, duration) -> Path
    mux(video, audio, out, *, subtitles, sub_style, watermark, watermark_cfg) -> Path
    concat_videos(paths, out)            -> Path
    thumbnail(video, out, *, at_seconds, title) -> Path
    """

    kind = "assembly"

    # ---- probing -------------------------------------------------------
    def probe_duration(self, path: Path | str) -> float:
        raise NotImplementedError

    # ---- audio ---------------------------------------------------------
    def make_silence(self, out_path: Path, seconds: float) -> Path:
        raise NotImplementedError

    def concat_audio(self, parts: list[Path], out_path: Path,
                     *, exact_duration: float | None = None) -> Path:
        raise NotImplementedError

    def fit_audio(self, src: Path, out_path: Path, target_seconds: float, *,
                  max_speedup: float = 1.35, max_slowdown: float = 0.85,
                  strategy: str = "pad_then_hold") -> dict[str, Any]:
        raise NotImplementedError

    # ---- video ---------------------------------------------------------
    def render_scene_clip(self, *, image: Path, audio: Path | None, out_path: Path,
                          duration: float, motion: str = "zoom_in") -> Path:
        raise NotImplementedError

    def concatenate(self, clips: list[Path], out_path: Path, *,
                    transition: str = "crossfade", transition_duration: float = 0.45,
                    vary: bool = True, enabled: bool = True) -> tuple[Path, float]:
        raise NotImplementedError

    def build_mix(self, *, voice: Path, music: Path | None, out_path: Path,
                  duration: float) -> Path:
        raise NotImplementedError

    def mux(self, video: Path, audio: Path, out_path: Path, *,
            subtitles: Path | None = None, sub_style: dict | None = None,
            watermark: Path | None = None,
            watermark_cfg: dict | None = None) -> Path:
        raise NotImplementedError

    def concat_videos(self, paths: list[Path], out_path: Path) -> Path:
        raise NotImplementedError

    def thumbnail(self, video: Path, out_path: Path, *,
                  at_seconds: float = 3.0, title: str | None = None) -> Path:
        raise NotImplementedError

    # ---- shared helpers -------------------------------------------------
    def ffmpeg(self) -> str:
        """Path to the ffmpeg binary (config -> PATH -> bundled imageio copy)."""
        from ..utils import resolve_ffmpeg
        return resolve_ffmpeg(str(self.setting("system.ffmpeg_bin", "ffmpeg")), None)

    def ffprobe(self) -> str | None:
        import shutil
        configured = str(self.setting("system.ffprobe_bin", "ffprobe"))
        found = shutil.which(configured) or (configured if Path(configured).exists() else None)
        if found:
            return found
        bundled = Path(self.ffmpeg()).with_name("ffprobe" + (".exe" if os.name == "nt" else ""))
        if bundled.exists():
            return str(bundled)
        return None

    @staticmethod
    def run(cmd: list[str], **kw: Any):                    # pragma: no cover
        from ..utils import run_cmd
        return run_cmd(cmd, **kw)
