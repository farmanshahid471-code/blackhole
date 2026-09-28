# How to test a 60-second local video

An original **six-scene, 0–60-second script** is ready at `examples/vector-60s.json`. It contains 3 vector shots, 1 WebGL shader shot, and 2 existing diagrams. The result is a *pipeline integration test*, not six new bespoke vector animations or a finished documentary.

I ran the full pipeline **locally** with the bot's `tts.provider=test` and checked `pilot/vector-60s-offline-test.mp4`: 60.00s, 640×360, 24 fps, H.264 video + AAC sound + captions. **The soundtrack is a synthesized test tone, NOT speech.** It proves the script/voice-timing/Remotion/shader/FFmpeg/caption path without network TTS, DeepSeek, or paid Vast.ai. The local CPU/SwiftShader run took about 9 minutes here; your machine may differ. Do not publish the tone version.

## Run it with a spoken Edge voice on your F: drive

1. Put the current `AutoVideoBot` folder somewhere on **F:** and open **PowerShell in that folder** (not in the parent folder). Use the existing F: installation if you already have one; **choose a new project name** so the 62-scene image project is not overwritten. Check `examples\vector-60s.json` exists there. The separate pilot script `pilot/build_narrated_test.py` makes the earlier 42-second video; it is **not** the command for this 60-second example.
2. If you have not set up the bot: run its `INSTALL-WINDOWS.bat` from the F: folder, then run `npm ci` in `render`. That installs `node_modules` under the repository. Remotion also needs a working local Chrome/Chromium; if automatic download is blocked, use a browser executable already installed on your PC.
3. In **PowerShell**, from inside `AutoVideoBot`, run these commands (copy the commands only, not the `PS>` prompt):

```powershell
Set-Location .\render
$env:npm_config_cache = (Join-Path (Split-Path (Get-Location)) '.cache\npm')
npm ci
Set-Location ..
& .\.venv\Scripts\python.exe main.py doctor --set visual.engine=remotion --set visual.render_backend=local --set tts.provider=edge
& .\.venv\Scripts\python.exe main.py run vector-60s-voice --script examples\vector-60s.json --set visual.engine=remotion --set visual.render_backend=local --set tts.provider=edge --set audio.music.enabled=false --set audio.sfx.enabled=false --set video.width=640 --set video.height=360 --set video.fps=24 --set video.preset=veryfast --set video.crf=28
```

**Output:** `workspace\projects\vector-60s-voice\output\final.mp4` under your F: bot directory. The subtitle file and `qa.json` are under that same project's `subs` and `output` folders. Check the voice at scene boundaries (10, 20, 30, 40, 50 seconds), any clipped words, and the shader's 30–40-second section. The six `start`/`end` timestamps aim for one minute; if a real voice cannot fit safely, the timing stage may **lengthen the video** rather than cut words. Check the final MP4 duration rather than assuming it is exactly 60.0 seconds.

If Edge TTS fails due to networking, change **only** the project name to `vector-60s-tone` and `--set tts.provider=edge` to `--set tts.provider=test` in the final command. This produces an **offline audible tone**, not a spoken voice. Never mistake its evenly spaced test word times for verified real-word alignment. You can also watch the already-rendered tone test before attempting any setup.

`--script` uses the supplied text, so no DeepSeek script API is needed. `visual.render_backend=local` and a new project name ensure **no Vast rental** and no edits to the existing 62-scene project. The configured Edge provider requires internet. Render/browser caches and installers may still use C: unless you point their cache or browser paths to F:; storing an installer on F: does not guarantee that its installed files avoid C:. If your F: setup has a portable Chrome, append `--set visual.browser_executable=F:\path\to\chrome.exe` to the `run` command. Do not paste the example placeholder path literally.
