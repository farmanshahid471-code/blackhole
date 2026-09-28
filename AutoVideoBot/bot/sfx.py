"""Licensed-asset-free procedural transitions, scheduled against the scene timeline.

The generated sounds are synthesized here (not sampled from third-party audio).
Set audio.sfx.enabled=false to remove them. Explicit scene sfx=[] suppresses
all automatic cues for that scene.
"""
from __future__ import annotations

import hashlib
import math
import random
import struct
import wave
from pathlib import Path

from .utils import ensure_dir

KINDS = ("whoosh", "rumble")
RATE = 48000


def synthesize(kind: str, out: Path) -> Path:
    if kind not in KINDS:
        raise ValueError(f"unsupported sound effect: {kind}")
    ensure_dir(out.parent)
    rng = random.Random(291 if kind == "whoosh" else 802)
    duration = 1.15 if kind == "whoosh" else 1.75
    count = int(RATE * duration)
    low = 0.0
    pcm = bytearray()
    for i in range(count):
        t = i / RATE
        x = i / count
        if kind == "whoosh":
            envelope = (math.sin(math.pi*x)**1.65) * .8
            cutoff = 200 + 11000*math.sin(math.pi*x)**2
            alpha = min(1, 2*math.pi*cutoff/RATE)
            noise = rng.uniform(-1, 1)
            low += alpha*(noise-low)
            sample = (low*.55 + .12*math.sin(2*math.pi*(90*t+450*t*t))) * envelope
        else:
            envelope = min(1.0, x*7) * (1-x)**1.5
            low += .028*(rng.uniform(-1, 1)-low)
            sample = (.31*math.sin(2*math.pi*42*t) + .16*math.sin(2*math.pi*59*t)
                      + low*.18)*envelope
        sample = max(-.95, min(.95, sample))
        pcm.extend(struct.pack('<h', int(sample*32767)))
    with wave.open(str(out), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return out


def plan_events(scenes: list[dict], cfg, folder: Path) -> list[dict]:
    """Return absolute timeline events with local WAVs and positive-safe gain."""
    if not cfg.get("audio.sfx.enabled", True):
        return []
    ensure_dir(folder)
    events = []
    # An effect-synthesis code change must not silently reuse an old WAV.
    version = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:8]
    for index, scene in enumerate(scenes):
        cues = scene.get("sfx")
        if cues is None:
            cues = []
            if index:
                cues.append({"kind": "whoosh", "t": 0.0})
            if scene.get("shot") == "event_horizon_flythrough":
                cues.append({"kind": "rumble", "t": round(float(scene["duration"])*.68, 3)})
        start, duration = float(scene.get("start") or 0), float(scene.get("duration") or 0)
        for cue in cues:
            kind = cue["kind"]
            rel = float(cue["t"])
            if not 0 <= rel < duration:
                raise ValueError(f"{scene['id']}: SFX cue at {rel}s is outside its {duration}s scene")
            path = folder / f"{kind}-{version}.wav"
            if not path.exists():
                synthesize(kind, path)
            events.append({"path": path, "kind": kind,
                           "at": round(max(0, start + rel - (.25 if kind == "whoosh" else .12)), 3),
                           "gain_db": float(cfg.get(f"audio.sfx.{kind}_gain_db", -20))})
    return events
