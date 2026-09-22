"""
bot/providers/image_kaggle.py
=============================
Kaggle's free GPU (30 hours/week) - the "batch" way of working.

WHY THIS PROVIDER IS DIFFERENT FROM ALL THE OTHERS
--------------------------------------------------
Kaggle does not let a program start a notebook on your behalf (no public API
for that), and notebooks cannot host a website while you wait. So the workflow
is turned around:

     1. the bot WRITES a ready-to-run notebook with YOUR prompts baked in
        -> workspace/kaggle_out/kernel.ipynb
     2. you upload that one file to Kaggle, switch the GPU on, press Run All
        (~3 minutes of your time, once per video)
     3. the notebook saves every image into output/images.zip
     4. you download that zip and drop it into  workspace/kaggle_out/
     5. you run the bot again - it finds the zip, unpacks the images and
        continues exactly where it left off

That is why the provider prints instructions instead of silently generating.

WHY ANYONE PUTS UP WITH THAT
----------------------------
30 free GPU hours per week is the most generous free GPU offer available, and
it resets every week. For a documentary channel that is a LOT of free images.

TIP: because the bot re-uses the cache, you can render images for several
videos, then upload all the zips at once.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from ..paths import ROOT
from ..registry import register
from ..utils import debug, ensure_dir, info, warn
from .base import ImageProvider


@register("image", "kaggle",
          cost="free (30 GPU hours per week)",
          needs_key=False, quality="excellent (SDXL / FLUX)",
          setup_time="10 minutes once, then ~3 minutes per video",
          doc="Writes a notebook with your prompts baked in. You run it on "
              "Kaggle's free GPU and drop the results zip into "
              "workspace/kaggle_out/ - the bot then imports the images.")
class KaggleProvider(ImageProvider):
    """Prepares a notebook, then imports the images you produced with it."""

    supports_batch = True
    supports_parallel = False

    def __init__(self, cfg, project=None):
        super().__init__(cfg, project)
        self._pending = False

    # ------------------------------------------------------------------
    def _out_dir(self) -> Path:
        d = str(self.setting("image.kaggle.output_dir", "workspace/kaggle_out"))
        return ensure_dir(ROOT / d)

    def _template(self) -> Path:
        t = ROOT / str(self.setting("image.kaggle.notebook_template",
                                    "deploy/kaggle/kaggle_batch_template.ipynb"))
        return t

    # ------------------------------------------------------------------
    def healthcheck(self) -> tuple[bool, str]:
        tpl = self._template()
        if not tpl.exists():
            return False, (f"the Kaggle notebook template is missing: {tpl}\n"
                           f"  Re-download the project, or point config.yaml ->\n"
                           f"  image.kaggle.notebook_template at your own template.")
        zips = sorted(self._out_dir().glob("*.zip"))
        if zips:
            return True, (f"Kaggle mode ready - found {len(zips)} result file(s) "
                          f"in {self._out_dir()} (they will be imported)")
        return True, ("Kaggle mode ready - a notebook will be written for you to "
                      "run on Kaggle (details in docs/07-COLAB-KAGGLE.md)")

    # ==================================================================
    # 1. write the notebook with the prompts baked in
    # ==================================================================
    def prepare_batch(self, jobs: list[dict[str, Any]]) -> Path:
        """
        Create workspace/kaggle_out/kernel.ipynb containing the jobs.

        The template has a marker cell  "# >>>JOBS<<<"  which we replace with
        real, self-contained Python: a JOBS list plus the model settings. This
        keeps the notebook readable and editable by a human afterwards.
        """
        tpl = self._template()
        out_dir = self._out_dir()
        out_nb = out_dir / "kernel.ipynb"

        try:
            nb = json.loads(tpl.read_text(encoding="utf-8"))
        except Exception as e:
            raise RuntimeError(f"could not read the Kaggle template ({e}). "
                               f"File: {tpl}")

        model = str(self.setting("image.kaggle.model", "stabilityai/stable-diffusion-xl-base-1.0"))
        prefix = str(self.setting("image.kaggle.filename_prefix", "s"))

        job_list = []
        for j in jobs:
            job_list.append({
                "id": str(j.get("scene_id")),
                "prompt": self.build_prompt(str(j.get("prompt") or "")),
                "negative_prompt": str(j.get("negative_prompt") or ""),
                "width": int(j.get("width") or 1024),
                "height": int(j.get("height") or 1024),
                "steps": int(j.get("steps") or 30),
                "guidance_scale": float(j.get("cfg_scale") or 7.0),
                "seed": j.get("seed"),
            })

        code = (
            "# >>>JOBS<<<  (generated by AutoVideoBot - do not edit)\n"
            f"MODEL_ID = {model!r}\n"
            f"FILENAME_PREFIX = {prefix!r}\n"
            "JOBS = " + json.dumps(job_list, indent=2, ensure_ascii=False) + "\n"
        )

        # The template has a CODE cell containing "# >>>JOBS<<<"
        # (markdown cells may mention the marker in their text - ignore them)
        replaced = False
        for cell in nb.get("cells", []):
            if cell.get("cell_type") != "code":
                continue
            src = "".join(cell.get("source", []))
            if "# >>>JOBS<<<" in src:
                cell["source"] = code.splitlines(keepends=True)
                replaced = True
                break
        if not replaced:
            warn("the template has no '# >>>JOBS<<<' code cell - appending one")
            nb.setdefault("cells", []).append({
                "cell_type": "code", "metadata": {}, "execution_count": None,
                "outputs": [], "source": code.splitlines(keepends=True),
            })

        # The notebook prints a summary the user can sanity-check
        out_nb.write_text(json.dumps(nb, indent=1, ensure_ascii=False), encoding="utf-8")
        self._pending = True
        return out_nb

    # ==================================================================
    # 2. import the images the user produced
    # ==================================================================
    def _import_zips(self, wanted: dict[str, Path]) -> dict[str, Path]:
        """Unpack every zip in the output folder and match files to scenes."""
        found: dict[str, Path] = {}
        out_dir = self._out_dir()
        for zpath in sorted(out_dir.glob("*.zip")):
            try:
                with zipfile.ZipFile(zpath) as z:
                    names = z.namelist()
                    debug(f"kaggle: {zpath.name} contains {len(names)} file(s)")
                    z.extractall(out_dir)
            except Exception as e:
                warn(f"could not open {zpath.name}: {e}")
                continue

        # Kaggle downloads often land in a subfolder like output/images/
        images = [p for p in out_dir.rglob("*")
                  if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and p.is_file()]
        debug(f"kaggle: found {len(images)} image file(s) in {out_dir}")

        for sid, target in wanted.items():
            # the notebook names files "<prefix><id>.<ext>"
            for img in images:
                stem = img.stem.replace("_", "")
                if stem == sid or stem.endswith(sid) or sid in stem:
                    try:
                        shutil.copy2(img, target)
                        found[sid] = target
                    except Exception as e:
                        warn(f"could not copy {img.name}: {e}")
                    break
        return found

    # ==================================================================
    # 3. the pipeline entry point
    # ==================================================================
    def generate_many(self, jobs: list[dict[str, Any]]) -> list[Path | None]:
        out_dir = self._out_dir()
        wanted = {str(j["scene_id"]): Path(j["out_path"]) for j in jobs}

        # --- A) try to import anything already downloaded -----------------
        imported = self._import_zips(wanted)
        if imported:
            info(f"  imported {len(imported)} image(s) from {out_dir}")
        missing = {sid: p for sid, p in wanted.items() if not p.exists()}

        results: list[Path | None] = []
        if missing:
            # --- B) no results yet: write the notebook and explain ---------
            nb = self.prepare_batch([j for j in jobs
                                     if str(j["scene_id"]) in missing])
            self._print_instructions(nb, len(missing))

        for job in jobs:
            p = Path(job["out_path"])
            results.append(p if p.exists() else None)
        return results

    def generate(self, prompt: str, out_path: Path, **kwargs: Any) -> Path | None:
        job = {"prompt": prompt, "out_path": out_path, **kwargs,
               "scene_id": kwargs.get("scene_id") or "single"}
        res = self.generate_many([job])
        return res[0] if res else None

    # ------------------------------------------------------------------
    def _print_instructions(self, notebook: Path, count: int) -> None:
        try:
            rel = notebook.relative_to(ROOT)
        except ValueError:
            rel = notebook
        print()
        print("  " + "-" * 72)
        print(f"  KAGGLE MODE: a notebook with your {count} prompt(s) is ready")
        print("  " + "-" * 72)
        print(f"   1. open  https://www.kaggle.com/code  ->  'New Notebook'")
        print(f"   2. File -> Import Notebook  ->  upload:  {rel}")
        print(f"   3. in the right-hand panel:")
        print(f"        Accelerator : GPU T4 x2")
        print(f"        Internet    : ON   (it downloads the model once)")
        print(f"   4. press 'Run All'  (first run ~5-10 minutes, mostly downloading)")
        print(f"   5. when it finishes, download the output file  images.zip")
        print(f"   6. move that zip into:  {self._out_dir()}")
        print(f"   7. run the SAME bot command again - it picks up where it stopped")
        print()
