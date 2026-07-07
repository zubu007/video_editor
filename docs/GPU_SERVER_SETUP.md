# GPU Server Setup (Windows + RTX 5060 via WSL2)

This guide sets up your Windows machine (NVIDIA RTX 5060) as a **GPU service** that your
Mac's video-editor backend can call over the network. The heavy GPU workloads —
**caption removal** (VideoSubtitleRemover) and optionally **transcription**
(faster-whisper) — run on the Windows GPU; the rest of the app stays on the Mac.

We run everything inside **WSL2 (Ubuntu)** because the tool's dependencies are Linux-first
and easier to manage there, while still getting full CUDA access to the GPU.

> **RTX 5060 note:** The 50-series is NVIDIA "Blackwell" (compute capability `sm_120`).
> It requires a **recent driver (572.xx+)** and **CUDA 12.8+** builds of PyTorch/etc.
> Older wheels fail with *"no kernel image is available for execution on the device."*
> Every install command below pins to CUDA 12.8 (`cu128`) for this reason.

---

## Section 1 — Setting up the GPU server with WSL2

### 1.1 Prerequisites (Windows side)

1. **Windows 11** (or Windows 10 21H2+). Windows 11 22H2+ strongly recommended for the
   simpler "mirrored" networking mode used in Section 2.
2. **Install/Update the NVIDIA Windows driver** (Game Ready or Studio), version **572.xx or
   newer**, from https://www.nvidia.com/download/index.aspx.
   - ⚠️ **Do NOT install an NVIDIA driver *inside* WSL.** WSL2 uses the Windows driver
     through a passthrough layer. Installing a Linux driver in WSL breaks GPU access.
3. Reboot after the driver install.

### 1.2 Install WSL2 + Ubuntu

Open **PowerShell as Administrator**:

```powershell
wsl --install -d Ubuntu-22.04
wsl --set-default-version 2
wsl --update              # ensure the latest WSL kernel (needed for CUDA passthrough)
wsl --shutdown            # restart WSL so the update takes effect
```

Launch **Ubuntu** from the Start menu and create your Linux user when prompted.

### 1.3 Verify the GPU is visible inside WSL

Inside the Ubuntu (WSL) shell:

```bash
nvidia-smi
```

You should see your **RTX 5060** listed with driver/CUDA version. If this fails, fix it
before continuing (usually: update the Windows driver, run `wsl --update`, `wsl --shutdown`).

### 1.4 Base tooling inside WSL

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip git ffmpeg
```

> `ffmpeg` is needed for video I/O. The CUDA *toolkit* (nvcc) is only needed if a dependency
> must compile CUDA code; the prebuilt `cu128` wheels below bundle their own runtime, so you
> usually don't need a full toolkit install.

### 1.5 Clone the project (for the GPU service code) and VideoSubtitleRemover

```bash
# Work in your Linux home dir, NOT under /mnt/c (WSL disk I/O there is very slow).
cd ~
git clone <your-video_editor-repo-url> video_editor
cd video_editor

# The caption-removal tool, cloned with its own virtualenv (per project CLAUDE.md):
git clone https://github.com/SysAdminDoc/VideoSubtitleRemover third_party/VideoSubtitleRemover
```

### 1.6 Set up VideoSubtitleRemover with a CUDA-enabled venv

```bash
cd ~/video_editor/third_party/VideoSubtitleRemover
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip

# Install its requirements first...
pip install -r requirements.txt

# ...then FORCE the CUDA 12.8 PyTorch build over whatever CPU torch it pulled in:
pip install --force-reinstall torch torchvision \
  --index-url https://download.pytorch.org/whl/cu128
```

**GPU sanity check** (this is the make-or-break step for the RTX 5060):

```bash
python -c "import torch; print('CUDA:', torch.cuda.is_available(), '| GPU:', torch.cuda.get_device_name(0))"
```

Expected: `CUDA: True | GPU: NVIDIA GeForce RTX 5060`. If `False`, your torch build doesn't
match the GPU/driver — re-check the `cu128` reinstall and driver version.

Then run the tool once on the GPU to download its inpainting/OCR model weights and confirm
end-to-end (uses `--gpu 0` for the first GPU):

```bash
python -m backend.processor -i sample.mp4 -o out.mp4 -m sttn --gpu 0
```

### 1.7 Run the GPU HTTP service

You need a small web service on the Windows/WSL side that your Mac calls. If the repo already
has one (e.g. `gpu_service.py`), run it; otherwise this is the minimal contract your Mac's
`remove.py` should talk to. Run it from the WSL Ubuntu shell:

```bash
cd ~/video_editor
source third_party/VideoSubtitleRemover/.venv/bin/activate   # or the service's own venv

# Bind to 0.0.0.0 so it's reachable from outside WSL, pick a port (e.g. 9000):
uvicorn gpu_service:app --host 0.0.0.0 --port 9000
```

Confirm it's alive **from within WSL** first:

```bash
curl http://localhost:9000/health
```

Networking so your **Mac** can reach it is covered in Section 2.

### 1.8 Point the Mac backend at the GPU service

On the **Mac**, in the repo `.env`, set the GPU service URL (exact var name depends on the
client code you wire up — see the "offload" work in `remove.py`):

```
GPU_SERVICE_URL=http://<windows-lan-ip>:9000
SUBTITLE_REMOVER_USE_GPU=1
```

---

## Section 2 — Firewall & networking changes

WSL2 runs in its own virtual network behind NAT, so a service on `0.0.0.0:9000` *inside* WSL
is **not automatically reachable** from other machines (your Mac). You have two options —
pick **A** if you're on Windows 11 22H2+.

### Option A (recommended) — Mirrored networking mode

Makes WSL share the Windows host's network directly, so `localhost` and the Windows LAN IP
"just work" with no port forwarding.

Create/edit `C:\Users\<you>\.wslconfig` (Windows side):

```ini
[wsl2]
networkingMode=mirrored
```

Then in **PowerShell (Admin)**:

```powershell
wsl --shutdown
```

Restart Ubuntu. Now the service is reachable at the **Windows machine's LAN IP** on port 9000.

### Option B — Port proxy (older Windows)

Forward a Windows host port to the WSL VM. In **PowerShell (Admin)**:

```powershell
# Find the WSL IP:
wsl hostname -I         # e.g. 172.23.45.67

# Forward Windows :9000 -> WSL :9000 (re-run if the WSL IP changes after reboot):
netsh interface portproxy add v4tov4 `
  listenaddress=0.0.0.0 listenport=9000 `
  connectaddress=172.23.45.67 connectport=9000

# Verify:
netsh interface portproxy show all
```

### 2.1 Windows Defender Firewall — inbound rule (required for BOTH options)

Windows blocks inbound connections by default. Open the port. In **PowerShell (Admin)**:

```powershell
New-NetFirewallRule -DisplayName "Video Editor GPU Service (9000)" `
  -Direction Inbound -Action Allow -Protocol TCP -LocalPort 9000
```

To remove it later:

```powershell
Remove-NetFirewallRule -DisplayName "Video Editor GPU Service (9000)"
```

### 2.2 Find the Windows LAN IP (use this in `GPU_SERVICE_URL`)

In PowerShell:

```powershell
ipconfig    # look for the IPv4 Address of your active adapter, e.g. 192.168.1.50
```

Set `GPU_SERVICE_URL=http://192.168.1.50:9000` in the Mac's `.env`.

### 2.3 Verify from the Mac

```bash
curl http://192.168.1.50:9000/health
```

### 2.4 Accessing it when NOT on the same LAN (remote)

**Do not** port-forward this to the public internet — an unauthenticated GPU endpoint is a bad
idea. Instead install **Tailscale** on both machines (https://tailscale.com). Each gets a
stable private `100.x.y.z` IP, encrypted, no router config or firewall port needed:

```
GPU_SERVICE_URL=http://<windows-tailscale-100.x.y.z>:9000
```

With Tailscale you can skip the Defender inbound rule for LAN and the port proxy entirely
(mirrored mode + Tailscale is the smoothest combo).

### Firewall checklist

| Situation | What you need |
|---|---|
| Same LAN, Win 11 22H2+ | Mirrored networking (A) + Defender inbound rule (2.1) |
| Same LAN, older Windows | Port proxy (B) + Defender inbound rule (2.1) |
| Remote / different network | Tailscale (2.4) — no port-forwarding, no public exposure |

---

## Section 3 — Which open-source model to download

### ⚠️ Important: caption removal is NOT an Ollama/LLM task

Ollama serves **text large-language models** (chat/generation). Caption removal is a
**computer-vision** problem: detect the caption pixels (OCR) and paint over them
(video inpainting). Ollama cannot do this, and there is **no Ollama model** for it. The
models you need come bundled with **VideoSubtitleRemover** and download automatically the
first time you run it (Section 1.6) — you don't fetch them via Ollama.

#### Caption-removal models — choose via the `-m/--mode` flag

Your backend already exposes these modes (`MODE_CHOICES` in
[remove.py](../backend/features/caption_removal/remove.py)):

| Mode | Model | Quality | Speed / VRAM | Use when |
|---|---|---|---|---|
| `sttn` | STTN | Good | **Fastest, lowest VRAM** | **Default & recommended for the RTX 5060 (8 GB).** Best speed/quality balance. |
| `lama` | LaMa | Good on stills | Fast | Simpler/static backgrounds. |
| `migan` | MI-GAN | Good | Fast, light | Lightweight alternative to STTN. |
| `propainter` | ProPainter | **Best** | **Heaviest — most VRAM** | Highest quality; may OOM on 8 GB for long/high-res clips. Try short clips first. |
| `auto` | tool picks | — | — | Let the tool decide. |

**Recommendation for the RTX 5060 (8 GB VRAM):** start with **`sttn`** (your current
default). Only reach for `propainter` when quality isn't good enough *and* the clip is short
enough to fit in VRAM — otherwise it will run out of memory.

> The RTX 5060 has 8 GB VRAM. If you hit CUDA out-of-memory errors, prefer `sttn`/`migan`,
> process shorter segments, or downscale before processing.

### Where Ollama DOES fit: the editing-plan feature

Your app also generates **AI editing plans** via **Groq Cloud** (an LLM) —
see [editing_plan/llm_client.py](../backend/features/editing_plan/llm_client.py). *That* is a
genuine LLM task you could run locally on the RTX 5060 with **Ollama**, replacing the Groq
cloud call. If that's what you actually want to self-host, install Ollama in WSL:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve            # exposes the API on :11434
```

Then pull a model sized for **8 GB VRAM** (pick one):

| Model | Pull command | Why |
|---|---|---|
| **Llama 3.1 8B** | `ollama pull llama3.1:8b` | Solid general-purpose, reliable **JSON-mode** output (your plan generator needs valid JSON). **Recommended.** |
| Qwen 2.5 7B | `ollama pull qwen2.5:7b` | Strong instruction-following, good structured output. |
| Mistral 7B | `ollama pull mistral:7b` | Lightweight fallback. |

Use a **quantized (`q4`) 7–8B** model — a 70B model will not fit in 8 GB. Wiring the editing
plan generator to Ollama instead of Groq is a separate change (point its base URL at
`http://<gpu-host>:11434/v1`, OpenAI-compatible); ask if you want that done.

### Summary

- **Caption removal → use `sttn` mode** (models auto-download with VideoSubtitleRemover). **Not Ollama.**
- **Editing-plan LLM → optionally Ollama `llama3.1:8b`** as a local replacement for Groq.
