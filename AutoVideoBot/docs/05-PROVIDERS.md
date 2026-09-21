# Providers - swapping and setting up every tool

Run `python main.py providers` to see the live list with the active ones
starred.

---

## 1. LLM (script + prompts + metadata)

### deepseek (recommended for topic mode)
```
https://platform.deepseek.com  ->  API Keys  ->  create  ->  copy
.env:  DEEPSEEK_API_KEY=sk-...
```
Cost: well under a cent per video script. `deepseek-chat` is the workhorse;
`deepseek-reasoner` for research-heavy topics.

### openai_compat (one provider, many services)
```yaml
llm: {provider: openai_compat}
```
```
.env:  OPENAI_BASE_URL=https://api.groq.com/openai/v1
       OPENAI_API_KEY=gsk_...
       OPENAI_MODEL=llama-3.3-70b-versatile
```
Works with OpenRouter, Together, Mistral, OpenAI, LM Studio
(`http://localhost:1234/v1`, key `lm-studio`), vLLM, anything OpenAI-shaped.

### ollama (free, offline)
Install https://ollama.com, `ollama pull llama3.1`, then
`llm.provider: ollama`. Small models are weaker at strict JSON; the bot
repairs common damage automatically, but if you get JSON errors use a bigger
model or DeepSeek.

### manual (your scripts only)
`llm.provider: manual` disables all LLM calls. Image prompts come from your
`@prompt:` lines or the template in `prompts/image_polish.txt`.

---

## 2. TTS (voiceover)

### edge (default, free, word timings)
Nothing to configure. Pick a voice:
`python main.py voices --filter en-US` then `tts.edge.voice: "..."`.
Documentary favourites: `en-US-GuyNeural`, `en-US-ChristopherNeural`,
`en-US-EricNeural`, `en-GB-RyanNeural`, `en-IN-PrabhatNeural`.

### voicestudio  (https://github.com/debpalash/VoiceStudio)
Self-hosted, local, voice-cloning capable.
```bash
git clone https://github.com/debpalash/VoiceStudio && cd VoiceStudio
# follow its README installer; backend listens on http://127.0.0.1:3900
```
```
.env:        VOICESTUDIO_URL=http://localhost:3900
             VOICESTUDIO_VOICE=default
config.yaml: tts.provider: voicestudio
```
The provider talks to its OpenAI-compatible endpoint
`POST /v1/audio/speech` first and falls back to the native form endpoint
`POST /generate`. Two superpowers:
* `use_target_duration: true` sends your scene length in the request
  (VoiceStudio's `duration` field), so the audio arrives already fitted to
  your timestamps - no tempo stretching at all.
* `profile_id` uses a voice you cloned in the VoiceStudio app.
`instruct` adds style direction ("calm, slow, ominous") where the engine
supports it.

To run VoiceStudio on a rented GPU instead of your CPU: install it on the
Vast/RunPod machine, start its backend with `--host 0.0.0.0 --port 3900`,
open that port in the provider firewall, and point `VOICESTUDIO_URL` at the
public address. Nothing else changes.

### elevenlabs (best quality, paid)
Key + a `voice_id` from the ElevenLabs dashboard (or a cloned voice).
`stability` 0.4-0.5 for natural documentary pacing.

### openai_tts / piper / espeak
* `openai_tts` - simple paid voices (`alloy`, `onyx`, ...).
* `piper` - fully offline neural TTS: `pip install piper-tts`,
  `python -m piper.download_voices en_US-lessac-medium --data-dir assets/piper`.
* `espeak` - robotic last resort so a pipeline never dead-ends.

---

## 3. IMAGE (visuals)

| Provider | Setup | Money | Speed | Notes |
|---|---|---|---|---|
| pollinations | none | $0 | 5-20 s/img | free shared service; retry ladder built in |
| sdwebui | WebUI with `--api` | your GPU | 2-8 s/img | one provider covers local/Colab/Vast/RunPod WebUIs |
| vast | API key + CLI | cents/video | 1-4 s/img | auto rent + auto destroy |
| colab | notebook + tunnel link | $0 | 3-6 s/img | you click Run once per session |
| kaggle | notebook batch | $0 | batch | 2 manual clicks, then automatic |
| gradio | any Gradio link | usually $0 | varies | HF Spaces too |
| replicate | API token | ~$0.003/img | 2-5 s/img | zero ops, FLUX quality |

### sdwebui details
Start AUTOMATIC1111/Forge with `--api --listen --port 7860`.
`SDWEBUI_URL` in `.env` can be `http://127.0.0.1:7860` or a tunnel URL.
Set `image.sdwebui.model` to auto-load a checkpoint
(`juggernautXL...safetensors`), `hires_fix: true` for a 2-pass upscale.

### gradio details
Open `https://<space>/info` in a browser to learn the real `api_name` and
argument order, then set `image.gradio.api_name` and `arg_order` to match.
`response_image_path` (e.g. `data[0].url`) tells the bot where the picture
hides in the reply. `HF_TOKEN` env for private spaces.

Full guides: `06-VAST-AI-GPU.md`, `07-COLAB-KAGGLE.md`.

---

## 4. ASSEMBLY (render engine)

* `ffmpeg` (default) - C-speed, exact filter control, what everything here is
  tuned for.
* `moviepy` - `pip install moviepy`, then `motion.engine: moviepy`. Slower
  (Python per frame) but the easiest place to prototype exotic effects; the
  file reads like a tutorial.

---

## How swapping actually behaves

* The manifest hashes the provider name into every cache key, so switching
  providers does not silently reuse another provider's output; it regenerates
  what changed and keeps what is still valid.
* `--set image.provider=vast --set image.vast.search.gpu_type="RTX 3090"`
  overrides config for one run - perfect for A/B testing tools.
* `python main.py doctor` health-checks the *currently configured* providers
  before you spend an hour on a render.
