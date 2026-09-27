"""Opt-in Vast.ai SSH batch renderer for Remotion scenes.

Reuses the image provider's Vast provisioning API, but never starts an image
server. Uploads allowlisted render source only; owned instances are destroyed
in finally even on render or transfer failure.
"""
from __future__ import annotations

import copy
import json
import re
import secrets
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Callable

from ..config import Config
from ..paths import ROOT
from ..utils import info
from .image_vast import VastProvider
from .render_remotion import RemotionRenderer

REMOTE = "/workspace/blackhole_doc"
SOURCE_FILES = ("package.json", "package-lock.json", "tsconfig.json", "shots.json")

class VastRenderProvisioner(VastProvider):
    """Create a direct SSH container without opening image-server ports."""

    def _create_instance(self, offer):
        settings = self.setting("image.vast.search", {}) or {}
        body = {
            "bundle_id": int(offer["id"]),
            "disk": float(settings.get("disk_gb", 35)),
            "image": str(settings.get("image", "node:22-bookworm")),
            "runtype": "ssh_direct",
            "label": "autovideobot-remotion",
        }
        if settings.get("region"):
            body["region"] = str(settings["region"])
        info("renting SSH GPU instance (billing starts now) ...")
        data = self._api("PUT", f"/asks/{int(offer['id'])}/", body, timeout=120)
        iid = str(data.get("new_contract") or data.get("id") or "")
        if not iid:
            raise RuntimeError(f"Vast did not return a new instance id: {str(data)[:180]}")
        self._instance_id = iid
        self._owns_instance = True
        info(f"rented instance {iid}; waiting for SSH")
        return {"id": iid}


class VastRemotionRenderer(RemotionRenderer):
    def __init__(self, cfg, project):
        super().__init__(cfg, project)
        data = copy.deepcopy(cfg.data)
        vast_settings = copy.deepcopy(cfg.section("visual.vast"))
        if not vast_settings:
            raise ValueError("Configure visual.vast (see docs/16-DOCUMENTARY-PIPELINE.md)")
        # VastProvider expects image.vast settings. Reuse only API/SSH lifecycle.
        vast_settings["destroy_after_use"] = True
        data.setdefault("image", {})["vast"] = vast_settings
        self.vast = VastRenderProvisioner(Config(data), project)
        self.known_hosts = project.tmp_dir / "vast_render_known_hosts"

    def healthcheck(self):
        if not shutil.which("ssh") or not shutil.which("scp"):
            raise RuntimeError("Vast rendering needs OpenSSH ssh and scp on PATH")
        if not self.cfg.env("visual.vast.api_key_env"):
            raise RuntimeError("Set VAST_API_KEY in .env for visual.vast rendering")
        mode = self.cfg.get("visual.vast.mode", "existing")
        if mode not in ("existing", "search"):
            raise ValueError("visual.vast.mode must be existing or search")
        if mode == "existing" and not self.cfg.get("visual.vast.instance_id"):
            raise ValueError("Set visual.vast.instance_id for an existing instance")
        for name in [*SOURCE_FILES, "src/index.ts"]:
            if not (self.root / name).is_file():
                raise FileNotFoundError(f"Renderer source missing: {name}")

    def _boot(self):
        mode = self.cfg.get("visual.vast.mode", "existing")
        if mode == "existing":
            iid = str(self.cfg.get("visual.vast.instance_id"))
            self.vast._instance_id = iid
            inst = self.vast._instance(iid)
            if str(inst.get("actual_status")) != "running":
                raise RuntimeError(f"Vast instance {iid} is not running: {inst.get('actual_status')}")
            info(f"reusing Vast instance {iid}")
        else:
            offer = self.vast._search_offer()
            self.vast._create_instance(offer)
        self.vast._ssh = self.vast._wait_for_ssh()
        endpoint = self.vast._ssh
        host, port = str(endpoint["host"]), int(endpoint["port"])
        if not re.fullmatch(r"[a-zA-Z0-9.:-]+", host) or not 1 <= port <= 65535:
            raise ValueError("Vast returned invalid SSH endpoint")
        self._remote = f"root@{host}"
        self._port = port

    def _ssh_options(self):
        # Fresh ephemeral hosts are accepted once; changed keys are refused.
        return ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                "-o", f"UserKnownHostsFile={self.known_hosts}", "-o", "ConnectTimeout=30"]

    def _ssh(self, command: str, *, timeout=3600, check=True) -> subprocess.CompletedProcess:
        proc = subprocess.run(["ssh", *self._ssh_options(), "-p", str(self._port),
                               self._remote, command], capture_output=True, text=True, timeout=timeout)
        if check and proc.returncode:
            raise RuntimeError(f"Remote renderer failed ({proc.returncode}): {proc.stderr[-2500:]} {proc.stdout[-1500:]}")
        return proc

    def _scp(self, src: str, dst: str, *, timeout=900):
        proc = subprocess.run(["scp", *self._ssh_options(), "-P", str(self._port),
                               src, dst], capture_output=True, text=True, timeout=timeout)
        if proc.returncode:
            raise RuntimeError(f"SCP failed: {proc.stderr[-1500:]}")

    def _archive(self, path: Path):
        """Allowlisted files only: no .env, credentials, node_modules or media."""
        with tarfile.open(path, 'w:gz') as tar:
            for name in SOURCE_FILES:
                tar.add(self.root / name, arcname=name)
            for source in sorted((self.root / "src").rglob("*")):
                if source.is_file() and not source.is_symlink():
                    tar.add(source, arcname=str(source.relative_to(self.root)))

    def render_many(self, jobs: list[tuple[dict, Path]], *, width: int, height: int,
                    fps: int, completed: Callable[[dict, Path], None]):
        """Run a bounded batch, download and mark each successful scene."""
        if not jobs:
            return
        self.healthcheck()
        archive = (self.project.tmp_dir / "render_source.tar.gz").resolve()
        jobfile = (self.project.tmp_dir / "render_jobs.json").resolve()
        self._archive(archive)
        workers = max(1, min(4, int(self.cfg.get("visual.vast.parallel_scenes", 2))))
        jobfile.write_text(json.dumps({"workers": workers,
            "gl": str(self.cfg.get("visual.vast.gl", "angle-egl")),
            "chrome_mode": "chrome-for-testing",
            "require_hardware_webgl": bool(self.cfg.get("visual.vast.require_hardware_webgl", True)),
            "jobs": [
            {"id": scene["id"], "crf": int(self.cfg.get("video.crf", 20)),
             "props": {"scene": {k: scene.get(k) for k in
                       ("shot", "params", "title", "text_overlays", "duration")},
                       "width": width, "height": height, "fps": fps}}
            for scene, _ in jobs]}, ensure_ascii=False), encoding='utf-8')
        remote_dir = f"{REMOTE}/{secrets.token_hex(8)}"
        booted = False
        try:
            self._boot()
            booted = True
            self._ssh(f"mkdir -p {remote_dir}", timeout=120)
            self._scp(str(archive), f"{self._remote}:{remote_dir}/source.tar.gz")
            self._scp(str(jobfile), f"{self._remote}:{remote_dir}/jobs.json")
            self._scp(str(ROOT / 'deploy/vast/render_worker.cjs'), f"{self._remote}:{remote_dir}/worker.cjs")
            # Fixed command; scene text is only passed as JSON, never as shell.
            bootstrap = (f"cd {remote_dir} && tar -xzf source.tar.gz && "
                         "(command -v chromium >/dev/null || "
                         "(apt-get update -qq && DEBIAN_FRONTEND=noninteractive "
                         "apt-get install -y chromium ca-certificates)) && "
                         "npm ci --no-audit --no-fund && node worker.cjs jobs.json")
            proc = self._ssh(bootstrap, timeout=int(self.cfg.get("visual.vast.render_timeout", 7200)), check=False)
            # Fetch status even on partial failure; cache successful downloads.
            status_text = self._ssh(f"cat {remote_dir}/status.json", timeout=60, check=False)
            statuses = json.loads(status_text.stdout) if status_text.returncode == 0 else {}
            failures = []
            for scene, out in jobs:
                result = statuses.get(scene["id"], {})
                if not result.get("ok"):
                    failures.append(f"{scene['id']}: {result.get('error', 'no result')}")
                    continue
                temp = out.with_name(out.stem + '.downloading.mp4').resolve()
                try:
                    self._scp(f"{self._remote}:{remote_dir}/clips/{scene['id']}.mp4", str(temp))
                    if not temp.exists() or temp.stat().st_size != result.get("bytes"):
                        raise RuntimeError(f"downloaded {scene['id']} has wrong size")
                    temp.replace(out)
                    completed(scene, out)
                except Exception as exc:
                    failures.append(f"{scene['id']}: {exc}")
                finally:
                    temp.unlink(missing_ok=True)
            if proc.returncode or failures:
                if proc.returncode and not statuses:
                    failures.insert(0, f"remote setup: {(proc.stderr or proc.stdout)[-1800:]}")
                raise RuntimeError("Vast scene render failed: " + "; ".join(failures or [proc.stderr[-1800:]]))
        finally:
            try:
                if booted:
                    try:
                        self._ssh(f"rm -rf {remote_dir}", timeout=120, check=False)
                    except Exception:
                        pass  # teardown is more important than temporary cleanup
            finally:
                try:
                    self.vast.teardown()
                finally:
                    archive.unlink(missing_ok=True)
                    jobfile.unlink(missing_ok=True)
