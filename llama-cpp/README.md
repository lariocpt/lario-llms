# llama.cpp backend (`llamacpp` container)

Local LLM serving for the stack — **replaces Ollama**. A single `llamacpp` container runs
[**llama-swap**](https://github.com/mostlygeek/llama-swap) (multi-model proxy, on-demand load/unload)
in front of **llama.cpp** `llama-server`, GPU-accelerated on the AMD **Strix Halo** iGPU (Radeon 8060S,
gfx1151) via **ROCm**. It listens on **`:11434`** (same port Ollama used) and serves an OpenAI-compatible
`/v1` API. The container has the network alias **`ollama`** on `lario-net`, so anything still pointing at
`ollama:11434` keeps working.

```
clients/agents ─► bifrost :8080 (router)  ─┐
Hermes agents (lario-net) ─────────────────┤─► llamacpp :11434 (alias: ollama)
host shell: `llama …` ─► docker exec ───────┘     = llama-swap → llama-server (ROCm)
                                                   mounts: /mnt/Shared/models/{ollama,gguf}, ~/.cache/huggingface
```

## Image
Self-contained (so the host `~/.local/bin/llama-b9842` + host Ollama can be deleted): it bundles the
validated llama.cpp build (`b9842`) + Ollama's bundled **ROCm 7.2.1** runtime + `llama-swap`.
- Build:  `./build.sh`  (stages `vendor/` ≈ 3 GB from the host, then `docker build`).
- Compose:  `docker compose up -d --build llamacpp`  (GPU passthrough is in `docker-compose.override.yml`).
- Env baked in: `HSA_OVERRIDE_GFX_VERSION=11.0.2` (gfx1151→gfx1102 spoof), `LD_LIBRARY_PATH`,
  `ROCBLAS_TENSILE_LIBPATH`, `HF_HOME=/root/.cache/huggingface`.

## Models
- **Reused Ollama blobs** — `setup-models.sh` symlinks each blob to `/mnt/Shared/models/gguf/<name>.gguf`
  (mounted read-only at `/models/gguf`). Re-run it after pulling new models in Ollama.
- **MiniMax-M2.7 / Mistral-Medium-3.5** — streamed from the mounted HF cache via `-hf` (no extra copy).
- Per-model flags/sampling live in **`config.yaml`** (live-reloaded; `-watch-config`). Model ids/aliases
  match the ids Bifrost/clients use (`gemma4`, `qwen3-coder:30b`, `llama3.2-vision:latest`, `minimax-m2`, …).
- GPU tuning for 128 GB unified (≈64 GB VRAM + 62 GB RAM): `-ngl 999` fills VRAM; for the 108 GB MoE
  MiniMax, `--n-cpu-moe N` parks overflow experts in system RAM (lower N = more on GPU = faster).

## The `llama` command (host)
`~/.local/bin/llama` execs tools inside the container:
`llama cli -hf <repo>:<quant>` · `llama server --version` · `llama bench -m /models/gguf/qwen3-coder-30b.gguf`
· `llama quantize in.gguf out.gguf Q4_K_M`.

## Verify
- GPU:  `docker run --rm --device /dev/kfd --device /dev/dri lario/llamacpp:latest llama-server --list-devices` → `ROCm0`.
- API:  `curl -s localhost:11434/v1/models | jq -r '.data[].id'`
- Chat: `curl -s localhost:11434/v1/chat/completions -d '{"model":"qwen3-coder:30b","messages":[{"role":"user","content":"hi"}]}'`

## Known issues
- **gemma4 / glm-4.7-flash** (new archs) fail to load from the *Ollama blobs* on build b9842
  (`wrong number of tensors; expected 2131, got 720` — tensor-layout mismatch). Fix: re-download fresh
  Unsloth GGUFs for these, or upgrade the bundled llama.cpp build. Other models load fine.
- **llama3.2-vision**: served as text only — the Ollama manifest has no projector layer; add `--mmproj`
  with a vision projector GGUF to enable images.
- `amdgpu.ids: No such file` on startup is cosmetic (friendly-name lookup only).

## Rollback
The previous `ollama` service is in git history: `git show HEAD:docker-compose.yml`. To restore quickly:
`docker run -d --name ollama --network lario-net -p 11434:11434 --device /dev/kfd --device /dev/dri -e HSA_OVERRIDE_GFX_VERSION=11.0.2 -v /mnt/Shared/models/ollama:/root/.ollama ollama/ollama:rocm`.
