# Local RTX image generation

This is a separate ComfyUI workload, selected through `rtx5080 images` or the
`lario_images` MCP. It cannot be loaded by llama-server as a chat model.
The controller borrows the idle, healthy RTX for one image and restores the
saved chat model/preset afterward. Chat/vision is unavailable during that job.
An active/unknown chat request, owner hold, occupied controller lock or foreign
image server prevents generation. There is no force option.

Weights, Python/CUDA runtime, download caches, inputs, outputs and temporary
files live under `/mnt/xfs/AI_Models/image-generation`. The manifest pins the
runtime commits, six model files, Hugging Face revisions, sizes and SHA256
digests. Both requested bundles total approximately 30.76 GB; file size is not
peak VRAM. `requirements.lock` records the resolved isolated Python environment.

- `qwen-image`: requested Qwen Image 2.1 Uncensored Q4_K_M, its INT8 ConvRot
  Qwen3-VL encoder and model-specific VAE. Encoder and image KV cache use CPU RAM.
- `flux-klein`: official FLUX.2-klein-4B distilled BF16 diffusion weights, with
  the matching Comfy-Org Qwen3-4B encoder and FLUX2 VAE. CPU encoder; four steps
  by default. This is not the 20-step base variant.

The graphs follow the pinned official templates without downloading their
optional prompt-rewriting model. One image, 256–1024 pixels per side in multiples
of 64, up to 40 steps. Host RAM preflight requires 40 GiB available to cover CPU
encoding/offload; actual memory/timing measurements determine suitability.

```sh
python3 rtx5080/image-generation/install.py --runtime --weights
rtx5080 images options
rtx5080 images generate --model qwen-image --prompt 'A clean blue app icon' --seed 42
rtx5080 images generate --model flux-klein --prompt 'A clean blue app icon' --seed 42
```

The source user unit is installed cmp-guarded; it is on demand and not enabled
at boot. RTX chat's existing saved selection boots normally, and subsequent
image calls use the persisted XFS installation. No weights download on startup.
ComfyUI is bound to loopback and runs only during the guarded job; do not queue
jobs directly into its worker outside this controller.

OpenCode owner clients on bigcachy/l-dev-ai expose `image_options` and
`image_generate` through existing SSH access. Media/mini-mobile expose only the
configured choices; they receive no SSH or management credentials. The result
contains the PNG path on bigcachy, not a fabricated client-local file path.

The original RTX Xid79/PCIe fault cause remains unresolved. Hardware readiness
is checked before borrowing, during polling and before restoring chat. Retain
failed outputs/diagnostics, and do not interpret installation or a smoke image
as a broad quality/performance benchmark.

Primary sources:

- [Requested Qwen Image conversion](https://huggingface.co/abenzerps/Qwen-Image-2.1-Uncensored-GGUF).
- [Official FLUX.2-klein-4B](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B).
- [Comfy-Org FLUX companions](https://huggingface.co/Comfy-Org/flux2-klein-4b).
- [Official workflow templates](https://github.com/Comfy-Org/workflow_templates).
- [Pinned ComfyUI](https://github.com/Comfy-Org/ComfyUI/tree/d49e888586dd8ae012c0667b33466b815fee07f7).
- [Pinned GGUF loader](https://github.com/leejet/ComfyUI-GGUF/tree/373048b8403a7820620065210a691263d4da0a61).


## Installed and locally verified, 2026-10-06

All six installed files were independently SHA256 checked against the pinned
manifest, and both runtime Git commits matched. The isolated environment is
Python 3.12.13, Torch 2.14.1+cu130 / CUDA 13.0, with native sm_120 support on
NVIDIA driver 615.71.09. All 105 resolved dependencies passed `uv pip check`.
The installer initially hit a network timeout; its cached retry completed.

Each case generated a valid PNG at its requested dimensions; the 512px images
were visually checked against the simple blue mountain-icon prompt. Every job
stopped the image worker and restored Qwen3.8 `fast-64k`, with the saved selection
unchanged. FLUX's jobs exercised the real MCP initialize/list/generate transport.

| Model | Size / steps | Image job time | Whole job + chat restore | Peak VRAM during image worker |
|---|---|---:|---:|---:|
| Qwen Image Q4 | 512 / 8 | 46.566 s | 58.342 s | 5597 MiB |
| Qwen Image Q4 | 1024 / 25 | 46.553 s | 54.353 s | 5853 MiB |
| FLUX Klein | 512 / 4 | 14.167 s | 21.797 s | 8077 MiB |
| FLUX Klein | 1024 / 4 | 24.293 s | 30.947 s | 8085 MiB |

These are single seeded synthetic cases, with different steps and cache states,
not an isolated speed/quality ranking. At 1024px, observed image-worker VRAM
headroom was 10450 MiB for Qwen and 8218 MiB for FLUX. Minimum sampled available
host RAM was 79.737 and 72.699 GiB respectively. Memory is sampled every two
seconds and includes other host processes; unsampled peaks are possible. Global
swap-out counters increased by 53 and 225 pages in those scopes; the first FLUX
512px scope had 32474 pages. Do not attribute global swap solely to image work.
Editing, alpha output, lettering/layout and multi-image quality remain untested.

Evidence: `../../research/rtx-image-install-verification-20261006.json`,
`../../research/benchmarks/20261006-qwen-image-q4-*.json`,
`../../research/benchmarks/20261006-flux-klein-*-mcp.json`, and
`../../research/rtx-image-final-state-20261006.json`. Final NVIDIA probe was
healthy, and the image unit is static/on demand rather than boot enabled.
A fresh unused-model audit on both hosts found zero unused download candidates;
all new companions are referenced by the tested graphs. Existing model cleanup
remains documented in `../../docs/MODEL-CLEANUP.md`.

All Hermes agents were subsequently paused at the user's explicit request, via
normal `.fleet-disabled` markers and graceful container stops. Keep them paused
until the user resumes them; this pause survives reboot. Geekom's prior balanced
3 × 245760 Flash profile was restored after it became idle. Its six-slot option
remains experimental because the live tests included ongoing Hermes traffic,
initial large-concurrency failures and scoped swap activity.
