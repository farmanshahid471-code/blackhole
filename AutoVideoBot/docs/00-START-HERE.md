# AutoVideoBot - The Complete A-to-Z Guide

Written for someone who has never built anything like this before.
Every concept is explained before it is used. Read it top to bottom once,
then use the other docs as references.

---

## PART 1 - WHAT YOU ARE ACTUALLY BUILDING

### 1.1 The problem in one paragraph

A "faceless" documentary video (the kind with a voice, still images that
slowly move, captions and music) is made of maybe 200 tiny decisions:
*what does scene 7 say, what picture shows it, how long is the picture on
screen, how does it move, when does the music duck under the voice...*
A human editor makes those decisions in a video editor over many hours.
This bot makes them from **rules and configuration**, in minutes, and it can
redo any single decision without redoing the rest.

### 1.2 The five raw materials of every video

1. **A script** - sentences, grouped into scenes, optionally with timestamps.
2. **A voice** - each sentence turned into sound by a TTS engine.
3. **Pictures** - one per scene, generated from a text prompt.
4. **Motion** - the picture slowly zooms/pans so it feels filmed, not slid.
5. **A mix** - voice + music + captions, glued to the moving pictures.

Everything in this repository exists to produce those five things and join
them. Nothing else. When you feel lost, come back to this list.

### 1.3 The architecture in one picture

```
                         YOU
                          │   script.txt  (or a topic like "black holes")
                          ▼
        ┌───────────────────────────────────────────────┐
        │            main.py  (the command line)        │
        └───────────────────┬───────────────────────────┘
                            ▼
        ┌───────────────────────────────────────────────┐
        │   bot/pipeline.py  (the ORCHESTRATOR)         │
        │   runs the 10 stages in order, skips finished │
        │   work using manifest.json                    │
        └───┬──────┬────────────┬────────────┬────────┘
            │      │      │      │      │      │
      ┌─────▼─┐ ┌──▼───┐ ┌▼────┐ ┌▼─────┐ ┌───▼──┐ ┌───▼────┐
      │  LLM  │ │ TTS  │ │IMAGE│ │MOTION│ │ MIX  │ │ASSEMBLY│   <- PROVIDERS
      │deepseek│ │edge/ │ │vast/│ │ffmpeg│ │ffmpeg│ │ ffmpeg │      (swappable)
      │ollama │ │voice-│ │colab│ │moviepy│ │     │ │ moviepy│
      │manual │ │studio│ │...  │ │      │ │     │ │        │
      └───────┘ └──────┘ └─────┘ └──────┘ └──────┘ └────────┘
            │      │      │      │      │      │
            ▼      ▼      ▼      ▼      ▼      ▼
        workspace/projects/<your-video>/
            script.json  audio/  images/  clips/  subs/  output/final.mp4
```

**Providers** are the replaceable tools. The pipeline never says "call
DeepSeek"; it says "call whatever `config.yaml` names as the LLM". That
single indirection is what lets you swap Vast.ai for Colab or Edge-TTS for
VoiceStudio without touching code.

### 1.4 The folder you are standing in

```
AutoVideoBot/
├── main.py                  THE door. Every command starts here.
├── config.yaml              THE control panel. All behaviour lives here.
├── .env.example             copy to .env and put your secret keys there
├── requirements.txt         python packages
├── bot/                     the engine (python package)
│   ├── pipeline.py          the 10 stages, in order
│   ├── script.py            parses YOUR script / normalises LLM output
│   ├── subtitles.py         caption timing
│   ├── audio.py             music choice + prep
│   ├── filters.py           the ffmpeg filter maths (Ken Burns, mixing)
│   ├── imaging.py           drawing text with Pillow (thumbnails, cards)
│   ├── state.py             script.json + manifest.json (the resume brain)
│   ├── config.py            reads config.yaml + .env + --set overrides
│   ├── paths.py             knows where every file lives
│   ├── registry.py          the provider switchboard
│   └── providers/           one file per tool (this is what you swap)
├── prompts/                 the words the bot says to the LLM (editable .txt)
├── scripts/                 setup.sh / setup.bat
├── examples/                a ready-to-run timestamped script
├── deploy/
│   ├── vast/server/         the image server uploaded to rented GPUs
│   ├── colab/               free-GPU notebook
│   └── kaggle/              free-GPU batch notebook
├── assets/
│   ├── background_music/    drop your licensed .mp3 files here
│   └── fonts/               optional custom fonts
└── workspace/projects/      one folder per video you make
```

### 1.5 The three files that matter per project

Inside `workspace/projects/<name>/`:

| File | Role |
|---|---|
| `script.json` | **the single source of truth**: every scene, its words, its prompt, its exact start/end, the tempo applied to its voice, the motion used. |
| `manifest.json` | **the memory**: "scene 12 image, provider=vast, these exact inputs = DONE". Re-running skips anything already in here. |
| `project.json` | a snapshot of the config used, so a video can be reproduced later. |

If you ever wonder "why did it do that?", open `script.json`. If you ever
want to force work to happen again, delete `manifest.json` or pass `--force`.

---

## PART 2 - THE 10 STAGES, ONE BY ONE

### STAGE 1 - SCRIPT  (`bot/script.py`)

**Input (mode A):** your text file. The parser understands four timestamp
styles (`[00:00 - 00:11]`, `00:00 text`, `00:00 -> 00:11 | text`, plain
JSON) plus header lines (`#title:`, `#voice:`...) and per-scene directives
(`@prompt:`, `@motion:`, `@pause:`, `@voice:`, `@skip:`...). Full reference:
`docs/03-SCRIPT-FORMAT.md`.

**Input (mode B):** a topic + duration. The bot asks the LLM for strict JSON
containing narration, an image prompt, a chapter title and a camera move per
scene. The instructions the LLM receives live in `prompts/script_system.txt`
and `prompts/script_user.txt` - ordinary text files you can rewrite to change
the bot's writing personality without touching code.

**Output:** `script.json`. Every scene has `target_start` / `target_end`
(either yours, or computed), `narration`, `image_prompt`, `motion`.

**What can go wrong and what the bot does about it:** overlapping timestamps
are repaired with a warning; a scene longer than `timing.max_duration` is
flagged; narration that is too dense to speak in its window is flagged with
the words-per-minute number so you can see exactly how bad it is.

### STAGE 2 - VOICE  (a TTS provider)

Each scene's narration is spoken and saved as
`audio/s01.wav`, `audio/s02.wav`, ...

Two extras happen here that matter later:

* **Word timings.** Edge-TTS reports the exact millisecond each word starts
  and ends. They are saved to `audio/words/s01.json`. Stage 7 turns them into
  captions that appear exactly when the word is spoken.
* **Voice overrides.** A scene can use a different narrator with `@voice:`.

Cached per scene: change one sentence and only that sentence is re-spoken.

### STAGE 3 - TIMING  (`bot/pipeline.py:stage_timing`)

The most subtle stage, and the reason your timestamps actually hold.

The problem: you said scene 3 lasts 12.0 seconds. The voice engine read it in
13.4 seconds. Left alone, every later scene slides later and your timestamps
become lies.

The solution, in order:

1. measure the natural speech length (`ffprobe`);
2. compute `tempo = natural / target` (1.12 means "speak 12% faster");
3. clamp it to `timing.max_speedup` / `max_slowdown` so a human voice stays
   human (defaults 1.35x / 0.85x);
4. apply it with ffmpeg's `atempo` filter (the bot chains it automatically
   past the 2x limit of a single filter);
5. whatever time is still missing becomes silence at the end of the scene;
   whatever is still extra is trimmed.

Each scene also gets `head_silence_ms` before its speech and, when
transitions are on, an invisible **extension tail** (see stage 6) so that
crossfades never eat your narration.

Outputs: `audio/sNN_fit.wav` (the stretched speech), `audio/sNN_full.wav`
(head silence + speech + tail = exactly the scene length), and the joined
`voice_full.wav` - one continuous narration track whose length equals your
script's total, to the millisecond.

### STAGE 4 - IMAGES  (an image provider)

Every `image_prompt` becomes a picture in `images/`. The provider decides
how:

* `pollinations` - free web service, zero setup, a 5-request retry ladder
  because free services hiccup;
* `sdwebui` - any Stable Diffusion WebUI (your PC, Colab, Vast, RunPod...);
* `vast` - rents a GPU, uploads `deploy/vast/server/`, boots it, tunnels in,
  generates, **destroys the machine**;
* `colab` / `gradio` - posts prompts to a link you paste from a notebook;
* `kaggle` - writes a notebook with your prompts baked in, you run it, the
  bot imports the zip;
* `replicate` - paid per image, zero management.

A shared `style_suffix` from config is appended to every prompt so the whole
video looks like one piece of work. Failed images never kill the project:
the bot draws a dark placeholder card and warns you, so you can re-run just
that scene later (`--only s07 --force`).

### STAGE 5 - MOTION  (`bot/filters.py`, `assembly_ffmpeg.py`)

The free animation. Each still becomes a clip of exactly the scene length.
How: the image is scaled to *cover* the frame, then **super-sampled** (blown
up by `motion.supersample`, chosen automatically from your RAM), then a crop
window the size of your video **moves and resizes over time** inside that
giant image, then is scaled back down. Because the window moves in a 2-6x
larger space, it can move in fractions of a pixel - which is what makes the
difference between "smooth camera" and "jittery slideshow".

13 named moves ship with the bot (`zoom_in`, `pan_left_right`,
`ken_burns_combo`, `orbit`, `pulse`, ...). `motion.preset: auto` cycles them
so two scenes in a row never move the same way. Then a colour grade
(`cinematic` by default), a vignette, and optional grain. Full explanation
and a preview of every preset: `docs/08-MOTION-VISUALS.md`.

### STAGE 6 - TRANSITIONS  (`concatenate`)

Joins the clips. With `crossfade`, clip B's first 0.45s is blended over clip
A's last 0.45s - that is why stage 3 grew every non-final clip by exactly
0.45s of *silent* tail: the blend happens over silence, never over speech.
The bot measures every clip's real duration and computes each xfade offset
from it, so the total length still equals your script total.

### STAGE 7 - SUBTITLES  (`bot/subtitles.py`)

Builds caption cues from the word timings of stage 2, grouped 3-5 words per
cue, and **always breaking at sentence ends** (captions that run "slower than
yours Not" across a full stop look broken, so the code walks your original
text to find the punctuation the TTS engine stripped away).

Two outputs: `subs/captions.srt` (upload to YouTube as a caption track) and
`subs/captions.ass` (carries your exact font size and colours; this is the
file that gets burned into the picture). If a provider gives no word
timings, the stage falls back to even splitting inside each scene.

### STAGE 8 - MIX  (`audio.py` + `build_mix`)

Narration + background music into one mastered track:

1. **Two-pass loudness normalisation** of the voice to -16 LUFS (the YouTube
   standard). Pass 1 only measures; pass 2 applies one fixed gain. A single
   dynamic pass would pump the volume *and* trim the tail of your audio -
   this bot was built after watching exactly that bug eat 0.5s off a video.
2. Music picked from `assets/background_music/` (random / first / by mood /
   exact filename), looped if shorter than the video, faded in and out.
3. **Ducking**: a sidechain compressor listens to the voice and squeezes the
   music down whenever someone speaks, releasing in the gaps. That is what a
   human editor does with volume automation; here it is one filter.
4. A limiter and a master fade so nothing ever clips.

### STAGE 9 - ASSEMBLY  (`mux`)

Picture + mastered audio + burned captions (+ optional watermark, + optional
intro/outro videos) into `output/final.mp4`. H.264 + AAC, `+faststart` so it
streams while uploading. If any encode is ever killed for using too much
RAM, the bot detects the kill, tells you, and retries automatically with
memory-cheap settings instead of dying silently.

### STAGE 10 - EXTRAS

`output/thumbnail.jpg` (a real frame, optionally with big title text drawn
by Pillow - not ffmpeg's drawtext, which many builds lack) and
`output/youtube_metadata.json`: title, alt titles, description with chapters,
tags, hashtags, thumbnail idea, category, pinned-comment question - written
by the LLM if you have one configured, otherwise assembled locally.

---

## PART 3 - THE IDEAS THAT MAKE IT SURVIVABLE

### 3.1 Resumability (the manifest)

Every artefact is recorded as `kind:scene:hash-of-everything-that-produced-it`.
Same inputs -> same hash -> skipped. Consequences you will love:

* crash at scene 40 of 50 -> re-run -> 39 scenes skipped;
* change only the music -> only stages 8-9 re-run;
* edit one sentence -> only that voice, its timing, its clip re-render.

Force a redo: `--force` (everything) or delete the manifest, or
`--only s03,s04` (some scenes).

### 3.2 Provider indirection (the registry)

`bot/registry.py` holds a dictionary: `{"image": {"vast": VastProvider, ...}}`.
Each provider file announces itself with one decorator:

```python
@register("image", "pollinations")
class PollinationsProvider(ImageProvider): ...
```

Adding a new tool = new file + one decorator + one import. The pipeline is
never edited. See `docs/12-EXTENDING.md`.

### 3.3 Configuration layering

```
config.yaml   (your defaults)
   + project.json        (per-video snapshot)
   + --set key=value     (per-run override, beats everything)
```

Anything secret is referenced by NAME (`api_key_env: DEEPSEEK_API_KEY`) and
read from `.env`, so keys never sit in a file you might commit.

### 3.4 Failing loudly, and usefully

Every error path in this bot is written to be read by a beginner:
* missing ffmpeg -> the exact Windows/macOS/Linux install commands;
* missing API key -> where to click and what line to paste;
* ffmpeg killed with no message -> "the OS killed it for RAM, here are the
  four settings to lower, and I am retrying cheaply right now";
* Pollinations 500 -> a 5-step retry ladder before it ever bothers you.

Run `python main.py doctor` whenever anything feels off. It checks python,
ffmpeg build (including whether it has the filters we need), packages, keys,
folders, disk space, and health-checks every configured provider.

---

## PART 4 - YOUR FIRST THREE RUNS, ANNOTATED

### Run 1: prove the toolchain (2 minutes, $0)

```bash
python main.py test
```
Renders an 8-second two-scene video with whatever free providers are
configured. If this finishes, your machine can make videos. Watch every log
line once; each stage prints what it decided and why.

### Run 2: your script (the mode you asked for)

```bash
python main.py run black-holes --script examples/black_holes_script.txt
```
Then open `workspace/projects/black-holes/output/final.mp4`, and afterwards:

```bash
python main.py inspect black-holes
```
That prints the stage checklist, a per-scene table (start, end, words,
motion, which files exist) and file sizes. This is your debugging cockpit.

### Run 3: topic mode (AI writes)

```bash
python main.py run oceans --topic "why the ocean is deep" --duration 90
```
Watch stage 1 print the scene plan *before* anything expensive happens. If
you hate the plan, edit `script.json` by hand (it is plain JSON) and re-run:
stage 1 sees the file exists and keeps your edits.

---

## PART 5 - THE DAILY WORKFLOW ONCE IT IS YOURS

1. Write/collect a script (`my_video.txt`) with timestamps.
2. `python main.py run NAME --script my_video.txt`
3. Watch it. Usually two kinds of tweaks:
   * *a scene's picture is wrong* -> edit its `@prompt:` line, then
     `python main.py images NAME --only s04 --force && python main.py run NAME --script my_video.txt`
   * *pacing feels off* -> edit `@pause:` or the timestamps, re-run; stages
     3-9 rebuild, voices and images are reused.
4. `python main.py inspect NAME` -> grab `output/final.mp4`,
   `output/thumbnail.jpg`, `output/youtube_metadata.json`, `subs/captions.srt`.
5. `python main.py clean NAME` to reclaim disk (keeps the finished video).

That loop - script, run, tweak one thing, re-run - is the whole product.
Everything else in these docs is making that loop faster, cheaper, or
better-looking.

---

## PART 6 - WHERE TO GO NEXT

* Want it to look expensive? `docs/08-MOTION-VISUALS.md` (grades, presets,
  vertical video) and `docs/10-SUBTITLES.md` (Shorts-style captions).
* Want it to cost nothing on GPUs? `docs/07-COLAB-KAGGLE.md`.
* Want it unattended and cents-per-video? `docs/06-VAST-AI-GPU.md`.
* Want your own cloned voice? `docs/05-PROVIDERS.md` -> VoiceStudio.
* Want it to be YOUR bot? `docs/12-EXTENDING.md`.
* Want the whole picture in one page - what runs where, what you must sign up
  for, every API call and every price? `docs/15-APIS-AND-REQUIREMENTS.md`.
