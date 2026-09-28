# Black-hole documentary pipeline (opt-in)

This path replaces AI-image/Ken Burns scenes with deterministic Remotion shots.
The original image path remains the default (`visual.engine: images`). Do not
reuse an image-mode project directory for this mode; use a new project name.

## Quick start: local render

From `AutoVideoBot/`, with Python dependencies and FFmpeg installed:

```bash
cd render && npm ci && cd ..
python main.py doctor --set visual.engine=remotion
python main.py run "gravity-trap" \
  --script examples/documentary_scene_graph.json \
  --set visual.engine=remotion
```

Node, Remotion's Chromium (it can download on first use), and working WebGL
(hardware or slower SwiftShader) are required. If browser downloads are blocked,
set `--set visual.browser_executable=/absolute/path/to/chrome`. On Linux you
may also choose `--set visual.local_gl=angle-egl` for hardware EGL if available.
For a cheap draft, append `--set video.width=640 --set video.height=360`.

The example asks for `deep_space_drone.mp3` in `assets/background_music/`.
Supply your **own licensed file** or add `--set audio.music.enabled=false`.
`--set tts.provider=test` provides a test **tone**, not spoken narration;
`output/qa.json` will warn you not to publish it.

For an LLM-written script, configure a working `llm.provider` and use
`--topic "What does an event horizon mean?" --duration 90` instead of
`--script`. The director only chooses from `render/shots.json`; Python validates shot
names and parameter bounds, and allows at most two focused LLM repair calls
for invalid scene sequences. If the director still repeats otherwise valid
shots, the script keeps those visuals with explicit `visual_variety_warnings`
in `script.json` rather than silently inventing a different scene or refusing
a test render. Malformed *optional* LLM text overlays are omitted with a
`director_warnings` entry instead of triggering repeated DeepSeek requests;
user-supplied scripts still validate overlays strictly. Narration and shot
choices are not modified. Unknown shots and invalid parameters always fail
before rental; review all draft warnings before publishing. An optional
`--reference-video` YouTube link can supply caption/story-flow cues and sampled
visual guidance; see [Reference video](17-REFERENCE-VIDEO.md) for the separate
vision-model setting and the renderer's fixed-shot limitations.
JSON mode is supported by existing LLM adapters, but native provider-enforced
JSON Schema/function calling is not yet uniform across them. Untimed JSON
uses measured voice duration and `duration_hint_s` as a **minimum** visual hold;
explicit editorial `start`/`end` timestamps retain the old audio-fitting path.

## Vast.ai GPU render (optional; costs money)

The new `visual.render_backend=vast` sends only the allowlisted Remotion source
and scene JSON over SSH. It **does not** boot an image-model server or upload
`.env`, music, audio, projects, or credentials. One rented instance can render
multiple scenes in a bounded parallel queue; successfully downloaded clips
are cached even if another scene fails. Final audio, captions, and mux happen
locally. Provide a valid `VAST_API_KEY` in `.env` and an SSH key registered
with Vast.ai before using this option. If `/users/current/` returns
`403` with `code: challenge`, see `docs/06-VAST-AI-GPU.md`: this is not a
signal to rotate your key or to use CAPTCHA-bypass tools.

To reuse **your own running** Vast instance (the bot does not destroy it):

```bash
python main.py run "gravity-remote" --script examples/documentary_scene_graph.json \
  --set visual.engine=remotion --set visual.render_backend=vast \
  --set visual.vast.mode=existing --set visual.vast.instance_id=YOUR_INSTANCE_ID
```

To **rent and destroy automatically** (opt in deliberately):

```bash
python main.py run "gravity-rental" --script examples/documentary_scene_graph.json \
  --set visual.engine=remotion --set visual.render_backend=vast \
  --set visual.vast.mode=search
```

Search mode bills you for boot/install/render/transfer time, not just render
frames. Before rental, the renderer checks the read-only Vast account API and
requires complete voice/timing artifacts and a narration track; missing,
unreadable, or implausibly short spoken audio aborts rather than silently
filling a narrated scene. Decodable Edge replies can still be partial (for
example, 0.36 seconds for a 20-word line); the voice stage retries these before
caching, and both timing and paid motion refuse old truncated artifacts. If a
120-second target stretches beyond its limit after TTS, re-speak at a slightly
faster `tts.rate` or shorten the narration before renting. After
rental, it verifies authenticated SSH before uploading and retries temporary
proxy startup failures for at most `visual.vast.ssh_ready_timeout` seconds
(default 60). If the account API returns a challenge, resolve it through
Vast's official dashboard/support rather than repeatedly renting instances.
These checks reduce avoidable charges but cannot guarantee the GPU, browser,
or SSH service will remain healthy for the entire render. Check
`visual.vast.search` (price cap, disk, GPU model). The default
container is `node:22-bookworm`; setup installs Debian Chromium, runs
`npm ci`, and uses OpenGL `angle-egl`. A browser GPU probe **refuses to render
and destroys the rented instance** if Chromium reports software WebGL;
set `visual.vast.require_hardware_webgl=false` only if you accept paying for
software fallback. It also destroys the owned instance in a `finally` block
on failure; if Vast's destroy API is unreachable the log prints the instance
ID for manual teardown. SSH, networking, browser driver exposure, billing, and
GPU performance vary by host. **Live Vast rental was not exercised in this
repository's offline tests**; use an existing instance to verify your host
before enabling automatic rental.

The worker only accepts scene JSON and IDs like `s01`, uses separate temporary
folders per run, and downloads clips via SCP. `visual.vast.parallel_scenes`
is capped at 4; start with 1 or 2 to avoid GPU/Chromium memory pressure.

## Physics and art direction

The WebGL shader integrates null rays in the **Schwarzschild optical metric
in isotropic coordinates**, using an adaptive midpoint integrator. Disk-plane
intersections and escaped star directions follow the bent rays; the disk starts
at the Schwarzschild ISCO (areal radius `6M`), with gravitational redshift and
approximate special-relativistic Doppler beaming. This is substantially closer
to a gravitationally lensed black hole than a screen-space displacement or
painted ring. It is **not a Kerr spacetime or GRMHD disk simulation**: spin
controls emissivity/turbulence only, lens-strength changes are editorial, the
disk radiance is procedural, and the camera flythrough ends outside the
horizon. Diagrams and mass bars remain stylized, not scientific scale charts.
Review scientific claims and visual accuracy before publishing. GPU render
speed at 1080p/4K has not been benchmarked here.

The nine shots are: `accretion_disk_orbit`, `event_horizon_flythrough`,
`starfield_warp` (WebGL); `core_cross_section_diagram`,
`two_perspectives_split`, `spaghettification`, `mass_scale_compare`,
`title_card`, and `outro` (motion graphics). `render/shots.json` contains the
complete parameter schema. `text_overlays` trigger at scene-relative seconds.

## Audio, cues and QA

Edge TTS already produces word boundaries. Absolute aligned `word_timings`
are saved in `script.json`; `.srt` and karaoke `.ass` captions use those timings.
The renderer makes silent scenes, FFmpeg joins them with cuts to retain exact
voice timing, then ducks licensed background music under the voice.

Transition whooshes and horizon impacts are **procedurally synthesized**, not
third-party samples. They are scheduled against the post-TTS timeline and
mixed under voice and music. Set `audio.sfx.enabled=false` to silence them.
An individual scene can replace automatic cues with an explicit list, e.g.
`"sfx": [{"kind":"rumble","t":2.4}]` (scene-relative seconds; kinds:
`whoosh`, `rumble`). `"sfx": []` suppresses automatic cues for that scene.
These sounds are intentionally subtle; adjust `audio.sfx.*_gain_db` to taste.
The completed documentary mix is normalized to `audio.master.target_lufs`
(default -14). `output/qa.json` reports final duration, loudness, long silences
and warnings. It is a diagnostic report, **not an artistic approval**.

Re-running caches individual shots and downstream content by input fingerprints.
Output files live in `workspace/projects/<name>/`: `script.json`, `clips/`,
`audio/`, `subs/`, `output/final.mp4`, and `output/qa.json`. Use `--only s03`
with the `motion` subcommand after an initial complete render to rebuild one
shot. The transition and assembly stages must then be rerun to pick it up.

## Verification scope and remaining work

Automated Python tests cover shot validation, director contracts, SFX timing,
asset-free synthesis, archive allowlisting, remote partial-failure cleanup, and
caption synchronization. TypeScript typechecking, real local Chromium renders
of all shader modes, a remote worker invocation with a local Chromium, an
end-to-end documentary with captions/music/SFX/QA, and an original image-mode
regression render have been run here. A *real* Vast API/SSH rental still needs
a credentialed host test. Other possible improvements: Kerr frame dragging,
measured disk spectra, full GPU renderer benchmarking, externally licensed
sound design, and forced alignment for TTS engines that provide no word data.
