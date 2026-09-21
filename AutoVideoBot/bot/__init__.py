"""
bot/__init__.py
================
AutoVideoBot core package.

Import this and you get:
    from bot import Config, load_config, Project, get_provider
"""
from __future__ import annotations

__version__ = "1.0.0"
__all__ = [
    "Config", "load_config", "Project", "Script", "Manifest",
    "get_provider", "list_providers", "registry",
]

from .config import Config, load_config
from .paths import Project, ROOT
from .registry import get_provider_class, list_providers, resolve
from .state import Manifest, Scene, Script


def get_provider(kind: str, name: str, cfg: Config, project: Project | None = None):
    """
    The one function the pipeline uses to obtain a tool.

        images = get_provider("image", cfg.get("image.provider"), cfg, project)
        images.generate(prompt, path)

    Swap the name and you get a completely different service.
    """
    cls = get_provider_class(kind, name)
    return cls(cfg, project)
