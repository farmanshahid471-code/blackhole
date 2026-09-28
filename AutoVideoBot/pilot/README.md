# Original vector-motion pilot — 24 seconds

**Watch:** `vector-pilot.mp4` (1280 × 720, 24 fps, 24 seconds, silent). This is a *visual proof of concept*, not a completed narrated documentary. It uses original procedural SVG artwork and keyframed motion in Remotion; no reference-video frames, licensed character designs, generated stills, or Vast.ai rental were used. It does **not** alter the existing 62-scene image-mode project.

| Time | Shot ID | Visual motion | Optional draft narration (NOT recorded in the video) |
| --- | --- | --- | --- |
| 0–8s | `stellar_equilibrium` | Pulsing layered star, rotating energy marks, gravity arrows | “A massive star lives in a tug of war. Energy pushing outward holds gravity back, at least for now.” |
| 8–16s | `stellar_collapse` | Core contracts, fusion bar fades, gravity bar grows, particles burst outward | “When fusion fades, the balance breaks. Gravity compresses the core; some massive stars can leave a black hole.” |
| 16–24s | `horizon_boundary` | Light paths draw around a dark center; one ray stops at the labeled horizon | “Around it lies the event horizon, a boundary of no return. Outside, light can bend; inside, it cannot escape.” |

The motion is schematic, **not** a physical stellar-collapse or ray-tracing simulation. Narration above is a writing reference only: it must be recorded, paced, and checked against the images before use. Music, SFX, captions, and transitions beyond short fades are also absent. Do not judge audio sync from this silent file.

## Re-render / edit

From `AutoVideoBot/render` on a machine with Node.js and npm:

```bash
npm ci
npm run typecheck
npm run render:pilot
```

If Remotion cannot download its browser, install Chromium/Chrome separately and run `npm run render:pilot -- --browser-executable /path/to/chrome`. The MP4 is written to `../pilot/vector-pilot.mp4`. On Windows, keep the repository on **F:** to keep `node_modules` and the resulting video off **C:** as much as possible; Chromium/Chrome installers may still put their own files on C:. Rendering uses local CPU/browser resources and **does not contact Vast.ai**.

The 3 reusable shot IDs live in `render/shots.json`; source art and animation live in `render/src/shots/VectorPilot.tsx`. The `Scene` composition accepts these shot IDs for individual pipeline scenes, while the `VectorPilot` composition is the fixed three-shot demonstration.

## Second test: narration, scene timing, and word-highlight captions

**Watch:** `narrated-pilot.mp4` (42.62s, H.264/AAC). This is a separate voice-driven test, not a modification of the original 24-second silent pilot or the existing 62-scene project. The three newly recorded spoken clips live in `audio/`, and their transcripts are in `build_narrated_test.py`. Scene boundaries follow the **actual decoded audio durations** with 0.5s of pre-roll and at least 0.5s of tail room. The Remotion `NarratedPilot` composition adapts the three vector motions to those durations, then crossfades into the WebGL `SpaceShader` warp on the estimated onset of “Outside” in the third scene; FFmpeg mixes the clips and burns per-word karaoke captions. The shader's internal canvas is 35% resolution and upscaled for this CPU-only SwiftShader test (the normal shader default is unchanged). Also provided: `narrated-pilot.srt` and `narrated-pilot.ass`.

**Timing caveat:** the selected recorded voice did **not** provide word-boundary metadata. Microsoft Edge TTS, which does, was unreachable from this sandbox. Instead `pocketsphinx` forced-aligns the known transcript to the decoded audio. The 81 word times in `render/src/narrated-timing.json` are **estimated**, not verified ground-truth or guaranteed frame-exact speech onsets. The video demonstrates the caption and audio assembly paths, not proof of exact TTS word synchronization; a provider returning timestamps or human QC is needed before claiming that. No music or sound design was added. These graphics remain schematic.

Rebuild from the `AutoVideoBot` root, after `npm ci` in `render` and Python dependencies from `requirements.txt`:

```bash
python -m pip install pocketsphinx
python pilot/build_narrated_test.py --browser-executable /path/to/chrome
```

Omit `--browser-executable` if Remotion can provision its own browser. `python pilot/build_narrated_test.py --metadata-only` only regenerates word alignment and subtitles. `pocketsphinx` is optional for the main bot; it is required for this separate local test. Keep the repository and test files on F: if C: space is tight. No Vast.ai, DeepSeek, or paid cloud rendering is invoked by this command.

I also ran a **separate** local SwiftShader still-frame check for the `Scene` composition with `starfield_warp` / `SpaceShader.tsx`: frames 16 and 32 both rendered and differed. In the narrated test itself, the shader transition is scheduled at the estimated word onset recorded in `shader_start_frame`; this checks frame scheduling, not physical accuracy or exact phonetic alignment. It does **not** establish that a remote GPU instance is reachable. The next gate is a timestamp-providing TTS or human-reviewed alignment, feedback on this audio/visual cut, and only then deciding whether a paid remote test is warranted.
