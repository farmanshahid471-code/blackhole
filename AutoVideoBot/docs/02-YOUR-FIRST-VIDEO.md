# Your first video, line by line

We will make the black-holes example and read every line of output together,
because the log is the bot explaining its decisions.

```bash
python main.py run black-holes --script examples/black_holes_script.txt
```

## STAGE 1 - SCRIPT

```
✔ parsed 4 scene(s) from black_holes_script.txt -> total 47.0s
· voice override from script header: en-US-ChristopherNeural
·   s01     0.0s ->   11.0s (11.0s,  17 words)  [zoom_in]
```
The parser found 4 scenes, kept your timestamps exactly, and assigned each
scene a camera move (yours if you wrote `@motion:`, a cycled default
otherwise). If a scene were impossible - zero length, overlapping, 300 words
in 6 seconds - you would see a `!` line with the number that is wrong.

## STAGE 2 - VOICEOVER

```
✔ Edge-TTS OK (en-US-ChristopherNeural) - 322 voices available
✔   [1/4] s01 06s of speech (400.6 KB)
```
One wav per scene. The word timings are saved silently to
`audio/words/s01.json` - they become your captions later.

## STAGE 3 - TIMING ANALYSIS

```
·   s01: speech 8.54s -> window 11.00s (slower x0.850)
·   s03: speech 12.46s -> window 12.00s (faster x1.051)
✔ narration track: 47s (2.2 MB)
```
The interesting one. Scene 1's voice naturally took 8.54s but your timestamp
window is 11.00s, so the voice was slowed to 85% - still inside the
`max_slowdown: 0.85` guard - and the rest padded with silence. Scene 3 was
slightly sped up. `x0.850` is recorded in `script.json` so subtitles can
divide word times by it later. If a tempo ever prints above ~1.3 or below
~0.85 you wrote more words than the window can hold: the bot warns and the
fix is editing the script, not the config.

## STAGE 4 - IMAGE GENERATION

```
✔   [1/4] s01
! pollinations attempt 1/5: server error 500
✔   [2/4] s02
```
Free services hiccup; the retry ladder (same params -> no upscale -> smaller
-> other model) absorbs it. A final failure produces a placeholder card and a
warning, never a dead video.

## STAGE 5 - MOTION

```
✔   [1/4] s02.mp4  (12s)
```
Each line is one rendered clip of exactly the scene length (plus the
transition tail, invisible and silent). Rendering is the slow stage: on a
normal PC roughly 1-3 seconds of wall clock per second of video.

## STAGE 6 - JOINING CLIPS

```
· joining 4 clips with crossfade transitions (0.45s) ...
✔ silent video: 47s
```
47.0 = your script total. If this number ever disagrees with the script by
more than half a second the bot warns - that would mean a clip failed.

## STAGE 7 - SUBTITLES

```
✔ 39 caption cues (112 words) -> workspace/projects/black-holes/subs/captions.srt
·   first: "Somewhere in this galaxy" @ 0.12s
```
Cues come from real word timings. Open the .srt in any text editor to read
exactly what will appear and when.

## STAGE 8 - AUDIO MIX

```
· music: test-ambient-dark.mp3  (random mode, 1 track(s) available)
· music is 40s, video is 47s -> looping 2x
· normalising narration loudness (two-pass) ...
✔ final audio: 47s
```
Voice to -16 LUFS, music ducked under it, limiter on top.

## STAGE 9 - FINAL ASSEMBLY

```
✔ FINAL VIDEO: workspace/projects/black-holes/output/final.mp4
✔   47s  |  12.0 MB
```

## STAGE 10 - EXTRAS

```
✔ thumbnail: .../output/thumbnail.jpg
```

## Now the useful habits

```bash
python main.py inspect black-holes     # table of everything per scene
python main.py run black-holes --script examples/black_holes_script.txt
                                       # run again = instant, all cached
```

Change one `@prompt:` line in the script and re-run: stages 1-3 and 5-9 reuse
their cache, stage 4 regenerates only that scene. That is the designed
feedback loop: **edit one thing, re-run, watch.**

## Deliverables per project

| File | Use it for |
|---|---|
| `output/final.mp4` | upload |
| `output/thumbnail.jpg` | YouTube thumbnail base |
| `output/youtube_metadata.json` | title/description/tags/chapters |
| `subs/captions.srt` | YouTube captions track (also burned in already) |
| `script.json` | your editable source of truth for re-renders |
