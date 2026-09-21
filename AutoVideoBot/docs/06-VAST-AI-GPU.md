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
         gpu_type: "RTX 4090"      # RTX 3090 is usually 2x cheaper
         min_vram_gb: 16
         max_price_per_hour: 0.50
   ```

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

| GPU | ~$/h | 30 images after warm start | first-boot total |
|---|---|---|---|
| RTX 3090 24 GB | 0.15-0.25 | ~$0.02 | ~$0.06 |
| RTX 4090 24 GB | 0.30-0.50 | ~$0.03 | ~$0.10 |
| A100 40 GB | 1.0-1.4 | ~$0.08 | ~$0.30 |
