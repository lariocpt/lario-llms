# Running NanoClaw against the local Bifrost AI

The NanoClaw install does **not** live in this repo. It runs from `~/nanoclaw`
(a self-contained clone with its own `.git`, `data/`, and `.env`). This file
documents how it's wired to the local Bifrost gateway and Discord so the setup
is reproducible from scratch.

> **TL;DR of the working setup:** the container agent uses the **OpenCode**
> provider (not Claude Code), pointed at the local **Bifrost** gateway's
> OpenAI-compatible endpoint, with credentials brokered by the local **OneCLI**
> gateway and chat via the **Discord** Chat-SDK adapter. Three small host-side
> code patches are required (see [Local code patches](#local-code-patches)) —
> without them the agent connects but never replies.

## Where things live

| Thing | Location |
|-------|----------|
| Install | `~/nanoclaw` |
| Service (systemd user unit) | `nanoclaw-v2-eda8560b` → `~/.config/systemd/user/nanoclaw-v2-eda8560b.service` |
| Agent container image | `nanoclaw-agent-v2-eda8560b:latest` |
| Host `.env` | `~/nanoclaw/.env` |
| Logs | `~/nanoclaw/logs/nanoclaw.log`, `~/nanoclaw/logs/nanoclaw.error.log` |
| Central DB (users, groups, wiring, provider config) | `~/nanoclaw/data/v2.db` |
| Per-session DBs | `~/nanoclaw/data/v2-sessions/<agent-group>/<session>/{inbound,outbound}.db` |
| Bifrost gateway | `127.0.0.1:8080` (this repo's `docker-compose.yml` + `bifrost/`) |
| OneCLI gateway | `onecli` + `onecli-postgres-1` containers, `172.17.0.1:10254` |
| Your OpenCode CLI config (reference) | `~/.config/opencode/opencode.jsonc` |

> The slug `eda8560b` is `sha1("/home/lario/nanoclaw")[:8]`. It's derived from
> the install path — **if you move the install, the service name and image tag
> change** and both must be regenerated (see [Relocating](#relocating-the-install)).

---

## Architecture in one paragraph

A single host Node process (the systemd unit) receives Discord messages, routes
them into a per-session SQLite `inbound.db`, and spawns a Docker **agent
container** per session. Inside the container an **agent provider** drives the
LLM. Two providers matter here:

- **`claude`** (default) — runs **Claude Code** (the Anthropic Agent SDK). It is
  tuned for real Anthropic models and sends Anthropic-only request features
  (extended *thinking*, prompt caching, beta headers). Local Ollama models served
  through Bifrost reject these (`400 ... does not support thinking`), so **this
  provider does not work against Bifrost/Ollama.**
- **`opencode`** — runs the **OpenCode** harness against any OpenAI-compatible
  endpoint. This is the provider we use for local Bifrost/Ollama models.

**This install uses the `opencode` provider.** The provider is selected
**per-agent-group in the central DB**, not in `.env` (see
[Selecting the provider](#selecting-the-provider)).

---

## Model routing — Bifrost via OpenCode

Bifrost exposes two compatible surfaces on `:8080`:

| Surface | Path | Used by |
|---------|------|---------|
| OpenAI-compatible | `/v1/chat/completions` | **OpenCode (our setup)** |
| Anthropic-compatible | `/anthropic/v1/messages` | Claude Code (unused here) |

Relevant `~/nanoclaw/.env` keys:

```dotenv
TZ=Africa/Johannesburg

# Local OneCLI gateway for credential brokering (NOT the api.onecli.sh cloud,
# which returns 401 without a cloud key).
ONECLI_URL=http://172.17.0.1:10254

# OpenCode provider config. OPENCODE_PROVIDER is the OpenCode provider *type*;
# `openai` is the built-in OpenAI-compatible client. The model id is in
# `provider/model` form. We use a hybrid local setup (Qwen 3 Coder 30B for the
# main agent logic, and Gemma 4 8B for lighter/small sub-tasks) to optimize
# accuracy, speed, and memory usage on our 64GB system.
OPENCODE_PROVIDER=openai
OPENCODE_MODEL=openai/qwen3-coder:30b
OPENCODE_SMALL_MODEL=openai/gemma4:latest

# Reused by the OpenCode container provider as the upstream baseURL. MUST be the
# OpenAI-compatible /v1 endpoint for OpenCode (NOT /anthropic — that path is only
# for the Claude Code provider). The container reaches the host via
# host.docker.internal.
ANTHROPIC_BASE_URL=http://host.docker.internal:8080/v1

# Bifrost is keyless locally, but the SDK always sends an Authorization header,
# so a placeholder token must be present.
ANTHROPIC_AUTH_TOKEN=local-bifrost

# Discord Chat-SDK adapter.
DISCORD_BOT_TOKEN=...
DISCORD_APPLICATION_ID=...
DISCORD_PUBLIC_KEY=...
```

> **Comment hygiene:** keep `#` comments on their own lines. A `#` inside a value
> is kept verbatim and will corrupt a model id or URL.

### Available Bifrost models

```bash
curl -s http://127.0.0.1:8080/v1/models \
  | python3 -c "import sys,json;[print(m['id']) for m in json.load(sys.stdin)['data']]"
```

Bifrost lists them with an `ollama/` prefix (e.g. `ollama/qwen3-coder:30b`), but
under OpenCode's `openai` provider you reference the **bare** id
(`qwen3-coder:30b`) — which is what `OPENCODE_MODEL=openai/qwen3-coder:30b` resolves to.
Your standalone OpenCode CLI config (`~/.config/opencode/opencode.jsonc`) uses
the same bare ids under a custom `bifrost` provider, for reference.

### Selecting the provider

The provider is stored per-agent-group in the central DB and is **not** set by
`.env`. Set it with the admin CLI:

```bash
cd ~/nanoclaw
./bin/ncl groups list                                   # find the agent-group id
./bin/ncl groups config update --id <agent-group-id> --provider opencode
./bin/ncl groups config get --id <agent-group-id>       # verify "provider": "opencode"
```

The `model` field shown by `config get` is **only used by the `claude` provider**.
OpenCode takes its model from `OPENCODE_MODEL` in `.env`, so a stale value there
is harmless.

---

## Local code patches

The stock NanoClaw + OpenCode skill does not, on its own, route OpenCode to a
**host-local** gateway behind the OneCLI proxy. Three small host-side patches in
`~/nanoclaw/src/` make it work. **These are local modifications — `git pull`,
`/update-nanoclaw`, or re-running `/add-opencode` can revert them.** After any
edit run `pnpm run build` and restart the service.

1. **`src/providers/opencode.ts`** — inject `ANTHROPIC_BASE_URL` into the
   container and read all `OPENCODE_*` / `ANTHROPIC_BASE_URL` from `.env` (via
   `readEnvFile`) as a fallback. Stock code only read them from `process.env`
   (empty, because the unit has no `EnvironmentFile`) and never passed
   `ANTHROPIC_BASE_URL` to the container, so OpenCode had no baseURL.

2. **`src/container-runner.ts`** — after the OneCLI gateway is applied, append a
   `NO_PROXY=host.docker.internal,localhost,127.0.0.1` bypass whenever the
   provider's `ANTHROPIC_BASE_URL` points at a local host. OneCLI otherwise sets
   `NO_PROXY=` (empty) last, forcing Bifrost calls through the proxy — which
   **cannot reach `host.docker.internal:8080`** (returns `000`). The bypass makes
   the container talk to Bifrost directly while external APIs still route through
   the proxy for credential injection.

3. **`src/providers/index.ts`** — `import './claude.js';` (alongside
   `./opencode.js`). Only needed if you ever switch *back* to the `claude`
   provider with a custom endpoint; harmless otherwise. The `claude` provider's
   `ANTHROPIC_BASE_URL` injection is dormant until this barrel imports it.

Quick check that all three are in place:

```bash
cd ~/nanoclaw
grep -q "import './claude.js'" src/providers/index.ts            && echo "patch 3 ok"
grep -q "Local-endpoint NO_PROXY bypass" src/container-runner.ts && echo "patch 2 ok"
grep -q "passthrough.*ANTHROPIC_BASE_URL" src/providers/opencode.ts && echo "patch 1 ok"
```

---

## Secrets — local OneCLI gateway

NanoClaw provisions per-agent credential vaults through OneCLI. Point it at the
**local** gateway, not the `api.onecli.sh` cloud:

```dotenv
ONECLI_URL=http://172.17.0.1:10254
```

Health check (the gateway also writes its api-host to `~/.onecli/config.json`):

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://172.17.0.1:10254/api/agents   # expect 200
ONECLI_API_HOST=http://172.17.0.1:10254 onecli agents list
```

Because Bifrost is keyless, the vault needs **no** Anthropic secret for this
setup — the `ANTHROPIC_AUTH_TOKEN=local-bifrost` placeholder satisfies the SDK's
Authorization header and Bifrost ignores it. (If you ever route to the real
Anthropic API instead of Bifrost, you'd add an Anthropic credential to the vault
via the web UI at `http://172.17.0.1:10254` or `onecli secrets create`.)

---

## Discord

The bot (`DrWarioClaw`) is wired via the Chat-SDK Discord adapter. Tokens live in
`~/nanoclaw/.env` (`DISCORD_BOT_TOKEN`, `DISCORD_APPLICATION_ID`,
`DISCORD_PUBLIC_KEY`). Confirm the gateway connected:

```bash
grep "Discord Gateway connected" ~/nanoclaw/logs/nanoclaw.log | tail -1
```

---

## Service control (starts on boot)

The unit is `enabled` and user lingering is on, so it starts at machine boot
without a login session.

```bash
systemctl --user status  nanoclaw-v2-eda8560b
systemctl --user restart nanoclaw-v2-eda8560b
systemctl --user stop    nanoclaw-v2-eda8560b
loginctl show-user "$USER" -p Linger        # expect Linger=yes
```

> The unit's `ExecStart` uses the **stable** fnm node path
> (`~/.local/share/fnm/node-versions/v22.22.3/installation/bin/node`), not an
> ephemeral `/run/user/.../fnm_multishells/...` path — the latter is wiped on
> reboot and would break boot startup.

The service reads `.env` from its `WorkingDirectory` (`~/nanoclaw`) at runtime;
there is **no** `EnvironmentFile`. Provider patch #1 is what makes the `.env`
values reach the container regardless.

---

## End-to-end verification

```bash
cd ~/nanoclaw

# 1. Bifrost up and serving models
curl -s http://127.0.0.1:8080/v1/models | head -c 120; echo

# 2. Service active, Discord connected
systemctl --user is-active nanoclaw-v2-eda8560b
grep "Discord Gateway connected" logs/nanoclaw.log | tail -1

# 3. Send DrWario a Discord DM, then inspect the spawned container
C=$(docker ps --filter name=dm-with-drwario --format '{{.Names}}' | head -1)
docker inspect "$C" --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep -E 'OPENCODE|ANTHROPIC_BASE|NO_PROXY'      # expect /v1 base + host.docker.internal in NO_PROXY
docker logs --tail 30 "$C"                          # expect OpenCode activity, no 4xx/000

# 4. Confirm a reply landed in the outbound DB
SESS=$(ls -d data/v2-sessions/*/sess-* | head -1)
pnpm -s exec tsx scripts/q.ts "$SESS/outbound.db" \
  "SELECT seq, substr(content,1,80) FROM messages_out ORDER BY seq DESC LIMIT 3"
```

Container logs are lost once the container exits (`--rm`); inspect them while a
session is live.

---

## Relocating the install

Because the slug is path-derived, moving `~/nanoclaw` requires:

1. `systemctl --user stop/disable` the old unit and delete its file.
2. `mv` the install directory.
3. Rebuild the image from the new path: `cd <new-path> && ./container/build.sh`
   (produces `nanoclaw-agent-v2-<newslug>:latest`).
4. Write a new unit `nanoclaw-v2-<newslug>.service` (stable fnm node path,
   `WorkingDirectory=<new-path>`), then `daemon-reload` + `enable` + `start`.
5. Re-verify the three [local code patches](#local-code-patches) survived the move
   and rebuild with `pnpm run build`.

---

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Agent connects but **never replies**; container logs show `400 ... does not support thinking` | Wrong provider — Claude Code can't run on Ollama. Set the agent group to `opencode` (see [Selecting the provider](#selecting-the-provider)). |
| Container logs show `401 No credentials configured for api.anthropic.com` | The `claude` provider is active without a custom base URL, or `ANTHROPIC_BASE_URL` isn't reaching the container. Use `opencode`, or apply the local patches. |
| Host error log shows `401 ... api.onecli.sh` | `ONECLI_URL` missing from `.env`; the SDK fell back to the cloud. Add `ONECLI_URL=http://172.17.0.1:10254`. |
| Container reaches Bifrost path but gets `405 Method Not Allowed` | Wrong base-URL path. OpenCode needs `/v1`; Claude Code needs `/anthropic`. |
| `curl` through the proxy to Bifrost returns `000`, direct returns `200/405` | The `NO_PROXY` bypass (patch #2) isn't applied or didn't rebuild. Check it and `pnpm run build` + restart. |
| Reply works from CLI but not NanoClaw after an update | `/update-nanoclaw` or `/add-opencode` reverted a [local patch](#local-code-patches). Re-apply, `pnpm run build`, restart. |
| Service fails after reboot | `ExecStart` points at a `/run/user/.../fnm_multishells/...` node path. Use the stable fnm path. |

---

## Quick reference — what makes a reply work

1. Bifrost up on `:8080`.
2. `.env`: `ONECLI_URL` (local), `ANTHROPIC_BASE_URL=…:8080/v1`,
   `OPENCODE_PROVIDER=openai`, `OPENCODE_MODEL=openai/qwen3-coder:30b`,
   `OPENCODE_SMALL_MODEL=openai/gemma4:latest`,
   `ANTHROPIC_AUTH_TOKEN=local-bifrost`, Discord tokens.
3. DB: agent group `provider = opencode`.
4. Code: the three [local patches](#local-code-patches) applied + `pnpm run build`.
5. Service restarted; old containers killed so they respawn with new config.
