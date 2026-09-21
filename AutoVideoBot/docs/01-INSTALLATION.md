# Installation

## TL;DR

| System | Command |
|---|---|
| Windows 10/11 | double-click `scripts\setup.bat` |
| macOS / Linux / WSL | `./scripts/setup.sh` |

The script installs ffmpeg (Linux/macOS), creates `.venv`, installs the
python packages, copies `.env.example` to `.env`, makes the folders, and runs
`python main.py doctor`. If doctor ends green you are done.

## Manual route (if you prefer to see every step)

### 1. Python 3.10+

* Windows: https://www.python.org/downloads - **tick "Add python.exe to PATH"**
* macOS: `brew install python`
* Ubuntu/Debian: `sudo apt install python3 python3-venv python3-pip`

Check: `python3 --version` (or `python --version` on Windows).

### 2. FFmpeg (the most common Windows stumbling block)

FFmpeg is a program, not a python package - pip cannot install it.

* **Windows**
  1. download https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
  2. unzip to `C:\ffmpeg`
  3. Windows key -> type "environment variables" -> *Edit the system
     environment variables* -> *Environment Variables...* -> under *System
     variables* select `Path` -> *Edit* -> *New* -> `C:\ffmpeg\bin` -> OK/OK
  4. **close and reopen the terminal** (PATH is read at startup)
  5. test: `ffmpeg -version`
* **macOS**: `brew install ffmpeg`
* **Linux**: `sudo apt install ffmpeg` (the "essentials/full" build matters:
  some minimal builds lack the `xfade` or `sidechaincompress` filters; the
  doctor checks for exactly those)

> No permission to install software? Download the static build from
> https://johnvansickle.com/ffmpeg/ and point config.yaml at it:
> `system.ffmpeg_bin: "C:/ffmpeg-7.0.2/ffmpeg.exe"`.

### 3. Python packages

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Secrets

```bash
cp .env.example .env               # Windows: copy .env.example .env
```
Open `.env` and fill only what you use. All keys are optional - with an empty
`.env` the bot still works in "free mode" (Edge-TTS + Pollinations + your own
scripts).

### 5. Verify

```bash
python main.py doctor
```

The doctor prints a checklist and ends with a VERDICT. Red lines block you;
yellow lines are optional improvements.

## Optional extras

| Want | Install |
|---|---|
| MoviePy engine | `pip install moviepy` |
| Gradio provider | `pip install gradio_client` |
| Kaggle auto-push | `pip install kaggle` + `kaggle.json` in `~/.kaggle/` |
| Vast.ai automation | `curl -fsSL https://vast.ai/install.sh \| bash` (or `pip install vastai`) + `ssh` client |
| Offline voice | `pip install piper-tts` + a voice model |
| Local LLM | https://ollama.com + `ollama pull llama3.1` |

## Disk & RAM expectations

* ~150 MB per finished 1-minute 1080p project (images + clips + wavs).
* 8 GB RAM is comfortable. On 2-4 GB machines the bot automatically lowers
  `motion.supersample` and retries encodes with cheap settings if the OS kills
  ffmpeg - see `system.encode_threads` in the config reference.
