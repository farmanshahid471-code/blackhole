"""
bot/config.py
==============
Loads configuration from THREE layers and merges them:

    layer 1 : config.yaml          (the defaults you edit)
    layer 2 : <project>/project.json  (a per-video override, if any)
    layer 3 : command line flags   (--set image.provider=vast)

It also resolves anything ending in `_env` from your .env file, so secrets
never live inside config.yaml.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except Exception:                                                  # pragma: no cover
    def load_dotenv(*a, **k):                                      # type: ignore
        return False

from .paths import ROOT
from .utils import deep_merge, die, ensure_dir

ASPECTS = {
    "16x9": (1920, 1080),
    "9x16": (1080, 1920),
    "1x1": (1080, 1080),
    "4x5": (1080, 1350),
    "21x9": (2560, 1080),
}


class Config:
    """A dict-like object with dot access:  cfg.get('image.provider')"""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    # ------------------------------------------------------------------
    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self._data
        for p in parts[:-1]:
            node = node.setdefault(p, {})
            if not isinstance(node, dict):
                raise KeyError(f"Cannot set {dotted}: {p} is not a section")
        node[parts[-1]] = value

    def section(self, dotted: str) -> dict:
        val = self.get(dotted, {})
        return val if isinstance(val, dict) else {}

    def env(self, key_dotted: str, fallback: Any = None) -> Any:
        """
        cfg.env('llm.deepseek.api_key_env')
          -> reads the NAME stored there (e.g. 'DEEPSEEK_API_KEY')
          -> returns os.environ['DEEPSEEK_API_KEY']
        """
        var = self.get(key_dotted)
        if not var:
            return fallback
        val = os.environ.get(str(var), "").strip()
        return val or fallback

    @property
    def data(self) -> dict:
        return self._data

    # ------------------------------------------------------------------
    def resolution(self) -> tuple[int, int]:
        w = self.get("video.width")
        h = self.get("video.height")
        if w and h:
            return int(w), int(h)
        aspect = str(self.get("video.aspect", "16x9")).lower().replace(":", "x")
        if aspect not in ASPECTS:
            die(f"Unknown video.aspect '{aspect}'. Choose one of: {', '.join(ASPECTS)}")
        return ASPECTS[aspect]

    def is_vertical(self) -> bool:
        w, h = self.resolution()
        return h > w

    def as_dict(self) -> dict:
        return self._data


# ---------------------------------------------------------------------------
def _coerce(value: str) -> Any:
    """Turn a command-line string into the right Python type."""
    v = value.strip()
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~", ""):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
    return v.strip("'\"")


def load_config(
    project_overrides: dict | None = None,
    cli_overrides: list[str] | None = None,
    config_path: Path | None = None,
) -> Config:
    """
    Build the final configuration.

    cli_overrides look like:  ["image.provider=vast", "video.fps=60"]
    """
    load_dotenv(ROOT / ".env")                 # secrets
    load_dotenv()                              # also respect a real environment

    cfg_path = Path(config_path) if config_path else ROOT / "config.yaml"
    if not cfg_path.exists():
        die(f"config.yaml not found at {cfg_path}. Did you delete it?")

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            base = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        die(
            "config.yaml has a YAML syntax error.\n"
            "Common causes: a TAB character instead of spaces, or a missing colon.\n\n"
            f"Details: {e}"
        )

    data = deep_merge(base, project_overrides or {})

    for item in cli_overrides or []:
        if "=" not in item:
            die(f"--set expects key=value, got: {item}")
        key, _, val = item.partition("=")
        # walk into data creating dicts as needed
        node = data
        parts = key.strip().split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = _coerce(val)

    cfg = Config(data)

    # make sure working folders exist
    ensure_dir(ROOT / cfg.get("system.projects_dir", "workspace/projects"))
    ensure_dir(ROOT / cfg.get("system.temp_dir", "workspace/tmp"))

    # propagate debug flag
    if str(cfg.get("system.log_level", "INFO")).upper() == "DEBUG":
        os.environ["AVB_DEBUG"] = "1"

    return cfg


def save_project_config(project_dir: Path, cfg: Config, extra: dict | None = None) -> None:
    """Snapshot the config used for this video so it can be reproduced later."""
    import json
    payload = {"config": cfg.data, **(extra or {})}
    with open(Path(project_dir) / "project.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
