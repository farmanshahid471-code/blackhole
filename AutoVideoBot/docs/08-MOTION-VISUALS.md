# Motion & visuals - the $0 animation department

## The one idea

A still image becomes film when a virtual camera moves over it. This bot
implements that by cropping a **moving window** out of a super-sampled copy
of the image:

```
 original 1920x1080
    -> scale to cover the frame aspect
    -> scale x{supersample}        e.g. 3840x2160 (2x) or 5760x3240 (3x)
    -> crop a 1920x1080 window whose position and size are functions of t
    -> scale back to 1920x1080
```

Because the window moves inside a bigger picture, it can move in fractions
of an output pixel. That is the whole secret of smooth Ken Burns; skip the
super-sampling and you get the famous jitter.

`motion.supersample: auto` measures your free RAM and picks the biggest
factor that fits (2 on small machines, 3 on 16 GB, up to 6 on workstations).
Memory grows with the **square** of this number - if ffmpeg ever gets
"killed", lower it.

## The 13 presets

| Preset | Feel | Use it for |
|---|---|---|
| `zoom_in` | slow push in | the default workhorse; intimacy, reveals |
| `zoom_in_slow` | half-strength push | dense images, talking-points scenes |
| `zoom_in_top` | push aimed above centre | skies, faces high in frame |
| `zoom_out` | slow pull back | endings, scale, "and it goes on" |
| `zoom_out_bottom` | pull back aimed low | ground-level subjects |
| `pan_left_right` | travel rightwards | landscapes, journeys, timelines |
| `pan_right_left` | travel leftwards | contrast against the previous scene |
| `pan_up_down` | tilt down | tall subjects, falling things |
| `pan_down_up` | tilt up | monuments, reveals of something big |
| `diagonal_tl_br` | push + drift corner-to-corner | energy, action beats |
| `diagonal_br_tl` | pull + drift the other diagonal | release after tension |
| `ken_burns_combo` | push in + slight right drift | the classic documentary move |
| `orbit` | gentle circular drift | space, dreams, weightlessness |
| `pulse` | in-then-out zoom | alarms, heartbeats, countdowns |
| `static` | no movement | only when the frame is already busy |

`motion.preset: auto` walks `motion.auto_order` and never repeats the same
move twice in a row. Override per scene with `@motion:` in your script.

## Tuning knobs

* `zoom_amount: 1.12` - how far a zoom travels (1.0 = none). 1.08 subtle,
  1.18 assertive, above 1.25 starts to feel like a screensaver.
* `pan_amount: 0.10` - fraction of the image width a pan crosses.
* `focus` - where zooms aim: `center`, `top`, `bottom`, `left`, `right`,
  `rule_of_thirds`.
* `shake: 0.02` - handheld micro-jitter. 0 = locked-off tripod. Tiny values
  add life; above ~0.05 looks broken.
* `scene_fade_seconds: 0.3` - fade each clip from/to black (usually leave 0;
  transitions do the joining).

## The look (colour)

`motion.color_grade`:

| Name | What it does |
|---|---|
| `cinematic` | slight desaturation, deeper blacks, cool shadows (default) |
| `warm` | golden, inviting |
| `cool` | clinical, techy |
| `noir` | monochrome, hard contrast |
| `vivid` | saturated punch (kids' content, nature) |
| `teal_orange` | the Hollywood split-tone |
| `film` | faded vintage curve |
| `none` | raw |

Plus `add_vignette: true` + `vignette_strength: 0.35` (darkened corners focus
the eye - documentary standard) and `add_film_grain` for texture.

**Consistency rule:** one grade per video. Changing grade mid-video reads as
a mistake unless the story changes worlds.

## Composition rules the prompts should follow

The LLM prompt template already enforces these; keep them when you hand-write
`@prompt:` lines:

1. Subject away from the top/bottom 15% (captions and title-safe live there).
2. One clear subject per frame; the camera move needs something to aim at.
3. Vary shot type between consecutive scenes (wide -> close -> aerial ...) so
   cuts feel like editing, not a slideshow.
4. Name the light: direction, colour, quality. "volumetric god rays at dawn"
   beats "beautiful lighting".
5. Never ask for text in images. Captions are burned in by the bot; AI-drawn
   letters are always wrong.

## Vertical video (9x16)

`video.aspect: 9x16` rewrites the whole geometry: frames 1080x1920, image
prompts composed portrait, captions enlarged automatically
(`subtitles.style.font_size` scales x1.35), thumbnail text re-laid. Generate
portrait images (set `image.width: 1080`, `image.height: 1920`) or accept a
centre crop of landscape art.

## Rendering cost

1080p30, `preset: medium`, supersample 3: roughly 1.5-3 s of CPU time per
second of video per scene on a modern 6-core PC. `preset: veryfast` halves
it; `ultrafast` quarters it and doubles file size. Use fast presets while
iterating on prompts, `medium` for the upload.
