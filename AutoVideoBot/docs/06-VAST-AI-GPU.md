# Vast.ai - renting a GPU that costs cents per video

## Why this provider is different

Most "cloud GPU" integrations make you manage a machine. This one does the
whole lifecycle per run:

```
search cheapest RTX 4090 under $0.50/h
   -> create instance (on-demand, ssh enabled)
   -> wait for "running"
   -> scp deploy/vast/server/ onto it
   -> run start_server.sh  (installs torch+diffusers first boot only,
                            then loads the model, then serves on :7860)
   -> ssh -L 17860:127.0.0.1:7860   (private tunnel, nothing exposed)
   -> POST /generate with ALL prompts in ONE request
   -> download every image
   -> destroy instance            <-- the meter stops here
   -> print what it cost
```

A 30-image video: ~10 min first run (model download), ~2-4 min afterwards.
At $0.35/h that is **about $0.02-0.08 per video**.

## One-time setup

1. https://cloud.vast.ai -> account -> add $5 credit (lasts months).
2. Account -> API Keys -> create -> `.env`: `VAST_API_KEY=...`
3. Install the official CLI:
   * Linux/macOS/WSL: `curl -fsSL https://vast.ai/install.sh | bash`
   * Windows: `pip install vastai`
   * then `vastai set api-key YOUR_KEY` and `vastai search offers --limit 3`
4. Make sure `ssh -V` works (Windows 10/11 and macOS have OpenSSH built in).
5. `config.yaml`:
   ```yaml
   image:
     provider: vast
     vast:
       mode: search
       destroy_after_use: true
       search:
         gpu_type: "RTX 4090"
         min_vram_gb: 24
         max_price_per_hour: 0.45
         disk_gb: 45
   ```

---

## Which GPU should I rent? (the short answer: a 24 GB card)

Image generation is **memory-bound, not compute-bound**. What decides whether
a model runs at all is VRAM; what decides how fast is a distant second. So:

| Card | VRAM | Typical price | Images/minute | Verdict |
|---|---|---|---|---|
| RTX 3090 | 24 GB | ~$0.12-0.22/h | 15-25 | **best value.** Runs SDXL and FLUX. A bit slower than a 4090 |
| RTX 4090 | 24 GB | ~$0.29-0.45/h | 25-40 | **best if a video is worth ~5 extra cents.** The default in config.yaml |
| A5000 | 24 GB | ~$0.20-0.35/h | 12-20 | datacenter card on steadier hosts; quieter about it, slower than a 3090 |
| RTX 4080 | 16 GB | ~$0.25-0.40/h | 20-30 | SDXL yes, FLUX no (or heavily quantised) |
| A100 40/80 GB | 40-80 GB | ~$0.30-1.40/h | 20-35 | pointless for stills; rent it if you also fine-tune LoRAs |
| H100 | 80 GB | $1.50+/h | 30-45 | 4-5x the price of a 4090 for ~1.3x the speed |

**Rules that matter more than the card:**

1. **24 GB = never think about it again.** SDXL needs ~10 GB, FLUX.1-dev ~20 GB.
   A 24 GB card (3090 / 4090 / A5000) runs everything this bot can ask for.
2. **A 3090 beats a 4090 for a single video.** You pay ~2.5x less per hour for
   images that take ~1.6x longer: 30 images ≈ $0.011 on a 3090 vs $0.019 on a
   4090 (and the whole video is only ~4 minutes of GPU time either way).
   Difference per finished documentary: about one cent.
3. **Anchor the price.** Vast is a marketplace: the same 4090 is listed at
   $0.14 and at $0.60 in the same minute. Sort by price, but read the host's
   **reliability** and **network** columns - a $0.14 host with 20 Mbit/s will
   spend longer downloading the 7-30 GB model than rendering your video, and a
   host with 0.4 reliability may disappear mid-render (the bot then restarts
   the remaining images elsewhere, but you paid for the dead minutes).
   That is exactly why the search now gates on quality before price:
   ```yaml
   min_reliability: 0.95
   min_inet_down_mbps: 200
   min_cuda: 12.0
   ```
4. **On-demand, not spot.** The bot already asks for `type: on-demand`.
   Spot/interruptible machines are ~30 % cheaper and can be reclaimed in the
   middle of a render.
5. **Disk: 45 GB.** The default is enough for SDXL (~15 GB) plus the torch
   stack; FLUX needs more (~30 GB of weights) - if you set `AVB_MODEL` to a
   FLUX checkpoint, use 60 GB. Disk is billed separately and cheaply.
6. **Warm machines save the most money.** The model download (10-15 min on a
   fresh instance) is the single biggest cost item - often more than the
   rendering. With `mode: existing` and a kept instance, the second and later
   videos skip it entirely.
7. **Region:** leave it empty. If you are in Pakistan/India, hosts in
   Singapore, UAE or Europe usually give you the best upload/download from your
   side; `region: ""` lets the price decide.

## Using an instance you already created

```yaml
image.vast.mode: existing
image.vast.instance_id: 12345678
```
The bot starts it if stopped, uses it, and only *stops* (never destroys) it
at the end.

## What runs on the GPU

`deploy/vast/server/` is uploaded as-is:

* `image_server.py` - FastAPI app. `/health` and `/generate` (batch).
  Picks its model by VRAM: >=20 GB -> FLUX.1-schnell, >=10 GB -> SDXL,
  else SD1.5. Override with `AVB_MODEL` env on the instance.
* `start_server.sh` - idempotent installer + launcher + health waiter.

Because images are generated in ONE batch request, the model loads once per
video, not once per image.

## Money safety (read once, sleep forever)

* `destroy_after_use: true` is the default and the important line.
* If the bot crashes mid-run, the instance keeps billing. Recover:
  ```bash
  vastai show instances
  vastai destroy instance <ID>
  ```
* First run of a fresh instance pays for the model download (~10-15 min).
  Every later video on a `mode: existing` instance skips that entirely.
* Storage of a stopped instance bills a few cents/day - destroy machines you
  will not reuse this week.

## Debugging a Vast run

```bash
python main.py images myvid --set system.log_level=DEBUG
```
You will see the ssh/scp/tunnel commands, then the server log tail if the
GPU server never became healthy (`/root/avb_server.log` on the machine).

## Cost sanity table (indicative - check vast.ai for today's prices)

What you actually pay for = (model download + rendering + boot) x hourly rate.
Boot is ~2-4 min, the download 10-15 min on a fresh machine, rendering ~2-4 s
per image on a 24 GB card.

| GPU | ~$/h | 30 images, warm start | first-boot total |
|---|---|---|---|
| RTX 3090 24 GB | 0.12-0.22 | ~$0.02 | ~$0.09 |
| RTX 4090 24 GB | 0.29-0.45 | ~$0.03 | ~$0.12 |
| A5000 24 GB | 0.20-0.35 | ~$0.03 | ~$0.13 |
| RTX 4080 16 GB | 0.25-0.40 | ~$0.03 | ~$0.13 (SDXL only) |
| A100 40 GB | 0.30-1.40 | ~$0.06 | ~$0.30 |
| H100 80 GB | 1.50-3.00 | ~$0.12 | ~$0.60 |

Plan for **$0.10-0.15 for the first video** (you pay for the model download
once) and **$0.02-0.04 for every video after that** on the same kept machine.
Compare with Replicate at ~$0.003 per image, i.e. ~$0.09 per 30-image video
with zero operations: if you only make occasional videos, Replicate is
simpler; if you make a batch, renting wins.
