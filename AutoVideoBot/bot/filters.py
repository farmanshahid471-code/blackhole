"""
bot/filters.py
===============
Builds FFmpeg filter strings. This is where the "free animation" lives.

============================================================================
THE KEN BURNS EFFECT, EXPLAINED FROM SCRATCH
============================================================================
A photograph on screen for 8 seconds is boring. Television documentaries
solve this by MOVING A VIRTUAL CAMERA over the still image:

    * slowly zooming IN          -> the subject feels closer, more intimate
    * slowly zooming OUT         -> reveals context, feels like an ending
    * slowly panning LEFT/RIGHT  -> feels like the camera is travelling
    * zoom + pan together        -> the classic "Ken Burns" move

We cannot move a real camera, but we CAN crop a moving window out of a big
image and output that window as video. That is exactly what these filters do.

============================================================================
WHY WE SCALE THE IMAGE UP FIRST (the jitter problem)
============================================================================
FFmpeg crops at whole-pixel positions. If the crop window moves 1 pixel per
frame, the motion looks steppy and cheap - this is the famous "zoompan
jitter" that ruins most AI video bots.

The fix is SUPER-SAMPLING:

    1. Blow the image up to 6x the output size  (1920x1080 -> 11520x6480)
    2. Move the crop window in that huge space
    3. Shrink the window back down to 1920x1080

Now 1 pixel of crop movement = 1/6 of a pixel on screen. The motion is
butter smooth, and downscaling also makes the image look sharper.

The cost: more RAM. `motion.supersample: 6` is the sweet spot. If your PC
has less than 8 GB of RAM, drop it to 3 in config.yaml.
"""
from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# MOTION PRESETS
# ---------------------------------------------------------------------------
# Each preset is a function of normalised progress p (0.0 -> 1.0 over the clip)
# returning (crop_scale, focus_x, focus_y), where:
#   crop_scale = fraction of the supersampled image the crop window covers
#                (1.0 = the whole image, 0.9 = zoomed in 10%)
#   focus_x/y  = 0..1 position the crop window is centred on
#
# Everything is turned into an FFmpeg expression with `t` (time in seconds)
# so the motion is computed per frame and is perfectly smooth.
# ---------------------------------------------------------------------------

MOTION_PRESETS: dict[str, dict[str, Any]] = {
    # --- zoom -------------------------------------------------------------
    "zoom_in": {
        "label": "slow push in (most common, feels intimate)",
        "scale": lambda p, z, pan: 1.0 - (1.0 - 1.0 / z) * p,
        "fx": 0.5, "fy": 0.5,
    },
    "zoom_out": {
        "label": "slow pull back (great for the LAST scene)",
        "scale": lambda p, z, pan: (1.0 / z) + (1.0 - 1.0 / z) * p,
        "fx": 0.5, "fy": 0.5,
    },
    "zoom_in_slow": {
        "label": "very subtle push in (use for talking-head style scenes)",
        "scale": lambda p, z, pan: 1.0 - (1.0 - 1.0 / z) * 0.5 * p,
        "fx": 0.5, "fy": 0.5,
    },
    "zoom_in_top": {
        "label": "push in aimed at the upper third",
        "scale": lambda p, z, pan: 1.0 - (1.0 - 1.0 / z) * p,
        "fx": 0.5, "fy": 0.36,
    },
    "zoom_out_bottom": {
        "label": "pull back aimed at the lower third",
        "scale": lambda p, z, pan: (1.0 / z) + (1.0 - 1.0 / z) * p,
        "fx": 0.5, "fy": 0.64,
    },

    # --- pan --------------------------------------------------------------
    "pan_left_right": {
        "label": "camera travels left to right",
        "scale": lambda p, z, pan: 1.0 / math.sqrt(z),      # slight zoom keeps it alive
        "fx_t": lambda p, pan: pan * 0.5 + (1.0 - pan) * p,
        "fy": 0.5,
    },
    "pan_right_left": {
        "label": "camera travels right to left",
        "scale": lambda p, z, pan: 1.0 / math.sqrt(z),
        "fx_t": lambda p, pan: (1.0 - pan * 0.5) - (1.0 - pan) * p,
        "fy": 0.5,
    },
    "pan_up_down": {
        "label": "camera tilts downwards (good for tall subjects)",
        "scale": lambda p, z, pan: 1.0 / math.sqrt(z),
        "fx": 0.5,
        "fy_t": lambda p, pan: pan * 0.5 + (1.0 - pan) * p,
    },
    "pan_down_up": {
        "label": "camera tilts upwards (reveals something big)",
        "scale": lambda p, z, pan: 1.0 / math.sqrt(z),
        "fx": 0.5,
        "fy_t": lambda p, pan: (1.0 - pan * 0.5) - (1.0 - pan) * p,
    },

    # --- combined ---------------------------------------------------------
    "diagonal_tl_br": {
        "label": "push in while travelling top-left to bottom-right",
        "scale": lambda p, z, pan: 1.0 - (1.0 - 1.0 / z) * p,
        "fx_t": lambda p, pan: 0.42 + 0.16 * p,
        "fy_t": lambda p, pan: 0.42 + 0.16 * p,
    },
    "diagonal_br_tl": {
        "label": "pull back while travelling bottom-right to top-left",
        "scale": lambda p, z, pan: (1.0 / z) + (1.0 - 1.0 / z) * p,
        "fx_t": lambda p, pan: 0.58 - 0.16 * p,
        "fy_t": lambda p, pan: 0.58 - 0.16 * p,
    },
    "ken_burns_combo": {
        "label": "the classic documentary move: zoom in + drift right",
        "scale": lambda p, z, pan: 1.0 - (1.0 - 1.0 / z) * p,
        "fx_t": lambda p, pan: 0.46 + 0.08 * p,
        "fy_t": lambda p, pan: 0.5 - 0.02 * p,
    },
    "orbit": {
        "label": "gentle circular drift (dreamy / space scenes)",
        "scale": lambda p, z, pan: 1.0 - (1.0 - 1.0 / z) * 0.6,
        "fx_t": lambda p, pan: 0.5 + 0.05 * math.sin(2 * math.pi * p),
        "fy_t": lambda p, pan: 0.5 + 0.05 * math.cos(2 * math.pi * p),
    },
    "pulse": {
        "label": "zooms in then out (tension / heartbeat moments)",
        "scale": lambda p, z, pan: 1.0 - (1.0 - 1.0 / z) * math.sin(math.pi * p),
        "fx": 0.5, "fy": 0.5,
    },
    "static": {
        "label": "no movement at all (use sparingly, feels like a slideshow)",
        "scale": lambda p, z, pan: 1.0 / math.sqrt(z),
        "fx": 0.5, "fy": 0.5,
    },
}

DEFAULT_ORDER = [
    "zoom_in", "pan_left_right", "zoom_out", "pan_right_left", "zoom_in_slow",
    "pan_up_down", "diagonal_tl_br", "ken_burns_combo", "diagonal_br_tl", "static",
]

# ---------------------------------------------------------------------------
# COLOUR GRADES  (subtle - these are applied AFTER the motion)
# ---------------------------------------------------------------------------
COLOR_GRADES: dict[str, str] = {
    "none": "",
    # slightly desaturated, deeper blacks, cool shadows -> "Netflix documentary"
    "cinematic": "eq=contrast=1.06:saturation=0.92:brightness=-0.012,colorbalance=rs=-0.04:gs=0.0:bs=0.05:rm=0.02:bm=-0.02",
    "warm":      "eq=contrast=1.04:saturation=1.06:brightness=0.01,colorbalance=rs=0.06:gs=0.02:bs=-0.05",
    "cool":      "eq=contrast=1.04:saturation=0.96:brightness=-0.005,colorbalance=rs=-0.05:gs=0.0:bs=0.06",
    "noir":      "hue=s=0,eq=contrast=1.18:brightness=-0.03",
    "vivid":     "eq=contrast=1.10:saturation=1.22:brightness=0.012",
    "teal_orange": "colorbalance=rs=0.10:gs=0.0:bs=-0.10:rh=-0.05:bh=0.10,eq=saturation=1.05:contrast=1.05",
    "film":      "eq=contrast=1.05:saturation=0.95:brightness=0.005,curves=preset=vintage",
}


def auto_supersample(out_w: int, out_h: int, parallel: int = 1,
                     budget_mb: int | None = None, floor: int = 2,
                     ceiling: int = 6) -> int:
    """
    Choose the largest supersampling factor this machine can actually afford.

    WHY THIS FUNCTION EXISTS
    ------------------------
    Super-sampling is what makes the Ken Burns move smooth instead of steppy,
    but it costs memory quadratically. A 1920x1080 frame blown up 6x is
    11520x6480 - about 224 MB per frame as raw RGB, and ffmpeg holds several
    frames in flight per filter. On a normal PC that is an out-of-memory kill
    (the process just vanishes with exit code -9).

    So we measure the machine and pick a factor that fits, with a hard floor
    of 2 (still visibly smoother than none) and a ceiling of 6.

        1080p on a 2 GB machine  -> 2
        1080p on an 8 GB machine -> 3
        4K   on a 32 GB machine  -> 2

    You can always override it in config.yaml -> motion.supersample
    """
    if budget_mb is None:
        try:
            import os
            pages = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            total_mb = pages / (1024 * 1024)
        except Exception:
            total_mb = 4096.0
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        total_mb = min(total_mb, float(line.split()[1]) / 1024.0)
                        break
        except Exception:
            pass
        # give ffmpeg at most a third of what is free, split across workers
        budget_mb = max(150.0, total_mb / 4.0 / max(1, int(parallel)))

    per_frame_mb = (out_w * out_h * 4.0) / (1024 * 1024)   # RGBA-ish working format
    headroom = 5.0                                          # frames ffmpeg keeps live
    best = floor
    for ss in range(ceiling, floor - 1, -1):
        need = per_frame_mb * (ss ** 2) * headroom
        if need <= budget_mb:
            best = ss
            break
    return int(max(floor, min(ceiling, best)))


# ===========================================================================
def motion_for_index(index: int, cfg_preset: str, order: list[str] | None = None) -> str:
    """Pick the motion preset for scene number `index`."""
    if cfg_preset and cfg_preset != "auto":
        return cfg_preset if cfg_preset in MOTION_PRESETS else "zoom_in"
    order = order or DEFAULT_ORDER
    order = [o for o in order if o in MOTION_PRESETS] or DEFAULT_ORDER
    # never repeat the previous scene's move
    return order[index % len(order)]


# ===========================================================================
def _bake(fn, z: float, pan: float, p: float) -> float:
    """Evaluate a preset lambda with the REAL zoom/pan values at progress p."""
    return float(fn(p, z, pan))


def _lerp_expr(v0: float, v1: float, p: str) -> str:
    """A linear ramp from v0 to v1 as an ffmpeg expression, or a constant."""
    if abs(v1 - v0) < 1e-9:
        return f"{v0:.6f}"
    return f"({v0:.6f}+({v1 - v0:.6f})*{p})"


def _curve_expr(fn, p: str, segments: int = 16) -> str:
    """
    Approximate any lambda(p) as a piecewise-linear ffmpeg expression.

    Used for the "pulse" and "orbit" presets, which are sine curves.
    FFmpeg has no easy way to run our Python lambdas, so we sample them at
    `segments` points and emit nested if(lt(p,x),value,...) tests. 16 segments
    on a sine is indistinguishable from the real curve at 30 fps.

    NOTE: commas inside ffmpeg expressions must be escaped as \\, otherwise
    ffmpeg thinks the argument ended.
    """
    values = [float(fn(i / segments, 1.0, 1.0)) for i in range(segments + 1)]
    if max(values) - min(values) < 1e-6:
        return f"{values[0]:.6f}"

    expr = f"{values[-1]:.6f}"
    for i in range(segments - 1, -1, -1):
        a = i / segments
        b = (i + 1) / segments
        va, vb = values[i], values[i + 1]
        ramp = f"({va:.6f}+({vb - va:.6f})*(({p})-{a:.6f})/{b - a:.6f})"
        expr = f"if(lt(({p})\\,{b:.6f})\\,{ramp}\\,{expr})"
    return expr


# ===========================================================================
def build_scene_filter(
    *,
    out_w: int,
    out_h: int,
    duration: float,
    fps: int,
    motion: str = "zoom_in",
    supersample: int = 6,
    zoom_amount: float = 1.12,
    pan_amount: float = 0.10,
    color_grade: str = "cinematic",
    vignette: bool = True,
    vignette_strength: float = 0.35,
    grain: float = 0.0,
    shake: float = 0.0,
    fade_seconds: float = 0.0,
    focus: str = "center",
) -> tuple[str, int, int]:
    """
    Build the -vf filtergraph that turns ONE still image into a moving clip.

    Returns (filter_string, padded_width, padded_height)
      padded_* are the even dimensions the source image is first scaled to
      (they must match what we pass to the `scale` filter before crop).

    HOW THE FILTER CHAIN READS
        [0:v] scale=W:H:force_original_aspect_ratio=increase   <- cover the frame
            , crop=W:H:(W-w)/2:(H-h)/2                          <- centre-crop to aspect
            , scale=iw*6:ih*6                                   <- supersample 6x
            , crop=cw(t):ch(t):cx(t):cy(t)                      <- the moving window
            , scale=out_w:out_h                                 <- back to video size
            , setsar=1, format=yuv420p                          <- player compatibility
            , <colour grade>, <vignette>, <grain>               <- the look
    """
    if motion not in MOTION_PRESETS:
        motion = "zoom_in"
    preset = MOTION_PRESETS[motion]

    z = max(1.0, float(zoom_amount))
    pan = max(0.0, float(pan_amount))
    d = max(0.2, float(duration))

    # focus bias: shift the aim point away from dead centre
    focus_offsets = {
        "center": (0.5, 0.5),
        "top": (0.5, 0.38), "bottom": (0.5, 0.62),
        "left": (0.38, 0.5), "right": (0.62, 0.5),
        "rule_of_thirds": (0.42, 0.42),
    }
    base_fx, base_fy = focus_offsets.get(str(focus), (0.5, 0.5))

    # ---- progress expression: p = t / duration ---------------------------
    p = f"(min(t\\,{d:.4f})/{d:.6f})"

    # ---- crop window SIZE over time --------------------------------------
    scale_fn = preset["scale"]
    s0 = _bake(scale_fn, z, pan, 0.0)
    s1 = _bake(scale_fn, z, pan, 1.0)
    smid = _bake(scale_fn, z, pan, 0.5)
    if abs(smid - (s0 + s1) / 2.0) < 1e-6:
        crop_scale_expr = _lerp_expr(s0, s1, p)          # straight line
    else:
        crop_scale_expr = _curve_expr(scale_fn, p)       # sine-ish preset

    # ---- crop window CENTRE over time ------------------------------------
    def centre_expr(time_key: str, const_key: str, fallback: float) -> str:
        if time_key in preset:
            fn = preset[time_key]
            v0, v1 = float(fn(0.0, pan)), float(fn(1.0, pan))
            vm = float(fn(0.5, pan))
            if abs(vm - (v0 + v1) / 2.0) < 1e-6:
                return _lerp_expr(v0, v1, p)
            return _curve_expr(lambda _p, _z, _pan, f=fn: f(_p, pan), p)
        value = float(preset.get(const_key, fallback))
        return f"{value:.6f}"

    fx_expr = centre_expr("fx_t", "fx", base_fx)
    fy_expr = centre_expr("fy_t", "fy", base_fy)

    # ---- the crop filter, clamped so ffmpeg can never go out of bounds ----
    ss = max(2, int(supersample))
    crop_w = f"trunc(iw*({crop_scale_expr})/2)*2"
    crop_h = f"trunc(ih*({crop_scale_expr})/2)*2"
    # x must stay inside [0, iw-crop_w]; the min/max pair guarantees that
    crop_x = f"max(0\\,min(iw-({crop_w})\\,(iw-({crop_w}))*min(1\\,max(0\\,({fx_expr})))))"
    crop_y = f"max(0\\,min(ih-({crop_h})\\,(ih-({crop_h}))*min(1\\,max(0\\,({fy_expr})))))"

    chain: list[str] = [
        # 1. make the image COVER the target aspect ratio (no black bars)
        f"scale={out_w}:{out_h}:force_original_aspect_ratio=increase:"
        f"flags=lanczos:eval=init",
        f"crop={out_w}:{out_h}",
        # 2. supersample so the moving crop is sub-pixel smooth
        f"scale=iw*{ss}:ih*{ss}:flags=lanczos:eval=init",
        # 3. the moving window (this IS the animation)
        f"crop=w={crop_w}:h={crop_h}:x={crop_x}:y={crop_y}",
        # 4. back down to video size (also sharpens)
        f"scale={out_w}:{out_h}:flags=lanczos",
        "setsar=1",
        f"fps={fps}",
        "format=yuv420p",
    ]

    # ---- optional handheld shake -----------------------------------------
    if shake and float(shake) > 0:
        amp = float(shake) * 6.0
        chain.append(
            f"crop={out_w}:{out_h}:"
            f"x='({amp:.2f}*sin(t*7.3))':y='({amp:.2f}*cos(t*5.1))':"
            f"exact=0"
        )
        chain.insert(-3, f"scale={out_w + int(amp * 4)}:{out_h + int(amp * 4)}")

    # ---- look -------------------------------------------------------------
    grade = COLOR_GRADES.get(str(color_grade), "")
    if grade:
        chain.append(grade)
    if vignette:
        # angle controls how dark the corners get; PI/5 is subtle, PI/3 heavy
        strength = max(0.0, min(1.0, float(vignette_strength)))
        angle = math.pi / 6.0 * (0.4 + strength)
        chain.append(f"vignette=angle={angle:.4f}:mode=forward:eval=init")
    if grain and float(grain) > 0:
        chain.append(f"noise=alls={float(grain) * 24:.0f}:allf=t+u")

    # ---- per-scene fade ----------------------------------------------------
    if fade_seconds and fade_seconds > 0:
        f = min(float(fade_seconds), d / 2.0 - 0.01)
        if f > 0:
            chain.append(f"fade=t=in:st=0:d={f:.3f}")
            chain.append(f"fade=t=out:st={max(0.0, d - f):.3f}:d={f:.3f}")

    return ",".join(chain), out_w * ss, out_h * ss


# ===========================================================================
# TRANSITIONS
# ===========================================================================
XFADE_MAP = {
    "crossfade": "fade",
    "fade": "fade",
    "fade_black": "fadeblack",
    "fade_white": "fadewhite",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "slide_up": "slideup",
    "slide_down": "slidedown",
    "wipe": "wipeleft",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
    "circle": "circleopen",
    "dissolve": "dissolve",
    "smooth": "smoothleft",
    "pixelize": "pixelize",
    "radial": "radial",
    "hblur": "hblur",
    "zoom": "zoomin",
}

# A tasteful rotation used when transitions.vary: true
VARY_POOL = ["fade", "fadeblack", "dissolve", "smoothleft", "wipeleft", "circleopen", "radial"]


def xfade_name(kind: str) -> str:
    return XFADE_MAP.get(str(kind).lower(), "fade")


def build_xfade_graph(durations: list[float], transition: str, tdur: float,
                      vary: bool = False) -> tuple[str, int, str]:
    """
    Build the filter_complex that crossfades N clips into one video.

    RETURNS
        filtergraph string
        number of video inputs expected
        label of the final video stream ("[vout]")

    WHY OFFSETS MATTER
        xfade overlaps the END of clip A with the START of clip B.
        offset = (total length of everything so far) - (transition duration)
        Get this wrong and the video jumps or freezes, so the bot computes it
        from the REAL measured duration of each clip, never from a guess.
    """
    n = len(durations)
    if n == 0:
        return "[0:v]null[vout]", 0, "[vout]"
    if n == 1:
        return "[0:v]null[vout]", 1, "[vout]"

    tdur = max(0.02, min(float(tdur), min(durations) * 0.45))
    parts: list[str] = []
    running = durations[0]
    prev = "[0:v]"

    for i in range(1, n):
        offset = max(0.0, running - tdur)
        name = transition
        if vary:
            name = VARY_POOL[(i - 1) % len(VARY_POOL)]
        out = f"[v{i}]" if i < n - 1 else "[vout]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition={name}:duration={tdur:.3f}:offset={offset:.3f}{out}"
        )
        prev = out
        running = offset + durations[i]

    return ";".join(parts), n, "[vout]"


# ===========================================================================
# AUDIO CHAINS
# ===========================================================================
VOICE_CHAINS = {
    "none": "",
    # remove rumble + hiss, add body and clarity, even out the dynamics
    "broadcast": (
        "highpass=f=75,"
        "lowpass=f=13000,"
        "equalizer=f=210:t=q:w=1.1:g=2.0,"     # chest/body
        "equalizer=f=3200:t=q:w=1.6:g=2.5,"     # presence/clarity
        "equalizer=f=6500:t=q:w=1.2:g=1.5,"     # air
        "deesser=i=0.4,"
        "acompressor=threshold=-19dB:ratio=3:attack=8:release=220:knee=6:makeup=2.2"
    ),
    "simple": "highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=10:release=200:makeup=2",
}


def voice_chain(kind: str = "broadcast") -> str:
    return VOICE_CHAINS.get(str(kind), VOICE_CHAINS["broadcast"])


def atempo_chain(tempo: float) -> str:
    """
    ffmpeg's atempo filter only accepts 0.5 - 2.0 per instance.
    To go faster/slower than that we CHAIN them: 1.6x -> atempo=1.2649,atempo=1.2649
    """
    tempo = float(tempo)
    if tempo <= 0:
        tempo = 1.0
    tempo = max(0.25, min(4.0, tempo))
    if abs(tempo - 1.0) < 1e-3:
        return ""
    filters: list[str] = []
    remaining = tempo
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return ",".join(filters)


def build_mix_graph(
    *,
    voice_duration: float,
    music_enabled: bool,
    music_volume_db: float,
    music_fade_in: float,
    music_fade_out: float,
    ducking: bool,
    duck_ratio: int,
    duck_attack_ms: int,
    duck_release_ms: int,
    voice_eq: str = "broadcast",
    normalize: bool = True,
    target_lufs: float = -16.0,
    limiter: bool = True,
    master_fade_out: float = 1.0,
    voice_chain_extra: str = "",
) -> str:
    """
    Build the filter_complex that mixes narration + background music.

    INPUT 0 = voice track      INPUT 1 = music track (may be absent)

    THE DUCKING TRICK
        sidechaincompress listens to the voice and squeezes the music whenever
        someone speaks, then lets it swell back up in the gaps. This is exactly
        what a human editor does by hand with volume automation - here it is
        automatic and free.
    """
    chain = voice_chain(voice_eq)
    if voice_chain_extra:
        chain = (chain + "," + voice_chain_extra) if chain else voice_chain_extra

    parts: list[str] = []
    if chain:
        parts.append(f"[0:a]{chain}[vc]")
        voice_label = "[vc]"
    else:
        voice_label = "[0:a]"

    if normalize:
        parts.append(
            f"{voice_label}loudnorm=I={target_lufs}:TP=-1.5:LRA=11:linear=true[vn]"
        )
        voice_label = "[vn]"

    total = max(0.5, float(voice_duration))

    if not music_enabled:
        # apad + the -t on the output guarantees an exact length: some filters
        # (loudnorm in particular) quietly eat the last few hundred ms.
        parts.append(f"{voice_label}aresample=48000:async=1:first_pts=0,apad[aout]")
        return ";".join(parts)

    mvol = max(-60.0, float(music_volume_db))
    mparts = [f"volume={mvol:.1f}dB"]
    if music_fade_in > 0:
        mparts.append(f"afade=t=in:st=0:d={music_fade_in:.2f}")
    if music_fade_out > 0:
        st = max(0.0, total - music_fade_out)
        mparts.append(f"afade=t=out:st={st:.2f}:d={music_fade_out:.2f}")
    mparts.append(f"atrim=0:{total:.3f}")
    mparts.append("asetpts=PTS-STARTPTS")
    parts.append("[1:a]" + ",".join(mparts) + "[mus]")

    if ducking:
        ratio = max(2, int(duck_ratio))
        parts.append(
            "[mus][0:a]sidechaincompress="
            f"threshold=0.05:ratio={ratio}:"
            f"attack={max(1, int(duck_attack_ms))}:release={max(50, int(duck_release_ms))}:"
            "knee=6:makeup=1.0[ducked]"
        )
        music_label = "[ducked]"
    else:
        music_label = "[mus]"

    parts.append(f"{voice_label}{music_label}amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix1]")

    # apad first: guarantees the graph can always reach the exact target length
    tail = ["aresample=48000:async=1:first_pts=0", "apad"]
    if limiter:
        tail.append("alimiter=limit=0.95:level=false")
    if master_fade_out > 0:
        tail.append(f"afade=t=out:st={max(0.0, total - master_fade_out):.2f}:d={master_fade_out:.2f}")
    parts.append("[mix1]" + ",".join(tail) + "[aout]")

    return ";".join(parts)


# ===========================================================================
# SUBTITLES
# ===========================================================================
def ass_style_from_cfg(style: dict, vertical: bool) -> str:
    """
    Build the -force_style string ffmpeg understands.
    Font size is auto-scaled for vertical video so captions stay readable.
    """
    size = int(style.get("font_size", 52))
    if vertical:
        size = int(size * 1.35)
    bits = [
        f"FontName={style.get('font', 'DejaVu Sans')}",
        f"FontSize={size}",
        f"Bold={-1 if style.get('bold', True) else 0}",
        f"PrimaryColour={style.get('primary_colour', '&H00FFFFFF')}",
        f"OutlineColour={style.get('outline_colour', '&H00000000')}",
        f"BackColour={style.get('back_colour', '&H80000000')}",
        f"Outline={style.get('outline', 3)}",
        f"Shadow={style.get('shadow', 1)}",
        f"MarginV={int(style.get('margin_v', 90))}",
        f"Alignment={style.get('alignment', 2)}",
        "BorderStyle=1",
    ]
    return ",".join(bits)


def escape_filter_path(path: str) -> str:
    """
    FFmpeg filter arguments need special escaping for  :  \\  '  and ,
    (this bites everyone on Windows paths like C:\\Users\\...)
    """
    p = str(path).replace("\\", "/")
    p = p.replace(":", "\\:").replace("'", "\\'")
    return p
