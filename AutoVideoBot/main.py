#!/usr/bin/env python3
"""
main.py
========
THE ONLY FILE YOU NEED TO RUN.

    python main.py run "black holes explained" --duration 120
    python main.py run "my video" --script my_script.txt
    python main.py doctor
    python main.py providers

Type  python main.py --help  for everything.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from bot.config import load_config                      # noqa: E402
from bot.paths import ROOT, Project, default_projects_dir  # noqa: E402
from bot.pipeline import Pipeline                        # noqa: E402
from bot.registry import list_providers                  # noqa: E402
from bot.utils import (                                  # noqa: E402
    die, ensure_dir, fail, fmt_time, human_bytes, info, log, ok, step, warn, write_json,
)

BANNER = r"""
     _         _        __     __          _ _    ____        _
    / \  _   _| |_ ___  \ \   / /__  _   _(_) | _| __ )  ___ | |_
   / _ \| | | | __/ _ \  \ \ / / _ \| | | | | |/ /  _ \ / _ \| __|
  / ___ \ |_| | || (_) |  \ V / (_) | |_| | |   <| |_) | (_) | |_
 /_/   \_\__,_|\__\___/    \_/ \___/ \__,_|_|_|\_\____/ \___/ \__|

        script -> voice -> images -> motion -> mix -> final.mp4
"""


# ===========================================================================
# COMMAND: doctor
# ===========================================================================
def cmd_doctor(args) -> int:
    """Check every dependency and every configured provider. Prints a report."""
    step("SYSTEM DOCTOR")
    cfg = load_config(cli_overrides=args.set)
    problems = 0
    notes = 0

    # ---- python ----
    v = sys.version_info
    if v < (3, 9):
        warn(f"Python {v.major}.{v.minor} is old - 3.10+ is recommended"); problems += 1
    else:
        ok(f"Python {v.major}.{v.minor}.{v.micro}")

    # ---- ffmpeg ----
    ff = str(cfg.get("system.ffmpeg_bin", "ffmpeg"))
    ffpath = shutil.which(ff) or (ff if Path(ff).exists() else None)
    if not ffpath:
        fail(f"ffmpeg NOT FOUND ('{ff}')")
        log("    [bold]Windows[/]: download https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip")
        log("            unzip it to C:\\ffmpeg, then add C:\\ffmpeg\\bin to your PATH")
        log("            (Settings -> System -> About -> Advanced -> Environment Variables)")
        log("            then CLOSE and REOPEN the terminal")
        log("    [bold]macOS[/]  : brew install ffmpeg")
        log("    [bold]Linux[/]  : sudo apt update && sudo apt install ffmpeg")
        problems += 1
    else:
        from bot.providers.assembly_ffmpeg import FFmpegAssembly
        asm = FFmpegAssembly(cfg, None)
        good, msg = asm.healthcheck()
        (ok if good else fail)(msg.splitlines()[0])
        if not good:
            for line in msg.splitlines()[1:]:
                log(f"    {line}")
            problems += 1
        else:
            w, h = cfg.resolution()
            ok(f"output will be {w}x{h} @ {cfg.get('video.fps')} fps")

    # ---- python packages ----
    required = {
        "requests": "pip install requests",
        "yaml": "pip install PyYAML",
        "PIL": "pip install Pillow",
        "dotenv": "pip install python-dotenv",
    }
    optional = {
        "edge_tts": "pip install edge-tts        (free TTS)",
        "pydub": "pip install pydub             (audio analysis)",
        "moviepy": "pip install moviepy         (only if motion.engine: moviepy)",
        "gradio_client": "pip install gradio_client (only for the gradio provider)",
        "librosa": "pip install librosa         (advanced audio analysis)",
    }
    for mod, fix in required.items():
        try:
            __import__(mod); ok(f"python module: {mod}")
        except ImportError:
            fail(f"python module missing: {mod}   ->   {fix}"); problems += 1
    for mod, fix in optional.items():
        try:
            __import__(mod); info(f"python module: {mod} (optional, present)")
        except ImportError:
            info(f"python module: {mod} not installed - {fix}"); notes += 1

    # ---- .env ----
    if (ROOT / ".env").exists():
        ok(".env file found")
    else:
        warn(".env file not found. Copy it:  cp .env.example .env  (Windows: copy .env.example .env)")
        notes += 1

    # ---- providers ----
    step("CONFIGURED PROVIDERS")
    for kind, key in (("LLM (script)", "llm.provider"),
                      ("TTS (voice)", "tts.provider"),
                      ("IMAGE (visuals)", "image.provider"),
                      ("ASSEMBLY (render)", "motion.engine")):
        name = str(cfg.get(key, "?"))
        log(f"  [bold]{kind:20s}[/] -> [cyan]{name}[/]")
        try:
            if kind.startswith("ASSEMBLY"):
                from bot.providers.assembly_ffmpeg import FFmpegAssembly
                inst = FFmpegAssembly(cfg, None)
            else:
                real_kind = {"LLM (script)": "llm", "TTS (voice)": "tts",
                             "IMAGE (visuals)": "image"}[kind]
                from bot.registry import get_provider_class
                cls = get_provider_class(real_kind, name)
                inst = cls(cfg, None)
            good, msg = inst.healthcheck()
            (ok if good else warn)(f"    {msg.splitlines()[0]}")
            if not good:
                for line in msg.splitlines()[1:]:
                    log(f"      {line}")
                if "not found" in msg.lower() or "empty" in msg.lower():
                    problems += 1
                else:
                    notes += 1
        except SystemExit:
            # A missing API key kills the provider, but it is only fatal if you
            # actually intend to use that provider. Explain instead of failing.
            if kind == "LLM (script)":
                warn("    no API key configured for this LLM.")
                log("      [dim]This is FINE if you always supply your own script[/]")
                log("      [dim](--script my_script.txt). It is only needed for[/]")
                log("      [dim]--topic mode, where the AI writes the narration.[/]")
                notes += 1
            else:
                fail(f"    cannot build the {kind} provider - see the message above")
                problems += 1
        except Exception as e:
            text = str(e)
            if "API key" in text or "empty" in text or "not installed" in text:
                warn(f"    {text.splitlines()[0]}"); notes += 1
            else:
                fail(f"    cannot build provider: {text.splitlines()[0][:160]}"); problems += 1

    # ---- folders ----
    step("FOLDERS")
    for p in ("assets/background_music", "prompts",
              cfg.get("system.projects_dir", "workspace/projects")):
        d = ROOT / p
        exists = d.exists()
        (ok if exists else warn)(f"{p} {'exists' if exists else 'MISSING (will be created)'}")
        if not exists:
            notes += 1
    music = list((ROOT / "assets/background_music").glob("*")) if (ROOT / "assets/background_music").exists() else []
    if music:
        ok(f"background music: {len(music)} file(s)")
    else:
        warn("assets/background_music/ is empty - videos will have no music (still fine)")
        notes += 1

    # ---- disk ----
    usage = shutil.disk_usage(str(ROOT))
    free_gb = usage.free / (1024 ** 3)
    if free_gb < 2:
        warn(f"only {free_gb:.1f} GB of free disk space - renders can need several GB")
        notes += 1
    else:
        ok(f"free disk space: {free_gb:.1f} GB")

    # ---- verdict ----
    step("VERDICT")
    if problems == 0:
        ok("Everything needed is in place. You can make a video right now.")
        log('    [bold green]python main.py run "my first video" --topic "the deepest point in the ocean" --duration 60[/]')
    else:
        fail(f"{problems} blocking problem(s) and {notes} note(s). Fix the red lines above first.")
    if notes and problems == 0:
        info(f"{notes} optional improvement(s) available")
    return 1 if problems else 0


# ===========================================================================
# COMMAND: providers
# ===========================================================================
def cmd_providers(args) -> int:
    step("AVAILABLE PROVIDERS (what you can hot-swap)")
    cfg = load_config()
    current = {
        "llm": cfg.get("llm.provider"), "tts": cfg.get("tts.provider"),
        "image": cfg.get("image.provider"), "assembly": cfg.get("motion.engine"),
    }
    for kind, items in list_providers().items():
        log(f"\n[bold]{kind.upper()}[/]   (config.yaml -> [cyan]{kind}.provider[/])")
        for it in items:
            star = " [bold green]<- ACTIVE[/]" if current.get(kind) == it["name"] else ""
            meta = " ".join(f"{k}={v}" for k, v in it.items()
                            if k in ("cost", "needs_key", "quality", "setup_time") and v not in (None, ""))
            log(f"   [bold]{it['name']:16s}[/] {meta}{star}")
            if it["doc"]:
                log(f"   {'':16s} [dim]{it['doc'][:96]}[/]")
    log("\n[dim]Switch by editing config.yaml, or per-run:  --set image.provider=vast[/]")
    return 0


# ===========================================================================
# COMMAND: voices
# ===========================================================================
def cmd_voices(args) -> int:
    step("AVAILABLE VOICES")
    cfg = load_config(cli_overrides=args.set)
    name = str(cfg.get("tts.provider", "edge"))
    from bot.registry import get_provider_class
    try:
        inst = get_provider_class("tts", name)(cfg, None)
    except Exception as e:
        die(str(e))
    voices = inst.list_voices()
    if not voices:
        warn(f"provider '{name}' did not return a voice list")
        return 0
    flt = (args.filter or "").lower()
    shown = [v for v in voices if flt in v.lower()] or voices
    for v in shown:
        log(f"   {v}")
    log(f"\n[dim]{len(shown)} voice(s). Set one with:  tts.edge.voice: \"...\"  in config.yaml[/]")
    return 0


# ===========================================================================
# PROJECT HELPERS
# ===========================================================================
def make_pipeline(args, cfg=None) -> Pipeline:
    cfg = cfg or load_config(cli_overrides=getattr(args, "set", None))
    projects_dir = ROOT / str(cfg.get("system.projects_dir", "workspace/projects"))
    proj = Project.from_name(projects_dir, args.project)
    p = Pipeline(cfg, proj)
    p.force = bool(getattr(args, "force", False))
    only = getattr(args, "only", None)
    p.only = set(only.split(",")) if only else None
    ep = getattr(args, "endpoint", None)
    if ep:
        p.endpoint_override = ep
    return p


# ===========================================================================
# COMMANDS: the pipeline stages
# ===========================================================================
def cmd_init(args) -> int:
    cfg = load_config(cli_overrides=args.set)
    proj = Project.from_name(ROOT / str(cfg.get("system.projects_dir")), args.project).create()
    if args.script:
        shutil.copyfile(Path(args.script), proj.input_file)
    if args.topic:
        proj.topic_file.write_text(args.topic, encoding="utf-8")
    ok(f"project created: {proj.dir}")
    for d in ("audio", "images", "clips", "subs", "output", "logs"):
        info(f"   {proj.dir / d}")
    return 0


def cmd_script(args) -> int:
    p = make_pipeline(args)
    p.stage_script(
        topic=args.topic, script_file=Path(args.script) if args.script else None,
        duration=args.duration, style=args.style or "", extra_instructions=args.instructions or "",
    )
    return 0


def cmd_stage(args) -> int:
    p = make_pipeline(args)
    fn = {
        "voice": p.stage_voice, "timing": p.stage_timing, "images": p.stage_images,
        "motion": p.stage_motion, "transition": p.stage_transition,
        "subtitles": p.stage_subtitles, "mix": p.stage_mix,
        "assembly": p.stage_assembly, "extras": p.stage_extras,
    }[args.stage]
    try:
        fn()
    finally:
        p.close_providers()
    return 0


def cmd_run(args) -> int:
    cfg = load_config(cli_overrides=args.set)
    p = make_pipeline(args, cfg)
    topic = args.topic
    if not topic and p.project.topic_file.exists() and not args.script:
        topic = p.project.topic_file.read_text(encoding="utf-8").strip()
    if not topic and not args.script and p.project.input_file.exists():
        args.script = str(p.project.input_file)
    script_file = Path(args.script) if args.script else None
    if not topic and not script_file:
        die(
            "Give the bot something to work with:\n"
            f'   python main.py run "{args.project}" --topic "what the video is about" --duration 120\n'
            f'   python main.py run "{args.project}" --script my_script.txt\n'
        )
    t0 = time.time()
    out = p.run_all(topic=topic, script_file=script_file, duration=args.duration,
                    style=args.style or "", extra_instructions=args.instructions or "")
    p.manifest.log_run("run", time.time() - t0)
    log("")
    log(f"[bold green]Open it here:[/] {out}")
    return 0


# ===========================================================================
# COMMAND: inspect / status
# ===========================================================================
def cmd_inspect(args) -> int:
    cfg = load_config(cli_overrides=args.set)
    pdir = ROOT / str(cfg.get("system.projects_dir"))
    proj = Project.from_name(pdir, args.project)
    if not proj.exists():
        die(f"No project called '{args.project}' in {pdir}\nList them with:  python main.py projects")

    from bot.state import Manifest, Script
    man = Manifest(proj.dir)
    scr = Script(proj.dir)
    step(f"PROJECT: {proj.slug}")
    log(f"  folder : {proj.dir}")

    log("\n  [bold]STAGES[/]")
    for stage, done in man.summary().items():
        mark = "[green]✔[/]" if done else "[dim]·[/]"
        extra = ""
        if man.data["stages"].get(stage, {}).get("info"):
            extra = f"  [dim]{man.data['stages'][stage]['info']}[/]"
        log(f"    {mark} {stage:12s}{extra}")

    if scr.load():
        d = scr.data
        log(f"\n  [bold]SCRIPT[/]  {d.get('title')}")
        log(f"    source   : {d.get('source')}")
        log(f"    scenes   : {len(scr)}")
        log(f"    duration : {fmt_time(d.get('total_duration', 0))}")
        log(f"    aspect   : {d.get('aspect', cfg.get('video.aspect'))}")
        log("")
        log("    [dim]id    start   end     dur   words  motion         image  audio  clip[/]")
        for sc in d.get("scenes", []):
            sid = sc.get("id")
            has_img = "yes" if (proj.images_dir / f"{sid}.jpg").exists() or (proj.images_dir / f"{sid}.png").exists() else "[red]NO[/]"
            has_aud = "yes" if (proj.audio_dir / f"{sid}.wav").exists() or (proj.audio_dir / f"{sid}.mp3").exists() else "[red]NO[/]"
            has_clp = "yes" if (proj.scene_clip(sid)).exists() else "[red]NO[/]"
            tempo = sc.get("tempo")
            tstr = f"x{tempo:.2f}" if tempo else ""
            log(f"    {sid:5s} {sc.get('start', 0):6.1f}  {sc.get('end', 0):6.1f}  "
                f"{sc.get('duration', 0):5.1f}  {sc.get('word_count', 0):5d}  "
                f"{str(sc.get('motion', '')):14s} {has_img:6s} {has_aud:6s} {has_clp:5s} {tstr}")
        if d.get("video_duration"):
            log(f"\n    rendered video length: {fmt_time(d['video_duration'])}")

    log("\n  [bold]FILES[/]")
    for label, path in (("final video", proj.final_video), ("narration", proj.voice_track),
                        ("mix", proj.mix_track), ("silent picture", proj.silent_video),
                        ("captions", proj.srt_file), ("thumbnail", proj.thumbnail),
                        ("metadata", proj.metadata_file)):
        if path.exists():
            log(f"    [green]✔[/] {label:15s} {human_bytes(path.stat().st_size):>10s}  {path.relative_to(ROOT)}")
        else:
            log(f"    [dim]·[/] {label:15s} [dim](not built yet)[/]")

    total = sum(f.stat().st_size for f in proj.dir.rglob("*") if f.is_file())
    log(f"\n  project size on disk: {human_bytes(total)}")
    if proj.final_video.exists():
        log(f"\n  [bold green]Watch it:[/] {proj.final_video}")
    return 0


def cmd_projects(args) -> int:
    cfg = load_config()
    pdir = ROOT / str(cfg.get("system.projects_dir"))
    ensure_dir(pdir)
    step("PROJECTS")
    rows = []
    for d in sorted(pdir.iterdir()):
        if not d.is_dir():
            continue
        final = d / "output" / "final.mp4"
        sj = d / "script.json"
        scenes = 0
        title = ""
        if sj.exists():
            try:
                data = json.loads(sj.read_text(encoding="utf-8"))
                scenes = len(data.get("scenes", []))
                title = data.get("title", "")
            except Exception:
                pass
        rows.append((d.name, scenes, title, final))
    if not rows:
        warn("No projects yet. Make one:")
        log('   python main.py run "my first video" --topic "why the sky is blue" --duration 60')
        return 0
    for name, scenes, title, final in rows:
        flag = "[green]✔ rendered[/]" if final.exists() else "[dim]  in progress[/]"
        log(f"  {flag} [bold]{name}[/]  {scenes} scenes  [dim]{title[:44]}[/]")
    return 0


# ===========================================================================
# COMMAND: clean / config / test-render
# ===========================================================================
def cmd_clean(args) -> int:
    p = make_pipeline(args)
    if not p.project.exists():
        die(f"No such project: {args.project}")
    freed = p.cleanup(keep_final=not args.all)
    ok(f"freed {human_bytes(freed)} from {p.project.dir}")
    return 0


def cmd_config(args) -> int:
    cfg = load_config(cli_overrides=args.set)
    if args.get:
        log(f"{args.get} = {json.dumps(cfg.get(args.get), default=str)}")
        return 0
    from bot.utils import flatten
    flat = flatten(cfg.data)
    flt = (args.filter or "").lower()
    step("CONFIGURATION (effective values)")
    for k in sorted(flat):
        if flt and flt not in k.lower():
            continue
        v = flat[k]
        if isinstance(v, str) and len(v) > 90:
            v = v[:87] + "..."
        log(f"  [cyan]{k}[/] = {json.dumps(v, default=str)}")
    log(f"\n[dim]{len(flat)} settings. Change them in config.yaml, or per-run with --set key=value[/]")
    return 0


def cmd_test(args) -> int:
    """Render a tiny 8-second sample so you can verify the whole toolchain."""
    step("SELF TEST")
    base_cfg = load_config()
    overrides = list(args.set or []) + [
        "video.preset=ultrafast",
        "video.crf=26",
        "transitions.enabled=true",
        "subtitles.enabled=true",
        "audio.music.enabled=false",
        "extras.metadata.enabled=false",
        "extras.thumbnail.enabled=true",
        f"image.provider={args.image or base_cfg.get('image.provider', 'pollinations')}",
        f"tts.provider={args.tts or base_cfg.get('tts.provider', 'edge')}",
    ]
    cfg = load_config(cli_overrides=overrides)
    name = args.project or "selftest"
    proj = Project.from_name(ROOT / str(cfg.get("system.projects_dir")), name)
    script = proj.dir / "input.txt"
    ensure_dir(proj.dir)
    script.write_text(
        "#title: AutoVideoBot Self Test\n"
        "#style: cinematic, dramatic lighting\n\n"
        "[00:00 - 00:04]\n"
        "This is a self test of the automatic video bot.\n"
        "@prompt: a futuristic robot film studio, glowing screens, cinematic\n"
        "@motion: zoom_in\n\n"
        "[00:04 - 00:08]\n"
        "If you can hear this voice and see these moving images, everything works.\n"
        "@prompt: a golden trophy on a dark stage, spotlight, confetti falling\n"
        "@motion: zoom_out\n",
        encoding="utf-8",
    )
    p = Pipeline(cfg, proj)
    t0 = time.time()
    out = p.run_all(script_file=script)
    log("")
    ok(f"self test video: {out}  ({fmt_time(time.time() - t0)})")
    info("If that played correctly, your toolchain is complete.")
    info("Delete it with:  python main.py clean selftest --all")
    return 0


# ===========================================================================
# COMMAND: prompts preview
# ===========================================================================
def cmd_prompts(args) -> int:
    step("PROMPT TEMPLATES")
    pdir = ROOT / "prompts"
    for f in sorted(pdir.glob("*.txt")):
        log(f"\n[bold cyan]{f.relative_to(ROOT)}[/]")
        text = f.read_text(encoding="utf-8")
        preview = text if args.full else text[:700]
        for line in preview.splitlines():
            log(f"  [dim]{line}[/]")
        if not args.full and len(text) > 700:
            log("  [dim]... (use --full to see the whole file)[/]")
    log("\n[dim]Edit these files to change how the AI writes. No Python knowledge needed.[/]")
    return 0


# ===========================================================================
# ARG PARSER
# ===========================================================================
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="main.py",
        description="AutoVideoBot - turn a script into a finished video automatically.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
QUICK START
  1. python main.py doctor                      check your installation
  2. python main.py run "my video" --topic "why the ocean is deep" --duration 60
  3. open workspace/projects/my-video/output/final.mp4

USE YOUR OWN SCRIPT WITH TIMESTAMPS
  python main.py run "my video" --script my_script.txt

RE-DO ONE STEP ONLY
  python main.py images "my video" --force
  python main.py motion "my video" --only s03,s04
""",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    def common(sp, with_project=True, with_force=True):
        if with_project:
            sp.add_argument("project", help="project name (a folder is created for it)")
        sp.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="override any config value, e.g. --set image.provider=vast")
        if with_force:
            sp.add_argument("--force", action="store_true", help="ignore the cache and redo everything")
        sp.add_argument("--only", default=None,
                        help="only these scenes: 3-7 or s03,s05 or 1,2,9")
        sp.add_argument("--endpoint", default=None,
                        help="override the image server URL (Colab/Vast/Gradio)")

    # --- run -------------------------------------------------------------
    sp = sub.add_parser("run", help="THE MAIN COMMAND: make a whole video")
    common(sp)
    sp.add_argument("--topic", help='what the video is about, e.g. "black holes explained"')
    sp.add_argument("--script", help="path to YOUR script file with timestamps")
    sp.add_argument("--duration", type=float, default=None, help="target length in seconds")
    sp.add_argument("--style", default="", help="extra visual style for every image")
    sp.add_argument("--instructions", default="", help="extra instructions for the LLM")
    sp.set_defaults(func=cmd_run)

    # --- individual stages ------------------------------------------------
    for stage, helptext in [
        ("script", "step 1: build script.json from a topic or your script file"),
        ("voice", "step 2: generate the voiceover for every scene"),
        ("timing", "step 3: measure + fit audio onto your timestamps"),
        ("images", "step 4: generate the pictures"),
        ("motion", "step 5: add the Ken Burns movement"),
        ("transition", "step 6: join the clips with crossfades"),
        ("subtitles", "step 7: write the caption file"),
        ("mix", "step 8: mix narration with background music"),
        ("assembly", "step 9: mux the final mp4"),
        ("extras", "step 10: thumbnail + youtube metadata"),
    ]:
        sp = sub.add_parser(stage, help=helptext)
        common(sp)
        if stage == "script":
            sp.add_argument("--topic")
            sp.add_argument("--script", dest="script_file_path", default=None)
            sp.add_argument("--duration", type=float, default=None)
            sp.add_argument("--style", default="")
            sp.add_argument("--instructions", default="")
            sp.set_defaults(func=cmd_script, script=None)
        else:
            sp.set_defaults(func=cmd_stage, stage=stage)

    # fix the script stage's odd argument naming
    # (--script means "input file" there, handled below in main())

    # --- utilities ---------------------------------------------------------
    sp = sub.add_parser("doctor", help="check ffmpeg, packages, keys and providers")
    sp.add_argument("--set", action="append", default=[])
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("providers", help="list every provider you can switch to")
    sp.set_defaults(func=cmd_providers)

    sp = sub.add_parser("voices", help="list the voices of the current TTS provider")
    sp.add_argument("--filter", help="only show voices containing this text")
    sp.add_argument("--set", action="append", default=[])
    sp.set_defaults(func=cmd_voices)

    sp = sub.add_parser("projects", help="list every project on this machine")
    sp.set_defaults(func=cmd_projects)

    sp = sub.add_parser("inspect", help="show the full state of one project")
    common(sp, with_force=False)
    sp.set_defaults(func=cmd_inspect)

    sp = sub.add_parser("init", help="create an empty project folder")
    common(sp, with_force=False)
    sp.add_argument("--topic")
    sp.add_argument("--script")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("clean", help="delete intermediate files of a project")
    common(sp, with_force=False)
    sp.add_argument("--all", action="store_true", help="also delete images and audio")
    sp.set_defaults(func=cmd_clean)

    sp = sub.add_parser("config", help="print the effective configuration")
    sp.add_argument("--filter", help="only show keys containing this text")
    sp.add_argument("--get", help="print one value, e.g. --get image.provider")
    sp.add_argument("--set", action="append", default=[])
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("test", help="render a tiny 8-second video to verify everything")
    sp.add_argument("project", nargs="?", default="selftest")
    sp.add_argument("--image", help="image provider to test (default: whatever config says)")
    sp.add_argument("--tts", help="tts provider to test")
    sp.add_argument("--set", action="append", default=[])
    sp.set_defaults(func=cmd_test)

    sp = sub.add_parser("prompts", help="show the LLM prompt templates you can edit")
    sp.add_argument("--full", action="store_true")
    sp.set_defaults(func=cmd_prompts)

    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    # the `script` subcommand uses --script for the input file
    if getattr(args, "command", "") == "script":
        args.script = getattr(args, "script_file_path", None)

    log(BANNER, style="bold cyan")
    try:
        return int(args.func(args) or 0)
    except KeyboardInterrupt:
        warn("\ninterrupted by you. Partial work is saved - just run the same command again.")
        return 130
    except SystemExit:
        raise
    except Exception as e:
        fail(f"{type(e).__name__}: {e}")
        log("\n[dim]Tip: run  python main.py doctor  to find missing pieces.[/]")
        log("[dim]Tip: set  system.log_level: DEBUG  in config.yaml to see every command.[/]")
        if os.environ.get("AVB_DEBUG") == "1":
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
