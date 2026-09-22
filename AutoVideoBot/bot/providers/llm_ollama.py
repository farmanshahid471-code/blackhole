"""
bot/providers/llm_ollama.py
===========================
A local, 100% free, 100% offline brain running on YOUR computer.

WHY THIS IS THE BEST OPTION FOR SOME PEOPLE
-------------------------------------------
  * no account, no key, no bill, ever
  * works with the internet unplugged, so the bot never "calls home"
  * a modern 7-8B model writes perfectly usable documentary scripts

The trade-off: you need ~5-8 GB of free RAM (or a GPU) and the first download
is a few GB. After that it is instant forever.

SETUP (one time, 5 minutes)
---------------------------
  1. install Ollama:            https://ollama.com/download
  2. open a terminal and run:   ollama pull llama3.1
     (other good picks: qwen2.5:7b, mistral, gemma2:9b)
  3. in config.yaml:            llm:
                                    provider: "ollama"
  4. check it works:            python main.py doctor

Ollama must be RUNNING (it starts automatically after install; if not, run
`ollama serve` in a terminal and leave that window open).
"""
from __future__ import annotations

from typing import Any

from ..registry import register
from ..utils import debug, die, info
from .base import LLMProvider

DEFAULT_URL = "http://localhost:11434"


@register("llm", "ollama",
          cost="free (your own PC)",
          needs_key=False, quality="medium to high",
          setup_time="5 minutes + model download",
          doc="Local offline LLM through Ollama. No account, no cost, no "
              "internet needed. Great for privacy and for testing.")
class OllamaProvider(LLMProvider):
    """Talks to the Ollama server on your own machine."""

    def _setup(self) -> None:
        if self._client is not None:
            return
        base = self.secret("llm.ollama.base_url_env", DEFAULT_URL) or DEFAULT_URL
        model = self.secret("llm.ollama.model_env") or self.setting("llm.ollama.model", "llama3.1")
        self._client = {"base": str(base).rstrip("/"), "model": str(model)}
        debug(f"ollama: base={self._client['base']} model={self._client['model']}")

    # ------------------------------------------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        self._setup()
        import requests
        try:
            r = requests.get(f"{self._client['base']}/api/tags", timeout=8)
        except Exception:
            return False, (
                "Ollama is not running (nothing answers on "
                f"{self._client['base']}).\n"
                "  1. install it:  https://ollama.com/download\n"
                "  2. run it:      ollama serve        (leave that window open)\n"
                "  3. download a model once:  ollama pull llama3.1\n"
                "  (or use another provider: llm.provider: deepseek)"
            )
        if r.status_code != 200:
            return False, f"Ollama answered HTTP {r.status_code}"

        try:
            models = [m.get("name", "") for m in (r.json().get("models") or [])]
        except Exception:
            models = []
        if not models:
            return False, ("Ollama is running but has NO models yet.\n"
                           "  Run:  ollama pull llama3.1   (about 4.7 GB, one time)")
        have = self._client["model"]
        if not any(m.split(":")[0] == have.split(":")[0] for m in models):
            return False, (f"Ollama is running, but your configured model "
                           f"'{have}' is not downloaded.\n"
                           f"  Run:  ollama pull {have}\n"
                           f"  (installed models: {', '.join(models[:6])})")
        return True, f"Ollama ready (model: {have})"

    # ------------------------------------------------------------------
    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False,
             temperature: float | None = None, max_tokens: int | None = None) -> str:
        self._setup()
        import requests

        payload: dict[str, Any] = {
            "model": self._client["model"],
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": float(temperature if temperature is not None
                                     else self.setting("llm.ollama.temperature", 0.8)),
            },
        }
        if json_mode:
            # Ollama forces valid JSON when you ask for this format
            payload["format"] = "json"

        url = f"{self._client['base']}/api/chat"
        info(f"  asking local model '{self._client['model']}' (this can take a minute on a CPU)")
        try:
            r = requests.post(url, json=payload, timeout=900)
        except Exception as e:
            die(f"Ollama request failed: {e}\n  Make sure 'ollama serve' is running.")

        if r.status_code != 200:
            raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        content = (data.get("message") or {}).get("content")
        if not content:
            raise RuntimeError(f"Ollama returned no text: {str(data)[:300]}")
        return str(content)

    def teardown(self) -> None:
        self._client = None
