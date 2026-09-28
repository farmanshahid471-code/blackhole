# Pipeline review after the narrated pilot

This is an audit of the **local test**, not certification of a ten-minute production or a copy of any reference video's artwork.

| Item in the proposed checklist | Verified state | Next gate |
| --- | --- | --- |
| 30–45-second narration | A locked 42.625-second, three-scene spoken test and its transcript exist in `pilot/audio/`, `pilot/build_narrated_test.py`, and `pilot/narrated-pilot.mp4`. The recording was made with the selected speech voice, **not** `bot/providers/tts_edge.py`. | Test the configured Edge provider on a machine that can reach its service, retaining the returned word boundaries; keep the current recording if preferred for style. |
| Voice-driven shot scheduling | `NarratedPilot` uses decoded audio lengths for 24-fps scene windows, with a 0.5-second pre-roll. The shader fade begins on the frame nearest the estimated onset of “Outside” (~37.083s). | Listen to the cut and hand-check whether the diagram-to-shader switch supports the sentence. |
| Word-level subtitles | 81 words were forced-aligned to the recorded speech; FFmpeg burns timed ASS karaoke. Captions do not overlap; SRT is also available. | **Not certified exact:** Pocketsphinx timings are estimates, and frame/centisecond rounding and encoding add uncertainty. Compare captions to the voice by ear, or use actual provider timing events and review the final MP4. |
| `SpaceShader.tsx` rendering | Two distinct SwiftShader still frames rendered; the 42.625-second narrated MP4 also renders a WebGL warp for the final ~5.5 seconds. The preview's internal shader canvas is scaled to 35% to make local CPU rendering manageable. | This is not a GPU performance benchmark, ray-tracing simulation, or remote Vast connectivity test. |
| Visual style | Original SVG vector shots are exposed as three `Scene` shot IDs; the fixed pilot compositions are separate. | Request human review of scientific clarity and timing before adding new shots or a longer script. |

## Corrections to the proposed architecture description

- `bot/audio.py` selects/prepares **background music**. TTS lives in `bot/providers/tts_edge.py` and `tts_others.py`; `bot/pipeline.py` invokes them. Piper is optional and returns no word-boundary data here.
- `prompts/image_polish.txt` currently asks for a **photorealistic still frame**, not a flat vector illustration. `bot/script.py` can use it as an image-prompt fallback; the SVG pilot does not use that prompt for its artwork. Do not silently replace it and change image-mode results in the existing 62-scene project. The pilot's SVG art is code in `render/src/shots/VectorPilot.tsx`.
- `examples/documentary_scene_graph.json` is an example contract, not evidence that an LLM will always generate valid or scientifically accurate shots. The shot library and timing checks catch some structural errors, not physics mistakes.
- `tests/test_timing_safety.py` protects against clipping fitted speech; it does **not** measure phonetic word-boundary accuracy in rendered audio. Subtitle timing fallbacks may be estimated. Documentation has been corrected to avoid promising perfect synchronization.
- The npm scripts are `render:demo`, `render:pilot`, `compositions`, and `typecheck`; there is no `npm run start`. `render/src/shots/Graphics.tsx` and `bot/providers/render_remotion.py` are the actual paths. SVG scales cleanly, but WebGL is rasterized and browser/render/remote-GPU time is not free.
- [`stefanwittwer/remotion-animated`](https://github.com/stefanwittwer/remotion-animated) exists and has an MIT license. The current pilot already uses Remotion's `interpolate` and frame-based motion. Adding a third-party animation package without a specific visual need would not fix word timing, storytelling, or the shader's CPU cost; try built-in `spring` on a selected shot first if animation polish is requested.

**Decision point:** keep the original image-mode project unchanged and do not start a paid Vast instance. First review `narrated-pilot.mp4` for voice/caption and diagram-to-shader timing. Then test a timestamp-producing TTS provider on a reachable machine, verify one short end-to-end output, and only after that consider a longer script or remote rendering.
