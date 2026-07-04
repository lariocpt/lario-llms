# cline config — local models inside the dev container

How to point **cline** at the **local** LLM stack (llama.cpp + llama-swap, served by the `llamacpp`
container). This repo's **t2-devbox is a podman container**, while the LLM stack runs under **docker** —
which is exactly why the base URL matters (see below).

> Using **Claude Code / Codex / other paid (cloud) agents** for office work instead? See
> **[AGENTS.md](AGENTS.md)**. This file is only about driving cline off the free local models.

## The one thing that trips people up — which base URL

Inside a container, **`127.0.0.1` is the container itself** — llama-swap isn't there, so cline
reports **"cannot access the API"**. The right hostname depends on the container's runtime/network,
because the LLM stack (`llamacpp`/`ollama`) runs under **docker** on `lario-net`:

```
# This repo's t2-devbox is a PODMAN container on its own network → use the host gateway:
✅ http://host.containers.internal:11434/v1   ← use this from t2-devbox
✅ http://host.docker.internal:11434/v1       ← also works

# Only if cline runs in a DOCKER container joined to lario-net (e.g. lario-dev-pop/mint/ubuntu):
   http://ollama:11434/v1   /   http://llamacpp:11434/v1

❌ http://127.0.0.1:11434/v1   ← never right inside a container
❌ http://ollama:11434/v1      ← does NOT resolve from the podman t2-devbox (docker-only name)
```

Verify from inside t2-devbox:
```sh
curl -s -o /dev/null -w '%{http_code}\n' http://host.containers.internal:11434/v1/models   # want 200
```

## cline settings

- **Provider:** `OpenAI Compatible`  (NOT the native "cline" cloud provider — that's the sign-in prompt)
- **Base URL:** `http://host.containers.internal:11434/v1`  (from the podman t2-devbox)
- **API key:** `dummy`  (any non-empty string — llama-swap does not authenticate)
- **Model:** one of the ids below
- **Reasoning:** `enabled` for `minimax-m2`, `disabled` otherwise

`providers.json` (`~/.cline/data/settings/providers.json` inside the container):

```json
{
  "version": 1,
  "lastUsedProvider": "openai-compatible",
  "providers": {
    "openai-compatible": {
      "settings": {
        "provider": "openai-compatible",
        "apiKey": "dummy",
        "baseUrl": "http://host.containers.internal:11434/v1",
        "model": "qwen3-coder:30b",
        "reasoning": { "enabled": false }
      },
      "tokenSource": "manual"
    }
  }
}
```

Restart cline after editing so it reloads the config.

## Sensible models to drive an agent

Pick by the job. List live ids with `curl -s http://host.containers.internal:11434/v1/models` (from t2-devbox).

| Model id | Speed | Context | Tool-calling | Use as agent brain? |
|----------|-------|---------|--------------|---------------------|
| **`qwen3-coder:30b`** | ~75 tok/s | 32k | ✅ built for it | **Yes — default for coding agents (cline/opencode).** Fast loop. |
| **`glm-4.7-flash`** | ~49 tok/s | 32k | ✅ | **Yes — solid general-purpose agent**, fast. |
| **`gemma4`** (26B-A4B) | ~44 tok/s | 32k | ~ | OK general agent; qwen3-coder is better for code. |
| **`minimax-m2`** (Q3_K_S) | ~18 tok/s | 32k | ✅ | **Heavy-reasoning agent** — for hard problems. Slower + "thinks" every turn; set `reasoning: enabled` and a generous max_tokens. |

Not sensible as an agent driver:

| Model id | Why not |
|----------|---------|
| `mistral-medium-3.5` | Dense 128B → ~2–3 tok/s. Loads/works but far too slow for an agent loop. |
| `qwen2.5-vl`, `gemma3-vision` | Vision models — call them directly for OCR/image tasks, not for driving an agent. |

**Rule of thumb:** `qwen3-coder:30b` for day-to-day agentic coding; switch to `minimax-m2` only when
you want the heavy reasoner and can tolerate the slower, thinky loop. All the "yes" models are MoE
and run fully on the GPU (see `/mnt/Shared/personal/lario-llms/` — llama-swap config + `docs/cline.md`).

> Big-model note: `minimax-m2` and `mistral-medium-3.5` require `-dio` in the llama-swap config
> (ROCm mmap→HIP upload hang, llama.cpp #19482). Already set — don't remove it.
