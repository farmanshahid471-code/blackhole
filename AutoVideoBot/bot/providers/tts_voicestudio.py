"""
bot/providers/tts_voicestudio.py
================================
VoiceStudio (https://github.com/debpalash/VoiceStudio) - a self-hosted voice
server that can render an EXACT number of seconds of speech.

WHY THIS ONE IS SPECIAL
-----------------------
Every other free voice service gives you "however long the sentence takes".
When your script has timestamps, the bot then has to speed the voice up or
slow it down to fit - and a voice sped up 30% sounds nervous.

VoiceStudio accepts a `duration` parameter. So the voice is generated to fit
the scene from the start: perfect sync, natural delivery, no stretching.

WHAT YOU NEED
-------------
  1. Clone/run VoiceStudio (it is a FastAPI app, default port 3900):
         https://github.com/debpalash/VoiceStudio
     It runs on your PC, on a Vast.ai GPU, or anywhere you like.
  2. Put its address in .env:
         VOICESTUDIO_URL=http://localhost:3900
  3. config.yaml ->  tts:
                        provider: "voicestudio"

TWO WAYS TO TALK TO IT (the bot tries both)
-------------------------------------------
  A) the OpenAI-compatible route, which VoiceStudio ships:
         POST /v1/audio/speech   {"input": "...", "voice": "...", "duration": 12.5}
     -> raw audio bytes back
  B) the native multipart route:
         POST /generate          (form fields: text, voice, duration)
     -> JSON or raw audio

If your build uses different names, DO NOT edit Python - edit config.yaml:
    tts.voicestudio.api_path, tts.voicestudio.method,
    tts.voicestudio.json_body, tts.voicestudio.response_field
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from ..registry import register
from ..utils import debug, ensure_dir, info
from .base import TTSProvider

DEFAULT_URL = "http://localhost:3900"


@register("tts", "voicestudio",
          cost="free (self-hosted; GPU rental if you use one)",
          needs_key=False, quality="very high (voice cloning)",
          setup_time="30 minutes (or use a cloud GPU)",
          doc="Self-hosted VoiceStudio / OmniVoice server. The only provider "
              "that can render an exact scene duration -> perfect sync with "
              "your timestamps, no tempo stretching.")
class VoiceStudioProvider(TTSProvider):
    """Self-hosted voice server with exact-duration support."""

    # ------------------------------------------------------------------
    def _url(self) -> str:
        return str(self.secret("tts.voicestudio.url_env", DEFAULT_URL) or DEFAULT_URL).rstrip("/")

    def _voice(self) -> str:
        return str(self.secret("tts.voicestudio.voice_env") or
                   self.setting("tts.voicestudio.voice", "default") or "default")

    # ------------------------------------------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        import requests
        base = self._url()
        for path in ("/health", "/"):
            try:
                r = requests.get(base + path, timeout=8)
            except Exception:
                continue
            if r.status_code < 500:
                return True, f"VoiceStudio reachable at {base} (voice: {self._voice()})"
        return False, (
            f"VoiceStudio is not answering at {base}.\n"
            "  * Is it running?  (it is a FastAPI app; check its terminal window)\n"
            "  * Is the port right?  VOICESTUDIO_URL in .env  (default http://localhost:3900)\n"
            "  * On a cloud GPU: use the public address it gave you, e.g.\n"
            "        VOICESTUDIO_URL=http://203.0.113.7:3900\n"
            "  * No VoiceStudio yet? Use the free default instead:\n"
            "        tts.provider: edge"
        )

    def list_voices(self) -> list[str]:
        import requests
        for path in ("/v1/audio/voices", "/voices", "/api/voices"):
            try:
                r = requests.get(self._url() + path, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict):
                        data = data.get("voices") or data.get("data") or []
                    out = []
                    for v in data:
                        if isinstance(v, dict):
                            out.append(str(v.get("id") or v.get("name") or v))
                        else:
                            out.append(str(v))
                    if out:
                        return out
            except Exception:
                continue
        return [self._voice()]

    # ------------------------------------------------------------------
    def _post_native(self, text: str, voice: str, want: float | None,
                     out_path: Path) -> bool:
        """Try the configurable native route. Returns True on success."""
        import requests
        vcfg = self.setting("tts.voicestudio", {}) or {}
        path = str(vcfg.get("api_path", "/api/tts"))
        method = str(vcfg.get("method", "POST")).upper()
        body_tpl = vcfg.get("json_body") or {"text": "{text}", "voice": "{voice}"}
        field = str(vcfg.get("response_field", "audio"))
        timeout = int(vcfg.get("timeout", 300))

        body: dict[str, Any] = {}
        for k, v in body_tpl.items():
            if isinstance(v, str):
                body[k] = (v.replace("{text}", text).replace("{voice}", voice)
                           .replace("{rate}", "1.0"))
            else:
                body[k] = v
        if want:
            body["duration"] = float(want)

        url = self._url() + path
        debug(f"voicestudio: {method} {url} (duration={want})")
        try:
            if method == "GET":
                r = requests.get(url, params=body, timeout=timeout)
            else:
                r = requests.post(url, json=body, timeout=timeout)
        except Exception as e:
            debug(f"voicestudio native route failed: {e}")
            return False

        if r.status_code != 200:
            debug(f"voicestudio native route HTTP {r.status_code}: {r.text[:200]}")
            return False

        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            try:
                data = r.json()
            except Exception:
                return False
            val = data.get(field) if isinstance(data, dict) else None
            if not val and isinstance(data, dict):
                for k in ("audio", "audio_base64", "audio_b64", "data", "url", "file"):
                    if data.get(k):
                        val = data[k]
                        break
            if not val:
                return False
            if isinstance(val, str) and len(val) > 256 and "://" not in val:
                try:
                    out_path.write_bytes(base64.b64decode(val))
                    return True
                except Exception:
                    return False
            if isinstance(val, str) and val.startswith("http"):
                rr = requests.get(val, timeout=timeout)
                if rr.status_code == 200:
                    out_path.write_bytes(rr.content)
                    return True
            return False

        if len(r.content) > 512:
            out_path.write_bytes(r.content)
            return True
        return False

    def _post_openai(self, text: str, voice: str, want: float | None,
                     out_path: Path) -> bool:
        """Try the OpenAI-compatible /v1/audio/speech route."""
        import requests
        url = self._url() + "/v1/audio/speech"
        payload: dict[str, Any] = {
            "model": "tts-1",
            "input": text,
            "voice": voice,
            "response_format": "wav",
        }
        if want:
            payload["duration"] = float(want)     # VoiceStudio extension
        try:
            r = requests.post(url, json=payload, timeout=600)
        except Exception as e:
            debug(f"voicestudio openai route failed: {e}")
            return False
        if r.status_code == 200 and len(r.content) > 512:
            out_path.write_bytes(r.content)
            return True
        debug(f"voicestudio openai route HTTP {r.status_code}: {r.text[:200]}")
        return False

    # ------------------------------------------------------------------
    def synthesize(self, text: str, out_path: Path, *, voice: str | None = None,
                   rate: str | None = None, pitch: str | None = None,
                   target_duration: float | None = None) -> dict[str, Any]:
        out_path = Path(out_path)
        ensure_dir(out_path.parent)
        voice = str(voice or self._voice())
        want = float(target_duration) if target_duration else None

        ok = self._post_openai(text, voice, want, out_path) or \
            self._post_native(text, voice, want, out_path)
        if not ok:
            raise RuntimeError(
                f"VoiceStudio did not return audio (tried {self._url()}/v1/audio/speech "
                f"and {self._url()}/api/tts).\n"
                f"  * Check the server is running and VOICESTUDIO_URL is right.\n"
                f"  * Different route names? Set them in config.yaml under tts.voicestudio.\n"
                f"  * In a hurry?  --set tts.provider=edge"
            )

        if not out_path.exists() or out_path.stat().st_size < 512:
            raise RuntimeError("VoiceStudio returned an empty file")

        # VoiceStudio usually replies with WAV. If it sent MP3 while we asked
        # for .wav, convert so the rest of the pipeline never has to care.
        self._fix_container(out_path)

        return {"path": out_path, "words": None, "voice": voice,
                "duration": want}

    @staticmethod
    def _fix_container(path: Path) -> None:
        """If an MP3 landed in a .wav file, convert it properly."""
        try:
            head = path.read_bytes()[:4]
        except Exception:
            return
        is_wav = head[:4] == b"RIFF"
        is_mp3 = head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0)
        if is_wav or not is_mp3:
            return
        try:
            from pydub import AudioSegment
            seg = AudioSegment.from_file(str(path), format="mp3")
            seg.export(str(path), format="wav")
            info("  (the server sent MP3 - converted to WAV)")
        except Exception:
            pass    # ffmpeg/ffprobe later stages can still read a mislabelled mp3
