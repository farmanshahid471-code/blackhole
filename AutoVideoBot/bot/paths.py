"""
bot/paths.py
=============
One single place that knows where every file lives.

WHY THIS FILE EXISTS
--------------------
Beginners get lost because file paths are scattered all over the code.
Here, every folder in a project is defined ONCE. If you want to move
things around, you change it here and nowhere else.
"""
from __future__ import annotations

from pathlib import Path

from .utils import ensure_dir, slugify

# The folder that contains main.py, config.yaml, bot/ ...
ROOT = Path(__file__).resolve().parent.parent


class Project:
    """
    Represents one video project on disk:

        workspace/projects/black-holes-explained/
            project.json      <- settings snapshot for this video
            manifest.json     <- what has already been generated (for resume)
            input.txt         <- YOUR script with timestamps (manual mode)
            script.json       <- the canonical scene list the bot works from
            audio/            <- one file per scene + the joined voice track
            images/           <- one image per scene
            clips/            <- one rendered .mp4 per scene (image + motion)
            subs/             <- .srt / .ass subtitle files
            output/           <- THE FINAL VIDEO + thumbnail + metadata
            logs/
    """

    def __init__(self, root: Path, slug: str):
        self.root = Path(root)
        self.slug = slug
        self.dir = self.root / slug

        # --- folders ---
        self.audio_dir = self.dir / "audio"
        self.words_dir = self.audio_dir / "words"
        self.images_dir = self.dir / "images"
        self.clips_dir = self.dir / "clips"
        self.trans_dir = self.dir / "trans"
        self.subs_dir = self.dir / "subs"
        self.output_dir = self.dir / "output"
        self.logs_dir = self.dir / "logs"
        self.tmp_dir = self.dir / "tmp"

        # --- important files ---
        self.project_file = self.dir / "project.json"
        self.manifest_file = self.dir / "manifest.json"
        self.script_file = self.dir / "script.json"
        self.input_file = self.dir / "input.txt"
        self.topic_file = self.dir / "topic.txt"
        self.voice_track = self.dir / "voice_full.wav"
        self.music_track = self.dir / "music_full.wav"
        self.mix_track = self.dir / "mix.wav"
        self.silent_video = self.dir / "video_silent.mp4"
        self.final_video = self.output_dir / "final.mp4"
        self.srt_file = self.subs_dir / "captions.srt"
        self.ass_file = self.subs_dir / "captions.ass"
        self.thumbnail = self.output_dir / "thumbnail.jpg"
        self.metadata_file = self.output_dir / "youtube_metadata.json"
        self.log_file = self.logs_dir / "run.log"

    # ------------------------------------------------------------------
    def create(self) -> "Project":
        for d in (self.dir, self.audio_dir, self.words_dir, self.images_dir,
                  self.clips_dir, self.trans_dir, self.subs_dir, self.output_dir,
                  self.logs_dir, self.tmp_dir):
            ensure_dir(d)
        return self

    # ------------------------------------------------------------------
    def scene_audio(self, scene_id: str, ext: str = "wav") -> Path:
        return self.audio_dir / f"{scene_id}.{ext}"

    def scene_words(self, scene_id: str) -> Path:
        return self.words_dir / f"{scene_id}.json"

    def scene_image(self, scene_id: str, ext: str = "png") -> Path:
        return self.images_dir / f"{scene_id}.{ext}"

    def scene_clip(self, scene_id: str) -> Path:
        return self.clips_dir / f"{scene_id}.mp4"

    def trans_clip(self, scene_id: str) -> Path:
        return self.trans_dir / f"{scene_id}.mp4"

    # ------------------------------------------------------------------
    @classmethod
    def from_name(cls, projects_root: Path | str, name: str) -> "Project":
        return cls(Path(projects_root), slugify(name))

    def exists(self) -> bool:
        return self.dir.exists()

    def __repr__(self) -> str:                                    # pragma: no cover
        return f"<Project {self.slug}>"


def default_projects_dir() -> Path:
    return ensure_dir(ROOT / "workspace" / "projects")


def default_assets_dir() -> Path:
    d = ensure_dir(ROOT / "assets")
    ensure_dir(d / "background_music")
    ensure_dir(d / "fonts")
    return d
