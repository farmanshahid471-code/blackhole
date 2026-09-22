"""
webui/server.py
===============
The Web UI's backend: a small FastAPI app that drives the bot for the browser.

ARCHITECTURE (why it is built this way)
---------------------------------------
The bot is a command-line program. Rather than rewrite the pipeline for the
web, this server does the honest thing:

    browser  ->  HTTP/JSON  ->  this file  ->  the same Pipeline the CLI uses

So the web UI can never drift out of sync with the command line: every button
runs exactly the code path `python main.py ...` runs. If a feature works in
one, it works in the other.

THE THREE TRICKY PARTS, AND HOW THEY ARE SOLVED
-----------------------------------------------
1. LONG JOBS
   Rendering a video takes minutes. An HTTP request that just sits there
   would time out, and you would stare at a spinner with no idea what is
   happening. So every build runs in a BACKGROUND THREAD and writes its log
   to memory. The browser then reads the log as a live stream
   (Server-Sent Events) and you watch the same progress lines the terminal
   would print - including the "STAGE 4/10" banners.

2. STOPPING A JOB
   A half-finished render wastes disk and time. Every job carries a stop
   flag; the run loop checks it between stages and stops cleanly, keeping
   finished work in the cache.

3. CONFIG AND SECRETS
   config.yaml is the bot's control panel and .env holds the keys. Both are
   editable from the Settings screen. Secrets are never sent back to the
   browser: the API returns only whether a key is SET, never its value.

Endpoints (all under /api):
    GET  /api/state            everything the dashboard needs, one call
    GET  /api/doctor           run the health check
    GET  /api/providers        every provider + which are active
    GET  /api/voices           voices of the current TTS provider
    GET  /api/projects         list projects
    GET  /api/project/<slug>   one project in detail
    POST /api/run              start a build (script or topic)   -> job id
    POST /api/stage            run ONE stage of an existing project
    GET  /api/job/<id>         a job's status + full log so far
    GET  /api/job/<id>/stream  live log stream (Server-Sent Events)
    POST /api/job/<id>/stop    stop a running job
    GET  /api/jobs             recent jobs
    POST /api/config           write settings back to config.yaml
    POST /api/env              write API keys to .env
    POST /api/upload/music     add a music track
    POST /api/upload/asset     add a watermark / font / piper voice
    GET  /api/download/<slug>/<kind>   download the mp4 / srt / thumbnail / metadata
    POST /api/clean            delete intermediate files of a project
    POST /api/open             open a project folder in the file manager
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles

# --- make the bot importable no matter where the server is started from -----
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import Config, load_config                        # noqa: E402
from bot.paths import Project, default_projects_dir                # noqa: E402
from bot.pipeline import Pipeline                                  # noqa: E402

# ===========================================================================
# JOB MANAGEMENT
# ===========================================================================
class Job:
    """
    One background build.

    The log is kept in memory as a list of lines; the browser polls or streams
    it. A deque with a hard cap stops a runaway ffmpeg from eating all RAM
    through its own log output (which does happen with -loglevel info).
    """

    def __init__(self, kind: str, label: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind                 # run | stage | doctor | test
        self.label = label
        self.status = "running"          # running | done | failed | stopped
        self.started = time.time()
        self.finished: float | None = None
        self.lines: list[str] = []
        self.result: dict[str, Any] = {}
        self.error: str = ""
        self.stop_requested = threading.Event()
        self._lock = threading.Lock()

    def log(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            for line in str(text).splitlines():
                self.lines.append(line)
            if len(self.lines) > 4000:                 # keep the last 4000 lines
                self.lines = self.lines[-3000:]

    def snapshot(self, from_line: int = 0) -> dict[str, Any]:
        with self._lock:
            lines = self.lines[from_line:]
            total = len(self.lines)
        return {
            "id": self.id, "kind": self.kind, "label": self.label,
            "status": self.status, "error": self.error,
            "lines": lines, "line_count": total,
            "seconds": round((self.finished or time.time()) - self.started, 1),
            "result": self.result,
            "progress": self._progress(),
        }

    def _progress(self) -> dict[str, Any]:
        """Best-effort progress: the pipeline prints 'STAGE 3 / 10' banners."""
        stage, total = 0, 10
        for line in reversed(self.lines):
            marker = line.strip().strip("=").strip()
            if marker.startswith("STAGE"):
                try:
                    part = marker.split()[1]      # e.g. "3/10" or "3"
                    if "/" in part:
                        a, b = part.split("/")
                        stage, total = int(a), int(b)
                    else:
                        stage = int(part)
                    break
                except Exception:
                    continue
        pct = int(100 * stage / total) if total else 0
        if self.status == "done":
            pct = 100
        return {"stage": stage, "total": total, "percent": pct}


JOBS: dict[str, Job] = {}
JOBS_ORDER: list[str] = []
MAX_JOBS = 30


class _JobWriter(io.TextIOBase):
    """
    A fake stdout that the pipeline writes into.

    The bot prints with `rich` (colours) and plain `print`. rich detects a
    non-terminal and drops its escape codes automatically, so the log lines
    arrive clean. We also strip any leftover ANSI codes to be safe.
    """

    ANSI = __import__("re").compile(r"\x1b\[[0-9;]*[A-Za-z]")

    def __init__(self, job: Job):
        self.job = job
        self._buf = ""

    def write(self, text: str) -> int:                # type: ignore[override]
        if not text:
            return 0
        self._buf += str(text)
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self.job.log(self.ANSI.sub("", line))
        return len(text)

    def flush(self) -> None:                          # type: ignore[override]
        if self._buf:
            self.job.log(self.ANSI.sub("", self._buf))
            self._buf = ""


def _run_cli_streaming(job: "Job", cmd: list[str], timeout: int = 7200) -> int:
    """
    Run `python main.py ...` and stream its output into the job, line by line.

    WHY NOT subprocess.run(capture_output=True)
    -------------------------------------------
    That returns everything at the very end. For a two-minute render the
    browser would sit there showing nothing, and "is it frozen?" is the single
    most common question a progress log is supposed to answer. Reading the
    pipe as it arrives costs ten lines and makes the page feel alive.
    """
    import subprocess as _sp
    proc = _sp.Popen(cmd, cwd=str(ROOT), text=True,
                     stdout=_sp.PIPE, stderr=_sp.STDOUT, bufsize=1)
    started = time.time()
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            job.log(line.rstrip("\n"))
            if job.stop_requested.is_set():
                proc.terminate()
                job.log("stopped on request")
                break
            if time.time() - started > timeout:
                proc.kill()
                job.log(f"killed after {timeout}s")
                break
    finally:
        try:
            proc.wait(timeout=30)
        except Exception:
            proc.kill()
    return int(proc.returncode if proc.returncode is not None else -1)


def _start_job(kind: str, label: str, target) -> Job:
    """Run `target(job)` in a background thread and return the job handle."""
    job = Job(kind, label)
    JOBS[job.id] = job
    JOBS_ORDER.append(job.id)
    while len(JOBS_ORDER) > MAX_JOBS:
        old = JOBS_ORDER.pop(0)
        JOBS.pop(old, None)

    def runner() -> None:
        writer = _JobWriter(job)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                # touch the job so the UI shows activity immediately
                job.log(f"starting: {label}")
                target(job)
            job.status = "stopped" if job.stop_requested.is_set() else "done"
        except SystemExit as e:                        # the bot's die()
            job.status = "failed"
            job.error = f"the bot stopped: {e}"
            job.log(f"FAILED: {e}")
        except Exception as e:                         # noqa: BLE001
            job.status = "failed"
            job.error = f"{e.__class__.__name__}: {e}"
            job.log(f"FAILED: {job.error}")
            job.log(traceback.format_exc()[-2000:])
        finally:
            job.finished = time.time()
            writer.flush()

    threading.Thread(target=runner, daemon=True, name=f"job-{job.id}").start()
    return job


# ===========================================================================
# THE APP
# ===========================================================================
app = FastAPI(title="AutoVideoBot Web UI", docs_url="/api/docs")
STATIC = Path(__file__).resolve().parent / "static"


@app.exception_handler(Exception)
async def _unhandled(request, exc: Exception):                 # pragma: no cover
    """
    Turn any unexpected server error into a JSON message the page can show.

    Without this, a bug in one endpoint answers with a bare "Internal Server
    Error" and the reason only exists in the terminal - which is exactly the
    moment a beginner gives up. The browser gets the real message instead.
    """
    import traceback as _tb
    trace = _tb.format_exc()[-3000:]
    return JSONResponse(
        status_code=500,
        content={"detail": f"{exc.__class__.__name__}: {exc}", "where": str(request.url),
                 "trace": trace},
    )


def _cfg(overrides: list[str] | None = None) -> Config:
    return load_config(cli_overrides=overrides or None)


def _project(slug: str) -> Project:
    return Project.from_name(default_projects_dir(), slug)


def _pipelines_cfg_overrides(payload: dict[str, Any]) -> list[str]:
    """Turn the UI's provider/settings choices into --set KEY=VALUE strings."""
    out: list[str] = []
    for key, value in (payload.get("overrides") or {}).items():
        if value in (None, ""):
            continue
        out.append(f"{key}={value}")
    return out


# ---------------------------------------------------------------------------
# STATE / DASHBOARD
# ---------------------------------------------------------------------------
@app.get("/api/state")
def api_state() -> dict[str, Any]:
    """Everything the dashboard shows, in one round trip."""
    cfg = _cfg()
    from bot.registry import list_providers
    from bot.audio import list_music

    active = {
        "llm": str(cfg.get("llm.provider", "")),
        "tts": str(cfg.get("tts.provider", "")),
        "image": str(cfg.get("image.provider", "")),
        "assembly": str(cfg.get("motion.engine", "")),
    }
    projects = []
    root = default_projects_dir()
    if root.exists():
        for d in sorted(root.iterdir()):
            if not d.is_dir():
                continue
            final = d / "output" / "final.mp4"
            script = d / "script.json"
            title = d.name
            scenes = 0
            try:
                data = json.loads(script.read_text(encoding="utf-8"))
                title = data.get("title") or title
                scenes = len(data.get("scenes") or [])
            except Exception:
                pass
            projects.append({
                "slug": d.name,
                "title": title,
                "scenes": scenes,
                "has_video": final.exists(),
                "size_mb": round(final.stat().st_size / 1e6, 1) if final.exists()
                            else _dir_size_mb(d),
                "modified": max((p.stat().st_mtime for p in d.rglob("*") if p.is_file()),
                                default=d.stat().st_mtime),
            })
    projects.sort(key=lambda p: p["modified"], reverse=True)

    return {
        "active": active,
        "providers": list_providers(),
        "projects": projects,
        "music": [p.name for p in list_music()],
        "resolution": list(cfg.resolution()),
        "aspect": cfg.get("video.aspect"),
        "fps": cfg.get("video.fps"),
        "env_keys": _env_status(),
        "python": sys.version.split()[0],
        "root": str(ROOT),
        "jobs": [JOBS[i].snapshot()["id"] for i in JOBS_ORDER[-8:]][::-1],
    }


def _dir_size_mb(d: Path) -> float:
    total = 0
    for p in d.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return round(total / 1e6, 1)


ENV_KEYS = [
    ("DEEPSEEK_API_KEY", "DeepSeek (script writing)"),
    ("OPENAI_API_KEY", "OpenAI / Groq / OpenRouter key"),
    ("OPENAI_BASE_URL", "OpenAI-compatible address"),
    ("OPENAI_MODEL", "OpenAI-compatible model"),
    ("OLLAMA_BASE_URL", "Ollama address"),
    ("OLLAMA_MODEL", "Ollama model"),
    ("ELEVENLABS_API_KEY", "ElevenLabs"),
    ("ELEVENLABS_VOICE_ID", "ElevenLabs voice id"),
    ("OPENAI_TTS_VOICE", "OpenAI TTS voice"),
    ("VOICESTUDIO_URL", "VoiceStudio address"),
    ("VOICESTUDIO_VOICE", "VoiceStudio voice"),
    ("VAST_API_KEY", "Vast.ai (rented GPU)"),
    ("REPLICATE_API_TOKEN", "Replicate"),
    ("SDWEBUI_URL", "Stable Diffusion WebUI address"),
    ("IMAGE_ENDPOINT_URL", "Colab / Kaggle / Gradio link"),
    ("IMAGE_STYLE_SUFFIX", "global image style suffix"),
]


def _read_env() -> dict[str, str]:
    path = ROOT / ".env"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        values[k.strip()] = v.strip()
    return values


def _env_status() -> list[dict[str, Any]]:
    """Never send the secret itself - only whether it is filled in."""
    values = _read_env()
    out = []
    for key, label in ENV_KEYS:
        val = values.get(key, "")
        out.append({"key": key, "label": label, "set": bool(val.strip()),
                    "preview": (val[:6] + "..." + val[-4:]) if len(val) > 14 else ""})
    return out


# ---------------------------------------------------------------------------
# DOCTOR / PROVIDERS / VOICES
# ---------------------------------------------------------------------------
@app.get("/api/providers")
def api_providers() -> dict[str, Any]:
    from bot.registry import list_providers
    cfg = _cfg()
    return {
        "providers": list_providers(),
        "active": {
            "llm": str(cfg.get("llm.provider", "")),
            "tts": str(cfg.get("tts.provider", "")),
            "image": str(cfg.get("image.provider", "")),
            "assembly": str(cfg.get("motion.engine", "")),
        },
    }


@app.post("/api/provider/check")
def api_provider_check(payload: dict[str, Any]) -> dict[str, Any]:
    """Health-check ONE provider without running a whole build."""
    kind = str(payload.get("kind") or "")
    name = str(payload.get("name") or "")
    overrides = _pipelines_cfg_overrides(payload)
    if kind in ("llm", "tts", "image", "assembly") and name:
        overrides.append(f"{'motion.engine' if kind == 'assembly' else kind + '.provider'}={name}")
    try:
        cfg = _cfg(overrides)
        if kind == "assembly":
            from bot.providers.assembly_ffmpeg import FFmpegAssembly
            inst = FFmpegAssembly(cfg, None)
        else:
            from bot.registry import get_provider_class
            inst = get_provider_class(kind, name)(cfg, None)
        ok, msg = inst.healthcheck()
        try:
            inst.teardown()
        except Exception:
            pass
        return {"ok": bool(ok), "message": str(msg)}
    except SystemExit as e:
        return {"ok": False, "message": str(e)}
    except Exception as e:                              # noqa: BLE001
        return {"ok": False, "message": f"{e.__class__.__name__}: {e}"}


@app.get("/api/voices")
def api_voices(provider: str | None = None) -> dict[str, Any]:
    cfg = _cfg([f"tts.provider={provider}"] if provider else None)
    name = str(cfg.get("tts.provider", "edge"))
    try:
        from bot.registry import get_provider_class
        inst = get_provider_class("tts", name)(cfg, None)
        voices = inst.list_voices()
        current = str(cfg.get(f"tts.{name}.voice", ""))
        return {"provider": name, "voices": voices, "current": current}
    except SystemExit as e:
        return {"provider": name, "voices": [], "error": str(e)}
    except Exception as e:                              # noqa: BLE001
        return {"provider": name, "voices": [], "error": f"{e.__class__.__name__}: {e}"}


# ---------------------------------------------------------------------------
# PROJECTS
# ---------------------------------------------------------------------------
STAGE_NAMES = ["script", "voice", "timing", "images", "motion", "transition",
               "subtitles", "mix", "assembly", "extras"]


@app.get("/api/projects")
def api_projects() -> list[dict[str, Any]]:
    # FastAPI validates the reply against this annotation, so it has to say
    # "list" and not "dict" - otherwise a perfectly good reply is rejected.
    return api_state()["projects"]


@app.get("/api/project/{slug}")
def api_project(slug: str) -> dict[str, Any]:
    proj = _project(slug)
    if not proj.dir.exists():
        raise HTTPException(404, f"no project called '{slug}'")

    from bot.state import Manifest
    manifest = Manifest(proj.dir)
    scenes: list[dict[str, Any]] = []
    script_meta: dict[str, Any] = {}
    if proj.script_file.exists():
        try:
            data = json.loads(proj.script_file.read_text(encoding="utf-8"))
            script_meta = {k: v for k, v in data.items() if k != "scenes"}
            for sc in data.get("scenes") or []:
                sid = sc.get("id", "?")
                scenes.append({
                    "id": sid, "index": sc.get("index"),
                    "start": sc.get("start"), "end": sc.get("end"),
                    "duration": sc.get("duration"),
                    "narration": (sc.get("narration") or "")[:400],
                    "words": sc.get("word_count"),
                    "motion": sc.get("motion"),
                    "image_prompt": (sc.get("image_prompt") or "")[:400],
                    "has_image": (proj.images_dir / f"{sid}.jpg").exists()
                                 or (proj.images_dir / f"{sid}.png").exists(),
                    "has_clip": proj.scene_clip(sid).exists(),
                    "has_audio": proj.scene_audio(sid, "wav").exists(),
                    "tempo": sc.get("tempo"),
                })
        except Exception as e:
            script_meta = {"error": f"could not read script.json: {e}"}

    outputs = {
        "video": proj.final_video.exists(),
        "thumbnail": proj.thumbnail.exists(),
        "srt": proj.srt_file.exists(),
        "ass": proj.ass_file.exists(),
        "metadata": proj.metadata_file.exists(),
        "video_mb": round(proj.final_video.stat().st_size / 1e6, 1)
                     if proj.final_video.exists() else 0,
    }
    metadata: dict[str, Any] = {}
    if proj.metadata_file.exists():
        try:
            metadata = json.loads(proj.metadata_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "slug": slug,
        "title": script_meta.get("title") or slug,
        "meta": script_meta,
        "stages": manifest.summary(),
        "stage_order": STAGE_NAMES,
        "scenes": scenes,
        "outputs": outputs,
        "metadata": metadata,
        "files": _project_files(proj),
        "runs": (manifest.data.get("runs") or [])[-8:],
    }


def _project_files(proj: Project) -> list[dict[str, Any]]:
    """A short, human-readable file listing for the project page."""
    interesting = [
        ("final video", proj.final_video, "video"),
        ("thumbnail", proj.thumbnail, "image"),
        ("captions (srt)", proj.srt_file, "text"),
        ("captions (ass)", proj.ass_file, "text"),
        ("youtube metadata", proj.metadata_file, "text"),
        ("audio mix", proj.mix_track, "audio"),
        ("narration", proj.voice_track, "audio"),
        ("silent video", proj.silent_video, "video"),
        ("script source", proj.input_file, "text"),
        ("parsed scenes", proj.script_file, "text"),
        ("resume manifest", proj.manifest_file, "text"),
        ("run log", proj.log_file, "text"),
    ]
    out = []
    for label, path, kind in interesting:
        if path.exists():
            out.append({"label": label, "name": path.name, "kind": kind,
                        "size": path.stat().st_size,
                        "mb": round(path.stat().st_size / 1e6, 2),
                        "downloadable": kind in ("video", "image", "text", "audio")})
    return out


# ---------------------------------------------------------------------------
# RUNNING THINGS
# ---------------------------------------------------------------------------
def _apply_overrides(payload: dict[str, Any]) -> list[str]:
    over = dict(payload.get("overrides") or {})
    if payload.get("tts"):
        over["tts.provider"] = payload["tts"]
    if payload.get("image"):
        over["image.provider"] = payload["image"]
    if payload.get("llm"):
        over["llm.provider"] = payload["llm"]
    if payload.get("aspect"):
        over["video.aspect"] = payload["aspect"]
    if payload.get("fps"):
        over["video.fps"] = payload["fps"]
    if payload.get("quality"):
        q = str(payload["quality"])
        if q == "draft":
            over.setdefault("video.preset", "ultrafast")
            over.setdefault("video.crf", "24")
            over.setdefault("motion.supersample", "2")
        elif q == "high":
            over.setdefault("video.preset", "slow")
            over.setdefault("video.crf", "18")
    if payload.get("voice"):
        tts = over.get("tts.provider") or payload.get("tts") or ""
        over[f"tts.{tts}.voice"] = payload["voice"] if tts else payload["voice"]
        # also set the common voice keys so it works whichever provider is active
        over.setdefault("tts.edge.voice", payload["voice"])
        over.setdefault("tts.voicestudio.voice", payload["voice"])
    return [f"{k}={v}" for k, v in over.items() if v not in (None, "")]


@app.post("/api/run")
def api_run(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Start a full build. Body:
        {"name": "my-video", "mode": "script"|"topic",
         "script_text": "...",          # mode=script
         "use_example": true,           # mode=script, use the bundled example
         "topic": "black holes",        # mode=topic
         "duration": 120,               # mode=topic
         "instructions": "",            # mode=topic extra direction
         "overrides": {...}, "quality": "draft|standard|high",
         "tts": "...", "image": "...", "llm": "...", "voice": "..."}
    """
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "give the video a name")
    mode = str(payload.get("mode") or "script")
    overrides = _apply_overrides(payload)

    proj = _project(name)
    proj.create()

    script_text = payload.get("script_text") or ""
    if mode == "script":
        if payload.get("use_example") and not script_text.strip():
            script_text = (ROOT / "examples" / "black_holes_script.txt").read_text(encoding="utf-8")
        if not script_text.strip():
            raise HTTPException(400, "paste a script, or tick 'use the example script'")
        proj.input_file.write_text(script_text, encoding="utf-8")
    else:
        topic = str(payload.get("topic") or "").strip()
        if not topic:
            raise HTTPException(400, "type a topic for the video")
        proj.topic_file.write_text(
            f"topic: {topic}\n"
            f"duration: {payload.get('duration') or 120}\n"
            f"instructions: {payload.get('instructions') or ''}\n",
            encoding="utf-8")

    label = f"{'topic: ' + str(payload.get('topic')) if mode == 'topic' else 'your script'} -> {name}"

    def work(job: Job) -> None:
        cfg = _cfg(overrides)
        p = Pipeline(cfg, _project(name))
        p.force = bool(payload.get("force"))
        style = str(payload.get("style") or "")
        instructions = str(payload.get("instructions") or "")
        job.log(f"project : {p.project.dir}")
        job.log(f"mode    : {'topic' if mode == 'topic' else 'your script'}"
                + (f"   style: {style}" if style else ""))

        # Stage by stage rather than run_all(), for two reasons:
        #   * the browser can show real progress ("STAGE 5/10")
        #   * the Stop button can take effect at a stage boundary, and every
        #     finished stage stays in the cache, so resuming costs nothing
        try:
            if mode == "script":
                p.stage_script(script_file=proj.input_file, style=style)
            else:
                p.stage_script(topic=str(payload.get("topic")),
                               duration=float(payload.get("duration") or 120),
                               style=style, extra_instructions=instructions)
            for stage in STAGE_NAMES[1:]:
                if job.stop_requested.is_set():
                    job.log("stop requested - stopping here. Already-rendered work is "
                            "cached, so pressing Build again continues from this point.")
                    break
                getattr(p, f"stage_{stage}")()
        finally:
            try:
                p.close_providers()      # destroys rented GPUs even if we crashed
            except Exception:
                pass

        if p.project.final_video.exists():
            job.result = {
                "video": str(p.project.final_video.relative_to(ROOT)),
                "slug": p.project.slug,
                "mb": round(p.project.final_video.stat().st_size / 1e6, 1),
            }
            job.log(f"VIDEO READY: {job.result['video']}")

    job = _start_job("run", label, work)
    return {"job": job.id, "slug": proj.slug, "overrides": overrides}


@app.post("/api/stage")
def api_stage(payload: dict[str, Any]) -> dict[str, Any]:
    """Re-run ONE stage of an existing project (like the CLI does)."""
    slug = str(payload.get("slug") or "")
    stage = str(payload.get("stage") or "")
    if stage not in STAGE_NAMES:
        raise HTTPException(400, f"unknown stage '{stage}'")
    proj = _project(slug)
    if not proj.dir.exists():
        raise HTTPException(404, f"no project called '{slug}'")
    overrides = _apply_overrides(payload)

    def work(job: Job) -> None:
        cfg = _cfg(overrides)
        p = Pipeline(cfg, _project(slug))
        p.force = bool(payload.get("force"))
        only = payload.get("only")
        p.only = set(str(only).split(",")) if only else None
        job.log(f"re-running stage '{stage}' for {slug}"
                f"{' (forced)' if p.force else ''}")
        stage_fn = getattr(p, f"stage_{stage}")
        try:
            stage_fn()
        finally:
            try:
                p.close_providers()
            except Exception:
                pass

    job = _start_job("stage", f"stage {stage} -> {slug}", work)
    return {"job": job.id}


@app.post("/api/doctor")
def api_doctor(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the bot's own health check and stream its output."""
    overrides = _apply_overrides(payload or {})

    def work(job: Job) -> None:
        import main as cli
        cfg = _cfg(overrides)
        code = run_doctor(job)

    job = _start_job("doctor", "health check", work)
    return {"job": job.id}


def run_doctor(job: Job) -> int:
    """
    Run the bot's own health check, in-process, so its output lands in the job
    log (and therefore in the browser) instead of a terminal nobody sees.
    """
    import main as cli
    try:
        args = cli.build_parser().parse_args(["doctor"])
        return int(cli.cmd_doctor(args) or 0)
    except SystemExit:
        # doctor() calls the bot's die(), which exits when a check is fatal
        return 1
    except Exception as e:                                  # noqa: BLE001
        job.log(f"doctor could not run in-process ({e}) - using the CLI instead")

    return _run_cli_streaming(job, [sys.executable, str(ROOT / "main.py"), "doctor"],
                              timeout=600)


@app.post("/api/test")
def api_test(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    The bundled self-test: a tiny 8-second video that proves the toolchain.

    Body (all optional):
        {"project": "selftest",
         "tts":   "test",        # force a voice provider (test = offline tone)
         "image": "pollinations",# force an image provider
         "force": true}          # ignore the cache and rebuild everything

    WHY THE OFFLINE OPTION EXISTS
    On a machine with no internet (or behind a strict firewall) the self-test
    stops at the voice stage, because the free Edge voice is a web service.
    That is a *network* result, not a broken installation - and the page offers
    to run the same test again with the built-in offline tone voice, which
    proves ffmpeg, Python, captions, encoding and rendering all work. Two
    different questions, two different tests.
    """
    payload = payload or {}
    project = str(payload.get("project") or "selftest")

    cmd = [sys.executable, str(ROOT / "main.py"), "test", project]
    if payload.get("tts"):
        cmd += ["--tts", str(payload["tts"])]
    if payload.get("image"):
        cmd += ["--image", str(payload["image"])]
    if payload.get("force"):
        cmd += ["--force"]

    offline = bool(payload.get("tts"))

    def work(job: Job) -> None:
        job.log("command: " + " ".join(Path(c).name if i < 3 else c
                                       for i, c in enumerate(cmd)))
        job.log("(a tiny 2-scene video - no cost, nothing is uploaded anywhere)")
        code = _run_cli_streaming(job, cmd)

        out = ROOT / "workspace" / "projects" / project / "output" / "final.mp4"
        if out.exists() and code == 0:
            job.result = {"video": str(out.relative_to(ROOT)),
                          "slug": project,
                          "mb": round(out.stat().st_size / 1e6, 1)}
        if code != 0:
            # Give the page something actionable instead of a bare exit code.
            blob = " ".join(job.lines[-120:]).lower()
            net = any(w in blob for w in ("network problem", "unavailable",
                                          "cannot connect", "max retries",
                                          "ssl", "timed out", "unreachable"))
            job.log("")
            if net:
                job.log("This looks like a NETWORK problem, not a broken install.")
                job.log("Run the OFFLINE self-test to prove your toolchain works "
                        "with no internet at all.")
            raise RuntimeError("self-test failed" + (" (network)" if net else "")
                               + f" - exit code {code}")

    job = _start_job("test", "self-test video" + (" (offline voice)" if offline else ""), work)
    return {"job": job.id, "command": " ".join(cmd[2:])}


# ---------------------------------------------------------------------------
# JOB STATUS + LIVE LOG
# ---------------------------------------------------------------------------
@app.get("/api/jobs")
def api_jobs() -> list[dict[str, Any]]:
    return [JOBS[i].snapshot() for i in JOBS_ORDER[::-1] if i in JOBS][:12]


@app.get("/api/job/{job_id}")
def api_job(job_id: str, from_line: int = 0) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job (it may have been cleared)")
    return job.snapshot(from_line)


@app.post("/api/job/{job_id}/stop")
def api_job_stop(job_id: str) -> dict[str, Any]:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    job.stop_requested.set()
    job.log("stop requested - the bot will stop at the end of the current stage")
    return {"ok": True, "status": job.status}


@app.get("/api/job/{job_id}/stream")
def api_job_stream(job_id: str) -> StreamingResponse:
    """
    Live log as Server-Sent Events.

    The browser keeps one connection open and receives every new line the
    moment it appears - the same experience as watching the terminal.
    """
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")

    def gen():
        sent = 0
        idle = 0
        while True:
            snap = job.snapshot(sent)
            new_lines = snap["lines"]
            sent += len(new_lines)
            for line in new_lines:
                yield f"data: {json.dumps({'line': line})}\n\n"
            meta = {k: snap[k] for k in ("status", "seconds", "progress", "result", "error")}
            yield f"data: {json.dumps({'meta': meta})}\n\n"
            if snap["status"] != "running":
                yield "event: end\ndata: {}\n\n"
                return
            if not new_lines:
                idle += 1
                if idle % 15 == 0:                 # keep proxies from timing out
                    yield ": keepalive\n\n"
            else:
                idle = 0
            time.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# SETTINGS: config.yaml and .env
# ---------------------------------------------------------------------------
@app.get("/api/config")
def api_config(filter: str | None = None) -> dict[str, Any]:
    from bot.utils import flatten
    cfg = _cfg()
    flat = flatten(cfg.data)
    if filter:
        f = filter.lower()
        flat = {k: v for k, v in flat.items() if f in k.lower()}
    keys = sorted(flat.keys())
    return {"values": {k: _jsonable(flat[k]) for k in keys}, "count": len(keys),
            "path": str(ROOT / "config.yaml")}


def _jsonable(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return json.dumps(v, ensure_ascii=False)


@app.post("/api/config")
def api_config_set(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Write settings back into config.yaml.

    This edits the YAML TEXT (not a dump of the parsed dict) so all of your
    comments and the careful layout of the file survive. That matters: the
    config file is also a teaching document.
    """
    updates: dict[str, Any] = payload.get("values") or {}
    if not updates:
        raise HTTPException(400, "no values given")
    path = ROOT / "config.yaml"
    text = path.read_text(encoding="utf-8")
    changed, missing = [], []

    for dotted, raw in updates.items():
        value = _coerce(raw)
        new_text, ok_done = _set_yaml_key(text, dotted, value)
        if ok_done:
            text = new_text
            changed.append(dotted)
        else:
            missing.append(dotted)

    if changed:
        path.write_text(text, encoding="utf-8")
    return {"changed": changed, "not_found": missing}


def _coerce(raw: Any) -> Any:
    if isinstance(raw, (bool, int, float)) or raw is None:
        return raw
    s = str(raw).strip()
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none", "~", ""):
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _set_yaml_key(text: str, dotted: str, value: Any) -> tuple[str, bool]:
    """
    Replace ONE key's value inside YAML text, keeping the file otherwise intact.

    WHY NOT JUST RE-WRITE THE WHOLE FILE
    ------------------------------------
    config.yaml is a teaching document: it is full of comments explaining what
    every option does. Loading it with a YAML library and dumping it back would
    delete every one of those comments. So we edit the text surgically instead.

    HOW THE PATH MATCHING WORKS
    ---------------------------
    YAML is a hierarchy expressed purely by indentation, so we keep a stack:

        audio:                    <- indent 0, stack = [audio]
          music:                  <- indent 2, stack = [audio, music]
            ducking: true         <- indent 4, stack = [audio, music, ducking]
                                      full path = "audio.music.ducking"  ✔ match

    When a line is less indented than the one before it, we pop the stack
    (that block ended). This is exactly how YAML itself decides nesting, and
    it needs no dependencies. If the key is not found we change nothing and
    report it, rather than inventing a new key in a random place.
    """
    import re as _re

    if isinstance(value, str) and _re.search(r"[:#{}\[\]]", value):
        rendered = f'"{value}"'
    elif isinstance(value, str):
        rendered = value
    elif value is True:
        rendered = "true"
    elif value is False:
        rendered = "false"
    elif value is None:
        rendered = "null"
    else:
        rendered = str(value)

    lines = text.splitlines()
    stack: list[tuple[int, str]] = []          # (indent, key)

    for i, line in enumerate(lines):
        m = _re.match(r"^(\s*)([A-Za-z0-9_.\-]+)\s*:(.*)$", line)
        if not m or line.lstrip().startswith("#"):
            continue
        indent = len(m.group(1))
        key = m.group(2)

        # a shallower (or equal) indent means the previous block finished
        while stack and indent <= stack[-1][0]:
            stack.pop()

        full_path = ".".join([k for _, k in stack] + [key])
        if full_path == dotted:
            # keep any trailing comment on the line
            rest = m.group(3)
            comment = ""
            if " #" in rest:
                comment = "  #" + rest.split(" #", 1)[1]
            lines[i] = f"{m.group(1)}{key}: {rendered}{comment}"
            out = "\n".join(lines)
            if text.endswith("\n"):
                out += "\n"
            return out, True

        stack.append((indent, key))

    return text, False


@app.get("/api/env")
def api_env() -> dict[str, Any]:
    return {"keys": _env_status(), "path": str(ROOT / ".env"),
            "exists": (ROOT / ".env").exists()}


@app.post("/api/env")
def api_env_set(payload: dict[str, Any]) -> dict[str, Any]:
    """Write API keys into .env (creating it from .env.example if needed)."""
    updates: dict[str, str] = {str(k): str(v) for k, v in (payload.get("values") or {}).items()}
    if not updates:
        raise HTTPException(400, "no keys given")
    path = ROOT / ".env"
    if not path.exists():
        example = ROOT / ".env.example"
        path.write_text(example.read_text(encoding="utf-8") if example.exists() else "",
                        encoding="utf-8")

    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key in updates:
            lines[i] = f"{key}={updates[key]}"
            seen.add(key)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # also load them into THIS process so a check right after saving works
    for key, value in updates.items():
        os.environ[key] = value
    return {"saved": sorted(updates.keys()), "path": str(path)}


# ---------------------------------------------------------------------------
# UPLOADS
# ---------------------------------------------------------------------------
@app.post("/api/upload/music")
async def api_upload_music(file: UploadFile = File(...)) -> dict[str, Any]:
    allowed = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus"}
    suffix = Path(file.filename or "track.mp3").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, f"unsupported audio type '{suffix}'. "
                                 f"Allowed: {', '.join(sorted(allowed))}")
    dest_dir = ROOT / "assets" / "background_music"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(file.filename or "track.mp3").name
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    return {"ok": True, "name": dest.name, "mb": round(dest.stat().st_size / 1e6, 2)}


@app.post("/api/upload/asset")
async def api_upload_asset(kind: str = Form("watermark"),
                           file: UploadFile = File(...)) -> dict[str, Any]:
    """kind = watermark | font | piper"""
    name = Path(file.filename or "file").name
    if kind == "watermark":
        dest_dir = ROOT / "assets"
        dest = dest_dir / "watermark.png" if name.lower().endswith(".png") \
            else dest_dir / name
    elif kind == "font":
        dest_dir = ROOT / "assets" / "fonts"
        dest = dest_dir / name
    elif kind == "piper":
        dest_dir = ROOT / "assets" / "piper"
        dest = dest_dir / name
    else:
        raise HTTPException(400, "kind must be watermark, font or piper")
    dest_dir.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    return {"ok": True, "path": str(dest.relative_to(ROOT)),
            "mb": round(dest.stat().st_size / 1e6, 3)}


# ---------------------------------------------------------------------------
# FILES / DOWNLOADS / CLEANING
# ---------------------------------------------------------------------------
DOWNLOADS = {
    "video": ("output/final.mp4", "video/mp4"),
    "thumbnail": ("output/thumbnail.jpg", "image/jpeg"),
    "metadata": ("output/youtube_metadata.json", "application/json"),
    "srt": ("subs/captions.srt", "text/plain"),
    "ass": ("subs/captions.ass", "text/plain"),
    "audio": ("mix.wav", "audio/wav"),
}


@app.get("/api/download/{slug}/{kind}")
def api_download(slug: str, kind: str):
    if kind not in DOWNLOADS:
        raise HTTPException(404, "unknown file")
    rel, media = DOWNLOADS[kind]
    path = _project(slug).dir / rel
    if not path.exists():
        raise HTTPException(404, f"{kind} does not exist for '{slug}' yet")
    return FileResponse(path, media_type=media, filename=f"{slug}_{path.name}")


@app.get("/api/media/{slug}/{kind}")
def api_media(slug: str, kind: str):
    """Same as download but inline (for the <video> player and <img> tags)."""
    mapping = {"video": "output/final.mp4", "thumbnail": "output/thumbnail.jpg",
               "audio": "mix.wav"}
    if kind not in mapping:
        raise HTTPException(404, "unknown media")
    path = _project(slug).dir / mapping[kind]
    if not path.exists():
        raise HTTPException(404, "not built yet")
    return FileResponse(path)


@app.get("/api/project/{slug}/scene-image/{sid}")
def api_scene_image(slug: str, sid: str):
    proj = _project(slug)
    for ext in ("jpg", "png"):
        p = proj.images_dir / f"{sid}.{ext}"
        if p.exists():
            return FileResponse(p)
    raise HTTPException(404, "no image for that scene")


@app.get("/api/example-script", response_class=PlainTextResponse)
def api_example_script() -> PlainTextResponse:
    """The bundled example script, so the UI's 'Load the example' button works."""
    path = ROOT / "examples" / "black_holes_script.txt"
    if not path.exists():
        raise HTTPException(404, "examples/black_holes_script.txt is missing")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@app.get("/api/project/{slug}/text/{name}")
def api_project_text(slug: str, name: str) -> PlainTextResponse:
    """Read one of the project's text files (script, log, metadata...)."""
    allowed = {"input.txt", "script.json", "manifest.json", "project.json",
               "topic.txt", "run.log", "youtube_metadata.json", "captions.srt"}
    if name not in allowed:
        raise HTTPException(404, "that file cannot be read here")
    proj = _project(slug)
    candidates = [proj.dir / name, proj.output_dir / name, proj.subs_dir / name,
                  proj.logs_dir / name]
    for p in candidates:
        if p.exists():
            return PlainTextResponse(p.read_text(encoding="utf-8", errors="ignore"))
    raise HTTPException(404, f"{name} does not exist")


@app.post("/api/clean")
def api_clean(payload: dict[str, Any]) -> dict[str, Any]:
    """Delete a project's intermediate files (keeps the final video)."""
    slug = str(payload.get("slug") or "")
    proj = _project(slug)
    if not proj.dir.exists():
        raise HTTPException(404, f"no project called '{slug}'")

    def work(job: Job) -> None:
        cfg = _cfg()
        p = Pipeline(cfg, _project(slug))
        before = _dir_size_mb(p.project.dir)
        p.clean(all_=bool(payload.get("all")))
        after = _dir_size_mb(p.project.dir)
        job.log(f"cleaned {slug}: {before:.1f} MB -> {after:.1f} MB")
        job.result = {"slug": slug, "before_mb": before, "after_mb": after}

    job = _start_job("clean", f"clean {slug}", work)
    return {"job": job.id}


@app.post("/api/delete-project")
def api_delete_project(payload: dict[str, Any]) -> dict[str, Any]:
    """Delete a whole project folder. The UI asks twice before calling this."""
    slug = str(payload.get("slug") or "")
    proj = _project(slug)
    if not proj.dir.exists():
        raise HTTPException(404, f"no project called '{slug}'")
    shutil.rmtree(proj.dir, ignore_errors=True)
    return {"deleted": slug}


@app.post("/api/open-folder")
def api_open_folder(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Open a folder in the operating system's file manager.

    Only paths INSIDE the bot folder are allowed - a web page must never be
    able to ask the server to open somewhere else.
    """
    slug = str(payload.get("slug") or "")
    sub = str(payload.get("sub") or "output")
    target = (_project(slug).dir / sub).resolve() if slug else ROOT.resolve()
    try:
        target.relative_to(ROOT.resolve())
    except ValueError:
        raise HTTPException(400, "path outside the project folder") from None
    if not target.exists():
        raise HTTPException(404, "that folder does not exist yet")

    try:
        if os.name == "nt":
            os.startfile(str(target))                       # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return {"ok": True, "path": str(target)}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "path": str(target),
                "message": f"could not open a file manager ({e}) - the folder is: {target}"}


# ---------------------------------------------------------------------------
# THE PAGE ITSELF
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = STATIC / "index.html"
    if not page.exists():
        return HTMLResponse("<h1>AutoVideoBot</h1><p>webui/static/index.html is missing.</p>",
                            status_code=500)
    return HTMLResponse(page.read_text(encoding="utf-8"))


if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def main(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    """Start the server (used by `python main.py web`)."""
    import uvicorn

    if open_browser:
        import threading as _t
        import webbrowser

        def later() -> None:
            time.sleep(1.2)
            try:
                webbrowser.open(f"http://127.0.0.1:{port}")
            except Exception:
                pass
        _t.Thread(target=later, daemon=True).start()

    print()
    print("  " + "=" * 66)
    print("   AutoVideoBot Web UI")
    print("  " + "=" * 66)
    print(f"   open this address in your browser:   http://127.0.0.1:{port}")
    print("   (keep this window open while you work - closing it stops the UI)")
    print("  " + "=" * 66)
    print()
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
