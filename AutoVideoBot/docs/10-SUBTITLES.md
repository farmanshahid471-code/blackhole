# Subtitles / captions

Two products come out of stage 7:

1. `subs/captions.srt` - a portable caption track (upload to YouTube, or feed
   any editor).
2. `subs/captions.ass` - the same cues with your exact styling and the video's
   real resolution baked in. **This is the file burned into the picture**,
   because burning an .srt makes ffmpeg guess a 384 px canvas and blow the
   text up absurdly.

## How timing is derived

* **word_boundaries (default)** - Edge-TTS reports the millisecond each word
  starts/ends. The bot groups 3-5 words per cue (`subtitles.words_per_line`),
  never crossing a sentence end, and divides times by the scene's tempo
  factor so captions stay glued to stretched speech.
* **scene_split** - fallback when a provider gives no word timings: each
  scene's words are spread evenly across its duration. Usable, less exact.
* **none** - disable captions entirely (`subtitles.enabled: false`).

## Why captions sometimes read "wrong" and how it is prevented

TTS engines strip punctuation from word events, so without help the grouper
would produce `slower than yours Not`. The builder walks your ORIGINAL
narration text to recover where the full stops were and hard-breaks there.
If you ever see a broken caption, check that the narration in `script.json`
still contains its punctuation.

## Styling (documentary look)

`subtitles.style` in config.yaml:

```yaml
font: "DejaVu Sans"        # any font installed on the machine
font_size: 52              # at 1080p; auto x1.35 for vertical
bold: true
primary_colour: "&H00FFFFFF"    # ASS colours are &HAABBGGRR (alpha first!)
outline_colour: "&H00000000"
back_colour: "&H80000000"       # semi-transparent box behind text
outline: 3
shadow: 1
margin_v: 90                    # distance from bottom edge
alignment: 2                    # 2 bottom-centre, 8 top-centre
```

Colour gotcha: ASS hex is **alpha, blue, green, red** - reverse of web CSS.
`&H00FFFFFF` = opaque white.

## Shorts / Reels style

Bigger, chunkier, centred lower third:

```yaml
video.aspect: 9x16
subtitles:
  words_per_line: 3
  style: { font_size: 78, margin_v: 220, outline: 4 }
```

For true one-word-at-a-time karaoke you want `subtitles.shorts_style.enabled`
plus the ASS path; the generated `captions.ass` already carries a highlight
colour slot for the active word.

## Burned in vs side-car

* `burn_in: true` (default) - captions are pixels in the mp4. Always visible,
  works everywhere, cannot be turned off by the platform.
* `burn_in: false` - clean picture + `captions.srt` for YouTube's own caption
  track (better for accessibility and SEO, and viewers can toggle it).

Many channels do both: burn a stylised version AND upload the .srt.

## Checking your captions without watching the video

```bash
cat workspace/projects/NAME/subs/captions.srt     # read every cue and time
python main.py inspect NAME                       # confirms the stage ran
```
And to see one frame with captions:
```bash
ffmpeg -ss 6.2 -i output/final.mp4 -frames:v 1 check.png
```
