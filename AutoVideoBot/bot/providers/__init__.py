"""
bot/providers/ - every interchangeable tool the bot can use
===========================================================

Each file in this folder is ONE tool, and each tool can be replaced by another
without touching any other part of the bot. The folder is scanned automatically
(bot/registry.py -> _autoload), so dropping a new .py file in here is enough to
make a new provider appear in the bot.

    llm_*.py       writes the script / image prompts / YouTube metadata
    tts_*.py       turns text into spoken audio
    image_*.py     turns a text prompt into a picture
    assembly_*.py  ffmpeg work: motion, transitions, mixing, final mux

The contract each provider must satisfy is written down (with examples) in
bot/providers/base.py. Read that file first if you want to add your own.
"""
