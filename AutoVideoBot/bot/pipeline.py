"""
bot/pipeline.py
================
THE ORCHESTRATOR. This is the file that actually runs your video.

============================================================================
THE SEQUENCE (every run, in this order)
============================================================================

  0. init      create workspace/projects/<name>/ and save the config snapshot
  1. script    MODE A: parse YOUR timestamped .txt   |   MODE B: ask the LLM
               -> script.json  (the single source of truth for the whole video)
  2. voice     every scene's narration -> a wav file, plus word timings
  3. timing    measure each wav, then stretch/pad it so it lands EXACTLY on
               your timestamps. Build the continuous narration track.
  4. images    every scene's image_prompt -> a picture (Vast/Colab/Kaggle/free)
  5. motion    picture + Ken Burns move + scene audio -> one .mp4 per scene
  6. transition  all clips -> one long video, crossfaded
  7. subtitles word-accurate .srt from the timings measured in step 2/3
  8. mix       narration + background music, ducked and loudness-normalised
  9. assembly  picture + sound + captions -> output/final.mp4
 10. extras    thumbnail.jpg + youtube_metadata.json

Every step checks the manifest first. Already done with identical inputs?
Skipped. That is why the bot is safe to re-run and why a crash costs nothing.

============================================================================
HOW PROVIDERS ARE PICKED (the hot-swap mechanism)
============================================================================
Nothing below says "use Vast" or "use DeepSeek". It says:

    self.provider("image")

which reads config.yaml -> image.provider and builds that class. Change the
word in config.yaml and the whole pipeline follows.
"""
from __future__ import annotations

import io
import json
import os
import random
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from . import audio as audio_stage
from . import script as script_stage
from . import subtitles as subs_stage
from .config import Config
from .filters import MOTION_PRESETS, motion_for_index
from .paths import ROOT, Project
from .registry import get_provider_class
from .state import Manifest, Scene, Script
from .utils import (
    debug, die, ensure_dir, fail, fmt_time, human_bytes, info, ok,
    read_json, retry, stable_hash, step, warn, write_json,
)


class Pipeline:
    """Runs the whole video pipeline for one project."""

    def __init__(self, cfg: Config, project: Project):
        self.cfg = cfg
        self.project = project
        self.manifest = Manifest(project.dir)
        self.script = Script(project.dir)
        self._providers: dict[str, Any] = {}
        self.scenes: list[dict] = []
        self.force = False
        self.only: set[str] | None = None
        self.endpoint_override: str | None = None
        project.create()

    # ==================================================================
    # PROVIDER FACTORY
    # ==================================================================
    def provider(self, kind: str, name: str | None = None, *, fresh: bool = False):
        """Build (and cache) the provider named in config.yaml."""
        name = name or self.cfg.get(f"{kind}.provider") or self.cfg.get(f"{kind}.engine")
        key = f"{kind}:{name}"
        if key in self._providers and not fresh:
            return self._providers[key]

        if self.endpoint_override and kind == "image":
            # --endpoint https://xxx  beats whatever is in the config
            self.cfg.set(f"image.{name}.endpoint", self.endpoint_override)
            self.cfg.set(f"image.{name}.url", self.endpoint_override)
            os.environ["IMAGE_ENDPOINT_URL"] = self.endpoint_override

        cls = get_provider_class(kind, str(name))
        inst = cls(self.cfg, self.project)
        self._providers[key] = inst
        return inst

    def close_providers(self) -> None:
        """Shut down anything that bills money (Vast instances, tunnels...)."""
        for p in list(self._providers.values()):
            try:
                p.teardown()
            except Exception as e:
                warn(f"teardown of {p}: {e}")
        self._providers.clear()

    # ==================================================================
    # FILTERING (so you can re-render only some scenes)
    # ==================================================================
    def _wanted(self, sid: str) -> bool:
        if not self.only:
            return True
        sid = str(sid).lower()
        for token in self.only:
            t = token.lower().strip()
            if not t:
                continue
            if t == sid:
                return True
            if t.isdigit() and sid == f"s{int(t):02d}":
                return True
            if t.startswith("s") and t[1:].isdigit() and sid == f"s{int(t[1:]):02d}":
                return True
            if "-" in t:                                   # range like 3-7 or s03-s07
                a, _, b = t.partition("-")
                def num(x):
                    x = x.strip().lower().lstrip("s")
                    return int(x) if x.isdigit() else None
                na, nb = num(a), num(b)
                ns = num(sid)
                if na and nb and ns and na <= ns <= nb:
                    return True
        return False

    def _cache_key(self, kind: str, ident: str, params: dict) -> str:
        return self.manifest.artifact_key(kind, ident, params)

    def _skip(self, key: str, path: Path | None = None) -> bool:
        if self.force:
            return False
        if self.manifest.is_done(key) and (path is None or Path(path).exists()):
            return True
        return False

    # ==================================================================
    # STAGE 1 - SCRIPT
    # ==================================================================
    def stage_script(self, *, topic: str | None = None, script_file: Path | None = None,
                     duration: float | None = None, style: str = "",
                     extra_instructions: str = "") -> dict:
        step("STAGE 1 / 10 - SCRIPT")
        self.manifest.start_stage("script")

        data: dict | None = None
        mode = None

        # ---- A. you supplied a script file -------------------------------
        if script_file:
            script_file = Path(script_file).resolve()
            if not script_file.exists():
                die(f"Script file not found: {script_file}")
            mode = "file"
            # keep a copy of the source inside the project folder, unless the
            # source already IS that copy (the `test` command does this)
            dest = self.project.input_file.resolve()
            if script_file != dest:
                shutil.copyfile(script_file, dest)
            data = script_stage.parse_script_file(
                script_file,
                default_scene_seconds=float(self.cfg.get("timing.default_scene_seconds", 6.0)),
            )

        # ---- B. a saved script.json already exists ------------------------
        elif self.script.load() and not topic:
            info("reusing the existing script.json (pass --force to regenerate)")
            self.scenes = self.script.data["scenes"]
            self.manifest.finish_stage("script", {"scenes": len(self.scenes), "source": "cached"})
            self._apply_meta_overrides()
            return self.script.data

        # ---- C. generate from a topic ------------------------------------
        elif topic:
            mode = "topic"
            self.project.topic_file.write_text(topic, encoding="utf-8")
            llm_name = str(self.cfg.get("llm.provider", "deepseek")).lower()
            if llm_name in ("manual", "none"):
                die(
                    "You asked the bot to write a script but llm.provider is 'manual'.\n"
                    "Either set llm.provider: deepseek (or ollama / openai_compat)\n"
                    "or pass your own script:  --script path/to/script.txt"
                )
            llm = self.provider("llm", llm_name)
            alive, msg = llm.healthcheck()
            if not alive:
                die(f"LLM is not usable:\n{msg}")
            ok(msg)
            data = script_stage.generate_script(
                llm, self.cfg, topic=topic, duration=duration,
                style=style, extra_instructions=extra_instructions,
            )
        else:
            die(
                "Nothing to work from. Give the bot either:\n"
                '    a topic:   python main.py run "black holes explained" --duration 120\n'
                '    a script:  python main.py run "my video" --script my_script.txt'
            )

        # ---- shared finishing touches ------------------------------------
        scenes = data["scenes"]
        style_suffix = str(self.cfg.get("image.style_suffix", "") or "")
        negative = str(self.cfg.get("image.negative_prompt", "") or "")
        scenes = script_stage.enrich_prompts(scenes, self.cfg, style_suffix, negative)

        # choose motions (cycled so two scenes in a row never match)
        preset = str(self.cfg.get("motion.preset", "auto"))
        order = list(self.cfg.get("motion.auto_order") or [])
        for i, sc in enumerate(scenes):
            sc["motion"] = sc.get("motion") or motion_for_index(i, preset, order)

        data["scenes"] = scenes
        data.setdefault("source", mode or "unknown")
        data["aspect"] = self.cfg.get("video.aspect")
        self.script.data = data
        self.script.save()
        self.scenes = scenes
        self._apply_meta_overrides()

        # ---- report ------------------------------------------------------
        problems = script_stage.validate(scenes, self.cfg)
        info(f"{len(scenes)} scenes, {fmt_time(self.script.data.get('total_duration', 0))} total")
        for sc in scenes[:60]:
            words = len((sc.get("narration") or "").split())
            info(
                f"  {sc['id']}  {sc.get('target_start', 0):6.1f}s -> {sc.get('target_end', 0):6.1f}s "
                f"({sc.get('duration', 0):4.1f}s, {words:3d} words)  [{sc.get('motion')}]"
            )
        if problems:
            warn("script sanity checks:")
            for p in problems:
                warn("   - " + p)
        self.manifest.finish_stage("script", {"scenes": len(scenes), "source": data.get("source")})
        return data

    def _apply_meta_overrides(self) -> None:
        """Header lines in your script file (#voice:, #music:) beat config.yaml."""
        meta = self.script.data.get("meta") or {}
        if meta.get("voice"):
            self.cfg.set("tts.edge.voice", meta["voice"])
            self.cfg.set("tts.voicestudio.voice", meta["voice"])
            info(f"voice override from script header: {meta['voice']}")
        if meta.get("aspect"):
            self.cfg.set("video.aspect", meta["aspect"])
            info(f"aspect override from script header: {meta['aspect']}")
        if meta.get("style"):
            current = str(self.cfg.get("image.style_suffix", ""))
            self.cfg.set("image.style_suffix", f"{current}, {meta['style']}".strip(", "))
        if meta.get("music"):
            self.cfg.set("audio.music.filename", meta["music"])
            self.cfg.set("audio.music.mode", "filename")

    # ==================================================================
    # STAGE 2 - VOICEOVER
    # ==================================================================
    def stage_voice(self) -> list[dict]:
        step("STAGE 2 / 10 - VOICEOVER (TTS)")
        self.manifest.start_stage("voice")
        self._ensure_scenes()

        tts_name = str(self.cfg.get("tts.provider", "edge"))
        tts = self.provider("tts", tts_name)
        alive, msg = tts.healthcheck()
        if not alive:
            die(f"TTS provider is not usable:\n{msg}")
        ok(msg)

        fmt = str(self.cfg.get("tts.audio_format", "wav")).lstrip(".")
        rate = str(self.cfg.get("tts.rate", "+0%"))
        pitch = str(self.cfg.get("tts.pitch", "+0Hz"))

        todo = [s for s in self.scenes if self._wanted(s["id"])]
        jobs = []
        for sc in todo:
            sid = sc["id"]
            out = self.project.scene_audio(sid, fmt)
            key = self._cache_key("voice", sid, {
                "provider": tts_name, "text": sc.get("narration", ""),
                "voice": sc.get("voice") or self.cfg.get(f"tts.{tts_name}.voice"),
                "rate": sc.get("rate") or rate, "pitch": pitch, "fmt": fmt,
            })
            if self._skip(key, out):
                debug(f"voice {sid}: cached")
                continue
            if not (sc.get("narration") or "").strip():
                warn(f"scene {sid} has no narration - it will be silent")
                continue
            jobs.append((sc, out, key))

        info(f"{len(jobs)} scene(s) to speak ({len(todo) - len(jobs)} already cached)")

        for i, (sc, out, key) in enumerate(jobs, 1):
            sid = sc["id"]
            text = sc["narration"]
            use_voice = sc.get("voice") or None
            use_rate = sc.get("rate") or rate

            def do():
                return tts.synthesize(text, out, voice=use_voice, rate=use_rate,
                                      pitch=pitch, target_duration=sc.get("duration"))

            try:
                res = retry(do, attempts=int(self.cfg.get("system.retry_attempts", 3)),
                            what=f"TTS scene {sid}", delay=2.0)
            except Exception as e:
                fail(f"scene {sid}: {e}")
                if str(self.cfg.get("system.on_error", "continue")) == "abort":
                    self.close_providers()
                    raise
                continue

            words = res.get("words")
            if words:
                write_json(self.project.scene_words(sid), {"scene": sid, "words": words})
            self.manifest.mark(key, out, {"words": len(words or [])})
            size = out.stat().st_size if out.exists() else 0
            ok(f"  [{i}/{len(jobs)}] {sid} {fmt_time(len(text.split()) / 3.0)} of speech ({human_bytes(size)})")

        self.manifest.finish_stage("voice", {"scenes": len(todo)})
        return self.scenes

    # ==================================================================
    # STAGE 3 - TIMING
    # ==================================================================
    def stage_timing(self) -> list[dict]:
        """
        Measure the real speech, then force it onto your timestamps.
        Also builds the single continuous narration track used for the mix.
        """
        step("STAGE 3 / 10 - TIMING ANALYSIS")
        self.manifest.start_stage("timing")
        self._ensure_scenes()

        asm = self.provider("assembly", self.cfg.get("motion.engine", "ffmpeg"))
        tcfg = self.cfg.section("timing")
        fit = bool(tcfg.get("fit_to_timestamps", True))
        head_ms = int(self.cfg.get("tts.head_silence_ms", 150))
        tail_ms = int(self.cfg.get("tts.tail_silence_ms", 450))
        max_up = float(tcfg.get("max_speedup", 1.35))
        max_down = float(tcfg.get("max_slowdown", 0.85))
        strategy = str(tcfg.get("overflow_strategy", "pad_then_hold"))
        default_scene = float(tcfg.get("default_scene_seconds", 6.0))

        trans = self.cfg.section("transitions")
        t_ext = float(trans.get("duration", 0.45)) if trans.get("enabled", True) else 0.0

        parts: list[Path] = []
        for i, sc in enumerate(self.scenes):
            sid = sc["id"]
            raw = self.project.scene_audio(sid, str(self.cfg.get("tts.audio_format", "wav")))
            target = float(sc.get("duration") or sc.get("target_end", 0) - sc.get("target_start", 0) or 0)

            if raw.exists():
                natural = asm.probe_duration(raw)
            else:
                natural = 0.0
                warn(f"scene {sid} has no audio file - using silence")

            sc["natural_duration"] = round(natural, 3)
            sc["speech_pad_before"] = round(head_ms / 1000.0, 3)

            if target <= 0:
                # no timestamp given -> the voice decides the length
                target = max(float(tcfg.get("min_duration", 2.0)),
                             natural + head_ms / 1000.0 + tail_ms / 1000.0 + float(sc.get("extra_pause") or 0))
                target = min(target, float(tcfg.get("max_duration", 30.0)))
                sc["target_start"] = sc.get("target_start") or 0.0
                sc["target_end"] = float(sc["target_start"]) + target
                sc["duration"] = round(target, 3)

            if not self._wanted(sid):
                sc["tempo"] = 1.0
                continue

            # --- fit the speech to the timestamp window -------------------
            fitted = self.project.audio_dir / f"{sid}_fit.wav"
            key = self._cache_key("timing", sid, {
                "natural": round(natural, 3), "target": round(target, 3),
                "fit": fit, "max_up": max_up, "max_down": max_down, "strategy": strategy,
            })
            if fit and natural > 0.05:
                if self._skip(key, fitted):
                    report = read_json(fitted.with_suffix(".json"), {"tempo": 1.0})
                else:
                    speech_window = max(0.4, target - head_ms / 1000.0)
                    report = asm.fit_audio(raw, fitted, speech_window,
                                           max_speedup=max_up, max_slowdown=max_down,
                                           strategy=strategy)
                    write_json(fitted.with_suffix(".json"), report)
                    self.manifest.mark(key, fitted, report)
                sc["tempo"] = float(report.get("tempo", 1.0))
                sc["audio_duration"] = round(float(report.get("final", target)), 3)
                if abs(sc["tempo"] - 1.0) > 0.02:
                    arrow = "faster" if sc["tempo"] > 1 else "slower"
                    info(f"  {sid}: speech {natural:.2f}s -> window {target:.2f}s "
                         f"({arrow} x{sc['tempo']:.3f})")
            else:
                sc["tempo"] = 1.0
                sc["audio_duration"] = round(natural or target, 3)
                fitted = raw

            # --- build the per-scene padded audio block --------------------
            block = self.project.audio_dir / f"{sid}_full.wav"
            bkey = self._cache_key("block", sid, {"src": str(fitted.name), "head": head_ms,
                                                  "target": round(target, 3),
                                                  "pause": sc.get("extra_pause")})
            if not self._skip(bkey, block):
                head = self.project.tmp_dir / f"{sid}_head.wav"
                tail = self.project.tmp_dir / f"{sid}_tail.wav"
                tail_seconds = max(0.0, target - head_ms / 1000.0 - float(sc.get("audio_duration") or 0))
                tail_seconds += float(sc.get("extra_pause") or 0) + (
                    0.0 if fit else tail_ms / 1000.0
                )
                if not fitted.exists():
                    asm.make_silence(block, target)
                else:
                    asm.make_silence(head, head_ms / 1000.0)
                    tail_seconds = max(0.0, tail_seconds)
                    asm.make_silence(tail, max(0.05, tail_seconds))
                    pieces = [head, fitted] + ([tail] if tail_seconds > 0.02 else [])
                    # exact_duration pins this block to the timestamp window so
                    # the narration track can never drift away from the picture
                    asm.concat_audio(pieces, block, exact_duration=target)
                    head.unlink(missing_ok=True)
                    tail.unlink(missing_ok=True)
                self.manifest.mark(bkey, block)
            parts.append(block)

            # --- how long the RENDERED clip must be ------------------------
            is_last = (i == len(self.scenes) - 1)
            sc["extend_for_transition"] = 0.0 if (is_last or t_ext <= 0) else round(t_ext, 3)
            sc["clip_duration"] = round(float(sc["duration"]) + float(sc["extend_for_transition"]), 3)

        # --- rebuild absolute timeline ------------------------------------
        cursor = 0.0
        for sc in self.scenes:
            sc["start"] = round(cursor, 3)
            sc["end"] = round(cursor + float(sc.get("duration") or 0.0), 3)
            cursor = sc["end"]
        self.script.data["total_duration"] = round(cursor, 3)

        # --- the continuous narration track --------------------------------
        if parts:
            voice_full = self.project.voice_track
            vkey = self._cache_key("voicefull", "all", {
                "parts": [p.name for p in parts], "total": round(cursor, 3),
            })
            if not self._skip(vkey, voice_full):
                asm.concat_audio(parts, voice_full, exact_duration=max(cursor, 0.1))
                self.manifest.mark(vkey, voice_full)
            vdur = asm.probe_duration(voice_full)
            ok(f"narration track: {fmt_time(vdur)} ({human_bytes(voice_full.stat().st_size)})")
            drift = vdur - cursor
            if abs(drift) > 0.6:
                warn(f"narration is {drift:+.2f}s vs the picture timeline - "
                     f"check your timestamps add up")
        else:
            warn("no audio blocks were produced - the video will be silent")

        self.script.save()
        self.manifest.finish_stage("timing", {"total": self.script.data["total_duration"]})
        return self.scenes

    # ==================================================================
    # STAGE 4 - IMAGES
    # ==================================================================
    def stage_images(self) -> list[dict]:
        step("STAGE 4 / 10 - IMAGE GENERATION")
        self.manifest.start_stage("images")
        self._ensure_scenes()

        name = str(self.cfg.get("image.provider", "pollinations"))
        img = self.provider("image", name)
        alive, msg = img.healthcheck()
        if not alive:
            warn(f"image provider says: {msg}")
            if str(self.cfg.get("system.on_error", "continue")) == "abort":
                die("aborting because system.on_error is 'abort'")
            # The provider has already told us it cannot work right now - no
            # internet, no GPU, an expired tunnel. Retrying every scene five
            # times with growing pauses would turn a 30-second run into a
            # 10-minute one and change nothing, so: one attempt each, then the
            # scene falls back to its placeholder card. Set
            # image.batch_retries yourself if you want the slow version.
            if int(self.cfg.get("image.batch_retries", 3) or 3) > 1:
                self.cfg.set("image.batch_retries", 1)
                info("  (provider is unreachable: one attempt per scene from now on)")

        icfg = self.cfg.section("image")
        w, h = self.cfg.resolution()
        gen_w = int(icfg.get("width") or w)
        gen_h = int(icfg.get("height") or h)
        negative = str(icfg.get("negative_prompt") or "")
        steps = int(icfg.get("steps", 30))
        cfg_scale = float(icfg.get("cfg", 7.0))
        seed_mode = str(icfg.get("seed_mode", "random"))
        base_seed = int(icfg.get("seed", 12345))

        jobs: list[dict] = []
        for i, sc in enumerate(self.scenes):
            sid = sc["id"]
            out = self.project.scene_image(sid, "jpg")
            params = {
                "provider": name, "prompt": sc.get("image_prompt", ""),
                "w": gen_w, "h": gen_h, "steps": steps, "cfg": cfg_scale,
                "negative": negative, "model": icfg.get(f"{name}", {}).get("model", ""),
            }
            key = self._cache_key("image", sid, params)
            if self._skip(key, out):
                sc["image_path"] = str(out)
                debug(f"image {sid}: cached")
                continue
            if not self._wanted(sid):
                if out.exists():
                    sc["image_path"] = str(out)
                continue

            seed = None
            if seed_mode == "fixed":
                seed = base_seed + i
            elif seed_mode == "scene":
                seed = int(sc.get("seed") or 0) or None

            jobs.append({
                "scene_id": sid, "prompt": sc.get("image_prompt", ""),
                "out_path": out, "width": gen_w, "height": gen_h,
                "negative_prompt": negative, "steps": steps, "cfg_scale": cfg_scale,
                "seed": seed, "_key": key, "_index": i,
            })

        info(f"{len(jobs)} image(s) to generate ({len(self.scenes) - len(jobs)} already cached)")
        if not jobs:
            self._link_images()
            self.manifest.finish_stage("images", {"count": len(self.scenes)})
            return self.scenes

        # ------------------------------------------------------------------
        # DISPATCH: some providers like receiving every prompt at once (Vast,
        # Colab, Replicate). Others are happiest one image at a time, and for
        # those we run a small thread pool so we are not waiting serially.
        # ------------------------------------------------------------------
        clean_jobs = [{k: v for k, v in j.items() if not k.startswith("_")} for j in jobs]
        results: list[Any] = []

        if getattr(img, "supports_batch", False):
            try:
                results = img.generate_many(clean_jobs)
            except Exception as e:
                fail(f"batch generation failed: {str(e)[:200]} - trying one at a time")
                results = []

        if len(results) != len(jobs):
            results = self._generate_serial_or_threaded(img, jobs, results)

        for j, res in zip(jobs, results):
            if res and Path(res).exists():
                self.manifest.mark(j["_key"], res)
                self.scenes[j["_index"]]["image_path"] = str(res)
            else:
                fail(f"  {j['scene_id']}: no image produced")
                if str(self.cfg.get("system.on_error", "continue")) == "abort":
                    self.close_providers()
                    die("aborting (system.on_error: abort)")

        self._link_images()
        self.script.save()
        self.manifest.finish_stage("images", {"count": len(jobs)})
        return self.scenes

    def _generate_serial_or_threaded(self, img, jobs: list[dict],
                                     partial: list[Any]) -> list[Any]:
        """Fill in any missing results one at a time (optionally in parallel)."""
        results = list(partial) + [None] * (len(jobs) - len(partial))
        todo = [(i, j) for i, (j, r) in enumerate(zip(jobs, results)) if r is None]
        if not todo:
            return results

        workers = max(1, int(self.cfg.get("image.parallel_requests", 1)))
        # never hammer a free service with parallel requests
        if getattr(img, "supports_parallel", False) is False:
            workers = 1

        def one(pair):
            i, j = pair
            try:
                return i, img.generate(
                    j["prompt"], j["out_path"], width=j["width"], height=j["height"],
                    negative_prompt=j["negative_prompt"], steps=j["steps"],
                    cfg_scale=j["cfg_scale"], seed=j["seed"],
                )
            except Exception as e:
                fail(f"  {j['scene_id']}: {str(e)[:180]}")
                return i, None

        done = 0
        if workers > 1:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for i, res in pool.map(one, todo):
                    results[i] = res
                    done += 1
                    if res:
                        ok(f"  [{done}/{len(todo)}] {jobs[i]['scene_id']}")
        else:
            for pair in todo:
                i, res = one(pair)
                results[i] = res
                done += 1
                if res:
                    ok(f"  [{done}/{len(todo)}] {jobs[i]['scene_id']}")
        return results

    def _link_images(self) -> None:
        """Point every scene at its picture, and warn about holes."""
        missing = []
        for sc in self.scenes:
            p = self.project.scene_image(sc["id"], "jpg")
            p2 = self.project.scene_image(sc["id"], "png")
            found = p if p.exists() else (p2 if p2.exists() else None)
            if found:
                sc["image_path"] = str(found)
            else:
                sc["image_path"] = None
                missing.append(sc["id"])
        if missing:
            warn(f"no image for scene(s): {', '.join(missing)} - "
                 f"they will use a generated placeholder card")

    def placeholder_image(self, sc: dict, out_path: Path) -> Path:
        """
        If an image provider failed for a scene, we still produce a frame so
        the video renders end to end: a dark card with the scene number and
        the first words of narration. One bad image never kills a project.
        """
        ensure_dir(out_path.parent)
        w, h = self.cfg.resolution()
        out_path = out_path.with_suffix(".jpg")
        try:
            from .imaging import make_placeholder_card
            make_placeholder_card(
                out_path, width=w, height=h,
                heading=str(sc.get("id", "?")).upper(),
                body=(sc.get("narration") or "")[:110],
                font=self.cfg.get("subtitles.style.font"),
            )
        except Exception as e:
            warn(f"could not draw a placeholder card ({e}); using a plain dark frame")
            from .utils import run_cmd
            run_cmd([
                str(self.cfg.get("system.ffmpeg_bin", "ffmpeg")), "-y", "-hide_banner",
                "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=0x0d1117:s={w}x{h}:d=1",
                "-frames:v", "1", str(out_path),
            ], check=False, timeout=120)
        return out_path

    # ==================================================================
    # STAGE 5 - MOTION
    # ==================================================================
    def stage_motion(self) -> list[dict]:
        step("STAGE 5 / 10 - MOTION (Ken Burns pan & zoom)")
        self.manifest.start_stage("motion")
        self._ensure_scenes()

        engine = str(self.cfg.get("motion.engine", "ffmpeg"))
        asm = self.provider("assembly", engine)
        mcfg = self.cfg.section("motion")

        jobs = []
        for i, sc in enumerate(self.scenes):
            sid = sc["id"]
            if not self._wanted(sid):
                continue
            img = Path(sc.get("image_path") or self.project.scene_image(sid, "jpg"))
            if not img.exists():
                img = self.placeholder_image(sc, self.project.scene_image(sid, "png"))
            audio = self.project.audio_dir / f"{sid}_full.wav"
            if not audio.exists():
                audio = self.project.scene_audio(sid, "wav")

            dur = float(sc.get("clip_duration") or sc.get("duration") or 4.0)
            motion = str(sc.get("motion") or motion_for_index(i, str(mcfg.get("preset", "auto"))))
            out = self.project.scene_clip(sid)

            key = self._cache_key("motion", sid, {
                "image": img.name, "duration": round(dur, 3), "motion": motion,
                "engine": engine, "res": self.cfg.resolution(),
                "fps": self.cfg.get("video.fps"), "zoom": mcfg.get("zoom_amount"),
                "grade": mcfg.get("color_grade"), "vig": mcfg.get("add_vignette"),
                "audio": audio.name if audio.exists() else None,
            })
            if self._skip(key, out):
                sc["clip_path"] = str(out)
                debug(f"motion {sid}: cached")
                continue
            jobs.append((sc, img, audio, out, dur, motion, key))

        info(f"{len(jobs)} scene(s) to animate ({len(self.scenes) - len(jobs)} already cached)")

        forced = str(mcfg.get("preset", "auto"))
        if forced != "auto" and forced not in MOTION_PRESETS:
            warn(f"motion.preset '{forced}' is not a known preset - using zoom_in.\n"
                 f"  valid presets: {', '.join(sorted(MOTION_PRESETS))}")

        parallel = max(1, int(self.cfg.get("system.parallel_scenes", 1)))
        t0 = time.time()

        def do_job(job):
            sc, img, audio, out, dur, motion, key = job
            asm.render_scene_clip(
                image=img, audio=audio if audio.exists() else None, out_path=out,
                duration=dur, motion=motion,
            )
            return sc, out, key, dur

        done = 0
        if parallel > 1 and engine == "ffmpeg":
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                futures = [pool.submit(do_job, j) for j in jobs]
                for fut in as_completed(futures):
                    try:
                        sc, out, key, dur = fut.result()
                        self.manifest.mark(key, out, {"seconds": round(dur, 2)})
                        sc["clip_path"] = str(out)
                        done += 1
                        ok(f"  [{done}/{len(jobs)}] {out.name}  ({fmt_time(dur)})")
                    except Exception as e:
                        fail(f"  render failed: {str(e)[:200]}")
                        if str(self.cfg.get("system.on_error", "continue")) == "abort":
                            raise
        else:
            for j in jobs:
                try:
                    sc, out, key, dur = do_job(j)
                    self.manifest.mark(key, out, {"seconds": round(dur, 2)})
                    sc["clip_path"] = str(out)
                    done += 1
                    ok(f"  [{done}/{len(jobs)}] {out.name}  ({fmt_time(dur)})")
                except Exception as e:
                    fail(f"  {j[0]['id']} render failed: {str(e)[:220]}")
                    if str(self.cfg.get("system.on_error", "continue")) == "abort":
                        raise

        self.script.save()
        elapsed = time.time() - t0
        self.manifest.finish_stage("motion", {"clips": done, "seconds": round(elapsed, 1)})
        ok(f"{done} clip(s) rendered in {fmt_time(elapsed)}")
        return self.scenes

    # ==================================================================
    # STAGE 6 - TRANSITIONS / CONCAT
    # ==================================================================
    def stage_transition(self) -> Path:
        step("STAGE 6 / 10 - JOINING CLIPS (transitions)")
        self.manifest.start_stage("transition")
        self._ensure_scenes()

        engine = str(self.cfg.get("motion.engine", "ffmpeg"))
        asm = self.provider("assembly", engine)
        tcfg = self.cfg.section("transitions")

        clips: list[Path] = []
        for sc in self.scenes:
            p = Path(sc.get("clip_path") or self.project.scene_clip(sc["id"]))
            if p.exists():
                clips.append(p)
            else:
                warn(f"scene {sc['id']} has no rendered clip - it will be missing from the video")

        if not clips:
            die("No clips exist. Run the motion stage first:  python main.py motion <project>")

        out = self.project.silent_video
        key = self._cache_key("transition", "all", {
            "clips": [c.name for c in clips],
            "type": tcfg.get("type"), "dur": tcfg.get("duration"),
            "enabled": tcfg.get("enabled"), "vary": tcfg.get("vary"),
        })
        if self._skip(key, out):
            info("concat result is cached")
            self.manifest.finish_stage("transition")
            return out

        info(f"joining {len(clips)} clips with "
             f"{tcfg.get('type', 'crossfade')} transitions ({tcfg.get('duration', 0.45)}s) ...")
        t0 = time.time()
        path, real_dur = asm.concatenate(
            clips, out,
            transition=str(tcfg.get("type", "crossfade")),
            transition_duration=float(tcfg.get("duration", 0.45)),
            vary=bool(tcfg.get("vary", True)),
            enabled=bool(tcfg.get("enabled", True)),
        )

        target = float(self.script.data.get("total_duration") or 0)
        ok(f"silent video: {fmt_time(real_dur)} rendered in {fmt_time(time.time() - t0)}")
        if target and abs(real_dur - target) > 0.5:
            warn(f"picture is {real_dur:.2f}s but the script timeline says {target:.2f}s "
                 f"(difference {real_dur - target:+.2f}s). The final mux uses the shorter one.")
        self.script.data["video_duration"] = round(real_dur, 3)
        self.script.save()
        self.manifest.mark(key, path, {"duration": round(real_dur, 3)})
        self.manifest.finish_stage("transition", {"duration": round(real_dur, 3)})
        return path

    # ==================================================================
    # STAGE 7 - SUBTITLES
    # ==================================================================
    def stage_subtitles(self) -> Path | None:
        step("STAGE 7 / 10 - SUBTITLES")
        self.manifest.start_stage("subtitles")
        self._ensure_scenes()

        scfg = self.cfg.section("subtitles")
        if not scfg.get("enabled", True):
            info("subtitles disabled in config.yaml")
            self.manifest.finish_stage("subtitles", {"enabled": False})
            return None

        source = str(scfg.get("source", "word_boundaries"))
        cues = subs_stage.build_srt(self.scenes, self.cfg, source=source,
                                    words_dir=self.project.words_dir)
        if not cues:
            warn("no caption cues could be built")
            self.manifest.finish_stage("subtitles", {"cues": 0})
            return None

        srt = subs_stage.write_srt(cues, self.project.srt_file)
        key = self._cache_key("subs", "srt", {"cues": len(cues), "src": source,
                                              "last": cues[-1]["end"] if cues else 0})
        self.manifest.mark(key, srt, {"cues": len(cues)})

        # also write an ASS version - handy if you want karaoke colours later
        try:
            w, h = self.cfg.resolution()
            subs_stage.cues_to_ass(cues, self.project.ass_file,
                                   dict(scfg.get("style") or {}), play_w=w, play_h=h)
        except Exception as e:
            debug(f"ass export skipped: {e}")

        total_words = sum(len(c["text"].split()) for c in cues)
        ok(f"{len(cues)} caption cues ({total_words} words) -> {srt.relative_to(ROOT)}")
        info(f"  first: \"{cues[0]['text']}\" @ {cues[0]['start']:.2f}s")
        info(f"  last : \"{cues[-1]['text']}\" @ {cues[-1]['start']:.2f}s")
        self.manifest.finish_stage("subtitles", {"cues": len(cues)})
        return srt

    # ==================================================================
    # STAGE 8 - AUDIO MIX
    # ==================================================================
    def stage_mix(self) -> Path:
        step("STAGE 8 / 10 - AUDIO MIX (voice + music + mastering)")
        self.manifest.start_stage("mix")
        self._ensure_scenes()

        asm = self.provider("assembly", str(self.cfg.get("motion.engine", "ffmpeg")))
        voice = self.project.voice_track
        if not voice.exists():
            die("No narration track exists. Run the voice+timing stages first.")

        video_dur = float(self.script.data.get("video_duration")
                          or self.script.data.get("total_duration") or 0)
        voice_dur = asm.probe_duration(voice)
        duration = max(video_dur, voice_dur)
        if duration <= 0:
            die("Cannot determine the video length")

        music_src = audio_stage.pick_track(self.cfg, self.scenes)
        music = None
        if music_src:
            music = self.project.music_track
            mkey = self._cache_key("music", "prep", {"track": music_src.name,
                                                     "duration": round(duration, 2)})
            if not self._skip(mkey, music):
                audio_stage.prepare_music(asm, music_src, music, duration, self.cfg)
                self.manifest.mark(mkey, music)

        out = self.project.mix_track
        key = self._cache_key("mix", "final", {
            "voice": voice.name, "voice_dur": round(voice_dur, 2),
            "music": music_src.name if music_src else None,
            "duration": round(duration, 3),
            "audio_cfg": self.cfg.section("audio"),
        })
        if self._skip(key, out):
            info("mix is cached")
            self.manifest.finish_stage("mix")
            return out

        info(f"mixing {fmt_time(duration)} of audio"
             f"{' with music' if music else ' (no music)'} ...")
        asm.build_mix(voice=voice, music=music, out_path=out, duration=duration)
        self.manifest.mark(key, out, {"duration": round(duration, 2)})
        ok(f"final audio: {fmt_time(asm.probe_duration(out))} ({human_bytes(out.stat().st_size)})")
        self.manifest.finish_stage("mix", {"duration": round(duration, 2)})
        return out

    # ==================================================================
    # STAGE 9 - FINAL ASSEMBLY
    # ==================================================================
    def stage_assembly(self) -> Path:
        step("STAGE 9 / 10 - FINAL ASSEMBLY")
        self.manifest.start_stage("assembly")

        # load the scene list first: we update video_duration in script.json at
        # the end of this stage and must never clobber the real data
        self._load_scenes_soft()
        asm = self.provider("assembly", str(self.cfg.get("motion.engine", "ffmpeg")))
        video = self.project.silent_video
        audio = self.project.mix_track
        if not video.exists():
            die("No picture track. Run the transition stage first.")
        if not audio.exists():
            die("No audio mix. Run the mix stage first.")

        out = self.project.final_video
        ensure_dir(out.parent)

        sub_cfg = self.cfg.section("subtitles")
        sub_file = None
        if sub_cfg.get("enabled") and sub_cfg.get("burn_in"):
            # Prefer the ASS we generated ourselves: it carries the exact
            # PlayRes of this video, so font sizes mean what you configured.
            # Burning the .srt directly makes ffmpeg guess a 384px canvas and
            # blow the text up to absurd proportions.
            sub_file = self.project.ass_file if self.project.ass_file.exists() \
                else (self.project.srt_file if self.project.srt_file.exists() else None)
            if sub_file is None:
                warn("subtitles enabled but none exist yet - running the subtitle stage")
                self.stage_subtitles()
                sub_file = self.project.ass_file if self.project.ass_file.exists() \
                    else (self.project.srt_file if self.project.srt_file.exists() else None)

        wm = None
        wcfg = self.cfg.section("extras.watermark")
        if wcfg.get("enabled"):
            wm_path = ROOT / str(wcfg.get("image", "assets/watermark.png"))
            if wm_path.exists():
                wm = wm_path
            else:
                warn(f"watermark enabled but {wm_path} does not exist - skipping")

        key = self._cache_key("assembly", "final", {
            "video": video.name, "audio": audio.name,
            "subs": sub_file.name if sub_file else None, "sub_style": sub_cfg.get("style"),
            "wm": str(wm) if wm else None, "wmcfg": wcfg,
            "codec": self.cfg.get("video.codec"), "crf": self.cfg.get("video.crf"),
            "preset": self.cfg.get("video.preset"),
        })
        if self._skip(key, out):
            ok(f"final video already exists: {out.relative_to(ROOT)}")
            self.manifest.finish_stage("assembly")
            return out

        info("muxing picture + sound" + (" + burned-in captions" if sub_file else "") + " ...")
        t0 = time.time()
        asm.mux(video, audio, out, subtitles=sub_file,
                sub_style=dict(sub_cfg.get("style") or {}),
                watermark=wm, watermark_cfg=wcfg)

        # optional intro / outro
        io_cfg = self.cfg.section("extras.intro_outro")
        if io_cfg.get("enabled"):
            chain = []
            intro = ROOT / str(io_cfg.get("intro_video", ""))
            outro = ROOT / str(io_cfg.get("outro_video", ""))
            if intro.exists():
                chain.append(intro)
            chain.append(out)
            if outro.exists():
                chain.append(outro)
            if len(chain) > 1:
                info("attaching intro/outro")
                tmp = self.project.tmp_dir / "with_io.mp4"
                asm.concat_videos(chain, tmp)
                shutil.move(str(tmp), str(out))

        dur = asm.probe_duration(out)
        size = out.stat().st_size
        ok(f"FINAL VIDEO: {out.relative_to(ROOT)}")
        ok(f"  {fmt_time(dur)}  |  {human_bytes(size)}  |  rendered in {fmt_time(time.time() - t0)}")
        self.script.data["video_duration"] = round(dur, 3)
        self.script.save()
        self.manifest.mark(key, out, {"duration": round(dur, 2), "bytes": size})
        self.manifest.finish_stage("assembly", {"duration": round(dur, 2)})
        return out

    # ==================================================================
    # STAGE 10 - EXTRAS
    # ==================================================================
    def stage_extras(self) -> None:
        step("STAGE 10 / 10 - THUMBNAIL + YOUTUBE METADATA")
        self.manifest.start_stage("extras")
        self._load_scenes_soft()
        asm = self.provider("assembly", str(self.cfg.get("motion.engine", "ffmpeg")))
        video = self.project.final_video
        if not video.exists():
            warn("no final video yet - skipping extras")
            return

        # ---- thumbnail ---------------------------------------------------
        tcfg = self.cfg.section("extras.thumbnail")
        if tcfg.get("enabled", True):
            at = float(tcfg.get("at_seconds", 3.0))
            strategy = str(tcfg.get("strategy", "best_scene"))
            if strategy == "scene_index":
                idx = min(int(tcfg.get("scene_index", 0)), len(self.scenes) - 1)
                at = float(self.scenes[idx].get("start", 0)) + 0.5
            title = None
            if tcfg.get("add_title_text"):
                words = str(self.script.data.get("title", "")).split()
                title = " ".join(words[:int(tcfg.get("title_max_words", 5))])
            try:
                asm.thumbnail(video, self.project.thumbnail, at_seconds=at, title=title)
                ok(f"thumbnail: {self.project.thumbnail.relative_to(ROOT)}")
            except Exception as e:
                warn(f"thumbnail failed: {str(e)[:160]}")

        # ---- youtube metadata --------------------------------------------
        mcfg = self.cfg.section("extras.metadata")
        if mcfg.get("enabled", True):
            meta = self._build_metadata()
            write_json(self.project.metadata_file, meta)
            ok(f"metadata: {self.project.metadata_file.relative_to(ROOT)}")
            info(f"  title: {meta.get('title', '')[:80]}")

        self.manifest.finish_stage("extras")

    def _build_metadata(self) -> dict:
        """Ask the LLM for title/description/tags/chapters. Falls back to local data."""
        base = {
            "title": self.script.data.get("title", "Untitled"),
            "description": self.script.data.get("description", ""),
            "tags": self.script.data.get("tags", []) or [],
            "chapters": self.script.chapters(),
            "duration": self.script.data.get("video_duration"),
            "language": self.script.data.get("language", "English"),
        }
        llm_name = str(self.cfg.get("llm.provider", "")).lower()
        if llm_name in ("manual", "none", ""):
            return base
        # IMPORTANT: providers call die() when they are not configured, and
        # die() raises SystemExit. Without the guard below, a missing API key
        # would print a full "how to fix this" essay in the middle of a
        # successful build and - worse - `except Exception` would not catch
        # it. Metadata is a nice-to-have, never a reason to frighten anyone.
        # The provider's noisy setup message is also silenced here, because a
        # clean one-line fallback note is what a user deserves.
        import contextlib as _ctx
        # Everything below runs with stdout captured, because providers explain
        # themselves at length when they are not configured ("here is where to
        # get a key, and here is what to put in .env..."). That speech is
        # genuinely helpful when you asked for it and pure noise when it lands
        # in the middle of an otherwise successful build. We keep the meaning
        # and drop the volume: one calm line, printed by the except block.
        noise = io.StringIO()
        try:
            with _ctx.redirect_stdout(noise), _ctx.redirect_stderr(noise):
                from .script import load_prompt_file
                llm = self.provider("llm", llm_name)
                tpl = load_prompt_file(
                    self.cfg.get("llm.prompt_files.metadata", "prompts/metadata.txt"))
                prompt = (tpl
                          .replace("{title}", str(base["title"]))
                          .replace("{duration}", str(base["duration"]))
                          .replace("{scenes}", json.dumps(
                              [{"t": s.get("start"), "text": (s.get("narration") or "")[:160]}
                               for s in self.scenes], ensure_ascii=False)))
                raw = llm.chat([{"role": "user", "content": prompt}],
                               json_mode=True, temperature=0.7)
            data = json.loads(raw) if raw.strip().startswith("{") else extract_json_local(raw)
            if isinstance(data, dict):
                base["title"] = str(data.get("title") or base["title"])[:100]
                base["description"] = str(data.get("description") or base["description"])[:4000]
                base["tags"] = [str(t)[:30] for t in (data.get("tags") or base["tags"])][:25]
                base["hashtags"] = [str(h) for h in (data.get("hashtags") or [])][:6]
                base["generated_by"] = llm_name
        except (Exception, SystemExit) as e:
            # A missing key is the normal state on a first run, so say it once,
            # calmly, and carry on with the title and description already in
            # the script. Metadata is never a reason to frighten anyone.
            why = "no LLM configured" if isinstance(e, SystemExit) else str(e)[:120]
            info(f"YouTube metadata written from your script "
                 f"(title, chapters, description) - {why}")
        return base

    # ==================================================================
    # HELPERS
    # ==================================================================
    def _load_scenes_soft(self) -> None:
        """Load scenes if a script exists, without dying when it does not."""
        if not self.scenes:
            if self.script.load():
                self.scenes = self.script.data.get("scenes", [])

    def _ensure_scenes(self) -> None:
        if not self.scenes:
            if not self.script.load():
                die(
                    f"No script.json in {self.project.dir}.\n"
                    "Run the script stage first:\n"
                    '    python main.py script "my video" --topic "..." \n'
                    '    python main.py script "my video" --script my_script.txt'
                )
            self.scenes = self.script.data.get("scenes", [])
            self._apply_meta_overrides()
        if not self.scenes:
            die("script.json exists but contains no scenes")

    # ==================================================================
    # RUN EVERYTHING
    # ==================================================================
    def run_all(self, *, topic: str | None = None, script_file: Path | None = None,
                duration: float | None = None, style: str = "",
                extra_instructions: str = "") -> Path:
        t0 = time.time()
        try:
            self.stage_script(topic=topic, script_file=script_file, duration=duration,
                              style=style, extra_instructions=extra_instructions)
            self.stage_voice()
            self.stage_timing()
            self.stage_images()
            self.stage_motion()
            self.stage_transition()
            self.stage_subtitles()
            self.stage_mix()
            out = self.stage_assembly()
            self.stage_extras()
        finally:
            self.close_providers()

        elapsed = time.time() - t0
        self.manifest.log_run("run_all", elapsed, ok=True)
        step("DONE")
        ok(f"video  : {out}")
        ok(f"time   : {fmt_time(elapsed)}")
        try:
            ok(f"size   : {human_bytes(out.stat().st_size)}")
        except Exception:
            pass
        info(f"project folder: {self.project.dir}")
        return out

    # ------------------------------------------------------------------
    def cleanup(self, *, keep_final: bool = True) -> int:
        """Delete intermediate files to reclaim disk space."""
        freed = 0
        targets = [self.project.clips_dir, self.project.trans_dir, self.project.tmp_dir]
        if not keep_final:
            targets += [self.project.images_dir, self.project.audio_dir]
        for d in targets:
            for p in Path(d).rglob("*"):
                if p.is_file():
                    try:
                        freed += p.stat().st_size
                        p.unlink()
                    except Exception:
                        pass
        self.manifest.reset()
        return freed


def extract_json_local(text: str):
    from .utils import extract_json
    return extract_json(text)
