# Installation

## TL;DR

| System | What to do |
|---|---|
| **Windows 10/11** | **Double-click `INSTALL-WINDOWS.bat`** in the project folder, then `START-WINDOWS.bat` whenever you want to use the bot. |
| macOS / Linux / WSL | `bash START-WEB.sh` (it installs anything missing and opens the browser), or `./scripts/setup.sh` for the command-line-only setup |

### What `INSTALL-WINDOWS.bat` does for you

It is a normal, readable batch file - open it in Notepad if you want to see
every single thing it runs. In order:

1. **finds Python** (`py`, `python`, or the usual install folders). If there is
   none, it opens the official python.org download page, waits for you, and
   then looks again.
2. creates a **private environment** in `.venv\` - nothing is installed
   system-wide and nothing is added to your PATH.
3. `pip install -r requirements.txt` - the core libraries, `edge-tts`, and
   the optional extras.
4. adds the **web interface** packages and **`imageio-ffmpeg`**, which
   downloads a complete, real FFmpeg binary *inside the project*. This is why
   you do not have to install FFmpeg yourself or edit your PATH - the single
   biggest stumbling block for beginners, removed.
5. checks FFmpeg is actually runnable (`ffmpeg -version` through the bot's own
   resolver) and warns clearly if it is not.
6. creates `workspace\`, `assets\background_music\`, `assets\fonts\`,
   `assets\piper\` and copies `.env.example` to `.env`.
7. runs `main.py doctor` and prints the result.
8. finally offers: **1** open the web interface, **2** open a terminal with the
   environment activated, **3** just exit.

It is **safe to run again** at any time: it reuses what exists, skips what is
installed, and repairs what is broken. That makes it the answer to most
"it stopped working" questions.

> If Windows blocks the file (a "Windows protected your PC" box), click
> **More info -> Run anyway**. That message appears for any downloaded `.bat`
> file; the script contains nothing but `pip` and `python` commands.

### The other launchers

| File | Purpose |
|---|---|
| `START-WINDOWS.bat` | Opens the **web interface** and installs anything missing first. |
| `START-CONSOLE.bat` | Opens a terminal with `.venv` already activated (for command-line users). |
| `START-WEB.sh` | The macOS/Linux equivalent of `START-WINDOWS.bat`. |
| `scripts/setup.bat` / `scripts/setup.sh` | The original, lighter setup scripts (command line only). Still work fine. |

## Manual route (if you prefer to see every step)

### 1. Python 3.10+

* Windows: https://www.python.org/downloads - **tick "Add python.exe to PATH"**
* macOS: `brew install python`
* Ubuntu/Debian: `sudo apt install python3 python3-venv python3-pip`

Check: `python3 --version` (or `python --version` on Windows).

### 2. FFmpeg (the most common Windows stumbling block)

> **Shortcut first:** you can skip this whole section. Run
> `pip install imageio-ffmpeg` and the bot will find that private copy by
> itself - that is exactly what `INSTALL-WINDOWS.bat` does for you. The
> instructions below are for people who want FFmpeg installed system-wide, or
> who want a specific build.

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

`requirements.txt` includes, besides the core libraries: `edge-tts` (the free
voice), `imageio-ffmpeg` (a private FFmpeg, see above), and the web interface
(`fastapi`, `uvicorn`, `python-multipart`, `psutil`). Optional providers are
commented out at the bottom of the file - uncomment the ones you use (for
example `replicate`, `vastai`, `gradio_client`).

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
