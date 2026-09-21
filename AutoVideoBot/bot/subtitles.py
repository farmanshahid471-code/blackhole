"""
bot/subtitles.py
=================
STAGE - captions.

Two caption flavours, both driven by REAL timing data (never guessed):

  word_boundaries : Edge-TTS / ElevenLabs tell us the exact millisecond each
                    word is spoken. We group 3-5 words per caption. This is the
                    "Shorts style" and it is frame-accurate.

  scene_split     : no word data available, so we split each scene's narration
                    into even chunks and spread them across the scene duration.
                    Slightly less exact, still perfectly usable.

Output: a .srt file (upload it to YouTube as a separate caption track, or
burn it into the picture with subtitles.burn_in: true).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .utils import chunk_words, ensure_dir, seconds_to_srt_time, warn


def _wrap(lines: list[str], max_chars: int) -> list[str]:
    """Re-wrap chunks so no subtitle line is uncomfortably long."""
    out: list[str] = []
    for ln in lines:
        if len(ln) <= max_chars:
            out.append(ln)
        else:
            words = ln.split()
            cur: list[str] = []
            size = 0
            for w in words:
                if cur and size + len(w) + 1 > max_chars:
                    out.append(" ".join(cur))
                    cur, size = [w], len(w)
                else:
                    cur.append(w)
                    size += len(w) + (1 if len(cur) > 1 else 0)
            if cur:
                out.append(" ".join(cur))
    return out


def _punctuation_flags(narration: str) -> list[bool]:
    """
    Which word of the narration ends a sentence?

    WHY THIS IS NEEDED
    ------------------
    TTS engines report word timings WITHOUT punctuation: the word event for
    "yours." arrives as plain "yours". Without the full stop the caption
    builder has no idea where a sentence ends, and it produces things like
    "slower than yours Not" on screen.

    So we walk the ORIGINAL narration text and remember where the full stops
    are, then line those flags up with the spoken words.
    """
    if not narration:
        return []
    flags: list[bool] = []
    for token in re.findall(r"\S+", narration):
        flags.append(bool(re.search(r"[.!?…][\"')\]]*$", token)))
    return flags


def _strip_punct(word: str) -> str:
    return re.sub(r"[^\w'-]+$", "", word).lower()


def build_cues_from_words(words: list[dict], scene_offset: float, tempo: float,
                          max_words: int = 4, max_chars: int = 42,
                          narration: str = "") -> list[dict]:
    """
    words = [{"w": "Black", "s": 0.12, "e": 0.44}, ...]  (seconds, inside the scene)
    scene_offset = where this scene starts in the final video
    tempo = the speed factor we applied to the audio (word times must shrink too)
    narration = the original text, used to find sentence boundaries
    """
    if not words:
        return []

    # line the spoken words up with the narration's punctuation
    flags = _punctuation_flags(narration)
    tokens = re.findall(r"\S+", narration) if narration else []
    stripped_tokens = [_strip_punct(x) for x in tokens]
    flag_map: dict[int, bool] = {}
    if flags:
        cursor = 0
        for idx, wd in enumerate(words):
            target = _strip_punct(str(wd.get("w", "")))
            if not target:
                flag_map[idx] = False
                continue
            # find the narration token that matches this spoken word
            while cursor < len(flags) and stripped_tokens[cursor] != target:
                cursor += 1
            if cursor < len(flags):
                flag_map[idx] = flags[cursor]
                cursor += 1
            else:
                flag_map[idx] = bool(re.search(r"[.!?…]+$", str(wd.get("w", ""))))
    else:
        for idx, wd in enumerate(words):
            flag_map[idx] = bool(re.search(r"[.!?…]+$", str(wd.get("w", ""))))

    cues: list[dict] = []
    bucket: list[dict] = []
    bucket_chars = 0

    for idx, wd in enumerate(words):
        text = str(wd.get("w", "")).strip()
        if not text:
            continue
        projected = bucket_chars + len(text) + (1 if bucket else 0)
        ends_sentence = flag_map.get(idx, False)

        # Fill the bucket first, THEN flush on a sentence end. Flushing BEFORE
        # adding would orphan the last word of the sentence into its own cue
        # ("By" / "centuries"), which looks broken on screen.
        if bucket and (len(bucket) >= max_words or projected > max_chars):
            cues.append(_cue(bucket, scene_offset, tempo))
            bucket, bucket_chars = [], 0
            projected = len(text)

        bucket.append(wd)
        bucket_chars = projected

        # A full stop ALWAYS closes the caption, so the next sentence starts
        # fresh. That is the difference between captions that read like prose
        # and captions that read like a glitch.
        if ends_sentence:
            cues.append(_cue(bucket, scene_offset, tempo))
            bucket, bucket_chars = [], 0

    if bucket:
        cues.append(_cue(bucket, scene_offset, tempo))
    return cues


def _cue(bucket: list[dict], offset: float, tempo: float) -> dict:
    t = float(tempo) if tempo else 1.0
    start = offset + float(bucket[0]["s"]) / t
    end = offset + float(bucket[-1]["e"]) / t
    if end - start < 0.35:                    # never flash a caption for <0.35s
        end = start + 0.35
    return {"start": round(start, 3), "end": round(end, 3),
            "text": " ".join(str(b["w"]).strip() for b in bucket).strip()}


def build_cues_from_scene(narration: str, start: float, duration: float,
                          max_words: int = 6, max_chars: int = 42) -> list[dict]:
    """Spread a scene's words evenly across its duration."""
    chunks = chunk_words(narration, max_words=max_words, max_chars=max_chars)
    if not chunks:
        return []
    total_words = sum(len(c.split()) for c in chunks) or 1
    cues: list[dict] = []
    cursor = start
    for c in chunks:
        share = (len(c.split()) / total_words) * duration
        cues.append({"start": round(cursor, 3), "end": round(cursor + share - 0.03, 3), "text": c})
        cursor += share
    return cues


# ---------------------------------------------------------------------------
def build_srt(scenes: list[dict], cfg, *, source: str = "word_boundaries",
              words_dir: Path | None = None) -> list[dict]:
    """
    Build every caption cue for the whole video, in timeline order.
    scenes must already have: start, duration, tempo, narration.
    """
    max_words = int(cfg.get("subtitles.words_per_line", 4))
    max_chars = int(cfg.get("subtitles.max_chars_per_line", 42))
    cues: list[dict] = []

    for sc in scenes:
        sid = str(sc.get("id"))
        offset = float(sc.get("start") or 0.0)
        dur = float(sc.get("duration") or 0.0)
        tempo = float(sc.get("tempo") or 1.0)

        words = None
        if source == "word_boundaries" and words_dir:
            wp = Path(words_dir) / f"{sid}.json"
            if wp.exists():
                try:
                    words = json.loads(wp.read_text(encoding="utf-8")).get("words")
                except Exception as e:
                    warn(f"could not read word timings for {sid}: {e}")

        if words:
            cues += build_cues_from_words(words, offset, tempo, max_words, max_chars,
                                          narration=sc.get("narration", ""))
        else:
            cues += build_cues_from_scene(sc.get("narration", ""), offset, dur,
                                          max_words + 2, max_chars)

    cues.sort(key=lambda c: c["start"])

    # de-overlap and drop anything absurdly short
    cleaned: list[dict] = []
    for c in cues:
        if not c["text"].strip():
            continue
        if cleaned:
            prev = cleaned[-1]
            if c["start"] < prev["end"]:
                prev["end"] = max(prev["start"] + 0.2, c["start"] - 0.02)
            if c["end"] - c["start"] < 0.25:
                c["end"] = c["start"] + 0.25
        cleaned.append(c)
    return cleaned


def write_srt(cues: list[dict], path: Path) -> Path:
    ensure_dir(Path(path).parent)
    lines: list[str] = []
    for i, c in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"{seconds_to_srt_time(c['start'])} --> {seconds_to_srt_time(c['end'])}")
        lines.append(c["text"].strip())
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
    return path


def cues_to_ass(cues: list[dict], path: Path, style: dict, *,
                play_w: int, play_h: int) -> Path:
    """
    Write a full ASS file - used when you want per-word karaoke colours or
    an exact font size that survives ffmpeg's auto-scaling.
    """
    ensure_dir(Path(path).parent)
    size = int(style.get("font_size", 52))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.get('font', 'DejaVu Sans')},{size},{style.get('primary_colour', '&H00FFFFFF')},{style.get('highlight_colour', '&H0000D7FF')},{style.get('outline_colour', '&H00000000')},{style.get('back_colour', '&H80000000')},{-1 if style.get('bold', True) else 0},0,0,0,100,100,0,0,1,{style.get('outline', 3)},{style.get('shadow', 1)},{style.get('alignment', 2)},{style.get('margin_l', 60)},{style.get('margin_r', 60)},{style.get('margin_v', 90)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for c in cues:
        s = _ass_time(c["start"])
        e = _ass_time(c["end"])
        text = c["text"].replace("\n", "\\N")
        events.append(f"Dialogue: 0,{s},{e},Default,,0,0,0,,{text}")
    Path(path).write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return path


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    cs = int(round((seconds - int(seconds)) * 100))
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if cs == 100:
        cs = 99
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"
