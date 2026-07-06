# 🛑 Lario LLMs Gotchas & Troubleshooting

This document tracks known edge cases, weird behaviors, and hard-won fixes across the agentic tech stack (Bifrost, llama-swap, llama.cpp, Discord Hermes bots, and VS Code extensions).

### 1. The OpenCode / Cline "Double Prefix" Stripping Bug
**Symptom:** OpenCode or Cline returns `HTTP 404: no router for requested model`.
**Cause:** The OpenAI compatibility layer within OpenCode/Cline's UI strips the *first* provider string from the model name before sending it to the API. If you pass `ollama/smart`, it strips `ollama/` and sends just `smart` to Bifrost. Bifrost then rejects it because `smart` lacks a provider prefix.
**Fix:** In the UI, supply the model as `ollama/ollama/smart`. The UI will strip the first `ollama/`, sending `ollama/smart` to Bifrost, which successfully routes it!

### 2. The `llama-swap` IPv6 Proxy Loopback Crash
**Symptom:** Logs for `llama.cpp` are filled with `http: proxy error: dial tcp [::1]:5801: connect: connection refused`.
**Cause:** The Go-based `llama-swap` proxy defaults to attempting IPv6 loopback (`[::1]`), but `llama-server` is explicitly bound strictly to IPv4 (`127.0.0.1`).
**Fix:** In `llama-cpp/config.yaml` (and the Windows setup yamls), change `--host 127.0.0.1` to `--host localhost`. This forces the server to bind to *both* IPv4 and IPv6 interfaces, preventing the proxy connection refusal.

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

### 5. HuggingFace Cache Filling Up the Root OS Partition
**Symptom:** Host-level Python scripts or HF CLI tools download models into `~/.cache/huggingface`, quickly filling up the root OS partition instead of the dedicated AI storage drive.
**Cause:** By default, HuggingFace tools always cache to `~/.cache/huggingface` unless explicitly told otherwise. If Docker is also using a bind-mount, it can create a messy reliance on host-level symlinks.
**Fix:** Set the `HF_HOME` environment variable globally in your `~/.zshrc` to point directly to the optimized XFS AI storage drive:
```bash
export HF_HOME=/mnt/AI_Models/huggingface
```
This ensures all host-level scripts and Docker containers natively cache directly to the dedicated XFS drive, perfectly in sync.
