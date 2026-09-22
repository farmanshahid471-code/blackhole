"""
bot/providers/llm_manual.py
===========================
NO AI AT ALL - you write the script yourself.

WHY THIS EXISTS
---------------
The best scripts are written by a human. This provider is the honest answer to
"what if I do not want an LLM?" Everything else in the pipeline (voice, images,
motion, captions, mix) works exactly the same, because the manual provider
simply refuses to write anything and the bot uses YOUR file instead.

WHAT STILL WORKS
----------------
  * your timestamped script file                -> the whole video
  * image prompts you wrote with @prompt:       -> your visuals
  * scene titles, motions, voices, pauses       -> via directives
  * YouTube metadata                            -> built from your titles
                                                   (no LLM call is made)

WHAT DOES NOT WORK
------------------
  * --topic mode (asking the bot to invent a topic) - there is no LLM to ask.

USAGE
-----
    config.yaml ->   llm:
                       provider: "manual"
    then:
    python main.py run myvideo --script examples/black_holes_script.txt
"""
from __future__ import annotations

from ..registry import register
from .base import LLMProvider


@register("llm", "manual",
          cost="free",
          needs_key=False, quality="yours",
          setup_time="0 minutes",
          doc="No LLM. You supply the script file; the bot uses your image "
              "prompts. Perfect if you want zero accounts and zero cost.")
class ManualProvider(LLMProvider):
    """Deliberately does nothing - the bot falls back to your own text."""

    def healthcheck(self) -> tuple[bool, str]:
        return True, ("manual mode: no LLM will be used - "
                      "you must pass --script <your_file.txt>")

    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False,
             temperature: float | None = None, max_tokens: int | None = None) -> str:
        from ..utils import die
        die(
            "llm.provider is 'manual', so the bot cannot invent a script.\n"
            "  * to WRITE your own video:   python main.py run myvideo --script my_script.txt\n"
            "  * to have the bot write it:  set  llm.provider: deepseek  (or ollama) "
            "in config.yaml, then use --topic\n"
            "\n"
            "  (Tip: examples/black_holes_script.txt is a working example to copy.)"
        )
        return ""                                              # pragma: no cover
