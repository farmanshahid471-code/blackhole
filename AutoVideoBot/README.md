# AutoVideoBot

**Give it a script with timestamps. Get back a finished video.**
Voice, images, camera movement, transitions, captions, music, thumbnail,
YouTube metadata - the whole thing, automatic, resumable, and every part
swappable.

```
your_script.txt ──> [parse] ──> [voice] ──> [timing] ──> [images] ──> [motion]
                  ──> [transitions] ──> [captions] ──> [music mix] ──> final.mp4
```

Built exactly around this stack (every line is a hot-swappable provider):

| Job | Options implemented | Default |
|---|---|---|
| Script & prompts | DeepSeek · any OpenAI-compatible API · Ollama · **your own file** | deepseek |
| Voiceover | **VoiceStudio** · Edge-TTS (free) · ElevenLabs · OpenAI · Piper · espeak | edge |
| Images | **Vast.ai (auto rent/destroy)** · Colab · Kaggle · SD WebUI · Gradio · Replicate · Pollinations (free) | pollinations |
| Motion | Ken Burns pan/zoom in FFmpeg ($0) · MoviePy | ffmpeg |
| Assembly | FFmpeg · MoviePy | ffmpeg |
| Server | your PC (this folder) | local |

---

## 30-second start (zero money, zero accounts)

```bash
# 1. install
./scripts/setup.sh                 # Windows: scripts\setup.bat

# 2. make a video right now - no API keys needed at all
python main.py run "my-first-video" --topic "why the ocean is deep" --duration 60

# 3. watch it
#    workspace/projects/my-first-video/output/final.mp4
```

## Start with YOUR script (the mode you asked for)

```bash
python main.py run "black-holes" --script examples/black_holes_script.txt
```

The script format (timestamps, `@prompt:`, `@motion:`, headers...) is
documented in [`docs/03-SCRIPT-FORMAT.md`](docs/03-SCRIPT-FORMAT.md).

## Switch any part, one line

```yaml
# config.yaml
image.provider: vast        # rent a GPU automatically, destroy it when done
tts.provider: voicestudio   # your self-hosted VoiceStudio server
llm.provider: ollama        # free offline script writing
```

or per run, no file editing:

```bash
python main.py run "vid" --script s.txt --set image.provider=vast
```

## The docs (read in this order)

| File | What you get |
|---|---|
| [docs/00-START-HERE.md](docs/00-START-HERE.md) | **The A-to-Z guide.** Every stage explained like you have never opened a terminal. |
| [docs/01-INSTALLATION.md](docs/01-INSTALLATION.md) | Windows / macOS / Linux setup, ffmpeg, keys |
| [docs/02-YOUR-FIRST-VIDEO.md](docs/02-YOUR-FIRST-VIDEO.md) | First render, what every log line means |
| [docs/03-SCRIPT-FORMAT.md](docs/03-SCRIPT-FORMAT.md) | The timestamped script format, every directive |
| [docs/04-CONFIG-REFERENCE.md](docs/04-CONFIG-REFERENCE.md) | Every single config.yaml setting, explained |
| [docs/05-PROVIDERS.md](docs/05-PROVIDERS.md) | How to swap/extend every provider, with setups |
| [docs/06-VAST-AI-GPU.md](docs/06-VAST-AI-GPU.md) | Auto-renting GPUs that cost cents per video |
| [docs/07-COLAB-KAGGLE.md](docs/07-COLAB-KAGGLE.md) | Free GPU notebooks, tunnels, batch flow |
| [docs/08-MOTION-VISUALS.md](docs/08-MOTION-VISUALS.md) | Ken Burns, the 13 motion presets, colour grades |
| [docs/09-AUDIO-MUSIC.md](docs/09-AUDIO-MUSIC.md) | Voices, ducking, loudness, where to get legal music |
| [docs/10-SUBTITLES.md](docs/10-SUBTITLES.md) | Word-accurate captions, styles, vertical video |
| [docs/11-TROUBLESHOOTING.md](docs/11-TROUBLESHOOTING.md) | Every error you will ever see, and the fix |
| [docs/12-EXTENDING.md](docs/12-EXTENDING.md) | Add your own provider in ~40 lines |
| [docs/13-COSTS.md](docs/13-COSTS.md) | What each path costs per finished video |

## Commands cheat-sheet

```bash
python main.py doctor                    # is everything installed?
python main.py providers                 # what can I swap?
python main.py voices                    # list TTS voices
python main.py test                      # tiny 8s video to verify the toolchain
python main.py run NAME --topic "..." --duration 120      # AI writes everything
python main.py run NAME --script file.txt                 # you write, bot films
python main.py voice NAME / images NAME / motion NAME ... # run ONE stage
python main.py inspect NAME              # what is done, what is missing
python main.py projects                  # list all projects
python main.py clean NAME                # free disk space (keeps the video)
```

Every stage is resumable: re-run anything after a crash or a power cut and
only the missing pieces are rebuilt.
