# 15 - How it all works, and everything it needs (APIs, keys, accounts)

This is the page to read if you are asking: *"What exactly happens between me
typing a topic and a finished MP4 appearing, and what do I have to sign up
for?"*

Read it top to bottom once. After that it works as a reference.

---

## 0. The 60-second answer

**What it does**

You give it either
* a **topic** ("how black holes bend time", 45 seconds long), or
* **your own script with timestamps** (a `.txt` file),

and it produces `workspace/projects/<name>/output/final.mp4` - 1920x1080,
30 fps, narrated, with moving visuals, crossfades, captions burnt in, background
music that ducks under the voice, a thumbnail and a YouTube title/description.

**What it needs, in total**

| # | Thing | Needed? | How you get it |
|---|---|---|---|
| 1 | A Windows PC, 8 GB RAM, ~15 GB free disk | Yes | You already have it |
| 2 | Python 3.10-3.12 | Yes | `INSTALL-WINDOWS.bat` installs it for you |
| 3 | FFmpeg (the video engine) | Yes | Bundled automatically - you install nothing |
| 4 | One LLM API key **or** your own script file | Only for topic mode | DeepSeek (~1 cent) / Groq (free) / Ollama (free, offline) |
| 5 | A voice | For the free default: nothing at all | Edge TTS is free, no key, no account |
| 6 | A way to make pictures | For the free default: nothing at all | Pollinations is free, no key, no account |

**That is the whole list.** There is no paid subscription, no credit card, no
account required for the default path. The paid options exist only if you want
better quality, and you can add them later by pasting one line into `.env`.

**Money, realistically**, for one 10-minute documentary:

```
Script (DeepSeek)          ~$0.002      <- fractions of a cent
Voice (Edge)               $0
Images (Pollinations)      $0           (or ~$0.10 via Replicate, or ~$0.05 via a rented GPU)
Music, motion, captions,
mix, render, thumbnail     $0           (all local, all free)
---------------------------------------------------------
TOTAL, free path           $0
TOTAL, best-quality path   ~$0.15 - $0.40
```

---

## 1. How it works, stage by stage

The bot is a **pipeline of 10 stages**. Each stage reads files the previous
stage wrote and writes its own. That is why you can re-run one stage without
redoing the whole video (`python main.py images myvideo --force`).

```
        YOUR INPUT                          WHAT THE BOT DOES
   ┌──────────────────┐
   │ topic  OR        │
   │ script.txt       │
   └────────┬─────────┘
            v
 1  SCRIPT      ->  script.json          topic mode: LLM writes scenes + image prompts
                                         script mode: your file is parsed (no LLM)
            v
 2  VOICE       ->  audio/sXX.mp3        one audio file per scene, from the TTS provider
            v
 3  TIMING      ->  timing.json          measures each audio file, fits it into your
                                         timestamps (max +35% / -15% speed), word timings
            v
 4  IMAGES      ->  images/sXX.png       one picture per scene (cloud, your GPU, or a
                                         placeholder card if nothing is available)
            v
 5  MOTION      ->  clips/sXX.mp4        Ken Burns pan/zoom on each still (15 presets)
            v
 6  TRANSITION  ->  video_silent.mp4     crossfades between scenes, exact total length
            v
 7  SUBTITLES   ->  subs/*.ass + .srt    captions built from real word timings
            v
 8  MIX         ->  mix.wav              voice mastered to -16 LUFS + music ducked 8:1
            v
 9  ASSEMBLY    ->  output/final.mp4     picture + sound + burnt-in captions, H.264/AAC
            v
10  EXTRAS      ->  thumbnail.jpg        best frame + YouTube title/description/tags
                    youtube_metadata.json
```

Every stage is **cached**. The bot keeps a manifest
(`project/manifest/script.json`) that records "stage 4 is done for scene s03,
and the file still exists". If you run the same project again and nothing
changed, it skips straight through. Change something and only the affected
stages redo their work.

### Which stages touch the internet

| Stage | Internet? | Who it talks to |
|---|---|---|
| 1 script | only in topic mode | your LLM (DeepSeek / Groq / OpenRouter / Ollama on your PC) |
| 2 voice | yes, unless you use an offline voice | Microsoft Edge TTS / VoiceStudio / ElevenLabs / Piper (offline) |
| 3 timing | no | FFmpeg on your PC |
| 4 images | yes, unless you use your own GPU on your own PC | Pollinations / your Colab / your Vast GPU / Replicate |
| 5 motion | no | FFmpeg on your PC |
| 6 transitions | no | FFmpeg |
| 7 subtitles | no | FFmpeg + Pillow |
| 8 mix | no | FFmpeg |
| 9 assembly | no | FFmpeg |
| 10 extras | needs the LLM for the YouTube text, not for the thumbnail | your LLM |

**Roughly: 3 of 10 stages need the internet, and only 1 needs a paid key.**
Everything that is heavy work - motion, encoding, mixing, captions - happens on
your own machine, for free.

### The files it creates

```
workspace/projects/black-holes/
├── project/
│   ├── manifest/script.json     the cache: what is finished, and the script itself
│   ├── voice_full.wav           every scene joined into one narration track
│   ├── voice_norm.wav           the same, mastered
│   ├── music_full.wav           background music, looped to the exact length
│   ├── mix.wav                  voice + music, ducked, limited  <- stage 8 output
│   └── video_silent.mp4         picture only, no sound        <- stage 6 output
├── audio/s01.mp3 ...            per-scene voice files  (+ audio/words/s01.json = word timings)
├── images/s01.png ...           per-scene pictures
├── clips/s01.mp4 ...            per-scene moving clips
├── subs/captions.ass, .srt      caption files
├── output/
│   ├── final.mp4                <- THE VIDEO
│   ├── thumbnail.jpg
│   └── youtube_metadata.json
└── logs/run.log                 full log of every run
```

Note the mix outputs live at the **project root** (`project/mix.wav`), not in
`audio/`. That surprises people looking for them.

---

## 2. What you need on the machine

### Hardware

| | Minimum | Comfortable |
|---|---|---|
| OS | Windows 10/11 64-bit | same |
| RAM | 8 GB | 16 GB+ |
| CPU | any 4-core | modern 6-8 core |
| Disk free | 10 GB | 30 GB+ |
| GPU | **not required** | not required either - the cloud does the AI |

The GPU is only useful if you want to generate the images *locally* (Stable
Diffusion WebUI). Nothing else here uses a GPU: video encoding is done by
FFmpeg on the CPU, and the AI models live in the cloud.

If your RAM is small, the bot protects itself: it caps x264 encode threads and
lookahead, picks a safe Ken Burns supersampling factor (2x instead of 6x), and
if FFmpeg still gets killed by the OS it retries automatically at `ultrafast`.

### Disk space, realistic

| Video length | Free space to plan for |
|---|---|
| 47-second test | ~1.5 GB with all intermediates kept |
| 5 minutes | ~2-3 GB |
| 10 minutes | ~4-6 GB |

Measured example from this machine: the finished 47-second video is 6.2 MB, but
the kept intermediates (images + clips + wavs) are a few hundred MB. If you set
`system.keep_intermediate_files: false`, the clips are deleted after the export
and you need far less.

### Software the installer handles for you

`INSTALL-WINDOWS.bat` does all of this, in order, and you can run it again any
time to repair:

1. Finds Python; if missing, offers to install it (winget, then the official
   installer as a fallback).
2. Creates `.venv` - a private Python sandbox inside the project folder, so
   nothing on your system is touched.
3. `pip install -r requirements.txt` - requests, PyYAML, python-dotenv, Pillow,
   rich, tqdm, edge-tts, pydub, fastapi, uvicorn, python-multipart, psutil,
   imageio-ffmpeg.
4. **Gets FFmpeg** through `imageio-ffmpeg`: a complete real FFmpeg binary is
   downloaded into the project and used directly. Nothing is added to your
   PATH, nothing is installed system-wide, and FFmpeg never needs to be found
   manually. (If FFprobe is missing, the bot reads durations by parsing
   `ffmpeg -i` output instead - you lose nothing.)
5. Creates `assets/background_music`, `assets/fonts`, `workspace/projects`,
   copies `.env.example` to `.env`.
6. Runs the **doctor** and prints a verdict.
7. Offers a menu: start the web UI, start the console, or exit.

Only three dependencies are genuinely optional and are not installed by
default: `replicate` (paid images), `elevenlabs` (paid voices),
`moviepy` (alternative renderer), `vastai` (the Vast.ai CLI - only needed for
the "let the bot rent a GPU" mode).

### Network

Only outbound HTTPS on port 443 to these hosts, depending on your choices:

| Host | Used for | Can you avoid it? |
|---|---|---|
| `api.deepseek.com` | script + metadata | yes - Groq, OpenRouter, or Ollama locally, or write your own script |
| `speech.platform.bing.com` | free Edge voices | yes - Piper or eSpeak, both fully offline |
| `image.pollinations.ai` | free images | yes - SD WebUI on your PC, or a rented GPU |
| `api.elevenlabs.io`, `api.openai.com`, `api.replicate.com` | the paid upgrades | not used unless you ask for them |
| `console.vast.ai` | renting a GPU | only if you pick that provider |

No inbound ports, no port forwarding, no router configuration. That is a
deliberate design choice: your PC dials out, nothing dials in.

---

## 3. Every API, in detail

This is the "api and all" section. For each one: what the bot sends, what comes
back, and where the key goes.

### 3.1 LLM - writing the script (stage 1) and the YouTube text (stage 10)

Only **two** calls per video, both plain JSON chat calls. No streaming, no
function calling, nothing exotic.

**DeepSeek (the recommended default)**

```
POST https://api.deepseek.com/chat/completions
Headers:
  Authorization: Bearer <DEEPSEEK_API_KEY>
  Content-Type: application/json

Body:
{
  "model": "deepseek-chat",
  "messages": [
    {"role": "system", "content": "<contents of prompts/script_system.txt>"},
    {"role": "user",   "content": "<topic, target length, scene rules>"}
  ],
  "temperature": 0.8,
  "max_tokens": 4096,
  "response_format": {"type": "json_object"}     <- the bot asks for pure JSON
}
```

The reply is a JSON object with the title, description, tags and one entry per
scene (narration + image prompt). The bot parses it, repairs the usual small
JSON damage automatically, and writes `script.json`.

The health check is `GET https://api.deepseek.com/models` with the same key, so
"is my key working?" costs nothing.

```ini
# .env
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```
Cost: about **$0.002** for a 10-minute script. You do not need to top up much -
$1 lasts a very long time.

**The same bot, a different brain** - `llm.provider: openai_compat` sends an
identical body to whatever base URL you give it:

| Service | `OPENAI_BASE_URL` | Model | Cost |
|---|---|---|---|
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` | free tier |
| OpenRouter | `https://openrouter.ai/api/v1` | `deepseek/deepseek-chat-v3` | pay per token |
| Together | `https://api.together.xyz/v1` | `deepseek-ai/DeepSeek-V3` | pay per token |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | pay per token |
| LM Studio (your PC) | `http://localhost:1234/v1` | any loaded model | free |

**Ollama** - `llm.provider: ollama`, `http://localhost:11434`, free, offline,
needs 5-8 GB of free RAM. Small models are weaker at strict JSON; the bot
repairs a lot, but for reliable output use a bigger model or DeepSeek.

**manual** - `llm.provider: manual` disables the LLM completely. Perfect if you
write your own scripts and want zero accounts and zero cost. Image prompts then
come from your `@prompt:` lines, or from the `prompts/image_polish.txt` template
(no LLM call at all).

### 3.2 TTS - the voice (stage 2)

**Edge TTS - the free default. No key, no account, no signup.**

The `edge-tts` library opens a WebSocket to Microsoft's public "read aloud"
service (`speech.platform.bing.com`) and streams back MP3, plus **word-level
timings**. Those timings are what make the captions land on the right word, so
Edge is not just free - it is the best-fitting default.

```
.env / config.yaml:  (nothing at all)
tts:
  provider: "edge"
  edge:
    voice: "en-US-ChristopherNeural"    # documentary-ish; many other voices exist
```
List them with `python main.py voices --filter en-US` (or `--filter en-GB`,
`--filter en-IN`). Unlimited length, unlimited use.

**VoiceStudio (self-hosted, voice cloning, exact scene durations)**

This is the option you asked for by name. VoiceStudio runs on your PC (or on a
rented GPU) and exposes two routes; the bot tries the first, falls back to the
second:

```
POST http://localhost:3900/v1/audio/speech        (OpenAI-compatible)
{
  "model": "tts-1",
  "input": "Somewhere in this galaxy, a star is dying.",
  "voice": "default",
  "duration": 12.5                 <- VoiceStudio extension: render EXACTLY this long
}
Headers: Content-Type: application/json    (optionally Authorization: Bearer <token>)

fallback:
POST http://localhost:3900/generate               (native multipart form)
fields: text, voice, duration
```

Because VoiceStudio accepts `duration`, the voice arrives already the right
length for your timestamp window and the bot does **no** speed-up/slow-down at
all - the cleanest possible sync. `.env`:

```ini
VOICESTUDIO_URL=http://localhost:3900
VOICESTUDIO_VOICE=default
```
plus `tts.provider: voicestudio` and, if you cloned a voice,
`tts.voicestudio.profile_id`. To run it on a rented GPU instead, start its
backend with `--host 0.0.0.0 --port 3900`, open that port in the provider's
firewall, and point `VOICESTUDIO_URL` at the public address - nothing else
changes.

**ElevenLabs (best quality, paid)**

```
POST https://api.elevenlabs.io/v1/text-to-speech/<ELEVENLABS_VOICE_ID>
Headers: xi-api-key: <ELEVENLABS_API_KEY>
Body:    {"text": "...", "model_id": "eleven_multilingual_v2",
          "voice_settings": {"stability": 0.45, "similarity_boost": 0.8}}
Health:  GET https://api.elevenlabs.io/v1/user   (also reports characters left)
```
About **$0.10-$0.30 per 10-minute video**. Voice cloning included.

**OpenAI TTS**

```
POST https://api.openai.com/v1/audio/speech
{"model": "gpt-4o-mini-tts", "voice": "onyx", "input": "..."}
```
About **$0.015 per 1,000 characters** (a 10-minute script is roughly 8,000
characters).

**Piper (offline, free)** - `pip install piper-tts`, then
`python -m piper.download_voices en_US-lessac-medium --data-dir assets/piper`.
Local binary, local model, no internet, decent neural quality.

**eSpeak (offline, free, robotic)** - the last resort so a pipeline never
dead-ends. Fine for testing sync, not for publishing.

**test** - `--set tts.provider=test` makes silent audio of exactly the right
length, plus fake word timings. Use it to test everything except the voice.
It is what makes the pipeline fully verifiable with no internet at all.

### 3.3 Images (stage 4)

**Pollinations - the free default. No key, no account.**

It is a plain URL - the prompt goes in the path, the settings go in the query:

```
GET https://image.pollinations.ai/prompt/<url-encoded prompt>
      ?width=1920&height=1080&model=flux&nologo=true&seed=12345
<- the image bytes themselves (PNG/JPEG)
```

That is the entire API. It is a free shared service, so the bot is built to
survive it: a delay between requests, a retry ladder that steps down through
several models when one is busy, and a couple of retries with backoff. If it
still fails, the scene gets a **placeholder card** instead of the whole run
dying, and that placeholder is never cached as final - the next run retries the
real image.

**Stable Diffusion WebUI (AUTOMATIC1111 / Forge) - your own GPU, local or remote**

```
GET  {SDWEBUI_URL}/sdapi/v1/sd-models                <- health + model list
POST {SDWEBUI_URL}/sdapi/v1/txt2img
{
  "prompt": "dark cinematic space photography, ultra detailed, ...",
  "negative_prompt": "text, watermark, blurry, deformed, ...",
  "width": 1920, "height": 1080,
  "steps": 30, "cfg_scale": 7.0,
  "sampler_name": "DPM++ 2M Karras",
  "seed": -1
}
<- {"images": ["<base64 png>"], "info": "{...}"}
```

Start it with `python launch.py --api --listen --port 7860`. Because this one
provider speaks the standard SD WebUI API, it covers a **local** GPU, a
**Colab**-hosted WebUI via a tunnel, a **Vast.ai** machine, and RunPod - all by
changing `SDWEBUI_URL`. Optional extras: auto-load a checkpoint by name
(`image.sdwebui.model`), and a 2-pass `hires_fix`.

**The bot's own GPU protocol (used by Colab, Vast.ai and Kaggle)**

Three different remote setups, one tiny fixed protocol, so the server can be
swapped as easily as the provider:

```
POST <endpoint>/generate
{"jobs": [
   {"id": "s01", "prompt": "...", "width": 1920, "height": 1080,
    "steps": 30, "guidance_scale": 7.0, "seed": null}, ...
]}
<- {"results": [
     {"id": "s01", "ok": true,  "image_b64": "<base64 png>"},
     {"id": "s02", "ok": false, "error": "CUDA out of memory"}]}

GET <endpoint>/health
<- {"ok": true, "gpu": "Tesla T4", "model": "SDXL"}
```

Batching matters: all the scenes for a run are sent in **one** request, so the
GPU loads the model once instead of once per image.

* **Colab (free T4 GPU)** - open `deploy/colab/colab_image_server.ipynb`, click
  *Run all*, and its last cell prints a public URL like
  `https://abcd-1234.ngrok-free.app`. Paste that into `.env` as
  `IMAGE_ENDPOINT_URL`, or pass `--endpoint https://...` for one run. The
  notebook serves exactly the two routes above. The bot pings `/health` every
  25 s so Colab does not fall asleep.
* **Vast.ai (rented GPU, pay per second)** - the bot drives it through the
  official CLI plus the REST API at `https://console.vast.ai/api/v0`:
  `search offers` (filter by GPU type, VRAM, max price) -> `create instance`
  with a PyTorch CUDA image, 32 GB disk, `--ssh` and a mapped port -> wait for
  SSH -> upload `deploy/vast/server` -> run `start_server.sh` (installs
  FastAPI + diffusers on the machine and starts the same `/generate` server) ->
  generate the images -> **destroy the instance**. `destroy_after_use: true`
  means you stop paying the moment rendering ends. A documentary's images
  usually cost **$0.03-$0.20** in total.
* **Kaggle (free 30 GPU-hours per week)** - Kaggle cannot host a live server, so
  the bot works in **batch**: it writes a notebook with your prompts already
  baked into it (`deploy/kaggle/kaggle_batch_template.ipynb`), you run it on
  Kaggle's free GPU (2 clicks), download the results zip, drop it into
  `workspace/kaggle_out/`, and the bot unzips the images and continues. 30 free
  GPU hours per week is the most generous free GPU offer anywhere.

**Gradio (any Gradio app, including Hugging Face Spaces)**

The `gradio_client` library talks to any Gradio endpoint. Open
`https://<the app>/info` to see its real `api_name` and argument order, set
`image.gradio.api_name` / `arg_order`, and `response_image_path` (for example
`data[0].url`) so the bot knows where the picture is hiding in the reply.

**Replicate (paid, zero ops, FLUX quality)**

```
POST https://api.replicate.com/v1/predictions
Headers: Authorization: Bearer <REPLICATE_API_TOKEN>
Body:    {"version": "<flux-schnell>", "input": {"prompt": "...", "width": 1920, ...}}
<- {"id": "...", "status": "starting"}
GET  https://api.replicate.com/v1/predictions/<id>     <- poll until "succeeded"
```
About **$0.003 per image**. A 40-image documentary is roughly $0.12, and you
never see a GPU.

### 3.4 Assembly, motion, subtitles, mix (stages 5-9)

**No API, no internet, no keys, no cost.** These are all local FFmpeg (and
Pillow for text) work: 15 motion presets (`zoom_in`, `pan_left_right`,
`ken_burns_combo`, `orbit`, `pulse`, ...), crossfades, `ebur128` loudness
analysis with a two-pass `loudnorm` to -16 LUFS, `sidechaincompress` ducking at
8:1 (music drops under narration automatically), vignette, colour grade, and
ASS subtitle burn-in.

The alternative engine is `assembly.provider: moviepy` (same output, slower,
easier to modify in Python).

---

## 4. Three ready-made setups

### A. The free setup (start here)

Nothing to sign up for except the LLM, and even that is optional.

```yaml
# config.yaml
llm:    {provider: "deepseek"}     # or openai_compat + Groq (free), or manual
tts:    {provider: "edge"}         # free, no key
image:  {provider: "pollinations"} # free, no key
assembly: {provider: "ffmpeg"}
```
```ini
# .env
DEEPSEEK_API_KEY=sk-...
```
```bat
INSTALL-WINDOWS.bat          :: once
START-WINDOWS.bat            :: every time after that
```
In the web UI: type a topic, set 60 seconds, press **Build**. Or from the
console:

```
python main.py run "black holes" --topic "how black holes bend time" --duration 60
```

### B. The quality setup (a few cents)

```
llm:    deepseek-reasoner          (better research, still ~1 cent)
tts:    elevenlabs or voicestudio  (cloned voice)
image:  replicate (FLUX) or vast   (better pictures, no waiting on a free service)
```

### C. The zero-internet setup

```
llm:    manual                     (you supply the script .txt)
tts:    piper  (offline)  or  --set tts.provider=test  (silent, for testing)
image:  sdwebui on your own GPU, or let it draw placeholder cards
```
Everything else in the pipeline is offline anyway. This is also how you verify
the whole machine works without touching a single API - the diagnostic command
`python main.py test --force --set tts.provider=test` renders a real 8-second
video end to end with no network at all.

---

## 5. Time and money per video

| Video | Images (free service) | Images (own/rented GPU) | Encode on a normal PC | Total, realistic |
|---|---|---|---|---|
| 8 s self-test | - | - | ~5 s | ~10 s |
| 1 min | 1-3 min | 20-40 s | ~30-60 s | 2-5 min |
| 10 min | 8-20 min | 3-6 min | ~4-8 min | 15-30 min |
| 30 min | 25-60 min | 10-20 min | ~15-25 min | 40-90 min |

The image stage dominates. The free service takes 5-20 s per picture and the
bot is deliberately polite to it; a rented GPU does the same work in 1-4 s per
picture. Rendering is done by FFmpeg on your CPU and is roughly real-time for
1080p at `preset: medium` (use `ultrafast` while testing).

Money per 10-minute video on each route is in the table in section 0 and the
per-service costs are in section 3. The short version: **the free path is
genuinely free**, and the expensive path is still cents.

---

## 6. Where keys go, and how to keep them safe

Everything secret goes in **one file**: `.env` in the project folder (copy
`.env.example`). It is git-ignored, it is never printed back to the browser by
the web UI (the UI shows only "set / not set" and a masked preview), and it is
never uploaded to your GPU machine except where a provider needs it.

```ini
DEEPSEEK_API_KEY=            # script + YouTube text
OPENAI_API_KEY=              # openai_compat LLM, or OpenAI TTS
OPENAI_BASE_URL=             # https://api.groq.com/openai/v1 etc.
OLLAMA_BASE_URL=http://localhost:11434
ELEVENLABS_API_KEY=          # paid voice
ELEVENLABS_VOICE_ID=
VOICESTUDIO_URL=http://localhost:3900
VOICESTUDIO_VOICE=default
VAST_API_KEY=                # renting a GPU
REPLICATE_API_TOKEN=         # paid images
SDWEBUI_URL=http://127.0.0.1:7860
IMAGE_ENDPOINT_URL=          # your Colab / Kaggle / Gradio tunnel link
```

`config.yaml` holds the non-secret settings and never needs a key in it. The
rule of thumb: **anything that ends in `KEY` or `TOKEN` lives in `.env`;
everything else lives in `config.yaml`.**

---

## 7. If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `DEEPSEEK_API_KEY is empty in .env` | key not pasted | paste it, or use `--script` with your own file, or `llm.provider: manual` |
| `Edge-TTS unavailable ... Cannot connect` | no internet / proxy / firewall | it is a network problem, not a bug. Use `piper`, `espeak`, or `--set tts.provider=test` |
| `Pollinations unreachable` | free service hiccup or offline | the bot draws placeholder cards and still finishes; re-run `python main.py images myvideo --force` later |
| FFmpeg "killed", exit code -9 | out of RAM during encode | lower `system.encode_threads`, set `motion.supersample: 2`, use `preset: ultrafast` |
| Voice sounds too fast | your timestamps are shorter than the words | the bot warns "too fast to be honest"; lengthen the scene or let it pad |
| Captions are off | you used a TTS that gives no word timings | set `subtitles.source: scene_split`, or use Edge/VoiceStudio/ElevenLabs |
| Nothing happens when you click in the web UI | stale JavaScript cache | hard-refresh (Ctrl+F5) |
| "project already done, nothing to do" | the cache working as designed | add `--force`, or re-run only one stage |
| A run stopped halfway | any error above | just run it again - finished stages are skipped, it resumes |

Every run writes `logs/run.log` next to the project. If you ever need to report
a problem, that file plus the output of `python main.py doctor` explains almost
everything.

---

## 8. Cheat sheet

```
python main.py doctor                     is everything ready?
python main.py test --force               render a tiny video to prove the whole chain works
python main.py web                        the point-and-click interface (default http://127.0.0.1:8765)
python main.py providers                  every provider, with cost and setup time, active one starred

python main.py run "my video" --topic "why the ocean is deep" --duration 60
python main.py run "my video" --script my_script.txt
python main.py images "my video" --force          redo one stage
python main.py motion "my video" --only s03,s04   redo two scenes only
python main.py inspect "my video"                 full state of the project
python main.py providers --set image.provider=vast   swap a provider for one run
```

`--set key=value` is a **global** flag and comes **before** the subcommand.

**Web UI, in one line per tab**: *Build* (topic or script file, length, style,
press Build), *Logs* (live streaming output of every stage), *Config* (edit
`config.yaml` with your comments preserved), *Secrets* (edit `.env` - values are
never echoed back), *Assets* (upload background music and a watermark),
*Projects* (open, inspect, re-run stages, download the MP4/thumbnail/subtitles),
*Doctor* (the same checks, with buttons), *Providers* (swap with a dropdown).

---

**The one-sentence version:** the bot is a 10-stage local pipeline with three
swappable internet steps - one model writes the words, one voice reads them,
one image service draws the pictures - and every one of those three has a free
option that needs nothing but an internet connection.
