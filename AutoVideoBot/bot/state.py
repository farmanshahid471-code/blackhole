"""
bot/state.py
=============
The project "brain": the scene list + the manifest.

WHAT IS A MANIFEST?
-------------------
A manifest is a little JSON file that remembers what the bot has ALREADY done.

    "scene s03 image, provider=pollinations, hash=ab12cd34" -> DONE

Next time you run the bot it checks the manifest first. If the inputs are
identical it skips that step. That means:

  * A crash at scene 40 of 50 does not make you re-render 39 scenes.
  * Changing only the music does not re-generate any images.
  * You can run `main.py run` ten times and only the missing parts get built.

To force a rebuild, delete manifest.json or pass --force.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .utils import ensure_dir, read_json, stable_hash, write_json

STAGES = [
    "script",       # scene list produced (by LLM or parsed from your file)
    "voice",        # TTS audio generated per scene
    "timing",       # durations measured / audio fitted to timestamps
    "images",       # stills generated per scene
    "motion",       # each still turned into a moving clip
    "transition",   # clips crossfaded together into one silent video
    "subtitles",    # .srt / .ass written
    "mix",          # voice + music + mastering
    "assembly",     # final muxed mp4
    "extras",       # thumbnail + youtube metadata
]


class Scene(dict):
    """
    A dict with attribute access, because scene['narration'] reads better
    than scene.get('narration') all over the codebase.

    A scene always has:
        id            's01'
        index         0
        narration     the words that get spoken
        image_prompt  what the picture should show
        duration      seconds this scene occupies in the final video
        start         seconds from video start (filled in by the timing stage)
        end           start + duration
        target_start  what YOUR timestamp said (None in auto mode)
        target_end    what YOUR timestamp said (None in auto mode)
        motion        which Ken Burns preset to use
        raw_natural   the length of the TTS audio before any stretching
        tempo         the speed factor applied to the audio (1.0 = untouched)
    """

    __getattr__ = dict.get          # scene.narration works

    def __setattr__(self, key: str, value: Any) -> None:   # noqa: D105
        self[key] = value

    @property
    def sid(self) -> str:
        return str(self.get("id", "s00"))


class Manifest:
    """Tracks completion per stage and per artefact, with content hashes."""

    def __init__(self, project_dir: Path):
        self.path = Path(project_dir) / "manifest.json"
        self.data: dict[str, Any] = read_json(self.path, default=None) or {
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stages": {},
            "artifacts": {},
            "runs": [],
        }
        self.data.setdefault("stages", {})
        self.data.setdefault("artifacts", {})
        self.data.setdefault("runs", [])

    # ------------------------------------------------------------------
    def save(self) -> None:
        ensure_dir(self.path.parent)
        write_json(self.path, self.data)

    # --- artefacts ----------------------------------------------------
    def artifact_key(self, kind: str, ident: str, params: Any) -> str:
        return f"{kind}:{ident}:{stable_hash(params)}"

    def is_done(self, key: str) -> bool:
        entry = self.data["artifacts"].get(key)
        if not entry:
            return False
        p = Path(entry.get("path", ""))
        # if the file vanished, we must redo it
        return bool(entry.get("done")) and (not entry.get("path") or p.exists())

    def mark(self, key: str, path: Path | str = "", extra: dict | None = None) -> None:
        self.data["artifacts"][key] = {
            "done": True,
            "path": str(path),
            "at": time.strftime("%H:%M:%S"),
            **(extra or {}),
        }
        self.save()

    # --- stages -------------------------------------------------------
    def stage_done(self, stage: str) -> bool:
        return bool(self.data["stages"].get(stage, {}).get("done"))

    def start_stage(self, stage: str) -> None:
        self.data["stages"][stage] = {
            "done": False,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.save()

    def finish_stage(self, stage: str, info: dict | None = None) -> None:
        cur = self.data["stages"].get(stage, {})
        cur.update({"done": True, "finished": time.strftime("%Y-%m-%d %H:%M:%S")})
        if info:
            cur["info"] = info
        self.data["stages"][stage] = cur
        self.save()

    # --- runs ---------------------------------------------------------
    def log_run(self, command: str, seconds: float, ok: bool = True) -> None:
        self.data["runs"].append({
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "command": command,
            "seconds": round(seconds, 1),
            "ok": ok,
        })
        self.data["runs"] = self.data["runs"][-40:]
        self.save()

    def reset(self, stage: str | None = None) -> None:
        if stage:
            self.data["stages"].pop(stage, None)
            self.data["artifacts"] = {
                k: v for k, v in self.data["artifacts"].items() if not k.startswith(f"{stage}:")
            }
        else:
            self.data["stages"] = {}
            self.data["artifacts"] = {}
        self.save()

    def summary(self) -> dict:
        return {s: self.stage_done(s) for s in STAGES}


# ---------------------------------------------------------------------------
class Script:
    """The canonical list of scenes for one project, saved as script.json."""

    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.path = self.project_dir / "script.json"
        self.data: dict[str, Any] = {
            "title": "Untitled",
            "description": "",
            "tags": [],
            "language": "English",
            "source": "unknown",          # 'llm' | 'file' | 'manual'
            "total_duration": 0.0,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "scenes": [],
        }

    # ------------------------------------------------------------------
    def load(self) -> bool:
        existing = read_json(self.path)
        if existing:
            self.data = existing
            return True
        return False

    def save(self) -> None:
        """
        Write script.json.

        SAFETY NET: a code path that forgot to load the script first would
        otherwise overwrite a perfectly good scene list with an empty one.
        That is data loss, so we refuse silently-dangerous writes: an empty
        scene list can never clobber a file that already has scenes.
        """
        ensure_dir(self.project_dir)
        if not self.data.get("scenes"):
            existing = read_json(self.path)
            if existing and existing.get("scenes"):
                import warnings
                warnings.warn(
                    "Refused to overwrite script.json (which has "
                    f"{len(existing['scenes'])} scenes) with an empty scene list. "
                    "A stage tried to save without loading the script first."
                )
                return
        write_json(self.path, self.data)

    # ------------------------------------------------------------------
    @property
    def scenes(self) -> list[Scene]:
        return [Scene(s) for s in self.data.get("scenes", [])]

    @scenes.setter
    def scenes(self, value: list[dict]) -> None:
        self.data["scenes"] = [dict(s) for s in value]
        self.recalc()

    def recalc(self) -> None:
        start = 0.0
        for s in self.data.get("scenes", []):
            s["start"] = round(start, 3)
            s["end"] = round(start + float(s.get("duration") or 0.0), 3)
            start = s["end"]
        self.data["total_duration"] = round(start, 3)

    def __len__(self) -> int:
        return len(self.data.get("scenes", []))

    def chapters(self) -> list[dict]:
        """YouTube chapter list derived from scene starts."""
        return [
            {"start": s.get("start", 0), "title": (s.get("title") or f"Scene {i+1}")[:80]}
            for i, s in enumerate(self.data.get("scenes", []))
        ]
