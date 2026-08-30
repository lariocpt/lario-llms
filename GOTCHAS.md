# 🛑 Lario LLMs Gotchas & Troubleshooting

This document tracks known edge cases, weird behaviors, and hard-won fixes across the agentic tech stack (Bifrost, llama-swap, llama.cpp, Discord Hermes bots, and VS Code extensions).

### 1. The OpenCode / Cline "Double Prefix" Stripping Bug
**Symptom:** OpenCode or Cline returns `HTTP 404: no router for requested model`.
**Cause:** The OpenAI compatibility layer within OpenCode/Cline's UI strips the *first* provider string from the model name before sending it to the API. If you pass `ollama/smart`, it strips `ollama/` and sends just `smart` to Bifrost. Bifrost then rejects it because `smart` lacks a provider prefix.
**Fix:** In the UI, supply the model as `ollama/ollama/smart`. The UI will strip the first `ollama/`, sending `ollama/smart` to Bifrost, which successfully routes it!

### 2. The `llama-swap` IPv6 Proxy Loopback Crash
**Symptom:** Logs for `llama.cpp` are filled with `http: proxy error: dial tcp [::1]:5801: connect: connection refused`.
**Fix:** In `llama-cpp/config.yaml` (and the Windows setup yamls), change `--host 127.0.0.1` to `--host ::`. This forces the server to bind to *both* IPv4 and IPv6 interfaces, completely resolving the proxy connection refusal.

### 3. Bifrost Gateway Auto-Resolve Rejecting Model Names
**Symptom:** Discord bots return `HTTP 400: provider is required in model field — no providers found for model "qwen3-coder:30b" in model catalog to auto-resolve`.
**Cause:** The model string `qwen3-coder:30b` requested by the Discord agent isn't natively known by Bifrost's static datasheet, so it refuses to attach a provider. 
**Fix:** Add the model as a recognizable alias in the downstream `llama-swap` config AND ensure the agent requests a known rule (like `smart`) or the exact mapped alias. Note that when Bifrost auto-resolves to the `ollama` provider, it forwards the model as `ollama/qwen3-coder:30b`, so this prefixed version *must* also exist in your `llama-swap` aliases array!

### 4. AMD GPU ROCm Silently Falling Back to CPU (Extremely Slow Generation)
**Symptom:** The model loads and generates text, but it's excruciatingly slow (~0.3 tokens per second for a 27B model).
**Cause:** The `llamacpp` Docker container lacks access to the host's AMD hardware identification files (`amdgpu.ids`), throwing `/usr/share/libdrm/amdgpu.ids: No such file or directory`. Without this, ROCm fails to engage, and `llama-server` secretly falls back to CPU-only execution.
**Fix:** Explicitly mount the host's DRM directory into the container. In your `docker-compose.override.yml`, under `llamacpp`, add:
```yaml
    volumes:
      - /usr/share/libdrm:/usr/share/libdrm:ro
```
Once mounted, ROCm correctly identifies the spoofed `gfx1102` architecture and inference jumps to blazing-fast GPU speeds (~10+ tokens/sec).

**Addendum (2026-08-30 — `agent-llm` on bigcachy's RX 7900 XT):** the item above was written in the gfx1102-spoof era; two halves of it age differently on the XT (gfx1100):
- The **`/usr/share/libdrm` mount still applies** — without `amdgpu.ids` the `agent-llm` container falls back to CPU at ~0.3 tok/s while looking perfectly healthy, exactly as described. It's in `docker-compose.bigcachy.yml`.
- **Do NOT carry over `HSA_OVERRIDE_GFX_VERSION`.** The 7900 XT is a first-class ROCm target — the override exists for iGPUs that misreport, and setting the spoof on this card would only *mask a real detection failure* (you'd rather see the error than silently run on the wrong code path). `agent-llm` deliberately sets no HSA override.
- One extra trap in the same image: `ghcr.io/ggml-org/llama.cpp:server-rocm` keeps `llama-server` at **`/app/llama-server`** — it is **not on `PATH`**. A llama-swap `cmd:` that says bare `llama-server` fails with `executable file not found in $PATH`; `llama-cpp/agent-config.yaml` uses the absolute path.

### 5. HuggingFace Cache Filling Up the Root OS Partition
**Symptom:** Host-level Python scripts or HF CLI tools download models into `~/.cache/huggingface`, quickly filling up the root OS partition instead of the dedicated AI storage drive.
**Cause:** By default, HuggingFace tools always cache to `~/.cache/huggingface` unless explicitly told otherwise. If Docker is also using a bind-mount, it can create a messy reliance on host-level symlinks.
**Fix:** Set the `HF_HOME` environment variable globally in your `~/.zshrc` to point directly to the optimized XFS AI storage drive:
```bash
export HF_HOME=/mnt/AI_Models/huggingface
```
This ensures all host-level scripts and Docker containers natively cache directly to the dedicated XFS drive, perfectly in sync.

### 6. Discord Bots (and other downstream agents) Crashing with Bifrost 400 Errors
**Symptom:** Your Discord Hermes Bots or other downstream consumers suddenly stop working, logging: `HTTP 400: provider is required in model field — no providers found for model "smart"`.
**Cause:** Bifrost acts as a strictly-typed AI SDK gateway. It *must* know the provider for the model it is proxying. While it has an auto-resolve datasheet for some standard models (like `gpt-4o`), custom local routing profiles like `smart` or `qwen-routing` are unknown to its static DB. If an agent requests `smart`, Bifrost drops it.
**Fix:** Any downstream API consumer (Discord Bots, Antigravity CLI, etc.) must explicitly pass the Bifrost provider prefix in the model string. Update their configuration from `model: smart` to `model: ollama/smart`.

### 7. OpenCode UI Flooded with Duplicate "backend match" Models
**Symptom:** In OpenCode, opening the model selector dropdown reveals the same string (e.g., "backend match") repeated 4 or 5 times instead of your actual model names.
**Cause:** `llama-swap` actively serves a list of *all* available models and aliases via its `/v1/models` endpoint. OpenCode automatically fetches this list, prepends the provider prefix (e.g., `openai/`), and then cross-references it with `opencode.jsonc`. If your config file tries to override a model's UI name using `{"name": "backend match"}`, OpenCode will erroneously apply that exact same label to *every single alias* that `llama-swap` broadcasted, entirely overriding the real names.
**Fix:** When connecting OpenCode directly to `llama-swap`, do *not* inject static `"name"` overrides for aliases in `opencode.jsonc`. Remove those lines and allow OpenCode to organically display the raw IDs returned by `llama-swap`.

### 8. A Container Reporting "healthy" While Every Request Fails (Inherited Healthchecks)
**Symptom:** `docker ps` shows `vision — Up 4 days (healthy)`, but every image call returns `500 {"error":"unspecific error: upstream command exited prematurely","src":"llama-swap"}`. Nothing alerts. Discovered 2026-08-01 after **five days** of total outage (2026-07-27 → 08-01): 81 failed model starts and 76 failed agent calls, entirely unnoticed.
**Cause:** Two separate traps compounding.

1. **The healthcheck was inherited, not written.** `ghcr.io/ggml-org/llama.cpp` ships a `HEALTHCHECK` for `llama-server`'s own `/health`. The `vision` service overrides `entrypoint` to run **llama-swap** instead — a *different program* that also answers 200 on `/health`, regardless of whether any upstream model can load. The check silently retargeted and became meaningless. Overriding `entrypoint`/`command` does **not** clear an image's inherited `HEALTHCHECK`; you must override it explicitly.
2. **llama-swap hides the real error.** When the upstream `llama-server` dies during startup, all the client sees is `upstream command exited prematurely`. The actual cause is only visible by running the `cmd:` from the model's config by hand inside the container:
   ```
   docker exec vision sh -lc '/app/llama-server --host 0.0.0.0 --port 5801 <rest of cmd from vision-config.yaml>'
   ```
   That surfaced the truth immediately: `cudaMalloc failed: out of memory` → `failed to allocate buffer for kv cache`.

**Fix:** Both halves, and note that **no cheap endpoint can detect this** — `/health` is llama-swap liveness, `/v1/models` reads config and answers 200 even when the model cannot load, `/running` returns `[]` when idle *and* when broken, and `/metrics` is host CPU/RAM telemetry with no per-model error counters. Only a real inference proves the model serves.
- Override the healthcheck explicitly in `docker-compose.bigcachy.yml` (catches a missing/renamed model — the cheap half).
- Run `scripts/vision-monitor.sh` on the `vision-monitor.timer` systemd user unit for the rest. It scans llama-swap's log for `exited prematurely` every 5 min (free, pins nothing) and does one real 1×1-image completion at most every 12h, so it never defeats the `ttl: 900` unload the GPU shares with `rag_api`.

**Lesson:** Never trust `(healthy)` on a container whose entrypoint you replaced. Ask what program is actually answering the probe.

### 9. llama.cpp's Host Prompt Cache (`--cache-ram`) Aborting the Server
**Symptom:** `llama-server` SIGABRTs at runtime. llama-swap logs `[WARN] group: running qwen3.6 exited: [qwen3.6] upstream exited unexpectedly` and returns 502; clients that were mid-request just time out. Downstream this reads as *"Hermes compaction hangs"*, not as a crashed server.

**Cause:** `-cram/--cache-ram` (the host-RAM prompt cache) defaults to **8192 MiB — on unless you disable it**. It checkpoints a slot's KV state whenever that slot is reassigned to a different prompt, and on build 10027 that path aborts:

```
ggml_abort <- ggml_backend_tensor_get <- llama_context::state_seq_get_data
            <- server_slot::prompt_save(server_prompt_cache&)
```

Adding `--cache-reuse 256` on 2026-08-05 16:49 changed which slot gets picked and how often a prompt is saved, turning a latent abort into a constant one — 13 crashes in the next five hours, against zero in the five days the journal covered before it. The binary never changed.

Hermes' auto-compaction is the reliable trigger: it presents a brand-new prompt prefix, which is exactly the evict-and-save path. Crash timestamps matched compression attempts in the agent logs to the second.

**Fix:** `--cache-ram 0` in `main-model.sh`. It disables `prompt_save` only; `--cache-reuse`'s in-slot KV shifting is a *separate* cache and keeps working, so the partial-prefix reuse the 12-slot budget depends on is retained.

**Lesson:** `--cache-reuse` and `--cache-ram` are two different caches with confusingly similar names. When a crash appears right after a flag change, read the stack — the flag you added is not always the flag that crashed.

### 10. Vision Encoder OOM on Large Images (Pixels, Not Bytes)
**Symptom:** `vision` answers small test images fine, then returns 502 in ~4s on a real one. `upstream exited unexpectedly`; the container still reports `(healthy)`.

**Cause:** Image tokens scale with **pixels**. The headroom for this box was measured against a 1080p frame, but a real product image off muscledynamix.co.za is 2334×3157 = **7.4MP** — ~6× that, ~9,400 image tokens. The encoder's matmul pool blew the remaining VRAM mid-request:

```
CUDA error: out of memory / cuMemCreate(&handle, reserve_size, &prop, 0)
ggml_cuda_pool_vmm::alloc <- ggml_cuda_mul_mat_q <- mtmd_helper_decode_image_chunk
```

Note the file size is a red herring — the crashing PNG was only 300KB. Note also this is a *runtime* crash, so llama-swap logs `upstream exited unexpectedly`, **not** the `exited prematurely` string that gotcha #8's `vision-monitor.sh` scans for.

**Fix:** `--image-max-tokens 2048` in `llama-cpp/vision-config.yaml`. A token cap bounds the allocation for *any* input image, so no future 12MP phone photo reproduces it; more VRAM would only move the threshold. 2048 is 2× the 1024 floor llama.cpp warns Qwen-VL needs for grounding accuracy.

**Lesson:** Size a vision box by megapixels it must accept, not by the test image that happened to be at hand.

### 11. llama.cpp Rebuilt Past Build 10027 — Both Workarounds Re-tested (2026-08-13)
**Symptom:** None. Recorded because the rebuild invalidated two long-standing workarounds; both have now been measured rather than assumed.

**Cause:** Adding Muse Glimmer on 2026-08-11 required a new llama.cpp: the `muse-glimmer` arch did not exist in build 10027 (2026-07-15), in the binary *or* the source tree. `~/llama.cpp` was pulled 339 commits to `704485942` and `build-vulkan` rebuilt **in place**, so every model — minimax, mistral, qwen3.6, gemma4 — moves to build **10367** on the next llama-swap restart.

Two flags in `main-model.sh` existed purely as build-10027 workarounds. **Both were re-tested on 10367 on 2026-08-13**, on a scratch server so the live fleet was never at risk:

- **`--cache-ram 0` is no longer required — the SIGABRT is fixed.** Ran a scratch server with the host prompt cache *enabled* (the 8192 MiB default) and drove 6 distinct 3.3k-token prompts through 2 slots, forcing a slot reassignment on every request after the second. The log confirms the crashing path actually executed — `saving idle slot to prompt cache`, `created context checkpoint 1 of 32` — and the server survived all six with zero `ggml_abort`. **The flag is still set**, deliberately: removing it is a behaviour change on a live fleet and buys only faster warm starts, which matter less now that there are 20 slots. Drop it when you want that benefit; the crash risk is gone.
- **`--cache-reuse 256` was a no-op and has been removed** from the three `muse-glimmer` entries. Build 10367 rejects it for this architecture at load time: `cache_reuse is not supported by this context, it will be disabled`. It was silently doing nothing. Left in place on `qwen3.6`, which was not re-tested — its architecture differs and it may still be honoured there.

Also new on 10367: `--mmap`/`--no-mmap` (and `--mlock`, `-dio`) are **deprecated** in favour of `-lm`/`--load-mode`. `emit_model()` now passes `--load-mode none`. Note the deprecation message says *"use `--load-mode mmap` instead"* for **both** spellings, which is wrong for us — the equivalent of `--no-mmap` is **`none`** ("no special loading mode"). Values: `auto` (default) | `none` | `mmap` | `mlock` | `mmap+mlock`.

**Fix / rollback:** the complete build-10027 `bin/` directory is preserved at `~/llama.cpp/build-vulkan-10027-backup` (86 MB). To roll back, point `~/llama.cpp/build-vulkan/bin` back at it — do **not** copy just `llama-server`, which is a 16 KB shim that dynamically links `libllama.so`, `libggml-vulkan.so` and five other objects from the same directory. A binary-only backup silently loads the *new* libraries and is not a rollback at all.

**Lesson:** when a rebuild is unavoidable, the fleet does not move to the new build at build time — it moves at the next restart, which may be an unattended `Restart=always` crash-restart hours later. Back up the whole link closure, not the entry point.
