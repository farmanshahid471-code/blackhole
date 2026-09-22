"""
bot/providers/llm_openai_compat.py
==================================
ANY service that speaks the OpenAI chat-completions language.

This one provider unlocks a huge list of brains, because almost every company
copied OpenAI's request format. You only change three values in .env:

    ---------------------------------------------------------------
    service        OPENAI_BASE_URL                    OPENAI_MODEL
    ---------------------------------------------------------------
    Groq           https://api.groq.com/openai/v1     llama-3.3-70b-versatile
    OpenRouter     https://openrouter.ai/api/v1       deepseek/deepseek-chat-v3
    Together       https://api.together.xyz/v1        deepseek-ai/DeepSeek-V3
    OpenAI         https://api.openai.com/v1          gpt-4o-mini
    LM Studio      http://localhost:1234/v1           any pulled model
    vLLM (your    http://localhost:8000/v1            your model
      own GPU)
    ---------------------------------------------------------------

The API key is optional on purpose: local servers (LM Studio, vLLM, Ollama's
OpenAI bridge) often need no key at all, so an empty key is not an error here.

USAGE
-----
    config.yaml ->   llm:
                       provider: "openai_compat"
    .env        ->   OpenAI_API_KEY=...      (or leave empty for local servers)
"""
from __future__ import annotations

from typing import Any

from ..registry import register
from ..utils import debug, info
from .base import LLMProvider


@register("llm", "openai_compat",
          cost="free to cheap",
          needs_key=False, quality="high",
          setup_time="3 minutes",
          doc="Any OpenAI-compatible API: Groq, OpenRouter, Together, "
              "OpenAI, LM Studio, vLLM. Just set OPENAI_BASE_URL + OPENAI_MODEL.")
class OpenAICompatProvider(LLMProvider):
    """One HTTP call, works with a dozen different companies."""

    def _setup(self) -> None:
        if self._client is not None:
            return
        key = self.secret("llm.openai_compat.api_key_env") or self.secret("llm.openai_compat.api_key")
        base = self.secret("llm.openai_compat.base_url_env") or self.setting("llm.openai_compat.base_url")
        model = self.secret("llm.openai_compat.model_env") or self.setting("llm.openai_compat.model")

        if not base:
            from ..utils import die
            die(
                "openai_compat needs an address.\n"
                "  Open .env and fill in BOTH lines:\n"
                "     OPENAI_BASE_URL=https://api.groq.com/openai/v1\n"
                "     OPENAI_MODEL=llama-3.3-70b-versatile\n"
                "  (the list of known services is in .env.example and docs/05-PROVIDERS.md)"
            )
        if not model:
            from ..utils import die
            die("openai_compat needs a model name. Set OPENAI_MODEL=... in your .env file.")

        self._client = {"key": key or "", "base": str(base).rstrip("/"), "model": str(model)}
        debug(f"openai_compat: base={self._client['base']} model={self._client['model']} "
              f"key={'yes' if key else 'none (ok for local servers)'}")

    # ------------------------------------------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        try:
            self._setup()
        except SystemExit:
            return False, "openai_compat is not configured yet (see the message above)"
        except Exception as e:
            return False, str(e)

        import requests
        headers = {"Content-Type": "application/json"}
        if self._client["key"]:
            headers["Authorization"] = f"Bearer {self._client['key']}"
        url = f"{self._client['base']}/models"
        try:
            r = requests.get(url, headers=headers, timeout=20)
        except Exception as e:
            return False, (f"could not reach {url} ({e.__class__.__name__}).\n"
                           f"  Is the server running? For LM Studio/vLLM check the port,\n"
                           f"  for cloud services check your internet connection.")
        if r.status_code in (200, 404):
            # 404 is fine: some compatible servers do not implement /models
            return True, f"OpenAI-compatible API reachable at {self._client['base']}"
        if r.status_code in (401, 403):
            return False, (f"{self._client['base']} rejected the key.\n"
                           f"  Put your key in .env -> OPENAI_API_KEY=...  "
                           f"(or leave it empty if this is a local server)")
        return False, f"HTTP {r.status_code} from {url}: {r.text[:160]}"

    # ------------------------------------------------------------------
    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False,
             temperature: float | None = None, max_tokens: int | None = None) -> str:
        self._setup()
        import requests

        headers = {"Content-Type": "application/json"}
        if self._client["key"]:
            headers["Authorization"] = f"Bearer {self._client['key']}"

        payload: dict[str, Any] = {
            "model": self._client["model"],
            "messages": messages,
            "temperature": float(temperature if temperature is not None
                                 else self.setting("llm.openai_compat.temperature", 0.8)),
            "max_tokens": int(max_tokens or self.setting("llm.openai_compat.max_tokens", 4096)),
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self._client['base']}/chat/completions"
        last = ""
        for attempt in range(1, 4):
            try:
                r = requests.post(url, json=payload, headers=headers, timeout=180)
            except Exception as e:
                last = f"{e.__class__.__name__}: {e}"
                info(f"  request failed ({attempt}/3) - retrying")
                continue
            if r.status_code == 200:
                data = r.json()
                try:
                    return str(data["choices"][0]["message"]["content"])
                except (KeyError, IndexError, TypeError):
                    raise RuntimeError(f"unexpected reply shape: {str(data)[:300]}")
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code in (429, 500, 502, 503, 504):
                info(f"  server busy ({r.status_code}) - retrying ({attempt}/3)")
                # Some OpenAI-compatible servers reject response_format: retry
                # once without it rather than failing the whole video.
                payload.pop("response_format", None)
                continue
            break
        raise RuntimeError(f"openai_compat request failed: {last}")

    def teardown(self) -> None:
        self._client = None
