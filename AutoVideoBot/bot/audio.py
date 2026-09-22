"""
bot/audio.py
=============
STAGE - background music handling.

Everything here is about PICKING and PREPARING the music track:
  * which file to use (random / first / a specific one / chosen by mood)
  * looping it so it is never shorter than the video
  * fading the ends so it never starts or stops abruptly

The actual mixing with the narration (including ducking) happens in
bot/providers/assembly_ffmpeg.py -> build_mix().

WHERE TO GET FREE MUSIC (do not skip the licence!)
--------------------------------------------------
  YouTube Audio Library   studio.youtube.com -> Create -> Audio Library
                          (free, safe for monetised videos)
  Pixabay Music           pixabay.com/music          (free, no attribution)
  Free Music Archive      freemusicarchive.org       (check each licence)
  Incompetech             incompetech.com            (needs a credit line)
  Uppbeat                 uppbeat.io                 (free tier, credit line)

Drop the files into  assets/background_music/  and the bot uses them.
"""
from __future__ import annotations

import random
from pathlib import Path

from .paths import ROOT
from .utils import debug, ensure_dir, info, warn

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus"}

# Mood keywords the LLM may return -> filename hints to look for
MOOD_HINTS = {
    "dark": ["dark", "tense", "ominous", "horror", "dramatic"],
    "space": ["space", "ambient", "cosmic", "ethereal", "drone"],
    "uplifting": ["uplift", "happy", "positive", "bright", "inspiring"],
    "sad": ["sad", "emotional", "melancholy", "piano"],
    "epic": ["epic", "cinematic", "trailer", "orchestral", "heroic"],
    "calm": ["calm", "chill", "lofi", "relax", "soft"],
    "mystery": ["mystery", "suspense", "thriller", "noir"],
    "tech": ["tech", "electronic", "synth", "digital", "cyber"],
}


def list_music(folder: Path | None = None) -> list[Path]:
    d = Path(folder) if folder else ROOT / "assets" / "background_music"
    if not d.exists():
        return []
    files = [p for p in sorted(d.iterdir()) if p.suffix.lower() in AUDIO_EXTS]
    return files


def pick_track(cfg, scenes: list[dict] | None = None,
               folder: Path | None = None) -> Path | None:
    """
    Choose the background music file according to audio.music.mode.

      random       -> any file from the folder (different every video)
      first        -> always the alphabetically first file (consistent branding)
      filename     -> exactly audio.music.filename
      match_mood   -> look at the script's mood/title and pick a file whose
                      NAME matches (e.g. mood "space" -> "cosmic-drone-01.mp3")
      per_scene    -> each scene can set its own @music: line
    """
    mus = cfg.section("audio.music")
    if not mus.get("enabled", True):
        debug("background music disabled in config")
        return None

    base = Path(folder) if folder else ROOT / str(mus.get("folder", "assets/background_music"))
    files = list_music(base)

    # an explicit per-project choice always wins
    forced = None
    if scenes:
        for sc in scenes:
            if sc.get("music"):
                forced = sc["music"]
                break
    forced = forced or mus.get("filename") or ""

    if forced:
        cand = Path(str(forced))
        if not cand.is_absolute():
            cand = base / cand.name
        if cand.exists():
            info(f"music: {cand.name} (explicitly requested)")
            return cand
        warn(f"requested music file '{forced}' not found in {base}")

    if not files:
        warn(
            f"No music files in {base}\n"
            "  The video will still be made, just without background music.\n"
            "  Add .mp3/.wav files there (see the licence list at the top of bot/audio.py)."
        )
        return None

    mode = str(mus.get("mode", "random")).lower()

    if mode == "first":
        chosen = files[0]
    elif mode == "match_mood" and scenes:
        chosen = _match_mood(files, scenes)
    else:
        chosen = random.choice(files)

    info(f"music: {chosen.name}  ({mode} mode, {len(files)} track(s) available)")
    return chosen


def _match_mood(files: list[Path], scenes: list[dict]) -> Path:
    """Score every file by how well its filename matches the script's mood."""
    text = " ".join(
        [str(s.get("title", "")) for s in scenes[:1]]
        + [str(s.get("narration", "")) for s in scenes[:3]]
        + [str(s.get("mood", "")) for s in scenes]
    ).lower()

    scores: list[tuple[int, Path]] = []
    for f in files:
        name = f.stem.lower().replace("-", " ").replace("_", " ")
        score = 0
        for mood, hints in MOOD_HINTS.items():
            if mood in text or any(h in text for h in hints):
                score += sum(3 for h in hints if h in name)
        for word in name.split():
            if len(word) > 3 and word in text:
                score += 2
        scores.append((score, f))

    scores.sort(key=lambda x: (-x[0], x[1].name))
    best_score, best = scores[0]
    if best_score == 0:
        return random.choice(files)
    debug(f"mood match: {best.name} scored {best_score}")
    return best


def prepare_music(asm, track: Path, out_path: Path, duration: float, cfg) -> Path | None:
    """
    Loop + fade the chosen track so it exactly covers the video.
    (Volume and ducking are applied later, inside the mix filtergraph.)
    """
    if not track or not Path(track).exists():
        return None
    mus = cfg.section("audio.music")
    ensure_dir(Path(out_path).parent)

    src_dur = asm.probe_duration(track)
    loops = 0
    if mus.get("loop", True) and src_dur > 0 and duration > src_dur:
        import math
        loops = int(math.ceil(duration / src_dur)) - 1
        info(f"music is {src_dur:.0f}s, video is {duration:.0f}s -> looping {loops + 1}x")

    fade_in = float(mus.get("fade_in_seconds", 1.5))
    fade_out = float(mus.get("fade_out_seconds", 3.0))
    af = []
    if fade_in > 0:
        af.append(f"afade=t=in:st=0:d={fade_in:.2f}")
    if fade_out > 0:
        af.append(f"afade=t=out:st={max(0.0, duration - fade_out):.2f}:d={fade_out:.2f}")
    af.append("aresample=48000:async=1")

    from .utils import resolve_ffmpeg, run_cmd
    # resolve_ffmpeg also finds the copy that `pip install imageio-ffmpeg`
    # downloads, so music works on a machine with no system ffmpeg.
    cmd = [resolve_ffmpeg(str(cfg.get("system.ffmpeg_bin", "ffmpeg"))),
           "-y", "-hide_banner", "-loglevel", "error"]
    if loops > 0:
        cmd += ["-stream_loop", str(loops)]
    cmd += ["-i", str(track)]
    cmd += ["-af", ",".join(af), "-t", f"{duration:.3f}",
            "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(out_path)]
    run_cmd(cmd, timeout=1800)
    return out_path
