# Lario local models

Hardware-owned configuration for bigcachy and l-dev-ai. Edit a hardware `models.json`;
`shared/modelctl.py` generates the llama-swap configuration. Model weights live on XFS:
`/mnt/xfs/AI_Models` on bigcachy and `/mnt/AI_Models` on l-dev-ai.

| Hardware folder | Host | Serving software | API | Selected-model alias |
|---|---|---|---|---|
| [geekom](geekom/README.md) | l-dev-ai, Strix Halo, 128 GiB unified RAM | Native Vulkan llama.cpp + llama-swap | :11434/v1 | `geekom` (compatibility: `main`) |
| [7900xt](7900xt/README.md) | bigcachy, RX 7900 XT, 20 GiB | ROCm llama.cpp + llama-swap, `agent-llm` container | :11436/v1 | `7900xt` (compatibility: `agent`) |
| [rtx5080](rtx5080/README.md) | bigcachy, RTX 5080, 16 GiB | Native CUDA llama.cpp + llama-swap | :11435/v1 | `rtx5080` (compatibility: `vision`) |
| [intel](intel/README.md) | bigcachy, Core Ultra 9 285K, iGPU + NPU | Native Python OpenVINO GenAI | :8001–8004 | No model switching alias |

The RTX card belongs entirely to its selected profile. RAG embeddings use Intel CPU;
`vision:8080` is an nginx proxy to native RTX serving, preserving container DNS.

## Selecting models

Run `geekom` on l-dev-ai, or `7900xt` / `rtx5080` on bigcachy. With no arguments each
opens a numbered menu. `list`, `show`, `budget`, `slots`, `reserved`, and `context` inspect
configuration or live capacity. Pass a model name to switch; for example `rtx5080 describe`.
`main-model` and `agent-model` remain compatibility wrappers. A switch stops the hardware
server, writes configuration atomically, starts it, and warms the selected model; failed
switches restore the previous configuration. It does not restart OpenCode.

Concrete model IDs are also requestable through the API and OpenCode; doing so swaps the
hardware's resident model. The hardware alias refers to the profile chosen with the selector,
so requesting that alias can swap it back. Budget queries use `/running`, not the saved selection.

| Hardware | Profile | Slots × context per slot | Reserved slots |
|---|---|---:|---:|
| geekom | qwen3.8-smart / qwen3.8-medium | 4 × 245760 | 2 |
| geekom | qwen3.8-smart-128k / qwen3.8-medium-128k | 8 × 122880 | 2 |
| geekom | qwen38-flash | 4 × 245760 | 2 |
| 7900xt | muse-glimmer-dflash | 2 × 131072 | 0 |
| 7900xt | muse-glimmer | 3 × 131072 | 0 |
| 7900xt | qwen3.8 | 1 × 262144 | 0 |
| rtx5080 | ocr / describe / qwen3.8 | 1 × 32768 / 65536 / 262144 | 1 |

`-c` is the **total** context allocation (slots × per-slot context).
`concurrencyLimit` equals slots. `lario-fleet` on bigcachy reads live capacity and subtracts
reserved slots: Geekom admits 2 or 6 agent slots; the Radeon admits 2, 3, or 1. These are
advisory enabled-agent budgets; concurrent sessions can exceed them and receive retryable 429s.
An unavailable backend reports zero capacity. The RTX slot is reserved for auxiliary/image work.

## Clients and agents

OpenCode sources are in `../machine-setup/machines/<host>/config/opencode.jsonc` and
`shared/agents/opencode.base.jsonc`. Render them with machine-setup's agent-config renderer.
The default is `geekom/geekom`; providers are `geekom`, `7900xt`, and `rtx5080`. Image
capability is explicit only for RTX `ocr` and `describe`. Hardware aliases use conservative
context limits that remain valid across selections. Intel translation, embeddings and
speech are available through the seven `lario_intel` MCP tools in OpenCode, Cline and
Hermes; there is no Intel coding provider. See [Intel tools](intel/README.md).

Hermes sources are in `../agents/hermes/*/config.src.yaml`; deploy through
`../agents/deploy/deploy-hermes.sh`, preserving disabled-agent markers and restarting live
agents only when idle. Update knowledge sources and run the real `deploy/ingest_kb.py`
(citation gate included), then verify `/retrieve` against `kb-lario-local-linux`.

## Starting and checking

`./start_all.sh` starts the native Geekom service on l-dev-ai, or the hardware and supporting
services on bigcachy. It uses explicit compose files and excludes legacy Fedora overrides.
Intel runtime requirements are pinned in `intel/requirements.txt`; see its README for setup.
Host ordering and service health are documented in [BOOT.md](docs/BOOT.md), and the
audited unused-model deletion in [MODEL-CLEANUP.md](docs/MODEL-CLEANUP.md).

Verification evidence: [Intel measurements](intel/research/), [GPU profile tests](research/),
and [OpenCode diagnosis](docs/OPENCODE.md). Unit checks: `python -m unittest discover -s tests`.
The old material in `docs/history/`, `legacy/`, and `attic/` is historical, not provisioning input.
