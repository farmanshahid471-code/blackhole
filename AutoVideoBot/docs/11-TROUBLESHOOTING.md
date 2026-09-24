# Troubleshooting - every error you are likely to meet

Start with:

```bash
python main.py doctor          # the 60-second diagnosis
python main.py inspect NAME    # what finished, what is missing
```

Set `system.log_level: DEBUG` in config.yaml to see every ffmpeg/http call.

**The run log.** Every run also writes everything it printed to
`workspace/projects/NAME/logs/run.log`, and appends to it instead of
overwriting, so the whole history of a project is in one file. If a render
failed, or you closed the window, that file is the thing to open first - and it
is the thing to send if you ask for help.

---

## Installation & toolchain

### "ffmpeg not found" / "No such filter: drawtext"
Install ffmpeg (docs/01). The `drawtext` gap is harmless: this bot draws text
with Pillow instead, precisely because many builds lack it. Missing `xfade`
or `sidechaincompress` is NOT harmless - install a full build.

### "Command failed (exit -9)" with no other output
The OS killed ffmpeg for RAM. The bot already retries cheaply; to prevent it:
```yaml
motion: {supersample: 2}
video: {preset: veryfast}
system: {encode_threads: 2, encode_lookahead: 12, parallel_scenes: 1}
```

### Python version errors
3.10+ required. `python3 --version`.

## Script stage

### "No scenes found in ..."
The file has no narration lines, or every line starts with a character the
parser treats as a comment. Narration must not begin with `#`, `//`, `@`
(unless it is a directive) or `[` (unless it is a timestamp).

### Timestamps shifted / warnings about overlaps
The parser repairs overlaps and says so. Fix the source file; re-running is
free for everything else.

### Topic mode: "Could not find valid JSON in LLM response"
A weak local model broke the contract. Use `deepseek-chat`, a bigger Ollama
model (`qwen2.5:14b`), or `--set llm.provider=deepseek` just for that run.

## Voice stage

### Edge-TTS: "returned no audio" / voice errors
Wrong voice name (`python main.py voices --filter en-US`), empty narration,
or a temporary Microsoft-side block. Retry; it usually passes.

### VoiceStudio: "Nothing is listening at ..."
Backend not started, wrong port, or (on a cloud GPU) the port is firewalled.
Health-check it: `curl http://localhost:3900/health`. For a remote machine,
open the port in the provider firewall and use the public address in
`VOICESTUDIO_URL`.

### ElevenLabs 401/402
Bad key / no credits left in the dashboard.

## Image stage

### Pollinations 429 / 500 storms
Free shared service. The 5-step ladder handles most of it. If it persists:
raise `image.pollinations.delay_seconds` to 6, or switch provider for the
run: `--set image.provider=replicate`.

### SD WebUI: "replied 404" or connection refused
You started it without `--api`, or the URL in `SDWEBUI_URL` is stale (Colab
tunnels change every session).

### Vast: instance stuck, or "did not reach running"
```bash
vastai show instances          # what is alive right now
vastai destroy instance <ID>   # stop the bleeding
```
Then check `image.vast.search.gpu_type` exists in your price range
(`vastai search offers --limit 5`).

### Vast: server never healthy
The bot prints `/root/avb_server.log` from the machine. Usually: first boot
still downloading the model (wait), or a gated model needing `HF_TOKEN`.

### Colab: 403/404 on the tunnel link
The link expired. Re-run the notebook, paste the new link
(`--endpoint URL` avoids editing .env).

### Kaggle: notebook imported but "No real prompts"
You imported the template, not the generated `workspace/kaggle_out/kernel.ipynb`.

### Placeholder cards in the video
An image failed and the bot kept the project alive on purpose. Fix the cause
(pick a provider, paste the tunnel link, fix the key), then simply run the
project again:

```bash
python main.py run NAME --script my_script.txt     # no --force needed
```

The pictures that are missing or still placeholders are generated again, and
because the bot fingerprints the *bytes* of every picture, only the affected
scenes re-render - the clips, the crossfade join and the final export follow
automatically. To redo one scene instead:
`python main.py images NAME --only s07 --force`.

## Timing / sync problems

### Voice drifts from timestamps
Look at the printed tempo factors. Beyond the clamp the bot pads with
silence; your scene is over-written. Cut words or widen the window.

### Captions out of sync after a re-render
Delete `subs/` and re-run stages 7-9: captions are rebuilt from the word
files and the current tempo values.

### Video a fraction of a second short/long vs the script
Should not happen any more (audio blocks and clips are pinned to exact
lengths). If it does: `python main.py inspect NAME`, then run with
`--set system.log_level=DEBUG` and look for the "drift" warning that names
the offending scene.

## Assembly

### Black frame at the very end
An old render from before the mux clamp. Delete `output/final.mp4` and the
`assembly:` keys in manifest.json, re-run stage 9.

### Captions enormous
You are burning an .srt (or an old final). The bot burns its own .ass with
the right PlayRes; re-run `python main.py assembly NAME --force`.

## Disk & cache

### Project folder huge
`python main.py clean NAME` (keeps final video + script) or
`clean NAME --all`. Clips and wavs are the bulk; they regenerate on demand.

### I want to force EVERYTHING
`--force`, or delete `manifest.json`.

## When all else fails

1. `python main.py test` - does the toolchain still work at all?
2. Delete the project's `manifest.json` and re-run (nothing external lost).
3. Re-run with `--set system.on_error=abort` to stop at the first real
   failure instead of skipping it.
4. Read the stage's section in docs/00-START-HERE.md - it lists exactly what
   that stage can complain about and why.
