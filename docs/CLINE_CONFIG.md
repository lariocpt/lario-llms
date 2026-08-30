# cline config — local models (host CLI, two endpoints)

How to point **cline** at the **local** LLM endpoints.

> **Rewritten 2026-08-30.** This file previously described cline inside the podman
> **t2-devbox** (`host.containers.internal:11434`, the `llamacpp` container). That devbox
> went with the Timbuk2 identity on **2026-08-07**, and there has been no llamacpp container
> since the CachyOS migration. cline now runs as a **host CLI** on each machine; its config
> is `~/.cline/data/settings/providers.json`.

> Using **Claude Code / Codex / other paid (cloud) agents** for office work instead? See
> **[AGENTS.md](AGENTS.md)**. This file is only about driving cline off the free local models.

## Two providers, two jobs

Since the 2026-08-23 fleet GPU rebalance there are **two** local endpoints (the why lives in
`../llama-cpp/agent-config.yaml`): a **coder** on l-dev-ai and the **agents' model** on
bigcachy's RX 7900 XT. cline gets a provider for each:

| Provider key | Base URL (bigcachy) | Model | What it is |
|---|---|---|---|
| `openai-compatible` | `http://192.168.2.1:11434/v1` | `main` | the **coder** — l-dev-ai's native llama-swap. `main` = qwen3.8 since 2026-08-30 and **follows `main-model.sh`** |
| `xt-agent` | `http://127.0.0.1:11436/v1` | `agent` | **Muse Glimmer 30B Q4** on bigcachy's RX 7900 XT (`agent-llm` container) — the same model the Hermes agents run on, 34.9 tok/s |

The base URLs are **per-machine** (the API is keyless — LAN/tailnet only, see
`docker-compose.bigcachy.yml`):

- **coder** (l-dev-ai `:11434`): `192.168.2.1` from bigcachy (direct 2.5G cable);
  `127.0.0.1` on l-dev-ai itself.
- **agent** (`agent-llm` `:11436`): `127.0.0.1` on bigcachy; `192.168.2.2` on l-dev-ai
  (direct cable); `100.127.91.5` on mini-mobile (tailnet — works while roaming off-LAN).

Verify (from bigcachy):
```sh
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.2.1:11434/v1/models   # coder — want 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:11436/v1/models     # agent — want 200
```

## cline settings

- **Provider type:** `OpenAI Compatible` for both (NOT the native "cline" cloud provider —
  that's the sign-in prompt).
- **API key:** `dummy` (any non-empty string — neither endpoint authenticates).
- **Model:** `main` on the coder provider, `agent` on `xt-agent`. Both are **aliases, not
  model ids** — `main` follows the global toggle on l-dev-ai, `agent` maps to whatever
  `agent-config.yaml` serves. Pin a specific id only to deliberately bypass that.
- **Reasoning:** both actives (qwen3.8 and Muse Glimmer) are reasoning models, already capped
  server-side with `--reasoning-budget 2048`. Leave `enabled: false` unless you want cline's
  own reasoning UI; an over-tight `max_tokens` yields an empty answer with
  `finish_reason: length`.

`providers.json` (`~/.cline/data/settings/providers.json`, bigcachy values):

```json
{
  "version": 1,
  "lastUsedProvider": "openai-compatible",
  "providers": {
    "openai-compatible": {
      "settings": {
        "provider": "openai-compatible",
        "apiKey": "dummy",
        "baseUrl": "http://192.168.2.1:11434/v1",
        "model": "main",
        "reasoning": { "enabled": false }
      },
      "tokenSource": "manual"
    },
    "xt-agent": {
      "settings": {
        "provider": "openai-compatible",
        "apiKey": "dummy",
        "baseUrl": "http://127.0.0.1:11436/v1",
        "model": "agent",
        "reasoning": { "enabled": false }
      },
      "tokenSource": "manual"
    }
  }
}
```

Restart cline after editing so it reloads the config.

## Sensible models to drive an agent

List live ids per endpoint: `curl -s <baseUrl>/models`.

| Model / alias | Endpoint | Speed | Per-slot ctx | Use as agent brain? |
|----------|-------|-------|--------------|---------------------|
| **`agent`** (= Muse Glimmer 30B Q4) | bigcachy `:11436` | **34.9 tok/s** | 131072 (3 slots, reject-not-queue at 4th) | **Yes — this is what the Hermes agents use.** Best agentic scores in the set (MCP Atlas 75.5). Over-ceiling requests fail fast with a typed HTTP 400 `exceed_context_size_error`, not a hang. |
| **`main`** (= qwen3.8) | l-dev-ai `:11434` | not yet measured | 245760 (4 slots) | **The coder** — pick it when you are mostly writing and running code. Follows `main-model.sh`. |
| `qwen3.6` | l-dev-ai `:11434` | 11.93 tok/s | — | Rollback coder (SWE-Bench 77.2); switch via `main-model qwen3.6`. |
| `muse-glimmer-fast` | l-dev-ai `:11434` | 13.94 tok/s | — | Rollback for the old single-backend setup; superseded by `agent` (same model, 2.5× faster on the XT). |

On l-dev-ai only **one** big model is resident at a time (`groups.big`, `swap: true`), so
picking a non-`main` id there means switching the whole box. The agent endpoint has no such
coupling — Muse Glimmer is permanently resident (`ttl: 0`) and swaps nothing.

**Rule of thumb:** leave the coder provider on **`main`** and let `main-model` decide what that
means; use **`xt-agent`** for agentic/tool-heavy loops. The old dilemma (thrash the fleet to
trade 1.2 SWE-Bench points of coding for agentic quality) is gone — the two jobs no longer
share a GPU.

> **Speed is bandwidth, not quantisation quality** (l-dev-ai measurement, 2026-08-12): decode
> there tracks weight size almost exactly, so a bigger quant buys quality strictly at the cost
> of tok/s. The XT's 34.9 tok/s on the *same* Q4 weights is the same rule on faster memory —
> don't go looking for a broken kernel either way.
