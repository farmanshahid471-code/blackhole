"""CLI bridge: JSON props, no shell interpolation, per-scene deterministic output."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from ..paths import ROOT
from ..utils import ensure_dir


class RemotionRenderer:
    def __init__(self, cfg, project):
        self.cfg, self.project = cfg, project
        self.root = ROOT / "render"

    def healthcheck(self):
        if not shutil.which("node"):
            raise RuntimeError("Node.js is required for Remotion")
        if not (self.root / "node_modules" / ".bin" / "remotion").exists():
            raise RuntimeError("Install renderer first: cd render && npm ci")

    def source_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for path in sorted((self.root / "src").rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(self.root)).encode())
                digest.update(path.read_bytes())
        digest.update((self.root / "package-lock.json").read_bytes() if (self.root / "package-lock.json").exists() else b"")
        return digest.hexdigest()

    def render(self, scene: dict, out: Path, *, width: int, height: int, fps: int):
        out = Path(out).resolve()
        ensure_dir(out.parent)
        props = (self.project.tmp_dir / f"{scene['id']}_props.json").resolve()
        props.write_text(json.dumps({"scene": {k: scene.get(k) for k in ("shot", "params", "title", "text_overlays", "duration")},
                                     "width": width, "height": height, "fps": fps}), encoding="utf-8")
        temp = out.with_name(out.stem + "_rendering.mp4")
        cmd = [str(self.root / "node_modules" / ".bin" / "remotion"), "render", "src/index.ts", "Scene", str(temp),
               "--props", str(props), "--codec", "h264", "--crf", str(self.cfg.get("video.crf", 20)),
               "--log", "error"]
        browser = str(self.cfg.get("visual.browser_executable", "") or "").strip()
        if browser:
            if not Path(browser).is_file():
                raise FileNotFoundError(f"visual.browser_executable does not exist: {browser}")
            cmd += ["--browser-executable", browser]
        gl = str(self.cfg.get("visual.local_gl", "") or "").strip()
        if gl:
            if gl not in ("angle", "egl", "swiftshader", "swangle", "vulkan", "angle-egl"):
                raise ValueError(f"unsupported visual.local_gl: {gl}")
            cmd += ["--gl", gl]
        try:
            subprocess.run(cmd, cwd=self.root, check=True, timeout=7200)
            if not temp.exists() or temp.stat().st_size == 0:
                raise RuntimeError(f"Remotion produced no clip for {scene['id']}")
            temp.replace(out)
        finally:
            temp.unlink(missing_ok=True)
            props.unlink(missing_ok=True)
