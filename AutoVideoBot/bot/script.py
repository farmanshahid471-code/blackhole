"""
bot/script.py
==============
STAGE 1 - get a scene list.

Two completely different ways in, one identical result:

  MODE A "file"    You wrote the script. You hand the bot a .txt file with
                   timestamps. The bot parses it into scenes and NEVER changes
                   your words.

  MODE B "topic"   You hand the bot a topic ("black holes, 2 minutes"). The
                   LLM writes the narration AND a Stable Diffusion prompt for
                   every scene, and returns strict JSON.

Both modes end with the same object:

    {
      "title": "...",
      "scenes": [
        {"id": "s01", "narration": "...", "image_prompt": "...",
         "target_start": 0.0, "target_end": 12.0, "duration": 12.0, ...},
        ...
      ]
    }

============================================================================
MODE A: THE SCRIPT FILE FORMAT (this is what you asked for)
============================================================================
Everything here is OPTIONAL except the narration. Use whichever style you
like - the parser recognises all of them.

--------------------------------------------------------------------------
STYLE 1 - a timestamp range per scene (the clearest)
--------------------------------------------------------------------------
    [00:00 - 00:12]
    Black holes are not empty holes in space. They are places where gravity
    has won completely.
    @prompt: a supermassive black hole bending light, accretion disk glowing

    [00:12 - 00:25]
    Everything that crosses the event horizon is gone forever.
    @prompt: event horizon close up, distorted starlight, cinematic

--------------------------------------------------------------------------
STYLE 2 - one timestamp at the start of each line
--------------------------------------------------------------------------
    0:00  Black holes are not empty holes in space.
    0:12  Everything that crosses the event horizon is gone forever.

--------------------------------------------------------------------------
STYLE 3 - arrow style
--------------------------------------------------------------------------
    00:00 -> 00:12 | Black holes are not empty holes in space.
    00:12 -> 00:25 | Everything that crosses the event horizon is gone.

--------------------------------------------------------------------------
STYLE 4 - JSON (if you generate the script with another tool)
--------------------------------------------------------------------------
    {"title": "...", "scenes": [{"start": 0, "end": 12, "narration": "..."}]}

--------------------------------------------------------------------------
OPTIONAL HEADER LINES (put them at the very top of the file)
--------------------------------------------------------------------------
    #title:       The Gravity Trap
    #description: Why nothing escapes a black hole
    #tags:        space, black holes, physics
    #voice:       en-US-ChristopherNeural      (overrides config.yaml)
    #music:       dark-ambient-01.mp3          (a file in assets/background_music)
    #style:       dark cinematic, volumetric light   (appended to every prompt)
    #aspect:      16x9

--------------------------------------------------------------------------
OPTIONAL PER-SCENE LINES
--------------------------------------------------------------------------
    @prompt:   the image to generate        (also accepted: @image: / @visual:)
    @motion:   zoom_in                      (any preset from bot/filters.py)
    @title:    Chapter name for YouTube chapters
    @pause:    1.5                          (extra silence after this scene)
    @voice:    en-GB-RyanNeural             (different narrator for one scene)
    @music:    tense-strings.mp3            (change music from this scene on)
    @skip:     true                         (leave this scene out)

--------------------------------------------------------------------------
WHAT IF YOU GIVE NO TIMESTAMPS AT ALL?
--------------------------------------------------------------------------
Perfectly fine. The bot measures how long the voice actually takes and uses
that as the scene length. Your video will be as long as the narration needs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .utils import die, extract_json, info, ok, parse_timestamp, warn

# ---------------------------------------------------------------------------
# header lines:  #title: something
HEADER_RE = re.compile(r"^\s*#\s*(title|description|tags|voice|music|style|aspect|"
                       r"negative|seed|language|fps)\s*[:=]\s*(.*)$", re.I)

# per-scene directives:  @prompt: something
DIRECTIVE_RE = re.compile(
    r"^\s*@\s*(prompt|image|visual|image_prompt|motion|title|pause|voice|music|"
    r"speed|skip|seed|sfx|subtitle)\s*[:=]\s*(.*)$", re.I)

# [00:00 - 00:12]   |   [00:00 -> 00:12]  |  [00:00 to 00:12]  |  [00:00]
BRACKET_RANGE_RE = re.compile(
    r"^\s*[\[\(]\s*([0-9][0-9:.hms\s]*)\s*(?:-|–|—|to|->|=>|\|)\s*([0-9][0-9:.hms\s]*)\s*[\]\)]\s*[:\-]?\s*(.*)$"
)
BRACKET_ONE_RE = re.compile(r"^\s*[\[\(]\s*([0-9][0-9:.hms\s]*)\s*[\]\)]\s*[:\-]?\s*(.*)$")

# 00:00 -> 00:12 | narration        (no brackets)
ARROW_RANGE_RE = re.compile(
    r"^\s*([0-9]{1,2}:[0-9]{2}(?:[.:][0-9]{1,3})?)\s*(?:-|–|—|to|->|=>)\s*"
    r"([0-9]{1,2}:[0-9]{2}(?:[.:][0-9]{1,3})?)\s*[|\-:]?\s*(.*)$"
)
# 00:00  narration
LEADING_TS_RE = re.compile(
    r"^\s*([0-9]{1,2}:[0-9]{2}(?:[.:][0-9]{1,3})?)\s*[|\-:–]?\s+(.*)$"
)

SCENE_HEADING_RE = re.compile(
    r"^\s*(?:scene|shot|clip|part|chapter)\s*[-#.:]?\s*(\d+)\s*[:\-–]?\s*(.*)$", re.I
)

SPLIT_SENTENCES = re.compile(r"(?<=[.!?])\s+")


# ===========================================================================
# MODE A - parse a script file
# ===========================================================================
def parse_script_file(path: Path, *, default_scene_seconds: float = 6.0) -> dict:
    """
    Read a human-written script and return the canonical scene dict.
    See the module docstring for every format this accepts.
    """
    path = Path(path)
    if not path.exists():
        die(f"Script file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")

    # --- maybe it is JSON ------------------------------------------------
    # CAREFUL: the most popular timestamp style starts with a bracket too!
    #
    #     [00:00 - 00:12]  <- this is a timestamp, not a JSON array
    #
    # So "starts with [ " is not enough to decide. A JSON script must either
    # contain a quoted key followed by a colon, or a "scenes" list. Anything
    # else is handed to the normal timestamp parser, silently - a warning
    # here would appear on almost every hand-written script and teach people
    # to ignore warnings, which is much worse than being one line longer.
    stripped = text.strip()
    looks_json = bool(
        stripped.startswith("{")
        or (stripped.startswith("[") and ('"' in stripped[:400] and ":" in stripped[:400]))
    )
    if stripped.startswith("{") and '"scenes"' in text[:2000]:
        looks_json = True
    if looks_json:
        try:
            data = extract_json(stripped)
            return normalise_llm_json(data, source="file-json")
        except Exception as e:
            warn(f"file looks like JSON but did not parse ({e}); reading it as plain text")

    meta: dict[str, Any] = {}
    scenes: list[dict] = []
    current: dict[str, Any] | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal current, buffer
        if current is None:
            if buffer:                                   # text before any timestamp
                body = " ".join(buffer).strip()
                if body:
                    current = {"narration": body}
                buffer = []
                if current:
                    scenes.append(current)
                    current = None
            return
        body = " ".join(x.strip() for x in buffer if x.strip()).strip()
        if body:
            existing = current.get("narration", "").strip()
            current["narration"] = (existing + " " + body).strip() if existing else body
        buffer = []
        scenes.append(current)
        current = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        s = line.strip()

        # ---- blank line: paragraph break, does NOT end a scene ----------
        if not s:
            if buffer:
                buffer.append("")
            continue

        # ---- comments ---------------------------------------------------
        if s.startswith("//") or s.startswith("<!--"):
            continue

        # ---- global header lines ----------------------------------------
        m = HEADER_RE.match(s)
        if m:
            key = m.group(1).lower()
            val = m.group(2).strip()
            if key == "tags":
                meta["tags"] = [t.strip() for t in re.split(r"[,;]", val) if t.strip()]
            else:
                meta[key] = val
            continue

        if s.startswith("#"):                            # any other # line = comment
            continue

        # ---- per-scene directives ---------------------------------------
        m = DIRECTIVE_RE.match(s)
        if m:
            key = m.group(1).lower()
            val = m.group(2).strip()
            if current is None:
                flush()
                current = {"narration": ""}
            if key in ("prompt", "image", "visual", "image_prompt"):
                current["image_prompt"] = val
            elif key == "pause":
                current["extra_pause"] = parse_timestamp(val) or 0.0
            elif key == "speed":
                current["rate"] = val
            elif key == "skip":
                current["skip"] = str(val).lower() in ("1", "true", "yes", "y")
            elif key == "subtitle":
                current["subtitle"] = val
            else:
                current[key] = val
            continue

        # ---- [00:00 - 00:12] --------------------------------------------
        m = BRACKET_RANGE_RE.match(s)
        if m:
            flush()
            current = {
                "target_start": parse_timestamp(m.group(1)),
                "target_end": parse_timestamp(m.group(2)),
                "narration": m.group(3).strip(),
            }
            buffer = []
            continue

        # ---- [00:00] -----------------------------------------------------
        m = BRACKET_ONE_RE.match(s)
        if m:
            flush()
            current = {
                "target_start": parse_timestamp(m.group(1)),
                "narration": m.group(2).strip(),
            }
            buffer = []
            continue

        # ---- 00:00 -> 00:12 | text ---------------------------------------
        m = ARROW_RANGE_RE.match(s)
        if m:
            flush()
            current = {
                "target_start": parse_timestamp(m.group(1)),
                "target_end": parse_timestamp(m.group(2)),
                "narration": m.group(3).strip(),
            }
            buffer = []
            continue

        # ---- Scene 3: ... ------------------------------------------------
        m = SCENE_HEADING_RE.match(s)
        if m and not re.match(r"^\d", m.group(2) or ""):
            flush()
            current = {"scene_number": int(m.group(1)), "narration": "",
                       "title": (m.group(2) or "").strip()}
            buffer = []
            continue

        # ---- 00:00  text --------------------------------------------------
        m = LEADING_TS_RE.match(s)
        if m:
            flush()
            current = {"target_start": parse_timestamp(m.group(1)),
                       "narration": m.group(2).strip()}
            buffer = []
            continue

        # ---- ordinary narration line --------------------------------------
        buffer.append(s)

    flush()

    # ---- clean up ---------------------------------------------------------
    scenes = [s for s in scenes if (s.get("narration") or "").strip() or s.get("image_prompt")]
    scenes = [s for s in scenes if not s.get("skip")]

    if not scenes:
        die(
            f"No scenes found in {path}.\n"
            "The file must contain at least one line of narration.\n"
            "See the big comment at the top of bot/script.py for every format."
        )

    # ---- assign timestamps ------------------------------------------------
    _fill_timestamps(scenes, default_scene_seconds)

    # ---- ids and defaults -------------------------------------------------
    for i, sc in enumerate(scenes):
        sc["id"] = f"s{i + 1:02d}"
        sc["index"] = i
        sc.setdefault("narration", "")
        sc["narration"] = re.sub(r"\s+", " ", sc["narration"]).strip()
        sc["word_count"] = len(sc["narration"].split())

    total = scenes[-1]["target_end"] if scenes else 0.0

    out = {
        "title": meta.get("title") or _derive_title(scenes),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "language": meta.get("language", "English"),
        "source": "file",
        "total_duration": round(total, 3),
        "meta": meta,
        "scenes": scenes,
    }
    ok(f"parsed {len(scenes)} scene(s) from {path.name} -> total {total:.1f}s")
    return out


def _fill_timestamps(scenes: list[dict], default_scene_seconds: float) -> None:
    """
    Make sure every scene has a usable start/end, whatever the author wrote.

    RULES (applied in order)
      1. start given, end given        -> use both
      2. start given, no end           -> end = next scene's start
                                         (last scene: start + default)
      3. end given, no start           -> start = previous scene's end
      4. neither given                 -> start = previous end,
                                          end = start + default
      5. overlaps / out of order       -> repair and warn loudly
    """
    n = len(scenes)
    for i, sc in enumerate(scenes):
        st = sc.get("target_start")
        en = sc.get("target_end")
        if st is not None and en is None:
            nxt = scenes[i + 1].get("target_start") if i + 1 < n else None
            en = nxt if nxt is not None else float(st) + default_scene_seconds
        if st is None and en is not None:
            prev = scenes[i - 1].get("target_end") if i > 0 else 0.0
            st = prev if prev is not None else max(0.0, float(en) - default_scene_seconds)
        if st is None and en is None:
            st = scenes[i - 1]["target_end"] if i > 0 else 0.0
            en = float(st) + default_scene_seconds
        sc["target_start"] = round(float(st), 3)
        sc["target_end"] = round(float(en), 3)

    # repair ordering problems
    for i, sc in enumerate(scenes):
        if i > 0 and sc["target_start"] < scenes[i - 1]["target_end"] - 0.001:
            warn(
                f"scene {i + 1} starts at {sc['target_start']}s but scene {i} ends at "
                f"{scenes[i - 1]['target_end']}s - shifting scene {i + 1} to remove the overlap"
            )
            sc["target_start"] = scenes[i - 1]["target_end"]
        if sc["target_end"] <= sc["target_start"]:
            warn(f"scene {i + 1} has zero/negative length - giving it {default_scene_seconds}s")
            sc["target_end"] = sc["target_start"] + default_scene_seconds
        sc["duration"] = round(sc["target_end"] - sc["target_start"], 3)


def _derive_title(scenes: list[dict]) -> str:
    first = (scenes[0].get("narration") or "Untitled").strip()
    first = re.split(r"[.!?]", first)[0]
    words = first.split()[:8]
    title = " ".join(words).strip().capitalize()
    return title or "Untitled"


# ===========================================================================
# MODE B - LLM generated
# ===========================================================================
def load_prompt_file(rel_path: str) -> str:
    from .paths import ROOT
    p = ROOT / rel_path
    if not p.exists():
        die(f"Prompt template missing: {p}\nRestore it from the prompts/ folder.")
    return p.read_text(encoding="utf-8")


def generate_script(llm, cfg, *, topic: str, duration: float | None = None,
                    style: str = "", extra_instructions: str = "") -> dict:
    """
    Ask the LLM for a full scene breakdown, returned as strict JSON.

    The prompt template lives in prompts/script_system.txt and
    prompts/script_user.txt so you can rewrite the bot's personality
    without touching any Python.
    """
    system = load_prompt_file(cfg.get("llm.prompt_files.system", "prompts/script_system.txt"))
    user_tpl = load_prompt_file(cfg.get("llm.prompt_files.user", "prompts/script_user.txt"))

    scenes_cfg = cfg.section("llm.scenes")
    per_scene = float(scenes_cfg.get("target_seconds_per_scene", 9))
    duration = float(duration or cfg.get("script.default_duration", 120))
    n_scenes = max(2, int(round(duration / per_scene)))

    user = (
        user_tpl
        .replace("{topic}", topic.strip())
        .replace("{duration}", f"{duration:g}")
        .replace("{scene_count}", str(n_scenes))
        .replace("{min_words}", str(scenes_cfg.get("min_words_per_scene", 18)))
        .replace("{max_words}", str(scenes_cfg.get("max_words_per_scene", 42)))
        .replace("{language}", str(scenes_cfg.get("language", "English")))
        .replace("{style}", style or str(cfg.get("image.style_suffix", "")))
        .replace("{aspect}", str(cfg.get("video.aspect", "16x9")))
        .replace("{extra}", extra_instructions or "")
    )

    info(f"asking {llm.provider_name} for {n_scenes} scenes (~{duration:.0f}s) ...")
    raw = llm.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=float(scenes_cfg.get("temperature", cfg.get("llm.deepseek.temperature", 0.8))),
        json_mode=True,
    )
    data = extract_json(raw)
    out = normalise_llm_json(data, source="llm")
    out["topic"] = topic
    out["requested_duration"] = duration

    # apply per-scene timings
    _fill_timestamps(out["scenes"], per_scene)
    for i, sc in enumerate(out["scenes"]):
        sc["id"] = f"s{i + 1:02d}"
        sc["index"] = i
        sc["word_count"] = len((sc.get("narration") or "").split())
    out["total_duration"] = round(out["scenes"][-1]["target_end"], 3) if out["scenes"] else 0.0
    ok(f"LLM returned {len(out['scenes'])} scenes -> {out['total_duration']:.1f}s")
    return out


def normalise_llm_json(data: Any, source: str = "llm") -> dict:
    """
    LLMs return JSON that is *almost* right. This fixes the usual damage:
      scenes nested one level too deep, "text" instead of "narration",
      "prompt" instead of "image_prompt", timestamps as strings, etc.
    """
    if isinstance(data, list):
        data = {"scenes": data}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}")

    scenes = (
        data.get("scenes") or data.get("shots") or data.get("segments")
        or data.get("script") or data.get("clips") or []
    )
    if isinstance(scenes, dict):
        scenes = scenes.get("scenes", [])
    if not isinstance(scenes, list) or not scenes:
        raise ValueError(f"No scene list found in the JSON. Keys were: {list(data)}")

    out_scenes: list[dict] = []
    for i, sc in enumerate(scenes):
        if isinstance(sc, str):
            sc = {"narration": sc}
        if not isinstance(sc, dict):
            continue
        narration = (
            sc.get("narration") or sc.get("text") or sc.get("voiceover")
            or sc.get("script") or sc.get("line") or sc.get("vo") or ""
        )
        prompt = (
            sc.get("image_prompt") or sc.get("prompt") or sc.get("visual")
            or sc.get("visual_prompt") or sc.get("image") or sc.get("description") or ""
        )
        entry = {
            "narration": str(narration).strip(),
            "image_prompt": str(prompt).strip(),
            "target_start": parse_timestamp(sc.get("start") if sc.get("start") is not None else sc.get("start_time")),
            "target_end": parse_timestamp(sc.get("end") if sc.get("end") is not None else sc.get("end_time")),
            "title": str(sc.get("title") or sc.get("chapter") or "").strip(),
            "motion": str(sc.get("motion") or "").strip() or None,
            "duration_hint": parse_timestamp(sc.get("duration")),
        }
        if entry["target_start"] is None and entry["duration_hint"] is not None:
            prev_end = out_scenes[-1]["target_end"] if out_scenes else 0.0
            entry["target_start"] = prev_end
            entry["target_end"] = prev_end + entry["duration_hint"]
        if not entry["narration"] and not entry["image_prompt"]:
            continue
        out_scenes.append(entry)

    if not out_scenes:
        raise ValueError("Every scene in the JSON was empty")

    return {
        "title": str(data.get("title") or _derive_title(out_scenes)).strip(),
        "description": str(data.get("description") or "").strip(),
        "tags": data.get("tags") or data.get("keywords") or [],
        "language": str(data.get("language") or "English"),
        "hook": str(data.get("hook") or "").strip(),
        "source": source,
        "scenes": out_scenes,
        "raw_meta": {k: v for k, v in data.items() if k not in ("scenes", "shots", "segments")},
    }


def enrich_prompts(scenes: list[dict], cfg, style_suffix: str = "",
                   negative: str = "") -> list[dict]:
    """
    Make sure every scene has an image prompt.
    If the author/LLM did not give one, build a usable prompt from the narration
    using the template in prompts/image_polish.txt (no LLM call needed).
    """
    tpl = ""
    try:
        tpl = load_prompt_file(cfg.get("llm.prompt_files.image_polish", "prompts/image_polish.txt"))
    except SystemExit:
        tpl = "{narration}"

    missing = 0
    for sc in scenes:
        p = (sc.get("image_prompt") or "").strip()
        if not p:
            missing += 1
            p = (tpl.replace("{narration}", sc.get("narration", ""))
                    .replace("{title}", sc.get("title", "")))
        parts = [p.strip().rstrip(",.")]
        if style_suffix:
            parts.append(style_suffix.strip())
        sc["image_prompt"] = ", ".join(x for x in parts if x)
        sc["negative_prompt"] = negative or sc.get("negative_prompt", "")
    if missing:
        warn(f"{missing} scene(s) had no image prompt - generated fallback prompts from the narration")
    return scenes


def validate(scenes: list[dict], cfg) -> list[str]:
    """Return a list of human-readable warnings about the scene list."""
    problems: list[str] = []
    mn = float(cfg.get("timing.min_duration", 2.0))
    mx = float(cfg.get("timing.max_duration", 30.0))
    for i, sc in enumerate(scenes, 1):
        d = float(sc.get("duration") or 0)
        if d < mn:
            problems.append(f"scene {i} is only {d:.1f}s (min_duration is {mn}s)")
        if d > mx:
            problems.append(f"scene {i} is {d:.1f}s (longer than max_duration {mx}s) - consider splitting it")
        wc = len((sc.get("narration") or "").split())
        if wc and d:
            wpm = wc / d * 60.0
            if wpm > 210:
                problems.append(f"scene {i}: {wpm:.0f} words/min is too fast to speak clearly")
            elif wpm < 60 and wc > 4:
                problems.append(f"scene {i}: only {wpm:.0f} words/min - the voice will be stretched a lot")
        if not (sc.get("image_prompt") or "").strip():
            problems.append(f"scene {i} has no image prompt")
    return problems
