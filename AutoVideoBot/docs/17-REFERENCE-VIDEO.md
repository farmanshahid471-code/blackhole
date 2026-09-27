# Optional YouTube reference for topic-mode videos

In **Create a video → Write it for me**, enter a topic and (optionally) a
single public YouTube video URL in **YouTube reference video**. The bot studies
the reference **before** writing its script, image prompts, and motion/shot
choices. CLI equivalent:

```bash
python main.py run "my-video" --topic "how a black hole forms" \
  --reference-video "https://www.youtube.com/watch?v=VIDEO_ID" --duration 120
```

You may also pass `--reference-video` to `python main.py script`. It is not
available when you provide your own script; your script always wins.

## What it really analyzes

- `yt-dlp` downloads **one** public video, up to 15 minutes and 150 MB, at a
  reduced resolution when available (video-only WebM is supported; reference
  audio is not needed or downloaded). FFmpeg samples eight ordered stills.
  A higher-resolution video stream is tried only if no reduced-resolution
  stream is available; the same 150 MB limit still applies. It also requests
  available English, Urdu or Hindi captions (including automatic captions).
  Downloading can fail when YouTube restricts the video, requires sign-in, or
  changes its delivery. Use material you have the right to analyze.
- Without a vision model: the script writer gets time-coded transcript excerpts,
  the video's title and duration, and measured frame palette/changes. This
  supports **narrative flow** and rough pacing. It does **not** recognize
  objects, camera actions, or animation styles from pixel statistics. A
  captionless video needs a configured vision model; otherwise the bot stops
  with a clear error rather than pretending to have studied it.
- For *visual content and animation style*, configure a **vision-capable**
  OpenAI-compatible chat endpoint. In `config.yaml`, set
  `reference.vision.model` to your actual vision model name, and in `.env` set:

  ```text
  REFERENCE_VISION_BASE_URL=https://api.openai.com/v1
  REFERENCE_VISION_API_KEY=your-own-key
  ```

  The bot sends eight resized frames to `/chat/completions` for a short style
  guide. This is an **extra API request** and may incur provider charges.
  For a local alternative, run an Ollama vision model (e.g. `ollama pull
  llava`) and set `REFERENCE_VISION_BASE_URL=http://127.0.0.1:11434/v1` with
  `reference.vision.model: llava`. The local endpoint needs no vision API key;
  the bot uses an Ollama-compatible placeholder. `llm.provider: deepseek` is
  text-only by default; its key does not automatically enable reference vision. If the vision API fails, stage 1
  fails explicitly. Review the vision provider's privacy and billing terms.
- The study feeds the topic LLM an **inspiration brief**, not frames or footage
  to reproduce. Image mode can only make new stills plus Ken Burns motion;
  documentary/Remotion mode has a fixed shot library. Neither engine can
  replicate arbitrary animation, transitions, character designs, or precise
  timing from an external video. The output should remain original, not a
  copy of another creator's footage, narration, branding, or music.

The report is kept as `workspace/projects/<name>/reference.json` for reuse;
temporary footage and sampled frames are deleted after study. `script.json`
records the source URL and whether captions/vision were actually used. To
change a reference, provide a new link and regenerate the **script** (and
later stages); a link with the same video ID reuses the cached study unless
you change `reference.vision.model` or delete `reference.json`. Do not add
untrusted downloaded video to the project repository.

Install/update dependencies via `INSTALL-WINDOWS.bat` or `pip install -r
requirements.txt`. If you already installed an older copy, run `python -m pip
install yt-dlp` in that copy's virtual environment, or extract the latest ZIP
and run its installer.
