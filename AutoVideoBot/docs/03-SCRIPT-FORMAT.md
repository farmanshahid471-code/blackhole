# The script format, completely

Your script is a plain `.txt` file. Everything below is optional except the
narration lines. A runnable example lives in
`examples/black_holes_script.txt`.

---

## Header lines (top of file, affect the whole video)

```
#title: The Gravity Trap
#description: Why nothing escapes a black hole.
#tags: space, black holes, physics
#style: dark cinematic space photography, volumetric light
#voice: en-US-ChristopherNeural
#music: test-ambient-dark.mp3
#aspect: 16x9
#language: English
```

| Line | Effect |
|---|---|
| `#title:` | video title (metadata + optional thumbnail text) |
| `#description:` | starting description |
| `#tags:` | comma separated tags |
| `#style:` | appended to EVERY image prompt (your visual signature) |
| `#voice:` | overrides `tts.*.voice` for this video |
| `#music:` | forces that file from `assets/background_music/` |
| `#aspect:` | `16x9` / `9x16` / `1x1` / `4x5` / `21x9` for this video |
| `#language:` | passed to the LLM in topic mode |

Headers **beat config.yaml** for that project.

---

## Four timestamp styles (mix at your own risk - pick one)

```
STYLE 1   [00:00 - 00:11]
          Narration text on the following lines.

STYLE 2   00:11  Narration starts right after the timestamp.

STYLE 3   00:23 -> 00:35 | Narration after a pipe.

STYLE 4   (none) The bot measures each spoken scene and builds the timeline.
```

Rules the parser applies automatically:

* `start` given but no `end` -> `end` = next scene's start.
* only `end` given -> `start` = previous scene's end.
* neither -> previous end, plus `timing.default_scene_seconds`.
* overlaps between scenes -> repaired and warned about.
* a scene whose end <= start -> given the default length and warned.
* `[01:30]`, `1:30`, `90`, `90s`, `1m30s`, `00:01:30.500` are all understood.

Multi-line narration is fine: consecutive lines join into one scene until the
next timestamp or directive appears. Blank lines do NOT end a scene.

---

## Per-scene directives

```
@prompt:   the image to generate (Stable Diffusion style description)
@image:    alias of @prompt
@motion:   zoom_in | zoom_out | zoom_in_slow | zoom_in_top | zoom_out_bottom |
           pan_left_right | pan_right_left | pan_up_down | pan_down_up |
           diagonal_tl_br | diagonal_br_tl | ken_burns_combo | orbit |
           pulse | static
@title:    chapter name (YouTube chapters + `inspect` table)
@pause:    1.5          extra silence appended after this scene (seconds)
@voice:    en-GB-RyanNeural     different narrator for this scene only
@speed:    +8%          speak this scene 8% faster (TTS rate)
@music:    tense.mp3    switch background music from this scene onwards
@skip:     true         leave this scene out of the video entirely
@subtitle: custom text  replace the auto captions for this scene
```

---

## Comments

Lines starting with `#` (that are not header lines), `//`, or `<!--` are
ignored. Use them to leave notes for yourself.

---

## Topic mode instead of a script

```bash
python main.py run oceans --topic "why the ocean is deep" --duration 90
python main.py run oceans --topic "..." --duration 90 \
       --style "underwater photography, bioluminescence" \
       --instructions "end with a question, mention the Mariana Trench"
```

The LLM returns JSON with narration + image prompt + chapter + motion per
scene; the bot normalises whatever damage the model did (wrong key names,
nested lists, timestamps as strings) and validates pacing
(words-per-minute per scene, min/max durations). The written instructions
live in `prompts/script_system.txt` / `prompts/script_user.txt`.

After a topic run, `script.json` is yours: edit any field (a prompt, a
narration line, a duration) and re-run. Stage 1 keeps an existing
`script.json` unless you pass a new `--script`/`--topic` or `--force`.

---

## Sanity checks the bot runs on every script

* scene shorter than `timing.min_duration` -> warning
* scene longer than `timing.max_duration` -> warning (split it)
* pacing above ~210 words/minute -> warning (unintelligible)
* pacing below ~60 words/minute with >4 words -> warning (voice will stretch)
* missing image prompt -> a fallback prompt is generated from the narration
  and a warning lists which scenes needed it

Fixing warnings is the difference between "a bot video" and "a video".
