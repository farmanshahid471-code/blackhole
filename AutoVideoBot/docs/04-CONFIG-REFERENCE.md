# config.yaml - every setting, explained

`config.yaml` is the control panel. YAML rules: **spaces not tabs**, two
spaces per indent level, `#` starts a comment.

Override anything for a single run without editing:

```bash
python main.py run vid --script s.txt --set image.provider=vast --set video.fps=60
```

---

## video

| Key | Default | Meaning |
|---|---|---|
| `aspect` | `16x9` | `16x9` 1920x1080, `9x16` 1080x1920, `1x1`, `4x5`, `21x9` |
| `width`/`height` | null | force exact pixels (ignores aspect) |
| `fps` | 30 | 24 = cinematic, 60 = smooth but 2x render time |
| `crf` | 20 | quality. 18 = very high, 28 = small test files |
| `preset` | medium | x264 speed. `ultrafast` while iterating, `medium` for uploads |
| `codec` | h264 | h265 = smaller files, slower, worse compatibility |

## llm

`provider`: `deepseek` | `openai_compat` | `ollama` | `manual`

* `deepseek.*` - base url / key env name / model / temperature / max tokens.
  `deepseek-chat` for scripts; `deepseek-reasoner` for hard research topics.
* `openai_compat.*` - any OpenAI-shaped API: Groq (free, fast), OpenRouter,
  Together, LM Studio (`http://localhost:1234/v1`), vLLM, OpenAI itself.
* `ollama.*` - free offline models on your PC.
* `manual` - no AI at all; you must supply scripts.
* `prompt_files.*` - the .txt files that define the bot's writing voice.
* `scenes.*` - target seconds per scene, word limits, language. Used only in
  topic mode.

## image

`provider`: `pollinations` | `sdwebui` | `vast` | `colab` | `kaggle` | `gradio` | `replicate`

Shared: `width`, `height`, `steps` (20-50), `cfg` (5-9), `sampler`,
`negative_prompt`, `style_suffix` (appended to every prompt - your house
style), `seed_mode` (`random` | `fixed` | `scene`), `batch_retries`.

Per-provider blocks:

* `pollinations.*` - model (`flux`/`turbo`), `delay_seconds` (politeness).
* `sdwebui.*` - `url_env` (SDWEBUI_URL), `model` (checkpoint to load),
  `hires_fix` + `hires_scale` (2-pass upscale).
* `vast.*` - see `docs/06-VAST-AI-GPU.md`. `mode: search|existing`,
  `instance_id`, `search.{gpu_type,min_vram_gb,max_price_per_hour,disk_gb,
  image,region}`, `server_dir`, `server_port`, `boot_timeout`,
  `destroy_after_use` (keep true!), `local_tunnel_port`.
  The three quality gates - `search.min_reliability` (default 0.95),
  `search.min_inet_down_mbps` (200) and `search.min_cuda` (12.0) - decide which
  hosts are even considered before price does. Raise the network gate on a fast
  connection; lower it if Vast keeps answering "no machine matched". A host
  that hides a figure is still allowed (it is only ranked after the hosts that
  publish one).
* `colab.*` / `gradio.*` - `endpoint_env` (IMAGE_ENDPOINT_URL), `api_path`,
  `keepalive_seconds`, `ngrok_header`.
* `kaggle.*` - `notebook_template`, `output_dir`, `auto_push`, `model`.
* `replicate.*` - `model` (e.g. `black-forest-labs/flux-schnell`).

`parallel_requests` - concurrent HTTP calls for providers that allow it
(pollinations/gradio). Keep 1-3 for free services.

## tts

`provider`: `edge` | `voicestudio` | `elevenlabs` | `openai_tts` | `piper` | `espeak`

Shared: `rate` (`+0%`), `pitch`, `volume`, `audio_format` (wav),
`sample_rate`, `head_silence_ms` (150), `tail_silence_ms` (450).

* `edge.voice` - e.g. `en-US-GuyNeural`, `en-US-ChristopherNeural`,
  `en-GB-RyanNeural`. List them: `python main.py voices`.
* `voicestudio.*` - `url_env`, `voice_env`, `api_path` (`/v1/audio/speech`),
  `native_path` (`/generate`), `prefer` (`openai_compat`|`native`|`auto`),
  `use_target_duration` (ask VoiceStudio for audio that already fits your
  timestamps - no tempo stretching at all), `engine`, `profile_id` (a cloned
  voice), `instruct` ("calm, slow, mysterious"), `num_step`, `guidance_scale`.
* `elevenlabs.*` - key env, `voice_id_env`, `model_id`, `stability`,
  `similarity_boost`, `style`.
* `openai_tts.*`, `piper.*`, espeak: see `docs/05-PROVIDERS.md`.

## timing

| Key | Default | Meaning |
|---|---|---|
| `fit_to_timestamps` | true | stretch speech to your timestamps |
| `min_duration` | 2.0 | floor for a scene |
| `max_duration` | 30.0 | ceiling (warns; split long scenes) |
| `default_scene_seconds` | 6 | when no timestamp is given |
| `max_speedup` | 1.35 | never speak faster than this |
| `max_slowdown` | 0.85 | never speak slower than this |
| `overflow_strategy` | pad_then_hold | `trim` or `split_scene` alternatives |

## motion

`engine`: `ffmpeg` (fast) | `moviepy` (hackable).
`preset`: `auto` (cycle) or a fixed name. `auto_order`: your cycle list.
`zoom_amount` (1.12), `pan_amount` (0.10), `focus`
(center/top/bottom/left/right/rule_of_thirds), `supersample` (`auto` -
measured from your RAM), `shake`, `add_vignette`, `vignette_strength`,
`add_film_grain`, `color_grade`
(`none|cinematic|warm|cool|noir|vivid|teal_orange|film`),
`scene_fade_seconds`.

Presets and the maths: `docs/08-MOTION-VISUALS.md`.

## transitions

`enabled`, `type` (`crossfade|cut|fade_black|slide_left|wipe|dissolve|...`),
`duration` (0.45 - above 1.0 feels slow), `vary` (rotate through a tasteful
pool instead of one effect).

## audio

* `music.folder` - where your licensed tracks live.
* `music.mode` - `random|first|filename|match_mood`.
* `music.volume_db` (-19) - music level under the voice.
* `music.fade_in_seconds`, `fade_out_seconds`, `loop`.
* `music.ducking` + `duck_ratio` (8), `duck_attack_ms` (25),
  `duck_release_ms` (450) - the automatic "get out of the voice's way".
* `voice.normalize`, `target_loudness_lufs` (-16 = YouTube), `compressor`,
  `eq` (`none|broadcast|simple`).
* `master.limiter`, `master.fade_out_seconds`.

## subtitles

`enabled`, `burn_in` (paint into the picture) , `source`
(`word_boundaries|scene_split|none`), `words_per_line` (4),
`max_chars_per_line`, `style.*` (font, size 52, colours as `&HAABBGGRR`,
outline, shadow, `margin_v`, `alignment` 2 = bottom centre),
`shorts_style.*` for the big one-word-at-a-time look.

## extras

* `thumbnail.strategy` (`best_scene|at_time|scene_index`), `at_seconds`,
  `add_title_text`, `title_max_words`.
* `metadata.enabled` - LLM-written title/description/tags/chapters.
* `watermark.*` - PNG overlay, position, opacity, scale.
* `intro_outro.*` - prepend/append your own mp4 branding clips.

## system

`ffmpeg_bin`, `ffprobe_bin` (full paths if not on PATH), `threads`,
`temp_dir`, `projects_dir`, `log_level` (`DEBUG` prints every ffmpeg
command - the best way to learn), `keep_intermediate_files`,
`parallel_scenes` (1 recommended), `retry_attempts`, `on_error`
(`continue|abort`), `encode_threads` (cap x264 threads on small machines),
`encode_lookahead` (cap x264 RAM buffer).
