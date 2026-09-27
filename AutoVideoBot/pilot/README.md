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

The 3 reusable shot IDs live in `render/shots.json`; source art and animation live in `render/src/shots/VectorPilot.tsx`. The `Scene` composition accepts these shot IDs for individual pipeline scenes, while the `VectorPilot` composition is the fixed three-shot demonstration. For a complete production, first approve/revise the visual direction, then record narration and set timing from the real voice track, design audio and transitions, test a short end-to-end render, and **only then** decide whether to authorize a paid remote render.
