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
                                                   mount: ~/.cache/huggingface (all models via -hf)
```

## Image
Self-contained (so the host `~/.local/bin/llama-b9842` + host Ollama can be deleted): it bundles the
validated llama.cpp build (`b9842`) + Ollama's bundled **ROCm 7.2.1** runtime + `llama-swap`.
- Build:  `./build.sh`  (stages `vendor/` ≈ 3 GB from the host, then `docker build`).
- Compose:  `docker compose up -d --build llamacpp`  (GPU passthrough is in `docker-compose.override.yml`).
- Env baked in: `HSA_OVERRIDE_GFX_VERSION=11.0.2` (gfx1151→gfx1102 spoof), `LD_LIBRARY_PATH`,
  `ROCBLAS_TENSILE_LIBPATH`, `HF_HOME=/root/.cache/huggingface`.

## Models
All models stream from the **`~/.cache/huggingface` cache via `-hf`** (the 172 GB of reused Ollama blobs
were deleted to free the shared partition). Current set (in `config.yaml`):

| id | source | size | speed |
|---|---|---|---|
| `gemma4` | unsloth/gemma-4-26B-A4B-it-GGUF:Q4_K_M | 16 GB MoE | ~44 tok/s |
| `glm-4.7-flash` | unsloth/GLM-4.7-Flash-GGUF:Q4_K_M | 18 GB MoE | ~49 tok/s |
| `qwen3-coder:30b` | unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF:Q4_K_M | 18 GB MoE | ~75 tok/s (coder) |
| `qwen2.5-vl` | unsloth/Qwen2.5-VL-7B-Instruct-GGUF:Q4_K_M + mmproj | 4.7+1.4 GB | vision: OCR/docs |
| `gemma3-vision` | unsloth/gemma-3-12b-it-GGUF:Q4_K_M + mmproj | 7.3+0.9 GB | vision: VQA/charts |
| `mistral-medium-3.5` | bartowski/…Mistral-Medium-3.5-128B-GGUF:Q4_K_M | 78 GB dense | ~2 tok/s |
| `minimax-m2` | unsloth/MiniMax-M2.7-GGUF:UD-IQ4_XS | 101 GB MoE | ~0.9 tok/s (iGPU) |

- Per-model flags/sampling live in **`config.yaml`** (live-reloaded; `-watch-config`); ids/aliases match Bifrost/clients.
- GPU tuning (iGPU ≈48 GB usable VRAM): MoE models that fit → `-ngl 999`; the big ones offload via
  `--n-cpu-moe N` (MiniMax) or partial `-ngl` (Mistral) + `-t 16` for CPU-side compute.
- **MiniMax/Mistral are memory-bound** on the iGPU (slow); both go fast once the RTX 5080 adds VRAM.

## The `llama` command (host)
`~/.local/bin/llama` execs tools inside the container:
`llama cli -hf <repo>:<quant>` · `llama server --version` · `llama bench -m /models/gguf/qwen3-coder-30b.gguf`
· `llama quantize in.gguf out.gguf Q4_K_M`.

## Verify
- GPU:  `docker run --rm --device /dev/kfd --device /dev/dri lario/llamacpp:latest llama-server --list-devices` → `ROCm0`.
- API:  `curl -s localhost:11434/v1/models | jq -r '.data[].id'`
- Chat: `curl -s localhost:11434/v1/chat/completions -d '{"model":"gemma4","messages":[{"role":"user","content":"hi"}]}'`

## Known issues
- **gemma4 / glm-4.7-flash**: the original *Ollama blobs* failed on b9842 (`wrong number of tensors` —
  tensor-layout mismatch). **Resolved** by using fresh Unsloth GGUFs (load fine, run fast); the blobs were deleted.
- **Vision**: use `qwen2.5-vl` (OCR/docs/diagrams) or `gemma3-vision` (general VQA/charts) — both work on
  b9842, addressed directly. **llama-3.2-vision was dropped** — b9842 lacks its `mllama` arch
  (`unknown model architecture: 'mllama'`). Their mmprojs are curl'd into `~/.cache/huggingface/mmproj/`.
- The **`hf` CLI is broken** here (typer/click clash under Python 3.14) — use `llama download -hf`/`curl`.
- **Dropped** (not restored): meditron, meditron:70b, llama3.3, translategemma. (qwen3-coder re-added.)
- `amdgpu.ids: No such file` on startup is cosmetic (friendly-name lookup only).

## Rollback
The old `ollama` compose service is in git history (`git show HEAD:docker-compose.yml`), but the 172 GB
Ollama model store was **deleted** to free disk — a full rollback would need re-pulling those models.
The llamacpp image is self-contained, so day-to-day you only edit `config.yaml`.
