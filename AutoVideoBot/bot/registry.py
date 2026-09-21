"""
bot/registry.py
================
The PROVIDER REGISTRY. This tiny file is what makes the bot modular.

HOW IT WORKS (plain English)
----------------------------
Every tool that can do a job (generate an image, speak a line, write a script)
is called a "provider". Each provider file announces itself like this:

    @register("image", "pollinations")
    class PollinationsProvider(ImageProvider):
        ...

That single decorator writes a note in a dictionary:

    _REGISTRY["image"]["pollinations"] = PollinationsProvider

Then config.yaml says  image.provider: "pollinations"  and the bot does:

    cls = get_provider_class("image", "pollinations")
    provider = cls(config, project)

TO ADD A NEW TOOL YOU NEVER EDIT THE CORE. You:
    1. create  bot/providers/image_mynewtool.py
    2. decorate the class with @register("image", "mynewtool")
    3. import it in bot/providers/__init__.py
    4. write  image.provider: "mynewtool"  in config.yaml
That is the whole procedure.
"""
from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Callable

_REGISTRY: dict[str, dict[str, Any]] = {
    "llm": {},
    "tts": {},
    "image": {},
    "assembly": {},
}

_ALIASES: dict[str, dict[str, str]] = {
    # friendly names people type -> the real registered name
    "llm": {
        "deepseek": "deepseek", "deepseek-api": "deepseek", "ds": "deepseek",
        "openai": "openai_compat", "openai-compat": "openai_compat",
        "groq": "openai_compat", "openrouter": "openai_compat",
        "together": "openai_compat", "lmstudio": "openai_compat",
        "ollama": "ollama", "local": "ollama",
        "manual": "manual", "none": "manual", "file": "manual",
    },
    "tts": {
        "edge": "edge", "edge-tts": "edge", "microsoft": "edge", "free": "edge",
        "voicestudio": "voicestudio", "voice-studio": "voicestudio",
        "omnivoice": "voicestudio",
        "elevenlabs": "elevenlabs", "eleven": "elevenlabs",
        "openai": "openai_tts", "openai-tts": "openai_tts", "gpt4o": "openai_tts",
        "piper": "piper", "espeak": "espeak",
    },
    "image": {
        "pollinations": "pollinations", "free": "pollinations", "web": "pollinations",
        "sdwebui": "sdwebui", "a1111": "sdwebui", "automatic1111": "sdwebui",
        "forge": "sdwebui", "sd": "sdwebui", "stablediffusion": "sdwebui",
        "vast": "vast", "vastai": "vast", "vast.ai": "vast", "gpu": "vast",
        "colab": "colab", "googlecolab": "colab", "google-colab": "colab",
        "kaggle": "kaggle",
        "gradio": "gradio", "space": "gradio", "huggingface": "gradio",
        "replicate": "replicate", "flux": "replicate",
        "local": "sdwebui",
    },
    "assembly": {
        "ffmpeg": "ffmpeg", "ff": "ffmpeg", "moviepy": "moviepy", "mp": "moviepy",
    },
}


def register(kind: str, name: str, **meta: Any) -> Callable:
    """Class decorator: @register('image', 'pollinations', needs_gpu=False)"""
    if kind not in _REGISTRY:
        _REGISTRY[kind] = {}

    def deco(cls):
        cls.provider_name = name
        cls.provider_kind = kind
        cls.provider_meta = meta
        _REGISTRY[kind][name] = cls
        return cls

    return deco


def _autoload() -> None:
    """Import every module inside bot/providers/ so their decorators run."""
    try:
        from . import providers as pkg
    except Exception as e:                                   # pragma: no cover
        raise RuntimeError(f"Could not import bot.providers package: {e}") from e

    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{pkg.__name__}.{mod.name}")
        except Exception as e:                               # pragma: no cover
            # A broken optional provider must never take the whole bot down.
            import os
            if os.environ.get("AVB_DEBUG") == "1":
                print(f"[registry] skipped provider module {mod.name}: {e}")


def resolve(kind: str, name: str) -> str:
    """Normalise whatever the user typed into a registered provider name."""
    key = str(name or "").strip().lower()
    table = _ALIASES.get(kind, {})
    if key in table:
        return table[key]
    if key in _REGISTRY.get(kind, {}):
        return key
    # fuzzy: allow "Vast" / "VAST" / "vast-ai"
    cleaned = key.replace("_", "").replace("-", "").replace(".", "").replace(" ", "")
    for real in _REGISTRY.get(kind, {}):
        if real.replace("_", "") == cleaned:
            return real
    for alias, real in table.items():
        if alias.replace("_", "").replace("-", "") == cleaned:
            return real
    raise KeyError(
        f"Unknown {kind} provider: '{name}'.\n"
        f"Available: {', '.join(sorted(_REGISTRY.get(kind, {})))}"
    )


def get_provider_class(kind: str, name: str) -> type:
    _autoload()
    real = resolve(kind, name)
    table = _REGISTRY.get(kind, {})
    if real not in table:
        raise KeyError(
            f"{kind} provider '{real}' is registered as an alias but its module "
            f"failed to import. Available: {', '.join(sorted(table)) or '(none)'}"
        )
    return table[real]


def list_providers(kind: str | None = None) -> dict[str, list[dict]]:
    _autoload()
    kinds = [kind] if kind else list(_REGISTRY)
    out: dict[str, list[dict]] = {}
    for k in kinds:
        out[k] = [
            {
                "name": n,
                "class": c.__name__,
                "doc": (c.__doc__ or "").strip().splitlines()[0] if c.__doc__ else "",
                **{kk: vv for kk, vv in (c.provider_meta or {}).items()},
            }
            for n, c in sorted(_REGISTRY.get(k, {}).items())
        ]
    return out
