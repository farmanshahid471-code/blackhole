"""Post-export checks. A report is evidence, not a guarantee of artistic quality."""
from __future__ import annotations

import re
from pathlib import Path

from .utils import run_cmd


def inspect(asm, video: Path, voice: Path, expected: float, silence_min: float = 2.5,
            target_lufs: float = -14.0) -> dict:
    actual = asm.probe_duration(video)
    voice_duration = asm.probe_duration(voice)
    loudness = asm.measure_loudness(video)
    issues: list[str] = []
    if abs(actual - expected) > .5:
        issues.append(f"Video duration differs from scene graph by {actual - expected:+.2f}s")
    if abs(actual - voice_duration) > .5:
        issues.append(f"Narration duration differs from video by {voice_duration - actual:+.2f}s")
    if loudness.get("lufs") is None:
        issues.append("Could not measure integrated loudness")
    elif abs(loudness["lufs"] - target_lufs) > 2:
        issues.append(f"Integrated loudness is {loudness['lufs']:.1f} LUFS (target {target_lufs:g} ±2)")
    proc = run_cmd([asm.ffmpeg_bin, "-hide_banner", "-i", str(video),
                    "-af", f"silencedetect=noise=-45dB:d={max(0.1, silence_min):.2f}",
                    "-f", "null", "-"], capture=True, check=False, timeout=900, quiet=True)
    if proc.returncode:
        issues.append("Silence detection could not complete")
    silence = [float(x) for x in re.findall(r"silence_duration:\s*([\d.]+)", proc.stderr or "")]
    if silence:
        issues.append(f"Detected {len(silence)} audio gap(s) >= {silence_min:g}s; check if intentional")
    return {"duration_seconds": round(actual, 3), "scene_graph_seconds": expected,
            "narration_seconds": round(voice_duration, 3), "loudness": loudness,
            "silence_durations_seconds": silence, "warnings": issues}
