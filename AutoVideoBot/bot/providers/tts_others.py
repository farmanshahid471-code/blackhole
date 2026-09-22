"""
bot/providers/tts_others.py
===========================
Four more voices, kept together because each one is short:

    elevenlabs   best quality money can buy, voice cloning (paid)
    openai_tts   simple and good (paid)
    piper        fully offline neural voice (free, needs one download)
    espeak       fully offline robotic fallback (free, sounds like 1995)

Every one of them satisfies the same contract, so `--set tts.provider=piper`
works exactly like `--set tts.provider=edge`.
"""
from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ..registry import register
from ..utils import debug, die, ensure_dir, info, which
from .base import TTSProvider


# ===========================================================================
# ELEVENLABS - the best voices available, paid
# ===========================================================================
@register("tts", "elevenlabs",
          cost="$0.10-$0.30 per 10-minute video",
          needs_key=True, quality="best available",
          setup_time="3 minutes",
          doc="Industry-leading neural voices and voice cloning. Word-level "
              "timings included. Get a key at elevenlabs.io.")
class ElevenLabsProvider(TTSProvider):
    BASE = "https://api.elevenlabs.io/v1"

    def _key(self) -> str:
        key = self.secret("tts.elevenlabs.api_key_env")
        if not key:
            die(
                "ElevenLabs needs an API key.\n"
                "  1. https://elevenlabs.io/app/settings/api-keys\n"
                "  2. .env ->  ELEVENLABS_API_KEY=sk_...\n"
                "  3. .env ->  ELEVENLABS_VOICE_ID=<the voice you want>\n"
                "     (find ids with:  python main.py voices --set tts.provider=elevenlabs)\n"
                "  Free alternative with no account:  --set tts.provider=edge"
            )
        return key

    def healthcheck(self) -> tuple[bool, str]:
        try:
            key = self._key()
        except SystemExit:
            return False, "ELEVENLABS_API_KEY is empty in .env"
        import requests
        try:
            r = requests.get(f"{self.BASE}/user", headers={"xi-api-key": key}, timeout=20)
        except Exception as e:
            return False, f"could not reach ElevenLabs ({e.__class__.__name__})"
        if r.status_code == 200:
            data = r.json()
            left = ((data.get("subscription") or {}).get("character_limit", 0) -
                    (data.get("subscription") or {}).get("character_count", 0))
            return True, f"ElevenLabs ready ({left:,} characters left this month)"
        if r.status_code == 401:
            return False, "ElevenLabs rejected the key (401) - check ELEVENLABS_API_KEY in .env"
        return False, f"ElevenLabs HTTP {r.status_code}: {r.text[:160]}"

    def list_voices(self) -> list[str]:
        import requests
        try:
            r = requests.get(f"{self.BASE}/voices", headers={"xi-api-key": self._key()}, timeout=30)
            return [f"{v['voice_id']}  {v.get('name', '')}" for v in (r.json().get("voices") or [])]
        except Exception as e:
            return [f"(could not list voices: {e})"]

    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None,
                   rate: str | None = None, pitch: str | None = None,
                   target_duration: float | None = None) -> dict[str, Any]:
        import requests
        e = self.setting("tts.elevenlabs", {}) or {}
        voice_id = str(voice or self.secret("tts.elevenlabs.voice_id_env") or
                       e.get("voice_id", "") or "21m00Tcm4TlvDq8ikWAM")
        fmt = str(e.get("output_format", "mp3_44100_128"))
        url = f"{self.BASE}/text-to-speech/{voice_id}/with-timestamps"   # gives word timings
        payload = {
            "text": text,
            "model_id": e.get("model_id", "eleven_multilingual_v2"),
            "voice_settings": {
                "stability": float(e.get("stability", 0.45)),
                "similarity_boost": float(e.get("similarity_boost", 0.80)),
                "style": float(e.get("style", 0.35)),
            },
        }
        r = requests.post(url, json=payload, timeout=300,
                          headers={"xi-api-key": self._key(), "Content-Type": "application/json"})
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs HTTP {r.status_code}: {r.text[:300]}")

        data = r.json()
        audio_b64 = data.get("audio_base64")
        if not audio_b64:
            raise RuntimeError("ElevenLabs returned no audio")
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        out_path.write_bytes(base64.b64decode(audio_b64))

        words: list[dict[str, Any]] = []
        al = (data.get("alignment") or {})
        chars = al.get("characters") or []
        starts = al.get("character_start_times_seconds") or []
        ends = al.get("character_end_times_seconds") or []
        if chars and starts and ends:
            # ElevenLabs aligns per CHARACTER; glue characters into words.
            cur, t0 = "", None
            for ch, s, en in zip(chars, starts, ends):
                if ch.isspace():
                    if cur:
                        words.append({"w": cur, "s": round(t0 or 0, 3), "e": round(en, 3)})
                        cur, t0 = "", None
                    continue
                if t0 is None:
                    t0 = float(s)
                cur += ch
            if cur:
                words.append({"w": cur, "s": round(t0 or 0, 3), "e": round(float(ends[-1]), 3)})

        return {"path": out_path, "words": words or None, "voice": voice_id,
                "duration": None}


# ===========================================================================
# OPENAI TTS - simple, good, paid
# ===========================================================================
@register("tts", "openai_tts",
          cost="~$0.015 per 1,000 characters",
          needs_key=True, quality="high",
          setup_time="2 minutes",
          doc="OpenAI's gpt-4o-mini-tts. Simple and reliable, but no word "
              "timings (captions are spread evenly instead).")
class OpenAITTSProvider(TTSProvider):
    def _setup(self) -> dict[str, str]:
        key = self.secret("tts.openai_tts.api_key_env")
        if not key:
            die("OpenAI TTS needs a key: .env -> OPENAI_API_KEY=sk-...\n"
                "  (free alternative:  --set tts.provider=edge)")
        o = self.setting("tts.openai_tts", {}) or {}
        return {
            "key": key,
            "base": str(o.get("base_url", "https://api.openai.com/v1")).rstrip("/"),
            "model": str(o.get("model", "gpt-4o-mini-tts")),
            "voice": str(self.secret("tts.openai_tts.voice_env") or o.get("voice", "alloy")),
        }

    def healthcheck(self) -> tuple[bool, str]:
        try:
            s = self._setup()
        except SystemExit:
            return False, "OPENAI_API_KEY is empty in .env"
        import requests
        try:
            r = requests.get(f"{s['base']}/models", timeout=20,
                             headers={"Authorization": f"Bearer {s['key']}"})
        except Exception as e:
            return False, f"could not reach OpenAI ({e.__class__.__name__})"
        if r.status_code == 200:
            return True, f"OpenAI TTS ready (model: {s['model']}, voice: {s['voice']})"
        if r.status_code == 401:
            return False, "OpenAI rejected the key (401)"
        return False, f"OpenAI HTTP {r.status_code}"

    def list_voices(self) -> list[str]:
        return ["alloy", "ash", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer"]

    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None,
                   rate: str | None = None, pitch: str | None = None,
                   target_duration: float | None = None) -> dict[str, Any]:
        import requests
        s = self._setup()
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        fmt = "wav" if out_path.suffix.lower() == ".wav" else "mp3"
        r = requests.post(
            f"{s['base']}/audio/speech",
            json={"model": s["model"], "input": text,
                  "voice": str(voice or s["voice"]), "response_format": fmt},
            headers={"Authorization": f"Bearer {s['key']}"}, timeout=300,
        )
        if r.status_code != 200:
            raise RuntimeError(f"OpenAI TTS HTTP {r.status_code}: {r.text[:300]}")
        out_path.write_bytes(r.content)
        return {"path": out_path, "words": None, "voice": voice or s["voice"], "duration": None}


# ===========================================================================
# PIPER - offline neural voice
# ===========================================================================
@register("tts", "piper",
          cost="free (offline)",
          needs_key=False, quality="medium (surprisingly good)",
          setup_time="10 minutes (download the binary + a voice)",
          doc="Piper runs fully offline on a normal CPU. Download it once, then "
              "it never touches the internet again.")
class PiperProvider(TTSProvider):
    def _binary(self) -> str:
        b = str(self.setting("tts.piper.binary", "piper") or "piper")
        found = which(b) or (b if Path(b).exists() else None)
        if not found:
            die(
                "Piper is not installed.\n"
                "  1. download it:  https://github.com/rhasspy/piper/releases\n"
                "  2. unzip it somewhere permanent (e.g. C:\\piper)\n"
                "  3. put the .exe (or the linux binary) on your PATH, or set its full\n"
                "     path in config.yaml -> tts.piper.binary\n"
                "  4. download a voice (.onnx + .onnx.json) into assets/piper/\n"
                "     e.g. https://huggingface.co/rhasspy/piper-voices\n"
                "  Free alternative needing no install:  --set tts.provider=edge"
            )
        return found

    def _model(self) -> Path:
        name = str(self.setting("tts.piper.voice_model", "en_US-lessac-medium.onnx"))
        from ..paths import ROOT
        for cand in (ROOT / "assets" / "piper" / name, Path(name)):
            if cand.exists():
                return cand
        die(f"Piper voice model not found: {name}\n"
            f"  Download the .onnx AND its .onnx.json into "
            f"{ROOT / 'assets' / 'piper'} and try again.")
        raise SystemExit(1)                                       # pragma: no cover

    def healthcheck(self) -> tuple[bool, str]:
        try:
            binary, model = self._binary(), self._model()
        except SystemExit:
            return False, ("piper binary or voice model not found "
                           "(see docs/05-PROVIDERS.md, or use --set tts.provider=edge)")
        try:
            subprocess.run([binary, "--help"], capture_output=True, timeout=20)
        except Exception as e:
            return False, f"could not run piper ({e})"
        return True, f"Piper ready ({model.name})"

    def list_voices(self) -> list[str]:
        from ..paths import ROOT
        d = ROOT / "assets" / "piper"
        return [p.name for p in d.glob("*.onnx")] or ["(no .onnx voices in assets/piper yet)"]

    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None,
                   rate: str | None = None, pitch: str | None = None,
                   target_duration: float | None = None) -> dict[str, Any]:
        binary = self._binary()
        model = Path(voice) if voice and Path(str(voice)).exists() else self._model()
        out_path = Path(out_path)
        ensure_dir(out_path.parent)

        # piper reads text on stdin and writes a wav to --output_file
        if out_path.suffix.lower() != ".wav":
            tmp = out_path.with_suffix(".wav")
        else:
            tmp = out_path
        proc = subprocess.run(
            [binary, "--model", str(model), "--output_file", str(tmp)],
            input=text.encode("utf-8"), capture_output=True, timeout=600,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"piper failed: {proc.stderr.decode('utf-8', 'ignore')[:300]}")
        if tmp != out_path:
            shutil.move(str(tmp), str(out_path))
        return {"path": out_path, "words": None, "voice": model.stem, "duration": None}


# ===========================================================================
# ESPEAK-NG - the always-works fallback
# ===========================================================================
@register("tts", "espeak",
          cost="free (offline)",
          needs_key=False, quality="low (robotic)",
          setup_time="2 minutes (install espeak-ng)",
          doc="The ultimate fallback: tiny, offline, never fails. Sounds "
              "robotic - use it to test, not to publish.")
class EspeakProvider(TTSProvider):
    def _binary(self) -> str:
        for name in ("espeak-ng", "espeak"):
            found = which(name)
            if found:
                return found
        die(
            "espeak-ng is not installed.\n"
            "  Windows: https://github.com/espeak-ng/espeak-ng/releases\n"
            "  macOS  : brew install espeak-ng\n"
            "  Linux  : sudo apt install espeak-ng\n"
            "  Or just use:  --set tts.provider=edge   (better and needs no install)"
        )
        raise SystemExit(1)                                       # pragma: no cover

    def healthcheck(self) -> tuple[bool, str]:
        try:
            b = self._binary()
        except SystemExit:
            return False, "espeak-ng not installed (see docs/05-PROVIDERS.md)"
        try:
            subprocess.run([b, "--version"], capture_output=True, timeout=15)
        except Exception as e:
            return False, f"could not run espeak ({e})"
        return True, f"espeak-ng ready ({Path(b).name}) - robotic but unbreakable"

    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None,
                   rate: str | None = None, pitch: str | None = None,
                   target_duration: float | None = None) -> dict[str, Any]:
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        wav = out_path.with_suffix(".wav")
        # espeak's -s is words per minute (default 175 is a calm narrator)
        wpm = 165
        cmd = [self._binary(), "-v", str(voice or "en-us"), "-s", str(wpm), "-w", str(wav), text]
        proc = subprocess.run(cmd, capture_output=True, timeout=600)
        if proc.returncode != 0 or not wav.exists():
            raise RuntimeError(f"espeak failed: {proc.stderr.decode('utf-8', 'ignore')[:300]}")
        if wav != out_path:
            shutil.move(str(wav), str(out_path))
        return {"path": out_path, "words": None, "voice": voice or "en-us", "duration": None}
