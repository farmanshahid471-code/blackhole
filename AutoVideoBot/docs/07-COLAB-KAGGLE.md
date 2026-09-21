# Free GPUs: Google Colab and Kaggle

Both give you real GPUs for $0. They differ in one crucial way:

* **Colab can be a live server** (with a tunnel) -> the bot talks to it.
* **Kaggle cannot** -> the bot writes a batch notebook, you run it once, and
  the bot imports the results.

---

## COLAB (live server mode)

### Setup per session (about 3 minutes, then hours of free GPU)

1. Open `deploy/colab/colab_image_server.ipynb` in Google Colab.
2. *Runtime -> Change runtime type -> T4 GPU*.
3. *Runtime -> Run all.*
   * cell 3 writes the server, cell 4 starts it, cell 5 opens a
     **cloudflared** tunnel (free, no account) and prints:
     ```
     YOUR PUBLIC LINK (paste this into .env as IMAGE_ENDPOINT_URL):
        https://abcd-1234.trycloudflare.com
     ```
   * If you prefer ngrok: put your authtoken in the cell's
     `NGROK_AUTHTOKEN` field.
4. Put the link in `.env`:
   ```
   IMAGE_ENDPOINT_URL=https://abcd-1234.trycloudflare.com
   ```
   or pass it per run:
   ```bash
   python main.py run myvid --script s.txt --endpoint https://abcd-1234.trycloudflare.com
   ```
5. Leave the last cell (keep-alive) running and the tab open. Colab kills
   idle notebooks; the bot also pings `/health` every 25 s while working.
6. ```bash
   python main.py images myvid        # or a full run
   ```

The server is the same code as `deploy/vast/server/image_server.py` (batch
`/generate`), so all 30 prompts go in one request and the model loads once.

### When the link dies

It always eventually does. Re-run the notebook, paste the new link. Scenes
already rendered on your PC are cached, so you only pay for what is missing.

### Colab limits to know

* Free tier: ~4 h sessions, T4 16 GB (SDXL fits; FLUX-schnell fits with CPU
  offload, slower).
* Google blocks raw port forwarding for free accounts - that is exactly why
  the tunnel exists.
* Heavy consecutive use can throttle you for a day. Colab Pro ($10/mo)
  removes almost all of this.

---

## KAGGLE (batch mode)

### Why batch

Kaggle kills tunnels and dies when the tab closes, so "calling" it live is
unreliable. Instead the work travels to Kaggle and the pictures travel back.

### The loop

```bash
# 1. bot writes a notebook with ALL your prompts baked in
python main.py images myvid
#    -> prints: workspace/kaggle_out/kernel.ipynb   (+ how many images needed)

# 2. you: kaggle.com/code -> New Notebook -> File -> Import notebook -> kernel.ipynb
# 3. you: right sidebar  Accelerator = GPU T4 x2 , Internet = ON
# 4. you: Run All            (15-40 min for a full video)
# 5. you: Output -> Download All  -> autovideobot_images.zip
# 6. put the zip into workspace/kaggle_out/
# 7. bot imports it and continues automatically:
python main.py images myvid
python main.py run myvid --script your_script.txt
```

Steps 2-6 are the only manual clicks in the entire system. The notebook
(`deploy/kaggle/kaggle_batch_template.ipynb`) names every image after its
scene id (`s01.jpg`, `s02.jpg`...) so the import can never misfile a picture.

### Fully automatic Kaggle (optional)

```bash
pip install kaggle
# Kaggle -> Account -> Create New API Token -> save as ~/.kaggle/kaggle.json
```
```yaml
image.kaggle.auto_push: true
```
with `KAGGLE_USERNAME` / `KAGGLE_KEY` in `.env`. The bot then pushes the
kernel, polls its status, and downloads the output zip itself.

### Quota

30 GPU hours/week free. A 30-image SDXL batch is ~20 minutes, so a week of
daily videos fits comfortably.

---

## Which free path should I use?

| Situation | Pick |
|---|---|
| you are at the computer anyway | Colab (live, fastest loop) |
| you want it running while you sleep | Kaggle batch (no session to babysit) |
| you publish daily and want zero babysitting | Vast auto ($0.02-0.10/video) or Replicate |
| you are testing scripts, not looks | pollinations (no GPU at all) |
