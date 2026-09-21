# Audio: voices, mixing, music, loudness

## The chain, in order

```
per-scene wav  ->  tempo fit to timestamps  ->  head/tail silence
              ->  joined narration track (voice_full.wav)
              ->  two-pass loudness normalise (-16 LUFS)
              ->  broadcast EQ + compressor (optional)
              ->  sidechain ducking under music
              ->  limiter + master fade
              ->  mix.wav  ->  muxed into final.mp4
```

## Choosing a voice

```bash
python main.py voices                    # everything the provider offers
python main.py voices --filter en-GB     # only British
```
Set it globally (`tts.edge.voice`), per video (`#voice:` header), or per
scene (`@voice:`). Documentary-safe Edge voices:

| Voice | Character |
|---|---|
| en-US-GuyNeural | deep male, the default "narrator" |
| en-US-ChristopherNeural | warm male, slightly conversational |
| en-US-EricNeural | mature male, authoritative |
| en-US-AriaNeural | clear female |
| en-US-JennyNeural | friendly female |
| en-GB-RyanNeural | British male |
| en-GB-SoniaNeural | British female |
| en-IN-PrabhatNeural | Indian male |

Pace with `tts.rate` (`+0%` normal, `+8%` brisker, `-5%` more solemn) or per
scene with `@speed:`.

## Why the tempo fit exists (and its limits)

Your timestamps are a promise to the viewer ("scene 3 starts at 0:23").
Speech is physical and rarely matches. The bot bridges the gap with
`atempo`, clamped by `timing.max_speedup` (1.35) and `max_slowdown` (0.85)
because beyond that a voice stops sounding human. If a scene needs more than
the clamp allows, the remainder becomes silence (or a trim - see
`timing.overflow_strategy`). The honest fix is editing the script: fewer
words, or a longer window. The stage prints the exact factor per scene so
you can see which lines are over-stuffed.

VoiceStudio users can skip tempo entirely:
`tts.voicestudio.use_target_duration: true` asks the engine for audio that is
already exactly the scene length.

## Music that will not get your video struck down

Only use music you have rights to. Safe sources:

| Source | Licence notes |
|---|---|
| YouTube Audio Library | free, monetisation-safe |
| Pixabay Music | free, no attribution |
| Incompetech | free with a credit line in the description |
| Uppbeat | free tier, credit line |
| Free Music Archive | check each track's CC licence |

Drop files into `assets/background_music/`. The bot picks per
`audio.music.mode`:

* `random` - different track each video (default)
* `first` - always the alphabetically first (brand consistency)
* `filename` - exactly `audio.music.filename`
* `match_mood` - scores filenames against the script's mood words
  (`dark`, `space`, `epic`, `calm`, ...) and the narration text
* per-scene `@music:` lines switch tracks mid-video

## Ducking, explained once

`sidechaincompress` uses the VOICE as the control signal for a compressor on
the MUSIC. When you speak, the music is squeezed down; when you stop, it
swells back over `duck_release_ms`. One filter, zero automation lanes.

Tuning: `audio.music.volume_db` (-19) sets the resting level; `duck_ratio`
(8) how hard speech pushes it down; `duck_attack_ms` (25) should stay fast;
`duck_release_ms` (450) should feel like a breath, not a door slamming.

## Loudness targets

* `-16 LUFS` integrated = the YouTube/Spoken-word standard (default).
* `-14 LUFS` = louder, for Shorts feeds.
* True peak limited to -1.5 dBTP so no platform ever clips you.

Verify any export with:
```bash
ffmpeg -i output/final.mp4 -af loudnorm=print_format=summary -f null -
```

## Silences are a feature

`head_silence_ms` (150) gives each scene a breath before speech;
`tail_silence_ms` (450) gives the thought room to land; `@pause: 1.5` adds a
deliberate beat after a scene. Videos that never pause feel like ads.
