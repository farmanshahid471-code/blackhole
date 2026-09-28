"""The single, versioned contract shared by the director and the Remotion renderer."""
from __future__ import annotations

import json
import math
from pathlib import Path

LIBRARY_PATH = Path(__file__).resolve().parent.parent / "render" / "shots.json"
SHOTS = json.loads(LIBRARY_PATH.read_text(encoding="utf-8"))
AUTO_ORDER = ("accretion_disk_orbit", "core_cross_section_diagram",
              "event_horizon_flythrough", "mass_scale_compare",
              "starfield_warp", "two_perspectives_split", "spaghettification")


def _overlay_error(overlay: object) -> str | None:
    if (not isinstance(overlay, dict)
            or not isinstance(overlay.get("text"), str)
            or len(overlay["text"]) > 160
            or overlay.get("style", "title_card") not in ("title_card", "lower_third")):
        return "invalid text overlay"
    t = overlay.get("t", 0)
    if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
        return "overlay t must be a positive time in seconds"
    return None


def sanitize_generated_overlays(scenes: list[dict]) -> list[str]:
    """Discard only malformed OPTIONAL LLM overlay decorations, with warnings.

    This is never used for a user-supplied script: those must still validate
    strictly. Narration, shot names/parameters, and scene timing are untouched.
    """
    issues: list[str] = []
    for i, scene in enumerate(scenes, 1):
        overlays = scene.get("text_overlays") or []
        if not isinstance(overlays, list):
            scene["text_overlays"] = []
            issues.append(f"scene {i}: omitted malformed optional text_overlays array")
            continue
        cleaned = []
        for j, overlay in enumerate(overlays, 1):
            problem = _overlay_error(overlay)
            if problem:
                issues.append(f"scene {i}: omitted optional text overlay {j} ({problem})")
            else:
                cleaned.append(overlay)
        scene["text_overlays"] = cleaned
    return issues


def validate_scene(scene: dict, index: int, *, auto_assign: bool = False) -> None:
    """Never silently map an invented LLM shot or parameter onto an unrelated visual."""
    name = scene.get("shot")
    if not name and auto_assign:
        name = AUTO_ORDER[index % len(AUTO_ORDER)]
    if not isinstance(name, str) or name not in SHOTS:
        raise ValueError(f"scene {index + 1}: unknown shot {name!r}; choose from {', '.join(SHOTS)}")
    specs = SHOTS[name]["params"]
    params = scene.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError(f"scene {index + 1}: params must be an object")
    unknown = set(params) - set(specs)
    if unknown:
        raise ValueError(f"scene {index + 1}: {name} has unknown params: {sorted(unknown)}")
    cleaned = {}
    for key, spec in specs.items():
        value = params.get(key, spec["default"])
        if spec["type"] == "number":
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not spec["min"] <= value <= spec["max"]:
                raise ValueError(f"scene {index + 1}: {key} must be between {spec['min']} and {spec['max']}")
        elif value not in spec["values"]:
            raise ValueError(f"scene {index + 1}: {key} must be one of {spec['values']}")
        cleaned[key] = value
    overlays = scene.get("text_overlays") or []
    if not isinstance(overlays, list):
        raise ValueError(f"scene {index + 1}: text_overlays must be an array")
    for overlay in overlays:
        problem = _overlay_error(overlay)
        if problem:
            raise ValueError(f"scene {index + 1}: {problem}")
    cues = scene.get("sfx")
    if cues is not None:
        if not isinstance(cues, list) or len(cues) > 8:
            raise ValueError(f"scene {index + 1}: sfx must be an array of at most 8 cues")
        for cue in cues:
            if not isinstance(cue, dict) or cue.get("kind") not in ("whoosh", "rumble"):
                raise ValueError(f"scene {index + 1}: SFX kind must be whoosh or rumble")
            t = cue.get("t")
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
                raise ValueError(f"scene {index + 1}: SFX t must be a nonnegative time")
    scene["shot"] = name
    scene["params"] = cleaned
    scene["text_overlays"] = overlays


class ShotVarietyError(ValueError):
    """Editorial shot repetition, not an invalid visual or unsafe parameter."""


def validate_sequence(scenes: list[dict], *, strict_variety: bool = True) -> list[str]:
    """Validate every shot; optionally report (rather than reject) repetition.

    Unknown shots and bad parameters always fail. After bounded LLM repair,
    repeated *valid* visuals may be kept as an explicitly warned draft rather
    than charging indefinitely for retries or blocking a safe test render.
    """
    previous = None
    issues: list[str] = []
    for i, scene in enumerate(scenes):
        validate_scene(scene, i)
        shot = scene["shot"]
        issue = None
        if previous and shot == previous:
            issue = f"scene {i + 1}: {shot} repeats the previous shot"
        elif previous and SHOTS[shot]["family"] == SHOTS[previous]["family"] and SHOTS[shot]["family"] != "card":
            issue = f"scene {i + 1}: consecutive {SHOTS[shot]['family']} shots; alternate wide, close and diagram"
        if issue:
            if strict_variety:
                raise ShotVarietyError(issue)
            issues.append(issue)
        previous = shot
    return issues
