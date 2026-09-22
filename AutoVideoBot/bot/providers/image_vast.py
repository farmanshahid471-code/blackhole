"""
bot/providers/image_vast.py
===========================
Rent a cloud GPU from Vast.ai automatically, use it, then destroy it.

THE MONEY STORY (read this, it is the whole point)
-------------------------------------------------
Vast.ai rents GPUs by the SECOND. An RTX 4090 costs roughly $0.35-$0.50/hour,
which sounds like a lot until you notice that a 40-scene 1080p video takes
about 4 minutes of GPU time:

        0.07 hours  x  $0.40  =  $0.03 per video

...and this provider destroys the instance as soon as the last image lands, so
you never pay for idle minutes. That is why `destroy_after_use: true` exists.

WHAT THIS FILE DOES, IN ORDER
-----------------------------
  1. searches Vast.ai for a cheap machine matching your requirements
  2. creates the instance
  3. waits for it to boot and for SSH to answer
  4. uploads deploy/vast/server/ (the image server)
  5. starts it, and opens a tunnel from your PC to the GPU
  6. renders every scene through the same protocol Colab uses
  7. DESTROYS the instance (even if rendering failed - see teardown)

ROBUSTNESS RULES THIS FILE LIVES BY
-----------------------------------
  * if anything fails, the instance is destroyed - a stuck instance is a
    silently-billing instance, the worst possible outcome
  * every stage prints what it is doing and how long it will take
  * if the instance is already running (mode: existing) it is reused, never
    re-created

Two ways to use it (config.yaml -> image.vast.mode):
    "search"   -> fully automatic (recommended, default)
    "existing" -> you made the instance by hand; put its id in instance_id.
                  Start it yourself before running the bot, and the bot will
                  NOT destroy it.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from ..paths import ROOT
from ..registry import register
from ..utils import debug, die, info, run_cmd, which, warn
from . import _wire
from .base import ImageProvider

API_BASE = "https://console.vast.ai/api/v0"


@register("image", "vast",
          cost="~$0.03-$0.20 per video (rented by the second)",
          needs_key=True, quality="excellent (SDXL / FLUX)",
          setup_time="10 minutes (mostly waiting for the machine to boot)",
          doc="Finds, rents, boots, uses and destroys a Vast.ai GPU for you. "
              "You pay only for the minutes used, then it is gone.")
class VastProvider(ImageProvider):
    """Full lifecycle management of a rented GPU."""

    supports_batch = True
    supports_parallel = False

    def __init__(self, cfg, project=None):
        super().__init__(cfg, project)
        self._instance_id: str | None = None
        self._ssh: dict[str, Any] | None = None
        self._tunnel: subprocess.Popen | None = None
        self._local_port: int = 0
        self._owns_instance = False

    # ==================================================================
    # API plumbing
    # ==================================================================
    def _key(self) -> str:
        key = self.secret("image.vast.api_key_env") or self.setting("image.vast.api_key")
        if not key:
            die(
                "Vast.ai needs an API key.\n"
                "  1. https://cloud.vast.ai/account/  ->  Account  ->  API Key\n"
                "  2. .env ->  VAST_API_KEY=...\n"
                "  Free alternatives:  image.provider: colab   (Google's free GPU)\n"
                "                      image.provider: pollinations  (no GPU at all)"
            )
        return str(key)

    def _api(self, method: str, path: str, body: dict | None = None,
             timeout: int = 60) -> Any:
        import requests
        url = f"{API_BASE}{path}"
        headers = {"Authorization": f"Bearer {self._key()}", "Accept": "application/json"}
        debug(f"vast: {method} {url}")
        if method == "GET":
            r = requests.get(url, headers=headers, timeout=timeout)
        elif method == "POST":
            r = requests.post(url, headers=headers, json=body or {}, timeout=timeout)
        elif method == "PUT":
            r = requests.put(url, headers=headers, json=body or {}, timeout=timeout)
        else:
            r = requests.delete(url, headers=headers, timeout=timeout)
        if r.status_code >= 400:
            raise RuntimeError(
                f"Vast.ai API {method} {path} failed: HTTP {r.status_code} {r.text[:300]}"
            )
        try:
            return r.json()
        except Exception:
            return {"raw": r.text}

    # ==================================================================
    # healthcheck
    # ==================================================================
    def healthcheck(self) -> tuple[bool, str]:
        try:
            key = self._key()
        except SystemExit:
            return False, "VAST_API_KEY is empty in .env"
        try:
            data = self._api("GET", "/users/current/", timeout=25)
        except Exception as e:
            return False, f"could not reach Vast.ai ({str(e)[:160]})"
        if isinstance(data, dict) and data.get("error"):
            return False, f"Vast.ai rejected the key: {str(data['error'])[:160]}"
        credit = None
        try:
            credit = data.get("credit") if isinstance(data, dict) else None
        except Exception:
            pass
        mode = str(self.setting("image.vast.mode", "search"))
        extra = f", credit ${float(credit):.2f}" if credit is not None else ""
        if mode == "existing":
            iid = self.setting("image.vast.instance_id")
            if not iid:
                return False, ("mode is 'existing' but image.vast.instance_id is empty.\n"
                               "  Put your Vast.ai instance id there, or switch mode: search")
            return True, f"Vast.ai ready (will reuse instance {iid}{extra})"
        return True, f"Vast.ai ready (will rent + destroy automatically{extra})"

    # ==================================================================
    # 1-2. find and create / reuse the instance
    # ==================================================================
    def _search_offer(self) -> dict[str, Any]:
        s = self.setting("image.vast.search", {}) or {}
        gpu = str(s.get("gpu_type", "RTX 4090"))
        min_vram = float(s.get("min_vram_gb", 16))
        max_price = float(s.get("max_price_per_hour", 0.50))
        disk = int(s.get("disk_gb", 32))

        query = {
            "gpu_name": {"eq": gpu},
            "gpu_ram": {"gte": min_vram * 1024},        # Vast reports VRAM in MB
            "dph_total": {"lte": max_price},
            "disk_space": {"gte": disk},
            "num_gpus": {"eq": 1},
            "rentable": {"eq": True},
            "verified": {"eq": True},
            "order": [["dph_total", "asc"]],
            "type": "on-demand",
        }
        info(f"  searching Vast.ai for {gpu} (>= {min_vram:.0f} GB VRAM, "
             f"<= ${max_price:.2f}/h) ...")
        data = self._api("GET", "/bundles/?" + json.dumps({"q": query}), timeout=90)
        offers = data.get("offers") if isinstance(data, dict) else None
        if not offers:
            raise RuntimeError(
                f"no Vast.ai machine matched: {gpu}, >= {min_vram:.0f} GB VRAM, "
                f"<= ${max_price:.2f}/hour.\n"
                f"  Easiest fixes (config.yaml -> image.vast.search):\n"
                f"   * max_price_per_hour: 0.80      (pay a bit more)\n"
                f"   * gpu_type: \"RTX 3090\"           (older but plentiful)\n"
                f"   * min_vram_gb: 12               (SDXL needs ~10 GB)\n"
                f"  Or use the free route:  image.provider: colab"
            )
        offers.sort(key=lambda o: float(o.get("dph_total", 9e9)))
        best = offers[0]
        info(f"  cheapest match: {best.get('gpu_name')} "
             f"${float(best.get('dph_total', 0)):.3f}/h on "
             f"{str(best.get('geolocation') or 'somewhere')[:40]}")
        return best

    def _create_instance(self, offer: dict[str, Any]) -> dict[str, Any]:
        s = self.setting("image.vast.search", {}) or {}
        v = self.setting("image.vast", {}) or {}
        body = {
            "bundle_id": int(offer["id"]),
            "disk": float(s.get("disk_gb", 32)),
            "image": str(s.get("image", "pytorch/pytorch:2.4.0-cuda12.4-cudnn9-runtime")),
            "runtype": "ssh",
            "label": "autovideobot",
            # The server needs a port reachable from your PC; Vast maps it for us.
            "env": {"-p 7860:7860": "1"},
        }
        region = str(s.get("region") or "")
        if region:
            body["region"] = region
        info("  creating the instance (you will be billed from this second) ...")
        data = self._api("PUT", f"/asks/{int(offer['id'])}/", body, timeout=120)
        iid = str(data.get("new_contract") or data.get("id") or "")
        if not iid:
            raise RuntimeError(f"Vast.ai did not return an instance id: {str(data)[:200]}")
        info(f"  instance {iid} created - it is now BOOTING (this is the slow part)")
        self._instance_id = iid
        self._owns_instance = True
        return {"id": iid}

    def _instance(self, iid: str) -> dict[str, Any]:
        data = self._api("GET", f"/instances/{iid}/", timeout=60)
        if isinstance(data, dict) and isinstance(data.get("instances"), dict):
            return data["instances"]
        return data if isinstance(data, dict) else {}

    def _wait_for_ssh(self) -> dict[str, Any]:
        """Poll the instance until it reports an SSH host and port."""
        timeout = float(self.setting("image.vast.boot_timeout", 600))
        t0 = time.time()
        last = ""
        while time.time() - t0 < timeout:
            try:
                inst = self._instance(str(self._instance_id))
            except Exception as e:
                last = str(e)[:120]
                time.sleep(10)
                continue
            status = str(inst.get("actual_status") or inst.get("status") or "?")
            host = inst.get("ssh_host") or inst.get("public_ipaddr")
            port = inst.get("ssh_port")
            if status == "running" and host and port:
                info(f"  machine is up after {time.time() - t0:.0f}s "
                     f"({inst.get('gpu_name', 'GPU')}, {status})")
                return {
                    "host": str(host),
                    "port": int(port),
                    "user": "root",
                    "gpu": str(inst.get("gpu_name") or "GPU"),
                    "instance": inst,
                }
            debug(f"vast: status={status} host={host} port={port} {last}")
            time.sleep(10)
        raise RuntimeError(
            f"the rented machine did not become reachable within {timeout:.0f}s.\n"
            f"  It is being destroyed so you are not billed further.\n"
            f"  Try again (another machine) or raise image.vast.boot_timeout."
        )

    # ==================================================================
    # 3. get the code onto the machine
    # ==================================================================
    def _scp_base(self) -> list[str]:
        assert self._ssh
        return [
            "scp", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-P", str(self._ssh["port"]),
        ]

    def _ssh_base(self) -> list[str]:
        assert self._ssh
        return [
            "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=20", "-p", str(self._ssh["port"]),
        ]

    def _upload_server(self) -> str:
        assert self._ssh
        local = ROOT / str(self.setting("image.vast.server_dir", "deploy/vast/server"))
        if not local.exists():
            raise RuntimeError(f"the server folder is missing: {local}")
        remote = "/workspace/image_server"
        info("  uploading the image server to the GPU ...")
        run_cmd(self._ssh_base() + [f"{self._ssh['user']}@{self._ssh['host']}",
                                    f"mkdir -p {remote}"],
                capture=True, check=True, timeout=120, quiet=True)
        run_cmd(self._scp_base() + ["-r", str(local), f"{self._ssh['user']}@{self._ssh['host']}:{remote}"],
                capture=True, check=True, timeout=900, quiet=True)
        return remote

    def _start_server(self, remote_dir: str) -> int:
        """Start the server on the instance and open a local tunnel to it."""
        assert self._ssh
        cmd = str(self.setting("image.vast.server_start_cmd", "bash start_server.sh"))
        port = int(self.setting("image.vast.server_port", 7860))
        target = f"{self._ssh['user']}@{self._ssh['host']}"

        info("  starting the image server on the GPU (first run downloads "
             "the model: 3-8 minutes) ...")
        run_cmd(self._ssh_base() + [target,
                                    f"cd {remote_dir} && nohup {cmd} > server.log 2>&1 & echo started"],
                capture=True, check=True, timeout=300, quiet=True)

        # Tunnel:  local_port  ->  gpu:port
        self._local_port = self._free_port()
        info(f"  opening the tunnel  localhost:{self._local_port} -> gpu:{port} ...")
        ssh_cmd = [
            "ssh", "-N",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ServerAliveInterval=15", "-o", "ExitOnForwardFailure=yes",
            "-p", str(self._ssh["port"]),
            "-L", f"{self._local_port}:127.0.0.1:{port}",
            target,
        ]
        self._tunnel = subprocess.Popen(ssh_cmd, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, text=True)
        return self._local_port

    @staticmethod
    def _free_port() -> int:
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    def _wait_for_server(self, port: int) -> None:
        """Wait for /health to answer through the tunnel."""
        timeout = float(self.setting("image.vast.boot_timeout", 600))
        t0 = time.time()
        url = f"http://127.0.0.1:{port}"
        while time.time() - t0 < timeout:
            ok, payload = _wire.health(url, timeout=10)
            if ok:
                info(f"  server ready after {time.time() - t0:.0f}s "
                     f"({payload.get('gpu', 'GPU')}, {payload.get('model', 'model')})")
                return
            debug(f"vast: server not ready yet ({payload.get('error', '')[:80]})")
            time.sleep(8)
        raise RuntimeError(
            f"the GPU server did not answer on /health within {timeout:.0f}s.\n"
            f"  Likely causes: the model download is slow, or the server crashed.\n"
            f"  (The machine is being destroyed so the meter stops.)"
        )

    # ==================================================================
    # 4. render
    # ==================================================================
    def _ensure_ready(self) -> str:
        """Boot everything if needed and return the base URL to talk to."""
        if self._local_port:
            return f"http://127.0.0.1:{self._local_port}"

        mode = str(self.setting("image.vast.mode", "search")).lower()
        if mode == "existing":
            iid = str(self.setting("image.vast.instance_id") or "")
            if not iid:
                die("image.vast.mode is 'existing' but instance_id is empty")
            self._instance_id = iid
            self._owns_instance = False
            inst = self._instance(iid)
            if str(inst.get("actual_status")) != "running":
                die(
                    f"your Vast.ai instance {iid} is not running.\n"
                    f"  Start it at https://cloud.vast.ai/instances/ (or let the bot do\n"
                    f"  everything: set image.vast.mode: search), then run again.\n"
                    f"  Status right now: {inst.get('actual_status')}"
                )
            info(f"  reusing your existing instance {iid} "
                 f"({inst.get('gpu_name', 'GPU')})")
        else:
            offer = self._search_offer()
            self._create_instance(offer)

        self._ssh = self._wait_for_ssh()
        remote = self._upload_server()
        port = self._start_server(remote)
        self._wait_for_server(port)
        return f"http://127.0.0.1:{port}"

    # ------------------------------------------------------------------
    def generate_many(self, jobs: list[dict[str, Any]]) -> list[Path | None]:
        base = self._ensure_ready()
        payload = _wire.jobs_from(jobs, style_suffix=self.style_suffix())
        info(f"  rendering {len(payload)} image(s) on the rented GPU ...")
        t0 = time.time()
        results = _wire.send_jobs(base, payload,
                                 api_path=str(self.setting("image.vast.api_path", "/generate")),
                                 timeout=max(600, 180 * len(jobs)))
        info(f"  GPU finished {len(results)} image(s) in {time.time() - t0:.0f}s "
             f"(about ${self._estimate_cost(time.time() - t0):.3f})")

        by_id = {str(r.get("id")): r for r in results if r.get("id")}
        out: list[Path | None] = []
        for job in jobs:
            res = by_id.get(str(job.get("scene_id")))
            out.append(_wire.save_result(res, Path(job["out_path"]), self.save_image_bytes)
                       if res else None)
        return out

    def generate(self, prompt: str, out_path: Path, **kwargs: Any) -> Path | None:
        job = {"prompt": prompt, "out_path": out_path, **kwargs,
               "scene_id": kwargs.get("scene_id") or "single"}
        res = self.generate_many([job])
        return res[0] if res else None

    def _estimate_cost(self, seconds: float) -> float:
        try:
            rate = float((self.setting("image.vast.search", {}) or {})
                         .get("max_price_per_hour", 0.5))
        except Exception:
            rate = 0.5
        return seconds / 3600.0 * rate

    # ==================================================================
    # 5. cleanup - the most important method in this file
    # ==================================================================
    def teardown(self) -> None:
        """
        Stop the tunnel and DESTROY the instance.

        Called automatically when the run ends (success or crash). If it did
        not run, you would keep paying for an idle GPU - so this method never
        raises and always tries its hardest.
        """
        if self._tunnel is not None:
            try:
                self._tunnel.terminate()
            except Exception:
                pass
            self._tunnel = None

        if not self._instance_id:
            return

        if not self._owns_instance:
            info(f"  leaving your instance {self._instance_id} running "
                 f"(you started it, so you decide when to stop it)")
            return

        if not bool(self.setting("image.vast.destroy_after_use", True)):
            warn(f"  image.vast.destroy_after_use is false - instance "
                 f"{self._instance_id} is STILL RUNNING and still billing.")
            warn(f"  Destroy it at https://cloud.vast.ai/instances/ when you are done.")
            return

        try:
            info(f"  destroying instance {self._instance_id} so the meter stops ...")
            self._api("DELETE", f"/instances/{self._instance_id}/", timeout=60)
            info("  instance destroyed")
        except Exception as e:
            warn(f"  could not destroy the instance automatically: {str(e)[:200]}")
            warn(f"  DESTROY IT BY HAND: https://cloud.vast.ai/instances/  "
                 f"(instance {self._instance_id})")
        finally:
            self._instance_id = None
