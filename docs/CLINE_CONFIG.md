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
- **Model:** prefer the **`ollama/smart`** consumer alias (or `main`) — it follows the global
  toggle, so cline moves with the fleet when you run `main-model <name>`. Pin a specific id only
  when you deliberately want to bypass the toggle.
- **Reasoning:** the active model (Muse Glimmer) is a reasoning model and is already capped
  server-side with `--reasoning-budget 2048`. Leave `enabled: false` unless you want cline's own
  reasoning UI; an over-tight `max_tokens` yields an empty answer with `finish_reason: length`.

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
        "model": "ollama/smart",
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

Only **one** big model is resident at a time (`groups.big`, `swap: true`), so "picking a model"
really means picking what the whole fleet runs. Speeds measured 2026-08-12 on build 10367.

| Model id | Speed | Per-slot ctx | Tool-calling | Use as agent brain? |
|----------|-------|--------------|--------------|---------------------|
| **`muse-glimmer-fast`** | **13.94 tok/s** | 131072 | ✅ built for it | **Yes — the active default.** Best agentic scores in the set (MCP Atlas 75.5 vs qwen3.6's 62.5). |
| **`qwen3.6`** | 11.93 tok/s | 122880 | ✅ | **Yes — the better *coder*** (SWE-Bench 77.2 vs 76.0, plus TerminalBench/OSWorld). Pick it for heavy code work. |
| **`muse-glimmer-q8`** | 7.21 tok/s | 131072 | ✅ | Near-lossless Muse. Fine, but 40% slower for ~1% quality. |
| **`gemma4`** | — | 122880 | ~ | OK general agent; the two above are better. |

Not sensible as an agent driver:

| Model id | Why not |
|----------|---------|
| `muse-glimmer` (BF16) | 4.05 tok/s. An 8192-token answer takes ~34 min — past the agents' stale timeout. |
| `mistral` | Dense 128B → far too slow for an agent loop. |
| `minimax` | ~87 GB MoE, memory-bound and slow. |

**Rule of thumb:** leave cline on `ollama/smart` and let `main-model` decide. Muse Glimmer for
agentic/tool-heavy work, qwen3.6 when you are mostly writing and running code. The coding gap is
1.2 SWE-Bench points — real, but not worth thrashing the fleet over.

> **Speed is bandwidth, not quantisation quality.** Decode on this box tracks weight size almost
> exactly (predicting from one quant lands within ~5% on all the others), so a bigger quant buys
> quality strictly at the cost of tok/s. Don't go looking for a broken kernel.
