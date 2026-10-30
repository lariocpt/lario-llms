# Lario local models

Hardware-owned configuration for bigcachy, l-dev-ai and cachyos-mini-mobile. Edit a hardware `models.json`;
`shared/modelctl.py` generates the llama-swap configuration. Model weights live on XFS:
`/mnt/xfs/AI_Models` on bigcachy and mini-mobile and `/mnt/AI_Models` on l-dev-ai.

| Hardware folder | Host | Serving software | API | Provider / hardware ID |
|---|---|---|---|---|
| [geekom](geekom/README.md) | l-dev-ai, Strix Halo, 128 GiB unified RAM | Halogen HIP + owner gateway / llama-swap | :11434/v1 | `geekom` |
| [geekom7900xt](geekom7900xt/README.md) | l-dev-ai, M.2 NVMe RX 7900 XT, 20 GiB | Rootless Podman ROCm + llama-swap | :11436/v1 | `geekom7900xt` |
| [rtx5080](rtx5080/README.md) | bigcachy, RTX 5080, 16 GiB | Strata CUDA Flash Next NVFP4 + owner gateway | :11435/v1 | `rtx5080` |
| [arcB70](arcB70/README.md) | bigcachy, Intel Arc Pro B70, 31.89 GiB usable | vLLM XPU GPTQ INT4 + FP8 KV / MTP | :11437/v1 | `arcB70` |
| [intel](intel/README.md) | bigcachy, Core Ultra 9 285K, iGPU + NPU | Native Python OpenVINO GenAI | :8001–8004 | No model switching alias |

The RTX card belongs entirely to its selected profile. RAG embeddings use Intel CPU;
`vision:8080` is an nginx proxy to native RTX serving, preserving container DNS.

The Radeon provider is `geekom7900xt` on l-dev-ai. The Winmax placement is
retired. Runtime acceptance is pending; see the
[cutover record](docs/hardware-transition-2026-10-23.md).
B70 serves its enabled profiles; other choices remain gated.

## Selecting fixed profiles

Choose hardware-prefixed entries directly in OpenCode. Each immutable ID fixes
model, context, KV precision, slots, preset and revision. Idle hardware loads the
selected profile; busy hardware refuses a different one. The [operator page](https://models.in.drlario.org)
shows residency and active inference with guarded registered OpenCode run control.
See [controls and session identity](docs/model-control.md) for behavior and limits.

Geekom now offers only Halogen Flash Next v2: 128K and 256K requests share one
512K-position pool and four streams. Retired Geekom defaults and agent pins are
migrated to Halogen 128K. RTX Flash Next NVFP4 has one 128K vision session; B70
GPTQ INT4 has two 168K vision/MTP sessions. Radeon choices remain unchanged.
These exact profiles also appear on the model page and in monitoring. Historical
benchmark/configuration records do not describe selectable current models.

`lario-fleet` reads live resident slots minus reservations. Current Geekom and B70 profiles reserve no dedicated coding slots; RTX uses its auxiliary class. Off,
loading and unavailable capacity is zero. Shared pools reserve the selected window per request; their total context pool
can be smaller than slots multiplied by the largest supported window. A
concurrency budget is not a measured throughput claim.

## Clients and agents

machine-setup owns the shared client material and three per-machine overlays.
Its renderer preserves unrelated providers/plugins and injects private scoped
credentials. The v2 plugin attaches installation, conversation and run identity
without logging prompts. Every fixed profile has its own exact context metadata.

`lario_models` exposes read-only `model_status` and `model_options` only. Lifecycle,
activation and guarded cancellation belong to the operator page. Intel retains its
seven tools and compatible RAG embedding space; it has no coding provider. Images
and encoding retain separate tools and their shared GPU lock. [MCP guide](docs/mcp-guide.html).

Keep parked Hermes agents paused. Agent source, fleet pins, deployment and verified
RAG publication are separate actions. Uninstrumented callers receive inference
cancellation only; the page does not claim their originating runner stopped.

## Starting and checking

`./start_all.sh` starts the native Geekom service on l-dev-ai, or the hardware and supporting
services on bigcachy, or the conditional Radeon service on l-dev-ai. It uses explicit compose files and excludes legacy Fedora overrides.
Intel runtime requirements are pinned in `intel/requirements.txt`; see its README for setup.
Host ordering and service health are documented in [BOOT.md](docs/BOOT.md), and the
audited unused-model deletion in [MODEL-CLEANUP.md](docs/MODEL-CLEANUP.md).

Verification evidence: [Intel measurements](intel/research/), [GPU profile tests](research/),
and [OpenCode diagnosis](docs/OPENCODE.md). Unit checks: `python -m unittest discover -s tests`.
The old material in `docs/history/`, `legacy/`, and `attic/` is historical, not provisioning input.

Lifecycle: `geekom7900xt start --experimental`, `geekom7900xt stop`, `geekom start`,
`geekom stop`, `rtx5080 start`, `rtx5080 stop`. See [GUIDE.md](GUIDE.md) and
[the MCP guide](docs/mcp-guide.md) for saved selections, tokens and boot semantics.
