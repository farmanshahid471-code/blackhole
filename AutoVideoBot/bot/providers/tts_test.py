"""
bot/providers/tts_test.py
=========================
A fake "voice" that needs no internet, no API key and no voices installed.

WHAT IT IS FOR (this is more useful than it sounds)
---------------------------------------------------
When something is broken you need to know WHICH half is broken:

    "Is my computer's setup wrong, or is it the voice service?"

Run any command with:

    python main.py run myvideo --script s.txt --set tts.provider=test

If a complete video comes out, your ffmpeg / Python / rendering setup is 100%
correct, and the problem is the real voice service (a key, a URL, a firewall).
If it still fails, the problem is local and you can see exactly where.

It is ALSO the answer to "I want to try the whole thing right now, offline,
before signing up for anything".

WHAT YOU HEAR
-------------
Not speech - a calm synthesised tone (a soft two-note pad) whose LENGTH is
proportional to the number of words, so timing, mixing, captions and rendering
all behave exactly like a real narration. Word timings are generated evenly,
so the caption pipeline is exercised too.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any

from ..registry import register
from ..utils import ensure_dir
from .base import TTSProvider

SAMPLE_RATE = 22050
WORDS_PER_SECOND = 2.6          # roughly a documentary narrator's pace


def _write_tone(path: Path, seconds: float, words: int) -> None:
    """
    Write a mono 16-bit WAV with a gentle two-note drone and soft word pulses.

    Pure Python on purpose: no numpy, no ffmpeg, no network. If THIS cannot
    run, Python itself is the problem.
    """
    ensure_dir(path.parent)
    n = max(1, int(seconds * SAMPLE_RATE))
    frames = bytearray()
    base = 138.59          # C#3, low and calm
    fifth = 207.65         # G#3
    pulse_every = max(0.25, seconds / max(1, words))

    for i in range(n):
        t = i / SAMPLE_RATE
        # fade the first and last 60 ms so there are no clicks
        env = min(1.0, t / 0.06, max(0.0, (seconds - t) / 0.06))
        # slow breathing movement between the two notes
        mix = 0.5 + 0.5 * math.sin(2 * math.pi * t / max(1.0, seconds))
        v = (0.30 * math.sin(2 * math.pi * base * t)
             + 0.18 * math.sin(2 * math.pi * fifth * t)
             + 0.05 * math.sin(2 * math.pi * (base * 2) * t))
        v *= (0.75 + 0.25 * mix)
        # a tiny amplitude bump at each "word" so you can HEAR the word grid
        phase = (t % pulse_every) / pulse_every
        v *= 0.85 + 0.15 * math.exp(-6.0 * phase)
        sample = int(max(-1.0, min(1.0, v * env)) * 32000)
        frames += struct.pack("<h", sample)

    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(bytes(frames))


@register("tts", "test",
          cost="free (offline)",
          needs_key=False, quality="a tone, not a voice",
          setup_time="0 minutes, works with no internet",
          doc="Toolchain check + offline demo voice. Synthesises a calm tone "
              "whose length matches the text, plus word timings. Use it to prove "
              "your setup works before signing up for anything.")
class TestTTSProvider(TTSProvider):
    """Offline placeholder narration - for testing and demos only."""

    def healthcheck(self) -> tuple[bool, str]:
        return True, "test voice ready (offline tone - no internet needed)"

    def list_voices(self) -> list[str]:
        return ["drone  (the only 'voice' - it is a test tone)"]

    def default_voice(self) -> str:
        return "drone"

    # ------------------------------------------------------------------
    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None,
                   rate: str | None = None, pitch: str | None = None,
                   target_duration: float | None = None) -> dict[str, Any]:
        words_list = [w for w in str(text).split() if w.strip()]
        n_words = max(1, len(words_list))

        # Honour the requested scene length when we are given one, so timing
        # behaves like a real service that supports exact durations.
        natural = n_words / WORDS_PER_SECOND
        seconds = float(target_duration) if target_duration else natural
        seconds = max(1.0, min(120.0, seconds))

        out_path = Path(out_path).with_suffix(".wav")
        _write_tone(out_path, seconds, n_words)

        # spread the word timings evenly, exactly like a caption engine would
        step = seconds / n_words
        words = [{
            "w": w,
            "s": round(i * step, 3),
            "e": round(min(seconds, (i + 1) * step), 3),
        } for i, w in enumerate(words_list)]

        return {
            "path": out_path,
            "words": words,
            "voice": "drone",
            "duration": round(seconds, 3),
        }
