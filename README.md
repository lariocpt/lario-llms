# lario-llms — local LLM stack (l-dev-ai · CachyOS · Strix Halo)

The LLM serving + orchestration stack for this box. The **model backend runs
natively** (llama.cpp via llama-swap, systemd user service on `:11434`);
containers handle gateway/RAG/pipeline around it.

```
clients / agents
      │
      ▼
bifrost  :8080  (container — LLM gateway, config in bifrost/config.db)
      │  provider base URL "http://ollama:11434" → host-gateway
      ▼
llama-swap  :11434  (NATIVE — systemd --user llama-swap.service)
      │  spawns/swaps llama-server per model
      ▼
llama.cpp  (~/llama.cpp/build-vulkan, Vulkan/RADV)
      │
      ▼
/mnt/AI_Models  (gguf/ + huggingface/ on the xfs models partition)
```

## The one toggle: `main-model.sh`

`llama-cpp/config.yaml` is **generated — never edit it by hand** (it's gitignored).
`main-model.sh` (symlinked as `~/.local/bin/main-model`) owns it:

```bash
main-model            # fzf menu
main-model minimax    # switch the big resident model (clean stop→rewrite→start)
main-model show       # active model + what's loaded
```

Aliases (`main`, `coder`, `hermes`, `smart`, `ollama/*`, …) follow the toggle.
`qwen3-vl` loads on demand for `visual`/`vision`/`image` and unloads after 15 min.
Big models > 64 GB (minimax ≈ 87 G) need the GTT kernel args — see
`~/Projects/personal/machine-setup` (the `ttm.` args, **not** `amdttm.`).

## Containers

```bash
cd ~/Projects/personal/lario-llms
docker compose -f docker-compose.yml -f docker-compose.cachyos.yml \
  up -d bifrost chromadb rag_api ml_pipeline
```

Both `-f` flags are **load-bearing** — they exclude the retired Fedora-era
override (now in `legacy/fedora/`). Never name `llamacpp` in the service list.

| service | image | notes |
|---|---|---|
| bifrost | `maximhq/bifrost:v1.6.3` (pinned) | gateway; admin API has **no auth** — loopback + tailnet only, bind via `.env` (`BIFROST_BIND_IP`, see `.env.example`) |
| chromadb | `chromadb/chroma:latest` | vector store, `./chroma-data` |
| rag_api | built from `./ml_env` | RAG API on :8100; GPU via /dev/kfd+dri (container-internal ROCm spoof 11.0.0 is correct there) |
| ml_pipeline | built from `./ml_env` | batch/pipeline sibling |

Data dirs `bifrost/` and `chroma-data/` are live docker bind mounts —
**in the repo tree but gitignored by design**.

## Layout

- `main-model.sh`, `scripts/llama-swap-warmup.sh` — live model management
- `llama-cpp/config.yaml` — generated (gitignored); `.main-model` — active-model state
- `docker-compose.yml` + `docker-compose.cachyos.yml` — the current topology
- `ml_env/` — Dockerfile + RAG/pipeline scripts
- `niri/`, `niri-wspaces/` — window-manager config *(slated to move to lario-linux-distro)*
- `legacy/fedora/` — retired Fedora stack. **DO NOT RUN** (see its README)
- `attic/` — one-off scripts/session notes kept for reference (stale paths)
- `docs/` — agent/tooling notes (some predate the CachyOS migration)
- `boot-dev-linux.sh`, `start_all.sh`, `install_host_env.sh` — host/dev-container
  helpers from the Fedora era; review before use

Machine provisioning (mounts, kernel args, unit install, backups) lives in
**`~/Projects/personal/machine-setup`** — not here.
