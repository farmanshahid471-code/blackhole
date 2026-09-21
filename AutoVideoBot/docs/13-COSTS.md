# What a finished video costs, per path

Indicative prices; verify current rates. Per **finished 2-minute video**
(~13 scenes, ~25 images, ~350 words of narration).

## Path A - Zero dollars, zero accounts

| Component | Choice | Cost |
|---|---|---|
| script | your own file | $0 |
| voice | Edge-TTS | $0 |
| images | Pollinations | $0 |
| render | your PC | $0 |
| **total** | | **$0** |

Limits: shared image service can be slow/rate-limited; no cloning; captions
and everything else fully featured.

## Path B - Free GPUs (Colab or Kaggle)

Same as A but images come from SDXL/FLUX on a free notebook.
Cost **$0**, price is ~3 minutes of clicking per Colab session (or 2 clicks
per Kaggle batch) plus session fragility.

## Path C - Vast.ai auto-rent

| Component | Typical | Cost |
|---|---|---|
| GPU (RTX 3090, warm instance) | ~10 min | ~$0.03 |
| GPU first boot (model download) | ~25 min once | ~$0.08 once |
| everything else | | $0 |
| **per video** | | **$0.03 - $0.10** |

## Path D - Replicate images

~25 images x $0.003 (flux-schnell) = **~$0.08/video**, zero ops.
flux-dev at $0.025/img would be ~$0.65/video for noticeably better art.

## Path E - Paid voice

| Voice | Per 350 words |
|---|---|
| Edge-TTS | $0 |
| VoiceStudio (self-hosted) | $0 (+ your electricity/GPU) |
| OpenAI TTS | ~$0.005 |
| ElevenLabs | ~$0.03-0.10 (plan dependent) |

## Path F - Script via LLM

| LLM | Per 2-min script |
|---|---|
| DeepSeek chat | ~$0.001 |
| Groq free tier | $0 |
| Ollama local | $0 |
| GPT-4o-mini class | ~$0.002 |

## Realistic monthly picture, one video per day

| Stack | Monthly |
|---|---|
| A (all free) | $0 |
| C + DeepSeek + Edge | ~$2-3 |
| D + ElevenLabs + DeepSeek | ~$5-8 |

The expensive part of faceless video was never the compute - it was the
hours. This bot's job is to make those hours zero.
