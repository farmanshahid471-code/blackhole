"""
bot/providers/tts_edge.py
=========================
Microsoft Edge voices - FREE, unlimited, no account, and they come with
WORD-LEVEL TIMESTAMPS.

This is the default voice of the bot and the best starting point for everyone.

WHY IT IS THE DEFAULT
---------------------
  * $0 and no sign-up: it is the same voice engine your Edge browser uses
  * documentary-quality neural voices (en-US-GuyNeural is the classic deep
    narrator voice)
  * it reports WHEN EVERY WORD IS SPOKEN. That single feature is what makes
    the subtitles line up perfectly with the audio, which is the difference
    between "AI slop" and "looks professionally edited".

REQUIREMENTS
------------
    pip install edge-tts        (already in requirements.txt)

HOW THE TIMESTAMPS WORK (why the code below looks the way it does)
------------------------------------------------------------------
edge-tts streams you two kinds of messages while it synthesises:
    WordBoundary  -> "the word 'horizon' starts at 1.24s, lasts 0.31s"
    audio chunks  -> the actual sound

We collect both at the same time, then write:
    audio -> the .wav/.mp3 file
    words -> <project>/audio/words/s01.json

If a scene's words are missing, the bot falls back to spreading the words
evenly over the scene - the video still works, captions are just less precise.

NOTE ON OFFSETS
---------------
edge-tts timestamps start at the beginning of ITS audio, but the bot adds a
little bit of silence in front of every scene (tts.head_silence_ms). The
timing stage adds that offset back, so captions stay in sync automatically.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..registry import register
from ..utils import ensure_dir, info, warn
from .base import TTSProvider

# Popular documentary voices, shown by  python main.py voices
FALLBACK_VOICES = [
    "en-US-GuyNeural", "en-US-ChristopherNeural", "en-US-EricNeural",
    "en-US-AriaNeural", "en-US-JennyNeural", "en-US-MichelleNeural",
    "en-GB-RyanNeural", "en-GB-SoniaNeural", "en-AU-WilliamNeural",
    "en-IN-PrabhatNeural", "en-IN-NeerjaNeural",
    "ur-PK-AsadNeural", "hi-IN-MadhurNeural",
]


@register("tts", "edge",
          cost="free (unlimited)",
          needs_key=False, quality="very high",
          setup_time="0 minutes (pip install edge-tts)",
          doc="Free Microsoft neural voices with word-level timestamps - the "
              "default. No key, no account, no limit.")
class EdgeTTSProvider(TTSProvider):
    """Free neural speech, with word timings for perfect captions."""

    # ------------------------------------------------------------------
    @staticmethod
    def _module():
        try:
            import edge_tts                                   # type: ignore
            return edge_tts
        except ImportError:
            from ..utils import die
            die(
                "edge-tts is not installed.\n"
                "  Run:   pip install edge-tts\n"
                "  (or run the installer:  scripts/install_windows.bat)"
            )

    # ------------------------------------------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        try:
            self._module()
        except SystemExit:
            return False, "edge-tts is not installed (pip install edge-tts)"

        voice = self.default_voice() or "en-US-GuyNeural"
        # The service is a web endpoint, so a real check needs a request.
        try:
            voices = asyncio.run(self._list_async())
        except Exception as e:
            return False, (
                f"Edge-TTS unavailable: {e.__class__.__name__}: {str(e)[:120]}\n"
                f"  This is a NETWORK problem (no internet, proxy, or firewall).\n"
                f"  Alternatives that work offline:  piper, espeak, voicestudio\n"
                f"  Or test the whole pipeline with:  --set tts.provider=test"
            )
        if voices and voice not in voices:
            close = [v for v in voices if v.startswith(voice.split("-")[0])][:5]
            return False, (f"voice '{voice}' was not found.\n"
                           f"  Close matches: {', '.join(close) or 'none'}\n"
                           f"  Full list:  python main.py voices --filter en-")
        return True, f"edge-tts ready ({len(voices)} voices available, using {voice})"

    async def _list_async(self) -> list[str]:
        edge_tts = self._module()
        result = await edge_tts.list_voices()
        return [v["ShortName"] for v in result]

    def list_voices(self) -> list[str]:
        try:
            return asyncio.run(self._list_async())
        except Exception as e:
            info(f"  could not fetch the online voice list ({str(e)[:80]}) - "
                 f"showing the built-in shortlist")
            return FALLBACK_VOICES

    # ------------------------------------------------------------------
    async def _speak(self, text: str, out_path: Path, voice: str,
                     rate: str, pitch: str, volume: str) -> list[dict[str, Any]]:
        """Run one synthesis and collect audio + word boundaries together."""
        edge_tts = self._module()
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, volume=volume)

        words: list[dict[str, Any]] = []
        ensure_dir(out_path.parent)
        with open(out_path, "wb") as fh:
            async for chunk in communicate.stream():
                kind = chunk.get("type")
                if kind == "audio":
                    fh.write(chunk["data"])
                elif kind == "WordBoundary":
                    # edge-tts gives 100-nanosecond units -> divide for seconds
                    offset = float(chunk.get("offset", 0)) / 1e7
                    dur = float(chunk.get("duration", 0)) / 1e7
                    words.append({
                        "w": str(chunk.get("text", "")),
                        "s": round(offset, 3),
                        "e": round(offset + dur, 3),
                    })
        return words

    # ------------------------------------------------------------------
    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None,
                   rate: str | None = None, pitch: str | None = None,
                   target_duration: float | None = None) -> dict[str, Any]:
        """
        Speak `text` into `out_path`.

        target_duration is accepted but IGNORED here on purpose: Microsoft's
        service does not let you ask for an exact length. The bot's timing
        stage stretches (up to tts.max_speedup) or pads the audio afterwards.
        """
        out_path = Path(out_path)
        voice = str(voice or self.default_voice() or "en-US-GuyNeural")
        rate = str(rate if rate is not None else self.setting("tts.rate", "+0%"))
        pitch = str(pitch if pitch is not None else self.setting("tts.pitch", "+0Hz"))
        volume = str(self.setting("tts.volume", "+0%"))

        words: list[dict[str, Any]] = []
        last_error: Exception | None = None

        # Small transient network errors are normal for a free shared service,
        # so try a few times before giving up on the scene.
        attempts = 3
        for attempt in range(1, attempts + 1):
            try:
                words = asyncio.run(self._speak(text, out_path, voice, rate, pitch, volume))
                last_error = None
                break
            except Exception as e:
                last_error = e
                if attempt < attempts:
                    info(f"  edge-tts hiccup ({attempt}/{attempts}) - retrying")

        if last_error is not None:
            raise RuntimeError(
                f"edge-tts failed for this scene: {last_error}\n"
                f"  If your internet is fine, try another voice, or switch with\n"
                f"     --set tts.provider=test     (offline toolchain check)"
            )

        if not out_path.exists() or out_path.stat().st_size < 512:
            raise RuntimeError(
                "edge-tts produced an empty file - the service may be blocking "
                "this machine. Try  --set tts.provider=test  to verify your setup."
            )

        if not words:
            warn("  no word timings came back for this scene - captions will be "
                 "spread evenly across it instead of word-perfect")

        return {
            "path": out_path,
            "words": words or None,
            "voice": voice,
            "duration": (words[-1]["e"] if words else None),
        }
