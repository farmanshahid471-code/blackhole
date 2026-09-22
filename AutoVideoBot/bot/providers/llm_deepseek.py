"""
bot/providers/llm_deepseek.py
=============================
DeepSeek - the cheap, high-quality brain that writes the script.

WHY DEEPSEEK
------------
A 10-minute documentary script (about 2,000 words) costs roughly $0.002 with
deepseek-chat. It is an OpenAI-compatible API, which means the code below is
almost identical to the openai_compat provider - the only difference is where
the base URL and the model name come from.

WHAT IT WRITES
--------------
  1. a whole script from a topic               (script mode B)
  2. an image prompt for every scene           (inside the same JSON)
  3. YouTube title / description / tags        (extras stage)

GET A KEY:  https://platform.deepseek.com/api_keys
PUT IT IN:  .env  ->  DEEPSEEK_API_KEY=sk-...
"""
from __future__ import annotations

import json
from typing import Any

from ..registry import register
from ..utils import debug, info
from .base import LLMProvider

# Default endpoints, used if .env does not override them
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


@register("llm", "deepseek",
          cost="~$0.001-$0.01 per video",
          needs_key=True, quality="very high",
          setup_time="2 minutes",
          doc="Official DeepSeek API. Writes the script, the image prompts and "
              "the YouTube metadata. Cheapest good option.")
class DeepSeekProvider(LLMProvider):
    """Talks to the DeepSeek chat-completions endpoint."""

    # ------------------------------------------------------------------
    def _setup(self) -> None:
        if self._client is not None:
            return
        key = self.secret("llm.deepseek.api_key_env") or self.secret("llm.deepseek.api_key")
        if not key:
            from ..utils import die
            die(
                "DeepSeek API key is missing.\n"
                "  1. get one at https://platform.deepseek.com/api_keys\n"
                "  2. open the file  .env  in this folder (copy .env.example if you "
                "have no .env yet)\n"
                "  3. put it on the line  DEEPSEEK_API_KEY=sk-...\n"
                "  4. save the file and run the command again\n"
                "\n"
                "  Want to skip the LLM completely? Use your own script file:\n"
                "     python main.py run myvideo --script my_script.txt"
            )
        base = self.secret("llm.deepseek.base_url_env", DEFAULT_BASE_URL)
        self._client = {
            "key": key,
            "base": str(base).rstrip("/"),
            "model": str(self.secret("llm.deepseek.model_env") or
                         self.setting("llm.deepseek.model", DEFAULT_MODEL)),
        }
        debug(f"deepseek: base={self._client['base']} model={self._client['model']}")

    # ------------------------------------------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        try:
            self._setup()
        except SystemExit:
            return False, ("DEEPSEEK_API_KEY is empty in .env  "
                           "(only needed when the LLM writes your script)")
        except Exception as e:
            return False, f"DeepSeek not configured: {e}"

        import requests
        url = f"{self._client['base']}/models"
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {self._client['key']}"},
                             timeout=20)
        except Exception as e:
            return False, (f"could not reach {url} ({e.__class__.__name__}).\n"
                           f"  If you have no internet, use --script <file> instead of --topic,\n"
                           f"  or switch the LLM:  llm.provider: ollama  (free, offline)")
        if r.status_code == 200:
            return True, f"DeepSeek reachable (model: {self._client['model']})"
        if r.status_code in (401, 403):
            return False, ("DeepSeek rejected the API key (401/403).\n"
                           "  Check DEEPSEEK_API_KEY in your .env file - no spaces, no quotes.")
        if r.status_code == 402:
            return False, "DeepSeek account has no credit left - top up or switch to ollama."
        return False, f"DeepSeek answered HTTP {r.status_code}: {r.text[:160]}"

    # ------------------------------------------------------------------
    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False,
             temperature: float | None = None, max_tokens: int | None = None) -> str:
        self._setup()
        import requests

        payload: dict[str, Any] = {
            "model": self._client["model"],
            "messages": messages,
            "temperature": float(temperature if temperature is not None
                                 else self.setting("llm.deepseek.temperature", 0.8)),
            "max_tokens": int(max_tokens or self.setting("llm.deepseek.max_tokens", 4096)),
            "stream": False,
        }
        if json_mode:
            # DeepSeek (like OpenAI) will then guarantee valid JSON in the reply
            payload["response_format"] = {"type": "json_object"}

        url = f"{self._client['base']}/chat/completions"
        attempts = max(1, int(self.setting("llm.deepseek.retries", 3)))
        timeout = int(self.setting("llm.deepseek.timeout", 120))
        last = ""

        for attempt in range(1, attempts + 1):
            try:
                r = requests.post(
                    url, json=payload, timeout=timeout,
                    headers={"Authorization": f"Bearer {self._client['key']}",
                             "Content-Type": "application/json"},
                )
            except Exception as e:
                last = f"{e.__class__.__name__}: {e}"
                info(f"  deepseek network problem ({attempt}/{attempts}) - retrying")
                continue

            if r.status_code == 200:
                data = r.json()
                try:
                    return str(data["choices"][0]["message"]["content"])
                except (KeyError, IndexError, TypeError):
                    raise RuntimeError(f"unexpected DeepSeek reply shape: {str(data)[:300]}")

            last = f"HTTP {r.status_code}: {r.text[:300]}"
            # 429 = rate limited, 5xx = their server hiccuped: both worth a retry
            if r.status_code in (429, 500, 502, 503, 504):
                info(f"  deepseek busy ({r.status_code}) - retrying ({attempt}/{attempts})")
                continue
            break

        raise RuntimeError(
            f"DeepSeek request failed: {last}\n"
            f"  Fixes: check DEEPSEEK_API_KEY in .env, or try  llm.provider: ollama  "
            f"(free, offline), or write the script yourself and use --script."
        )

    # ------------------------------------------------------------------
    def teardown(self) -> None:
        self._client = None
