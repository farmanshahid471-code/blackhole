# 14 - The Web Interface (point and click)

Everything the bot can do from the command line, it can do from a browser
window: create videos, watch every stage happen live, play and download the
results, change any setting, and paste your API keys.

You do **not** need to learn a single command to use it.

---

## 1. Starting it

### Windows - the easy way

Double-click **`START-WINDOWS.bat`** in the project folder. That is it.

The first time you do this, it installs anything missing (Python libraries, a
private copy of FFmpeg) and then opens your browser on
`http://127.0.0.1:8765` by itself.

> If the file refuses to run or a window flashes past, right-click it and choose
> **Run as administrator** once. Some managed computers block `.bat` files until
> you do.

### macOS / Linux

```bash
bash START-WEB.sh
```

### From the command line (any system)

```bash
python main.py web
```

Useful extras:

```bash
python main.py web --port 9000        # a different port
python main.py web --no-browser       # do not open a browser automatically
python main.py web --host 0.0.0.0     # also reachable from your phone on the
                                      # same wifi (your computer stays awake and
                                      # will show its firewall asking to allow it)
```

**Keep the terminal window open** while you use the interface. Closing it stops
the bot. That is normal: the web page is just a remote control for the program
running on your computer.

---

## 2. The six screens

### Dashboard

The state of everything, in one glance: how many videos you have made, which
image/voice/script tools are active, how many API keys are filled in, and your
background music list.

Buttons:

| Button | What it does |
|---|---|
| **Run health check** | The same as `main.py doctor`. Checks Python, FFmpeg, every configured provider and your folders. |
| **Run the 8-second self-test** | Builds a tiny complete video. If this works, your installation is correct. Do this first on a new machine. |
| **Create a video** | Takes you to the build page. |
| **Try the example script** | Loads the bundled 4-scene script into the editor. |

The **Recent builds** panel lists every job from this session with a live
status pill, so you can start a build and keep working.

### Create a video

The main screen. Two ways in, both ending in the same finished MP4:

**I have a script** - paste your script, or load a `.txt` file with
*drag-and-drop style* file picker, or click **Load the example**. Timestamps
are optional. See the Help tab for the exact formats.

**Write it for me** - type a topic and a target length. This needs an LLM
(the script writer) configured in Settings. Free choices: **Ollama** (runs
offline on your PC) or the **openai_compat** provider pointed at Groq, which
has a free tier.

Then:

| Option | Why it matters |
|---|---|
| **Quality** | *Draft* switches to ultrafast encoding and low super-sampling: about 4x faster, noticeably rougher. Use it while you are experimenting, then rebuild at *Standard*. |
| **Shape** | 16:9 for YouTube, 9:16 for Shorts/Reels/TikTok, 1:1 for square. |
| **Frames per second** | 24 looks filmic, 30 is standard, 60 is very smooth but doubles the render time. |
| **Rebuild from scratch** | Ignores the cache. Only needed if you changed something the bot does not track (like editing an image file by hand). |
| **Voice / Voice / Image / LLM provider** | Per-video overrides. Leave them on *use my settings* and the bot follows `config.yaml`. Setting them here does **not** change your saved settings. |

Press **Build the video**. The monitor on the right shows the real log, stage
by stage, exactly as the terminal would print it - including the
`STAGE 4 / 10` banners and the progress bar at the top.

You can close the browser tab: the build keeps running (the bot is a program on
your PC, not a web page). Reopen the page to see it again.

**Stop** asks the bot to finish the stage it is in and then stop. Everything
already rendered stays cached, so pressing Build again continues from there
instead of starting over.

### My videos

Every build is kept as a *project*. Click **Details** to see:

* the **scene table** - each scene's timing, word count, motion preset, whether
  it has an image and a clip, and the narration text
* the **stage list** with **Run** and **Force** buttons, so you can rebuild just
  one step (force = ignore the cache)
* the **files** it produced, and a **run history**
* the **YouTube metadata** the bot wrote (title, description, tags) ready to
  copy and paste

Buttons: **Play** (inline video player), **Download MP4**, **Thumbnail**,
**Metadata**, **Captions**, **Open folder** (opens the real folder on your
computer), **Clean cache** (deletes intermediate files to save disk - the final
video and your script survive), and **Delete project** (asks twice).

### Providers

Every interchangeable tool the bot has, grouped by stage, with cost, quality,
setup time and whether it needs an API key.

* **Test** runs that provider's own health check - no video is built, so it
  costs nothing and takes seconds. The message tells you exactly what to fix.
* **Use** makes it the active provider by writing one line into `config.yaml`.

This is the fastest way to answer "why did my images fail?".

### Settings & keys

**API keys** - paste keys here and they are saved to the `.env` file. Once
saved, the page only ever shows *whether* a key is set, never the key itself:
the value is never sent back to the browser. That is deliberate, and it is why
you will re-type a key to change it.

**Common settings** - the twenty options people actually change (quality,
motion strength, caption size, music volume, ducking, parallel scenes...).
Saving rewrites those lines in `config.yaml` and **keeps all the comments** in
that file, because the file is also the manual.

**Add your own files** - the three things a beginner always asks about:

| File | Where it goes | What happens then |
|---|---|---|
| Background music (.mp3/.wav/.m4a) | `assets/background_music/` | used automatically as the music bed, at -19 dB, ducked under the voice |
| Watermark (.png) | `assets/watermark.png` | turn it on with `extras.watermark.enabled: true` |
| Caption font (.ttf/.otf) | `assets/fonts/` | set its name in `subtitles.style.font` |
| Piper voice (.onnx) | `assets/piper/` | lets the `piper` voice provider work offline |

**Advanced** - a filtered editor for *every* key in `config.yaml`, in case
something is not in the common list.

### Help

The five-minute guide, the complete script format (timestamps, `@prompt:`,
`@motion:`, `@pause:`, `@voice:`, headers...), a troubleshooting table, and an
honest cost table for every provider combination.

---

## 3. Troubleshooting

| What you see | What it means | Fix |
|---|---|---|
| The page will not load at all | The server is not running | Run `START-WINDOWS.bat` / `START-WEB.sh` again and keep its window open |
| "server not reachable" in the sidebar | Same as above, or you changed the port | Check the terminal for the real address |
| A build ends with "failed" | Read the log - the last red line says why | Usually a provider problem: test it on the Providers tab |
| The log stops halfway, nothing new | A long image batch (free services are slow) | Wait; the progress bar still moves between stages |
| Images all look like dark cards with text | That *is* the placeholder card - the image provider failed for those scenes | Providers tab -> Test the image provider |
| The browser asks whether to allow a firewall rule | You started with `--host 0.0.0.0` | Allow it if you want to use the bot from your phone, refuse otherwise |
| Chinese/Japanese text in the terminal | The bot writes UTF-8 and your terminal is set to another code page | Cosmetic only. In Windows: `chcp 65001` before starting, or just use the web UI |

---

## 4. How it works (for the curious)

The web interface is a small **FastAPI** server inside `webui/`:

```
webui/
    server.py          the API: starts builds, streams logs, reads/writes config
    static/index.html  the page
    static/app.css     the styling
    static/app.js      the logic (no frameworks, no build step)
```

Two design decisions worth knowing:

**1. The web UI runs the same code as the command line.**
Every button calls the same `Pipeline` class that `python main.py` calls. There
is no second, web-only implementation that can drift out of sync. If a feature
works in one place it works in both, and bug fixes apply to both.

**2. Builds run in the background and the log is streamed.**
An HTTP request that waited five minutes for a render would time out, and you
would be blind while it happened. Instead, each build is a background thread
whose output is captured line by line and pushed to your browser over
**Server-Sent Events**. That is why the log appears as it happens, exactly like
a terminal.

Security note: the server listens on `127.0.0.1` (this computer only) unless you
explicitly pass `--host 0.0.0.0`. It has no login screen, so do not expose it to
the internet as-is. It is a local tool, not a web service.
