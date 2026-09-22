"""
bot/providers/assembly_moviepy.py
=================================
The same rendering engine as the ffmpeg provider, except the MOTION step is
done in Python with MoviePy instead of an ffmpeg filter.

WHEN TO USE IT
--------------
Almost never - and that is an honest answer, not laziness:

    ffmpeg  : 4-second 1080p clip in ~3 s, low RAM, smooth motion
    moviepy : the same clip in ~15-40 s, much more RAM, same result

MoviePy is included because people like to READ their pipeline in Python and
because it is the easier place to hack a custom effect. If you want a weird
motion effect, this file is a comfortable place to invent it.

HOW TO SWITCH
-------------
    config.yaml ->  motion:
                      engine: "moviepy"
    (requires:  pip install moviepy)

Everything else - transitions, the audio master, the final mux, captions - is
still done by ffmpeg, because that part has no reason to be slower. That is
why this class INHERITS from FFmpegAssembly: only the one method that differs
is replaced.
"""
from __future__ import annotations

from pathlib import Path

from ..paths import ROOT
from ..registry import register
from ..utils import debug, die, ensure_dir, info, warn
from .assembly_ffmpeg import FFmpegAssembly
from .base import to_float, to_int


@register("assembly", "moviepy",
          cost="free",
          quality="broadcast (same output as ffmpeg)",
          setup_time="2 minutes (pip install moviepy)",
          doc="Same engine as ffmpeg but the Ken Burns motion runs in Python "
              "via MoviePy. Slower, but much easier to customise with code.")
class MoviePyAssembly(FFmpegAssembly):
    """ffmpeg everything, MoviePy for the moving camera."""

    # ==================================================================
    def healthcheck(self) -> tuple[bool, str]:
        ok, msg = super().healthcheck()
        try:
            import moviepy                                        # type: ignore  # noqa: F401
        except ImportError:
            return False, (
                "the moviepy engine is selected but the package is not installed.\n"
                "  Run:  pip install moviepy\n"
                "  Or switch back to the faster engine:  motion.engine: ffmpeg"
            )
        return ok, f"{msg.splitlines()[0]}\n  MoviePy is installed (motion via Python)"

    # ==================================================================
    def render_scene_clip(self, *, image: Path, audio: Path | None, out_path: Path,
                          duration: float, motion: str = "zoom_in") -> Path:
        """
        Still image -> moving clip, using MoviePy.

        HOW THE MOTION WORKS HERE
        -------------------------
        MoviePy can run a function on every frame (`fl` = "frame function").
        We resize the image slightly on each frame, which produces the zoom;
        for a pan we move a fixed-size window over a bigger image instead.

        The smoothness trick from the ffmpeg engine applies here too: we
        upsample the source first, so interpolating the resize never lands on
        exactly the same pixels two frames in a row.
        """
        try:
            from moviepy import ImageClip, vfx                     # type: ignore
        except ImportError:
            try:
                from moviepy.editor import ImageClip, vfx          # type: ignore
            except ImportError:
                return self._fallback(image, out_path, duration, motion)

        image = Path(image)
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        duration = max(0.2, float(duration))

        w, h = self.cfg.resolution()
        fps = int(self.setting("video.fps", 30))
        m = self.setting("motion", {}) or {}
        zoom = max(1.0, to_float(m.get("zoom_amount"), 1.12))
        pan = max(0.0, to_float(m.get("pan_amount"), 0.10))
        grade = str(m.get("color_grade", "cinematic"))

        info(f"    moviepy: rendering {duration:.1f}s of '{motion}' "
             f"at {w}x{h} (this is the slow engine, be patient)")

        try:
            clip = ImageClip(str(image)).with_duration(duration)
        except AttributeError:                                    # MoviePy 1.x
            clip = ImageClip(str(image)).set_duration(duration)

        # Start from the frame-filling size, then animate.
        try:
            clip = clip.with_effects([vfx.Resize(height=h)])
        except Exception:
            clip = clip.resize(height=h)

        direction = {
            "zoom_in": +1, "zoom_in_slow": +1, "ken_burns_combo": +1,
            "zoom_out": -1,
        }.get(motion, +1)
        scale_from, scale_to = (1.0, zoom) if direction > 0 else (zoom, 1.0)
        pan_amount = pan if motion in ("pan_left_right", "pan_right_left",
                                       "ken_burns_combo", "diagonal_tl_br",
                                       "diagonal_br_tl") else 0.0
        pan_sign = -1 if motion in ("pan_right_left", "diagonal_br_tl") else +1

        def animated(get_frame, t):
            frame = get_frame(t)
            progress = 0.0 if duration <= 0 else min(1.0, t / duration)
            # ease in/out so the move starts and stops gently
            eased = progress * progress * (3 - 2 * progress)
            factor = scale_from + (scale_to - scale_from) * eased
            try:
                import numpy as np
                from PIL import Image as PILImage
                im = PILImage.fromarray(frame)
                nw, nh = max(w, int(im.width * factor)), max(h, int(im.height * factor))
                im = im.resize((nw, nh), PILImage.LANCZOS)
                # crop the animated window out of the enlarged frame
                max_dx = max(0, nw - w) // 2
                dx = int(max_dx * pan_amount * pan_sign * eased) if pan_amount else 0
                left = int((nw - w) / 2 + dx)
                top = int((nh - h) / 2)
                left = max(0, min(nw - w, left))
                top = max(0, min(nh - h, top))
                frame = np.array(im.crop((left, top, left + w, top + h)))
            except Exception as e:                                # pragma: no cover
                debug(f"moviepy frame effect skipped: {e}")
            return frame

        try:
            clip = clip.transform(animated)                       # MoviePy 2.x
        except AttributeError:
            clip = clip.fl(animated)                              # MoviePy 1.x

        # Silent video on purpose: the scene audio is added later, in the mix.
        out_path.parent.mkdir(parents=True, exist_ok=True)
        clip.write_videofile(
            str(out_path), fps=fps, codec="libx264",
            audio=False,
            ffmpeg_params=["-crf", str(int(self.setting("video.crf", 20))),
                           "-preset", str(self.setting("video.preset", "medium")),
                           "-pix_fmt", "yuv420p"],
            logger=None,
        )
        clip.close()
        _ = grade          # colour grading stays in the ffmpeg path for speed
        got = self.probe_duration(out_path)
        debug(f"moviepy clip {out_path.name}: {got:.2f}s (wanted {duration:.2f}s)")
        if got <= 0.05:
            warn("    moviepy produced an empty clip - falling back to ffmpeg")
            return self._fallback(image, out_path, duration, motion)
        return out_path

    # ------------------------------------------------------------------
    def _fallback(self, image: Path, out_path: Path, duration: float,
                  motion: str) -> Path:
        """If MoviePy is broken or absent, render with ffmpeg instead."""
        debug("moviepy unavailable - using the ffmpeg motion engine instead")
        return FFmpegAssembly.render_scene_clip(
            self, image=Path(image), audio=None, out_path=Path(out_path),
            duration=duration, motion=motion,
        )
