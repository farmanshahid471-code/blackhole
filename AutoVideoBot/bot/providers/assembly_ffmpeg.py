"""
bot/providers/assembly_ffmpeg.py
================================
The rendering engine. Everything that touches a video or audio file happens
here, using ffmpeg from the command line.

WHY THE COMMAND LINE INSTEAD OF A PYTHON LIBRARY
------------------------------------------------
  * it is 5-20x faster than MoviePy for the same work
  * it does not need 4 GB of RAM to hold a video in memory
  * the exact command is printed (set system.log_level: DEBUG) so when
    something looks wrong you can paste it into a terminal and experiment
  * it is the same tool that every professional pipeline on earth uses

THE EIGHT JOBS THIS FILE DOES
-----------------------------
  1. probe_duration()      how long is this file?        (ffprobe, or ffmpeg -i)
  2. make_silence()        a wav of pure silence
  3. concat_audio()        glue per-scene audio into one narration track
  4. fit_audio()           stretch speech to fit a timestamp window
  5. render_scene_clip()   still image + Ken Burns motion -> an .mp4 clip
  6. concatenate()         crossfade all clips into the silent film
  7. build_mix()           narration + ducked music -> the mastered soundtrack
  8. mux()                 picture + sound + burned captions + watermark

THE FILTERGRAPH IDEA (the one thing worth understanding)
--------------------------------------------------------
ffmpeg reads `-i input` files and pushes them through filters written as a
string. Filters are separated by commas and they run left to right:

    -vf "scale=1920:-1,crop=1920:1080,eq=contrast=1.06"

When you need TWO inputs to meet (e.g. picture + sound), you cannot use -vf;
you use -filter_complex and name your streams with labels in square brackets:

    -filter_complex "[0:v]scale=1920:1080[v];[1:a]volume=-19dB[a];[v][a]..."
                    ^ input 0 video                 ^ labelled outputs

That naming is the only genuinely tricky part of ffmpeg, and every function
below follows the same pattern: build a graph string, then run one command.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from ..filters import (
    ass_style_from_cfg,
    atempo_chain,
    auto_supersample,
    build_mix_graph,
    build_scene_filter,
    build_xfade_graph,
    escape_filter_path,
    voice_chain,
)
from ..paths import ROOT
from ..registry import register
from ..utils import (
    debug,
    die,
    ensure_dir,
    human_bytes,
    info,
    resolve_ffmpeg,
    resolve_ffprobe,
    run_cmd,
    warn,
)
from .base import AssemblyProvider, to_float, to_int


@register("assembly", "ffmpeg",
          cost="free",
          quality="broadcast",
          setup_time="0 minutes (ffmpeg is bundled by the installer)",
          doc="The default and fastest engine. Ken Burns motion, crossfades, "
              "voice mastering, music ducking, caption burn-in - all in ffmpeg.")
class FFmpegAssembly(AssemblyProvider):
    """All video/audio operations, executed by the ffmpeg binary."""

    # ==================================================================
    # BINARY HANDLING
    # ==================================================================
    @property
    def ffmpeg_bin(self) -> str:
        if not hasattr(self, "_ffmpeg_cache"):
            self._ffmpeg_cache = resolve_ffmpeg(
                str(self.setting("system.ffmpeg_bin", "ffmpeg")), "ffmpeg")
        return self._ffmpeg_cache

    @property
    def ffprobe_bin(self) -> str | None:
        if not hasattr(self, "_ffprobe_cache"):
            self._ffprobe_cache = resolve_ffprobe(
                str(self.setting("system.ffprobe_bin", "ffprobe")))
        return self._ffprobe_cache

    def _threads(self) -> list[str]:
        n = int(self.setting("system.encode_threads", 0) or 0)
        return ["-threads", str(n)] if n > 0 else []

    # ==================================================================
    # HEALTHCHECK
    # ==================================================================
    def healthcheck(self) -> tuple[bool, str]:
        try:
            proc = run_cmd([self.ffmpeg_bin, "-version"], capture=True, check=False, timeout=30)
        except Exception as e:
            return False, (
                f"ffmpeg could not be started ({e}).\n"
                "  Windows: run  scripts/install_windows.bat  (it installs ffmpeg for you)\n"
                "  macOS  : brew install ffmpeg\n"
                "  Linux  : sudo apt install ffmpeg\n"
                "  Or: pip install imageio-ffmpeg  (downloads a private copy)"
            )
        if proc.returncode != 0:
            return False, f"ffmpeg is present but not working: {(proc.stderr or '')[:200]}"

        version = (proc.stdout or "").splitlines()[0] if proc.stdout else "ffmpeg"
        # Check the filters we actually depend on - a stripped-down build
        # (some Docker images) silently lacks xfade or loudnorm.
        need = ["xfade", "zoompan", "loudnorm", "sidechaincompress", "atempo",
                "vignette", "alimiter", "eq", "ass", "noise"]
        try:
            fl = run_cmd([self.ffmpeg_bin, "-hide_banner", "-filters"],
                         capture=True, check=False, timeout=60)
            have = (fl.stdout or "") + (fl.stderr or "")
        except Exception:
            have = ""
        missing = [f for f in need if f not in have]
        probe = "ffprobe found" if self.ffprobe_bin else "no ffprobe (using ffmpeg -i instead)"

        if missing:
            return False, (f"{version}\n  MISSING FILTERS: {', '.join(missing)}\n"
                           f"  Your ffmpeg build is too old or stripped down.\n"
                           f"  Fix:  pip install -U imageio-ffmpeg   (bundles a complete build)")
        w, h = self.cfg.resolution()
        return True, (f"{version}\n  all required filters present; {probe}; "
                      f"output {w}x{h}@{self.setting('video.fps', 30)}fps")

    # ==================================================================
    # 1. PROBE
    # ==================================================================
    def probe_duration(self, path: Path | str) -> float:
        """
        Length of any media file, in seconds.

        Uses ffprobe when it exists. Many machines (including every Windows
        install that used `pip install imageio-ffmpeg`) have ONLY ffmpeg, so
        there is a fallback that reads the same information out of
        `ffmpeg -i file`'s banner text. Both paths return the same number.
        """
        path = str(path)
        if not Path(path).exists():
            return 0.0

        probe = self.ffprobe_bin
        if probe:
            try:
                proc = run_cmd(
                    [probe, "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", path],
                    capture=True, check=False, timeout=120, quiet=True,
                )
                val = (proc.stdout or "").strip().splitlines()
                if val:
                    dur = to_float(val[-1].strip(), 0.0)
                    if dur > 0:
                        return dur
            except Exception as e:
                debug(f"ffprobe failed ({e}) - falling back to `ffmpeg -i`")

        # ---- fallback: parse ffmpeg's own report --------------------------
        try:
            proc = run_cmd([self.ffmpeg_bin, "-hide_banner", "-i", path],
                           capture=True, check=False, timeout=120, quiet=True)
        except Exception:
            return 0.0
        text = (proc.stderr or "") + (proc.stdout or "")

        # Duration: 00:00:47.07, start: ...
        m = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", text)
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mi * 60 + s
        # Very short files report a bare 'time=00:00:01.20' at the end
        m = re.search(r"time=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", text)
        if m:
            h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
            return h * 3600 + mi * 60 + s
        return 0.0

    def probe_info(self, path: Path | str) -> dict[str, Any]:
        """Resolution / codec / fps, for the `inspect` command and the web UI."""
        path = str(path)
        out: dict[str, Any] = {"path": path, "exists": Path(path).exists()}
        if not out["exists"]:
            return out
        out["duration"] = round(self.probe_duration(path), 3)
        out["bytes"] = Path(path).stat().st_size
        try:
            proc = run_cmd([self.ffmpeg_bin, "-hide_banner", "-i", path],
                           capture=True, check=False, timeout=120, quiet=True)
            text = proc.stderr or ""
            v = re.search(r"Video:\s*([^,\s]+).*?(\d{2,5})x(\d{2,5})", text)
            if v:
                out["video_codec"] = v.group(1)
                out["width"] = int(v.group(2))
                out["height"] = int(v.group(3))
            a = re.search(r"Audio:\s*([^,\s]+).*?(\d{4,6})\s*Hz", text)
            if a:
                out["audio_codec"] = a.group(1)
                out["sample_rate"] = int(a.group(2))
            f = re.search(r"(\d+(?:\.\d+)?)\s*fps", text)
            if f:
                out["fps"] = float(f.group(1))
        except Exception:
            pass
        return out

    # ==================================================================
    # 2. SILENCE
    # ==================================================================
    def make_silence(self, out_path: Path, seconds: float) -> Path:
        """A mono 48 kHz WAV of pure silence - the glue between scenes."""
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        seconds = max(0.01, float(seconds))
        run_cmd([
            self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=mono",
            "-t", f"{seconds:.4f}", "-c:a", "pcm_s16le", str(out_path),
        ], capture=True, check=True, timeout=300, quiet=True)
        return out_path

    # ==================================================================
    # 3. CONCAT AUDIO
    # ==================================================================
    def concat_audio(self, parts: list[Path], out_path: Path, *,
                     exact_duration: float | None = None) -> Path:
        """
        Join audio files end to end.

        Two strategies, because the obvious one has a trap:

          * the concat DEMUXER is instant and lossless, but it can only output
            the length that the pieces add up to. If a scene's audio is 20 ms
            longer than its timestamp window, every later scene drifts.
          * the concat FILTER is slower (it decodes everything) but can be
            pinned to an exact length with `-t`.

        The pipeline passes exact_duration for scene blocks precisely to stop
        that drift, so when it is given we use the filter - and the result is
        `apad`ded first so it can never be too SHORT either.
        """
        parts = [Path(p) for p in parts if Path(p).exists()]
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        if not parts:
            return self.make_silence(out_path, exact_duration or 0.5)

        if len(parts) == 1 and exact_duration is None:
            shutil.copy2(parts[0], out_path)
            return out_path

        if exact_duration is None:
            # ---- fast path: the concat demuxer ---------------------------
            listfile = out_path.parent / f"{out_path.stem}_concat.txt"
            lines = []
            for p in parts:
                safe = str(p.resolve()).replace("'", "'\\''")
                lines.append(f"file '{safe}'")
            listfile.write_text("\n".join(lines), encoding="utf-8")
            try:
                run_cmd([
                    self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(listfile),
                    "-c:a", "pcm_s16le", "-ar", "48000", str(out_path),
                ], capture=True, check=True, timeout=900, quiet=True)
                return out_path
            except Exception as e:
                warn(f"fast audio join failed ({str(e)[:120]}) - using the slow, safe one")
            finally:
                listfile.unlink(missing_ok=True)

        # ---- exact path: the concat filter -------------------------------
        args: list[str] = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
        for p in parts:
            args += ["-i", str(p)]
        labels = "".join(f"[{i}:a]" for i in range(len(parts)))
        graph = f"{labels}concat=n={len(parts)}:v=0:a=1[cat];[cat]apad[out]"
        args += ["-filter_complex", graph, "-map", "[out]"]
        if exact_duration:
            args += ["-t", f"{float(exact_duration):.4f}"]
        args += ["-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out_path)]
        run_cmd(args, capture=True, check=True, timeout=1800, quiet=True)
        return out_path

    # ==================================================================
    # 4. FIT AUDIO (time-stretching)
    # ==================================================================
    def fit_audio(self, src: Path, out_path: Path, target_seconds: float, *,
                  max_speedup: float = 1.35, max_slowdown: float = 0.85,
                  strategy: str = "pad_then_hold") -> dict[str, Any]:
        """
        Make `src` fit a window of `target_seconds`.

        THE RULE THAT KEEPS VOICES HUMAN
        -------------------------------
        Speeding a voice up past about +35% makes it sound like a chipmunk
        reading the news. So we clamp: if the window cannot be filled by
        stretching, the scene keeps its natural speech and the leftover time
        becomes a pause (the "too fast to be honest" warning in the log).

        atempo ALSO cannot go beyond 2.0x or below 0.5x in one instance, so
        the helper atempo_chain() chains several of them when needed.
        Returns a report dict that is saved next to the file, so a resumed run
        knows exactly what it did last time.
        """
        src = Path(src)
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        target = max(0.3, float(target_seconds))
        natural = self.probe_duration(src)
        report: dict[str, Any] = {"natural": round(natural, 3), "target": round(target, 3),
                                  "tempo": 1.0, "method": "copy"}

        if natural <= 0.05:
            self.make_silence(out_path, target)
            report.update({"method": "silence", "final": round(target, 3)})
            return report

        raw_tempo = natural / target
        tempo = max(float(max_slowdown), min(float(max_speedup), raw_tempo))

        if abs(raw_tempo - tempo) > 0.02:
            direction = "fast" if raw_tempo > 1 else "slow"
            warn(f"    this scene's narration is too {direction} to fit honestly "
                 f"({natural:.1f}s of speech in a {target:.1f}s window): "
                 f"capped at {tempo:.2f}x")
            report["capped"] = True
        report["requested_tempo"] = round(raw_tempo, 3)

        if abs(tempo - 1.0) < 0.01:
            # Nothing to do: copy (or trim/pad, which the caller handles)
            shutil.copy2(src, out_path)
            report.update({"final": round(natural, 3), "method": "copy"})
            return report

        chain = atempo_chain(tempo)
        run_cmd([
            self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src), "-filter:a", chain,
            "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(out_path),
        ], capture=True, check=True, timeout=900, quiet=True)
        report.update({"tempo": round(tempo, 4), "method": "atempo",
                       "final": round(self.probe_duration(out_path), 3)})
        return report

    # ==================================================================
    # 5. RENDER ONE SCENE CLIP (Ken Burns)
    # ==================================================================
    def render_scene_clip(self, *, image: Path, audio: Path | None, out_path: Path,
                          duration: float, motion: str = "zoom_in") -> Path:
        """
        One still image + motion -> one silent .mp4 of exactly `duration`.

        The motion itself is built by bot/filters.py (build_scene_filter),
        which is where the smooth supersampled crop lives. This method's job
        is to turn that filter string into a working ffmpeg command, including
        the two things that break every first attempt:

          1. the source image must be scaled to the padded size the filter
             expects (returned by build_scene_filter)
          2. x264 needs memory, so if the machine dies we retry with cheap
             settings instead of failing the scene
        """
        image = Path(image)
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        duration = max(0.2, float(duration))

        w, h = self.cfg.resolution()
        fps = int(self.setting("video.fps", 30))
        m = self.setting("motion", {}) or {}
        parallel = max(1, int(self.setting("system.parallel_scenes", 1) or 1))

        ss = m.get("supersample", "auto")
        if str(ss).lower() in ("auto", "none", ""):
            ss = auto_supersample(w, h, parallel, ceiling=int(m.get("supersample_max", 6) or 6))
        ss = max(1, min(8, to_int(ss, 2)))

        vf, pad_w, pad_h = build_scene_filter(
            out_w=w, out_h=h, duration=duration, fps=fps, motion=motion,
            supersample=ss,
            zoom_amount=to_float(m.get("zoom_amount"), 1.12),
            pan_amount=to_float(m.get("pan_amount"), 0.10),
            color_grade=str(m.get("color_grade", "cinematic")),
            vignette=bool(m.get("add_vignette", True)),
            vignette_strength=to_float(m.get("vignette_strength"), 0.35),
            grain=to_float(m.get("add_film_grain", 0.0), 0.0),
            shake=to_float(m.get("shake", 0.0), 0.0),
            fade_seconds=to_float(m.get("scene_fade_seconds", 0.0), 0.0),
            focus=str(m.get("focus", "center")),
        )
        debug(f"scene filter ({motion}, supersample={ss}x, pad={pad_w}x{pad_h}): {vf[:200]}")

        # ---- the source image gets normalised first ----------------------
        # -loop 1 turns a single image into an endless video stream; -t stops it.
        pre = (f"scale={pad_w}:{pad_h}:force_original_aspect_ratio=increase,"
               f"crop={pad_w}:{pad_h},setsar=1")
        full_graph = f"[0:v]{pre},{vf}[v]"

        def build(preset: str, threads: int, ss_value: int) -> list[str]:
            cmd = [
                self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                "-loop", "1", "-framerate", str(fps), "-i", str(image),
                "-t", f"{duration:.4f}",
                "-filter_complex", full_graph, "-map", "[v]",
                "-c:v", "libx264", "-preset", preset, "-crf",
                str(int(self.setting("video.crf", 20))),
                "-pix_fmt", "yuv420p", "-r", str(fps),
                "-tune", "stillimage",
            ]
            if threads:
                cmd += ["-threads", str(threads)]
            look = int(self.setting("system.encode_lookahead", 20) or 20)
            cmd += ["-x264-params", f"rc-lookahead={look}:ref={1 if ss_value >= 4 else 3}"]
            cmd += [str(out_path)]
            return cmd

        preset = str(self.setting("video.preset", "medium"))
        threads = int(self.setting("system.encode_threads", 0) or 0)

        try:
            run_cmd(build(preset, threads, ss), capture=True, check=True, timeout=3600, quiet=True)
        except Exception as e:
            msg = str(e)
            if "KILLED" in msg.upper() or "exit -9" in msg or "exit 137" in msg:
                warn("    the encoder ran out of RAM - retrying smaller and cheaper")
                small = max(1, min(2, ss))
                vf_small, pw, ph = build_scene_filter(
                    out_w=w, out_h=h, duration=duration, fps=fps, motion=motion,
                    supersample=small,
                    zoom_amount=to_float(m.get("zoom_amount"), 1.12),
                    pan_amount=to_float(m.get("pan_amount"), 0.10),
                    color_grade=str(m.get("color_grade", "cinematic")),
                    vignette=bool(m.get("add_vignette", True)),
                    grain=0.0, shake=0.0,
                )
                full_graph_small = (f"[0:v]scale={pw}:{ph}:force_original_aspect_ratio=increase,"
                                    f"crop={pw}:{ph},setsar=1,{vf_small}[v]")
                cmd = [
                    self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                    "-loop", "1", "-framerate", str(fps), "-i", str(image),
                    "-t", f"{duration:.4f}",
                    "-filter_complex", full_graph_small, "-map", "[v]",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf",
                    str(min(28, int(self.setting("video.crf", 20)) + 4)),
                    "-pix_fmt", "yuv420p", "-r", str(fps), "-threads", "2",
                    str(out_path),
                ]
                run_cmd(cmd, capture=True, check=True, timeout=3600, quiet=True)
            else:
                raise

        got = self.probe_duration(out_path)
        if got <= 0.05:
            die(f"ffmpeg produced an empty clip for {image.name} - check that the "
                f"image is a valid picture file")
        if abs(got - duration) > 0.35:
            debug(f"clip is {got:.2f}s instead of {duration:.2f}s")
        return out_path

    # ==================================================================
    # 6. CONCATENATE CLIPS (with transitions)
    # ==================================================================
    def concatenate(self, clips: list[Path], out_path: Path, *,
                    transition: str = "crossfade", transition_duration: float = 0.45,
                    vary: bool = True, enabled: bool = True) -> tuple[Path, float]:
        """
        All the scene clips -> one silent film.

        TYPES OF JOIN
          * cut        -> the concat demuxer, instant, no re-encode
          * crossfade  -> the xfade filter: clip A fades into clip B while
                          both are visible. xfade needs the running OFFSET of
                          every clip, computed from real measured durations
                          (bot/filters.py -> build_xfade_graph); guessing it is
                          what makes most home-made bots glitch.

        IMPORTANT: with crossfades the total film is SHORTER than the sum of
        its clips, because each fade overlaps two clips. The pipeline knows
        this and compensates when it plans the scene lengths.
        """
        clips = [Path(c) for c in clips if Path(c).exists()]
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        if not clips:
            die("no clips to join - the motion stage produced nothing")
        if len(clips) == 1:
            shutil.copy2(clips[0], out_path)
            return out_path, self.probe_duration(out_path)

        cut = (not enabled) or str(transition).lower() in ("cut", "none")
        if cut:
            listfile = out_path.parent / f"{out_path.stem}_join.txt"
            listfile.write_text(
                "\n".join(f"file '{str(c.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
                          for c in clips),
                encoding="utf-8")
            try:
                run_cmd([
                    self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(listfile),
                    "-c", "copy", str(out_path),
                ], capture=True, check=True, timeout=3600, quiet=True)
                return out_path, self.probe_duration(out_path)
            finally:
                listfile.unlink(missing_ok=True)

        durations = [self.probe_duration(c) for c in clips]
        missing = [c.name for c, d in zip(clips, durations) if d <= 0.05]
        if missing:
            die(f"could not read the length of {', '.join(missing)} - "
                f"the clip is corrupt. Re-render it:  python main.py motion <project> --force")
        debug(f"xfade durations: {[round(d, 2) for d in durations]}")

        graph, n, label = build_xfade_graph(durations, transition, transition_duration, vary)
        args: list[str] = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
        for c in clips:
            args += ["-i", str(c)]
        args += ["-filter_complex", graph, "-map", label]
        args += ["-c:v", "libx264", "-preset", str(self.setting("video.preset", "medium")),
                 "-crf", str(int(self.setting("video.crf", 20))),
                 "-pix_fmt", "yuv420p", "-r", str(int(self.setting("video.fps", 30)))]
        args += self._threads()
        args += [str(out_path)]
        run_cmd(args, capture=True, check=True, timeout=7200, quiet=True)
        return out_path, self.probe_duration(out_path)

    # ==================================================================
    # 7. THE AUDIO MIX
    # ==================================================================
    def build_mix(self, *, voice: Path, music: Path | None, out_path: Path,
                  duration: float) -> Path:
        """
        Narration + music -> the mastered soundtrack.

        What happens, in order:
          1. the voice is cleaned with a broadcast EQ/compressor chain
          2. loudnorm brings it to the target loudness (-16 LUFS = YouTube)
          3. the music is turned down to `volume_db` and faded in/out
          4. DUCKING: the music is squeezed by a sidechain compressor that
             listens to the voice, so it dips automatically whenever the
             narrator speaks and swells back in the gaps
          5. both are summed, limited, and faded out at the very end

        Steps 1-5 are one filtergraph (bot/filters.py -> build_mix_graph), so
        the whole master is a single ffmpeg pass - about a second of CPU.
        """
        voice = Path(voice)
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        duration = max(0.5, float(duration))

        a = self.setting("audio", {}) or {}
        mus = a.get("music") or {}
        master = a.get("master") or {}
        vcfg = a.get("voice") or {}
        has_music = bool(music) and Path(str(music)).exists()

        # ---- normalise the voice first (two-pass, so it is accurate) -----
        norm = voice
        if bool(vcfg.get("normalize", True)):
            norm = out_path.parent / "voice_norm.wav"
            if not norm.exists() or norm.stat().st_mtime < voice.stat().st_mtime:
                self.normalize_track(voice, norm,
                                     target_lufs=to_float(vcfg.get("target_loudness_lufs"), -16.0))
        if not Path(norm).exists():
            norm = voice

        target_lufs = to_float(vcfg.get("target_loudness_lufs"), -16.0)
        graph = build_mix_graph(
            voice_duration=duration,
            music_enabled=has_music,
            music_volume_db=to_float(mus.get("volume_db"), -19.0),
            music_fade_in=to_float(mus.get("fade_in_seconds"), 1.5),
            music_fade_out=to_float(mus.get("fade_out_seconds"), 3.0),
            ducking=bool(mus.get("ducking", True)),
            duck_ratio=to_int(mus.get("duck_ratio"), 8),
            duck_attack_ms=to_int(mus.get("duck_attack_ms"), 25),
            duck_release_ms=to_int(mus.get("duck_release_ms"), 450),
            voice_eq=str(vcfg.get("eq", "broadcast")),
            # the voice was already normalised above, so the graph only shapes it
            normalize=False,
            target_lufs=target_lufs,
            limiter=bool(master.get("limiter", True)),
            master_fade_out=to_float(master.get("fade_out_seconds"), 1.0),
        )
        debug(f"mix graph: {graph[:400]}")

        args = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(norm)]
        if has_music:
            args += ["-i", str(music)]
        args += ["-filter_complex", graph, "-map", "[aout]",
                 "-t", f"{duration:.4f}",
                 "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out_path)]
        run_cmd(args, capture=True, check=True, timeout=3600, quiet=True)

        # Final safety net: some loudnorm builds quietly eat the last frames,
        # so verify the length and pad if needed.
        got = self.probe_duration(out_path)
        if got < duration - 0.35:
            warn(f"mix came out {got:.2f}s instead of {duration:.2f}s - padding it")
            padded = out_path.with_name(out_path.stem + "_pad.wav")
            run_cmd([
                self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(out_path), "-af", "apad",
                "-t", f"{duration:.4f}", "-ar", "48000", "-ac", "2",
                "-c:a", "pcm_s16le", str(padded),
            ], capture=True, check=True, timeout=900, quiet=True)
            padded.replace(out_path)
        return out_path

    def normalize_track(self, src: Path, out_path: Path,
                        target_lufs: float = -16.0) -> Path:
        """
        Two-pass loudness normalisation.

        WHY TWO PASSES
        --------------
        One-pass loudnorm is a live estimate: it changes volume as it goes,
        which can pump. The two-pass method MEASURES the file first (pass 1),
        then applies a fixed, accurate gain (pass 2). It is the difference
        between "sounds a bit off" and "sounds like a broadcast".
        Both passes are fast (audio only, no video involved).
        """
        src = Path(src)
        out_path = Path(out_path)
        ensure_dir(out_path.parent)

        measured: dict[str, float] = {}
        try:
            proc = run_cmd([
                self.ffmpeg_bin, "-hide_banner", "-i", str(src),
                "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
                "-f", "null", "-",
            ], capture=True, check=False, timeout=900, quiet=True)
            text = (proc.stderr or "") + (proc.stdout or "")
            block = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", text, re.S)
            if block:
                measured = json.loads(block[-1])
        except Exception as e:
            debug(f"loudnorm measurement failed ({e}) - using a single pass")

        if measured:
            graph = (
                f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"
                f":measured_I={measured.get('input_i', -24)}"
                f":measured_TP={measured.get('input_tp', -2)}"
                f":measured_LRA={measured.get('input_lra', 7)}"
                f":measured_thresh={measured.get('input_thresh', -34)}"
                f":offset={measured.get('target_offset', 0)}:linear=true"
            )
            run_cmd([
                self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(src), "-af", graph,
                "-ar", "48000", "-c:a", "pcm_s16le", str(out_path),
            ], capture=True, check=True, timeout=1800, quiet=True)
        else:
            run_cmd([
                self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(src), "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
                "-ar", "48000", "-c:a", "pcm_s16le", str(out_path),
            ], capture=True, check=True, timeout=1800, quiet=True)
        debug(f"normalised {src.name} -> {out_path.name} ({target_lufs} LUFS)")
        return out_path

    def measure_loudness(self, path: Path) -> dict[str, float]:
        """Read back the real loudness, for the report at the end of a build."""
        out: dict[str, float] = {}
        try:
            proc = run_cmd([self.ffmpeg_bin, "-hide_banner", "-i", str(path),
                            "-af", "ebur128", "-f", "null", "-"],
                           capture=True, check=False, timeout=900, quiet=True)
            text = (proc.stderr or "") + (proc.stdout or "")
            m = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", text)
            peak = re.findall(r"Peak:\s*(-?[\d.]+)\s*dBFS", text)
            if m:
                out["lufs"] = float(m[-1])
            if peak:
                out["peak_dbfs"] = float(peak[-1])
        except Exception:
            pass
        return out

    # ==================================================================
    # 8. MUX (picture + sound + captions + watermark)
    # ==================================================================
    def mux(self, video: Path, audio: Path, out_path: Path, *,
            subtitles: Path | None = None, sub_style: dict | None = None,
            watermark: Path | None = None,
            watermark_cfg: dict | None = None) -> Path:
        """
        The final export: one video, one audio track, optional burn-ins.

        Captions are BURNED IN (not a separate track) on purpose: burned text
        shows up in every player, on every phone, in every screen recording.
        A subtitle TRACK can be switched off or ignored by the player, and
        many viewers never turn them on.

        ASS vs SRT: we prefer the .ass file we generated, because it carries
        the exact PlayRes of this video. Burning a bare .srt makes ffmpeg
        assume a 384-pixel canvas and the text comes out comically huge.
        """
        video = Path(video)
        audio = Path(audio)
        out_path = Path(out_path)
        ensure_dir(out_path.parent)

        args: list[str] = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
                           "-i", str(video), "-i", str(audio)]
        wm_cfg = watermark_cfg or {}
        use_wm = bool(watermark) and Path(str(watermark)).exists()

        if use_wm:
            # Watermark is input 2; it is scaled, faded and overlaid.
            args += ["-i", str(watermark)]

        chains: list[str] = []
        v_label = "0:v"

        if subtitles and Path(str(subtitles)).exists():
            sub = Path(str(subtitles))
            style = sub_style or {}
            w, h = self.cfg.resolution()
            vertical = h > w
            if sub.suffix.lower() == ".ass":
                chain = f"[{v_label}]ass='{escape_filter_path(sub)}'"
            else:
                chain = (f"[{v_label}]subtitles='{escape_filter_path(sub)}'"
                         f":force_style='{ass_style_from_cfg(style, vertical)}'")
            chains.append(chain + "[vsub]")
            v_label = "vsub"
            debug(f"burning in captions from {sub.name}")

        if use_wm:
            wcfg = wm_cfg
            scale = to_float(wcfg.get("scale"), 0.12)
            opacity = to_float(wcfg.get("opacity"), 0.55)
            pos = str(wcfg.get("position", "bottom_right"))
            pad = 24
            positions = {
                "top_left": f"{pad}:{pad}",
                "top_right": f"W-w-{pad}:{pad}",
                "bottom_left": f"{pad}:H-h-{pad}",
                "bottom_right": f"W-w-{pad}:H-h-{pad}",
                "center": "(W-w)/2:(H-h)/2",
            }
            xy = positions.get(pos, positions["bottom_right"])
            chains.append(f"[2:v]scale=iw*{scale:.3f}:-1,format=rgba,"
                          f"colorchannelmixer=aa={opacity:.2f}[wm]")
            chains.append(f"[{v_label}][wm]overlay={xy}[vout]")
            v_label = "vout"

        args += ["-map", f"[{v_label}]" if v_label.startswith("v") and v_label != "0:v" else "0:v",
                 "-map", "1:a"]
        if chains:
            args += ["-filter_complex", ";".join(chains)]

        codec = str(self.setting("video.codec", "h264")).lower()
        args += ["-c:v", "libx265" if codec in ("h265", "hevc") else "libx264"]
        if codec in ("h265", "hevc"):
            args += ["-tag:v", "hvc1", "-crf", str(int(self.setting("video.crf", 20))),
                     "-preset", str(self.setting("video.preset", "medium"))]
        else:
            args += ["-crf", str(int(self.setting("video.crf", 20))),
                     "-preset", str(self.setting("video.preset", "medium"))]
        args += ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        args += self._threads()
        args += ["-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
        # -t = video duration: guarantees the film is never shorter than the
        # picture because the audio mix ended a hair early.
        vdur = self.probe_duration(video)
        if vdur > 0:
            args += ["-t", f"{vdur:.4f}"]
        args += ["-shortest", str(out_path)]

        try:
            run_cmd(args, capture=True, check=True, timeout=7200, quiet=True)
        except Exception as e:
            msg = str(e)
            if use_wm or subtitles:
                warn(f"the fancy export failed ({str(e)[:120]}) - retrying without "
                     f"captions/watermark so you still get a video")
                return self.mux(video, audio, out_path, subtitles=None, watermark=None)
            if "KILLED" in msg.upper() or "exit -9" in msg or "exit 137" in msg:
                warn("the encoder ran out of RAM - retrying with cheap settings")
                cheap = [a for a in args]
                if "-preset" in cheap:
                    cheap[cheap.index("-preset") + 1] = "ultrafast"
                if "-threads" in cheap:
                    cheap[cheap.index("-threads") + 1] = "2"
                else:
                    cheap = cheap[:-1] + ["-threads", "2"] + [cheap[-1]]
                run_cmd(cheap, capture=True, check=True, timeout=7200, quiet=True)
            else:
                raise
        return out_path

    # ==================================================================
    # EXTRAS
    # ==================================================================
    def concat_videos(self, paths: list[Path], out_path: Path) -> Path:
        """Glue finished videos together (used for intro / outro clips)."""
        paths = [Path(p) for p in paths if Path(p).exists()]
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        if not paths:
            die("concat_videos: nothing to join")
        if len(paths) == 1:
            shutil.copy2(paths[0], out_path)
            return out_path

        # Re-encode rather than stream-copy: intro/outro clips usually have a
        # different resolution or bitrate, and `-c copy` refuses mismatches.
        args: list[str] = [self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error"]
        for p in paths:
            args += ["-i", str(p)]
        w, h = self.cfg.resolution()
        fps = int(self.setting("video.fps", 30))
        parts = []
        for i in range(len(paths)):
            parts.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                         f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}]")
        for i in range(len(paths)):
            parts.append(f"[{i}:a]aresample=48000,aformat=sample_fmts=fltp:"
                         f"channel_layouts=stereo[a{i}]")
        joined = "".join(f"[v{i}][a{i}]" for i in range(len(paths)))
        parts.append(f"{joined}concat=n={len(paths)}:v=1:a=1[vout][aout]")
        args += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
                 "-c:v", "libx264", "-crf", str(int(self.setting("video.crf", 20))),
                 "-preset", str(self.setting("video.preset", "medium")),
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out_path)]
        run_cmd(args, capture=True, check=True, timeout=7200, quiet=True)
        return out_path

    def thumbnail(self, video: Path, out_path: Path, *,
                  at_seconds: float = 3.0, title: str | None = None) -> Path:
        """Grab one frame (and optionally draw the title on it)."""
        video = Path(video)
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        at = max(0.0, float(at_seconds))
        dur = self.probe_duration(video)
        if dur and at > dur - 0.2:
            at = max(0.0, dur * 0.25)

        run_cmd([
            self.ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{at:.3f}", "-i", str(video), "-frames:v", "1",
            "-q:v", "2", str(out_path),
        ], capture=True, check=True, timeout=600, quiet=True)

        if title:
            try:
                from ..imaging import add_title_to_image
                add_title_to_image(out_path, str(title),
                                   font=self.setting("subtitles.style.font"))
            except Exception as e:
                debug(f"thumbnail title text skipped: {e}")
        return out_path

    def teardown(self) -> None:
        return None
