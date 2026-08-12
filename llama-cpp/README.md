# llama.cpp backend (native llama-swap on l-dev-ai)

Local LLM serving for the stack. [**llama-swap**](https://github.com/mostlygeek/llama-swap)
(multi-model proxy, on-demand load/unload) sits in front of **llama.cpp** `llama-server`,
GPU-accelerated on the AMD **Strix Halo** iGPU (Radeon 8060S, gfx1151) via **Vulkan/RADV**.
It listens on **`:11434`** and serves an OpenAI-compatible `/v1` API.

> **There is no `llamacpp` container.** It runs as a **systemd user unit** on l-dev-ai
> (`llama-swap.service`), started from `~/.local/bin/llama-swap`. Never start the retired
> `llamacpp` compose service. Rewritten 2026-08-13 — this file previously described the
> container/ROCm era and was wrong in almost every particular.

```
clients/agents ─► bifrost :8080 (router)  ─┐
Hermes agents (on bigcachy) ───────────────┤─► l-dev-ai :11434
opencode / cline ──────────────────────────┘     = llama-swap → llama-server (Vulkan)
                                                  HF_HOME=/mnt/AI_Models/huggingface
```

## Where things live

| | |
|---|---|
| Unit | `~/.config/systemd/user/llama-swap.service` (installed by `machine-setup`, not this repo) |
| Binary | `~/.local/bin/llama-server` → `~/llama.cpp/build-vulkan/bin/llama-server` |
| Build | **10367** (`704485942`, 2026-08-11). Rollback copy of build 10027 at `~/llama.cpp/build-vulkan-10027-backup` — see GOTCHAS #11 |
| Weights | `/mnt/AI_Models` (782 G XFS): `gguf/` for explicit `-m` models, `huggingface/` for `-hf` |
| Config | `llama-cpp/config.yaml` — **GENERATED** by `main-model.sh`, gitignored. Never hand-edit |
| GPU pool | 105 GiB unified GTT, **no dedicated VRAM** (`ttm.pages_limit=27648000`) |

A second **ROCm** build exists at `~/llama.cpp/build-rocm` (`llama-server-rocm`, `llama-bench-rocm`)
for A/B testing. Vulkan is what actually serves — see `scripts/benchmark-backends.sh`.

## Models

Registered in `main-model.sh` (`MODELS` / `ORDER` / `BASE_ALIASES`). One big model is resident at a
time (`groups.big`, `swap: true`); switch the whole fleet with `main-model <name>`.

| id | source | weights | decode |
|---|---|---|---|
| `muse-glimmer-fast` | unsloth/Muse-Glimmer-30B-GGUF:UD-Q4_K_XL | 15.9 GB dense | **13.94 tok/s** |
| `muse-glimmer-q8` | unsloth/Muse-Glimmer-30B-GGUF:UD-Q8_K_XL | 32.3 GB | 7.21 tok/s |
| `muse-glimmer` | Muse-Glimmer-30B BF16 (2 shards, `gguf/muse-glimmer/BF16/`) | 55.7 GB | 4.05 tok/s |
| `qwen3.6` | unsloth/Qwen3.6-27B-GGUF:UD-Q4_K_XL | 17.6 GB | 11.93 tok/s |
| `gemma4` | unsloth/gemma-4-31B-it-GGUF:Q4_K_M | — | — |
| `mistral` | Mistral-Medium-3.5-128B-Q4_K_M (3 shards) | ~70 GB dense | slow, memory-bound |
| `minimax` | MiniMax-M2.7-UD-Q3_K_S (3 shards) | ~87 GB MoE | slow, memory-bound |

All Muse decode figures measured 2026-08-12 on build 10367, same method (3 × 200-token
generations through llama-swap). **Decode is purely bandwidth-bound on this box**: scaling by
weight size predicts every one of them within ~5%, so pick a quant by the tok/s you need — there
is no broken kernel to hunt for.

`muse-glimmer-fast` is the active default: faster *and* lighter than the qwen3.6 it replaced, and
decisively better at agentic work (MCP Atlas 75.5 vs 62.5). qwen3.6 remains the better coder
(SWE-Bench 77.2 vs 76.0).

- **Muse Glimmer and Qwen3.6 are multimodal** and load their own `--mmproj`. There is no standalone
  vision *service* here — that lives on bigcachy's RTX 5080. Note the 8060S is slow at image
  *encoding*, but that cost is only paid on requests carrying an image.
- **Slots and context:** `-c` is a TOTAL KV pool split across `--parallel`, not per-slot. Muse KV is
  13 KiB/token vs qwen3.6's 64, so 20 × 131072 fits in ~54 GiB where qwen3.6's 8 × 122880 took 80.
  131072/slot is a hard ceiling: the GGUF ships no rope-scaling keys.
- **BF16 has its own `MUSE_BF16_PARALLEL=12`** — 20 slots would need ~90 GiB and OOM at load.

## Commands

```bash
main-model                 # fzf menu — switch the whole fleet
main-model <name>          # direct switch (restarts llama-swap, waits for ready)
main-model show            # active model + what is loaded
systemctl --user status llama-swap
journalctl --user -u llama-swap -f
```

`~/.local/bin/llama-{server,cli,bench}` are symlinks straight into `build-vulkan/bin` (managed by
machine-setup's symlink table). There is no `llama` wrapper and no `docker exec` hop any more.

## Verify

```bash
curl -s localhost:11434/running                     # what is resident, and its full cmdline
curl -s localhost:11434/v1/models | jq -r '.data[].id'
curl -s localhost:11434/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"main","messages":[{"role":"user","content":"hi"}],"max_tokens":64}'
awk '{printf "%d GiB\n", $1/1024/1024/1024}' /sys/class/drm/card1/device/mem_info_gtt_used
```

Use the `main` alias, not a model id — it follows the toggle.

## Known issues

See [../GOTCHAS.md](../GOTCHAS.md). The ones that bite here:

- **`--cache-ram 0` is load-bearing** (#9). llama.cpp's host prompt cache aborts the server on
  slot reassignment. Every model carries the flag.
- **Build 10367 is newer than two workarounds** (#11) — `--cache-ram 0` and `--cache-reuse 256`
  were fitted to build 10027 and have not been re-validated.
- **Restarting llama-swap unloads the resident model**, which is a 55–90 GB reload. Avoid casual
  restarts; `main-model <name>` restarts deliberately (and frees the old model first, so two big
  models are never briefly co-resident).
- **Reasoning models can return an empty answer.** Both Muse Glimmer and qwen3.6 emit all
  reasoning before any content, so an insufficient `max_tokens` yields `content: ''` with
  `finish_reason: length`. Hence `--reasoning-budget 2048`.
