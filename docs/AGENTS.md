# Agents in the devbox — local (free) vs paid (cloud)

The devbox ships five terminal AI-agent CLIs. **For office work, use the paid/cloud providers**
(better quality, tool-use, long context); the local llama-swap models are the free/offline option
for experimentation. This file covers the **paid** path — for driving cline off the **local** models
see **[CLINE_CONFIG.md](CLINE_CONFIG.md)**.

> **Updated 2026-08-30.** Two things have changed since this was written. (1) The **t2-devbox
> is gone** (removed 2026-08-07 with the Timbuk2 identity) — these CLIs now run directly on the
> hosts, so ignore the `make sh` / podman framing below. (2) The **local option is now two
> endpoints, two aliases**: **`main`** = the coding model (qwen3.8) on **l-dev-ai `:11434`**
> (native llama-swap, follows `main-model.sh`), and **`agent`** = Muse Glimmer 30B on
> **bigcachy `:11436`** (the `agent-llm` container, RX 7900 XT, 34.9 tok/s — what the Hermes
> agents run on). Point coding tools at `main`, agent loops at `agent`.

Run any of them inside the box: `make sh` (or `make ssh`), then the command.

| Command | Agent | Paid/cloud auth | Local option |
|---------|-------|-----------------|--------------|
| `claude` | Claude Code (Anthropic) | `claude login` (Claude subscription) **or** `ANTHROPIC_API_KEY` | — (use its own models) |
| `codex` | OpenAI Codex CLI | `codex login` **or** `OPENAI_API_KEY` | — |
| `cline` | Cline CLI | native **Cline** account, **or** OpenAI-compatible pointed at a paid API | ✅ local models, both endpoints — see CLINE_CONFIG.md |
| `opencode` | opencode | `opencode auth login` (Anthropic/OpenAI/…) **or** provider `API_KEY` | ✅ via bifrost/llama-swap (`main`) + the `xt` provider (`agent` on bigcachy `:11436`) |
| `agy` | Google Antigravity | Google account login | — |

## Recommended for office work

- **`claude` (Claude Code)** is the primary office agent — best coding/agentic quality.
  - **Subscription:** `claude login` → OAuth device flow → creds saved under `~/.claude` in the box.
  - **Pay-per-use API:** set `ANTHROPIC_API_KEY` instead (see secret handling below).
- **`codex`** for OpenAI models — `codex login` or `OPENAI_API_KEY`.

## Setting API keys securely

Never commit keys or paste them inline. Two options inside the box:

**A. Login flows (preferred — no raw key on screen):**
```bash
claude login       # Anthropic OAuth
codex login        # OpenAI
opencode auth login
```
Credentials persist in `/home/claude/` across container restarts (but **not** across a
`make build`/recreate — you'd re-login).

**B. API key via environment** — fetch into a var and echo masked before use (monorepo convention),
so the secret never lands in a single paste blob / shell history verbatim:
```bash
# example: pull from AWS Secrets Manager (the box already has the AWS profile mounted)
ANTHROPIC_API_KEY=$(aws secretsmanager get-secret-value \
  --region eu-west-1 --secret-id office/anthropic/api-key \
  --query SecretString --output text)
export ANTHROPIC_API_KEY
echo "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:0:4}…${ANTHROPIC_API_KEY: -4}"   # masked check
```
Then just run `claude`. Same pattern for `OPENAI_API_KEY` / others.

- To make a key available to every shell in the box, add the `export` to `~/.bashrc` in the
  container, or set it in `docker-compose.yml` `environment:` (do **not** hardcode the value there —
  reference a host env var: `ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY:-}"`).
- **Never** write keys into files that get committed. `.env` is gitignored; keep secrets there or in
  your shell env only.

## When to use which

- **Paid/cloud (`claude`, `codex`)** — real office work: highest quality, reliable tool-calling,
  large context, no local VRAM limits.
- **Local (`cline`/`opencode` → llama-swap)** — free, private, offline; good for bulk/experimental
  runs. See **[CLINE_CONFIG.md](CLINE_CONFIG.md)** for the current per-machine base URLs
  (coder → l-dev-ai `:11434`, model `main`; agents → `agent-llm` on bigcachy `:11436`, model
  `agent`) and which local models make sense. *(The podman `host.containers.internal` URL that
  used to be cited here died with the devbox.)*

## Persisting & resuming sessions

Agent sessions, history, and auth persist across restarts **and rebuilds**: the container's
`/home/claude` is on the `agent_home` named volume (`docker-compose.yml`). So `claude login` /
`codex login` and every prior conversation survive `make down` + `make up`, and anyone using the box
can pick up where the last session left off.

- **Enable it (once):** `make down && make up`. That first recreate repopulates `/home/claude` from
  the image, so **re-run your logins / re-check the `cline` config once** — after that it's permanent.
  (To keep the *current* box's state, migrate it first — see below.)
- **Resume:** use each CLI's continue/resume — e.g. `claude --resume` / `claude --continue`,
  `codex resume`, and `cline`/`opencode` list prior sessions on launch. State lives under
  `~/.claude`, `~/.cline`, `~/.codex`, `~/.config`, `~/.local/share` — all on the volume.
- **Reset all agent state:** with the box down, `podman volume rm t2-containerized-agent-workspace_agent_home`.
- **Migrate the current running box into the volume** (so you don't lose today's sessions/logins):
  ```bash
  podman cp t2-devbox:/home/claude/. ./_home_backup      # grab current state
  make down && make up                                    # creates the volume
  podman cp ./_home_backup/. t2-devbox:/home/claude/      # restore into the volume
  ```
- **Caveats:** build-time home files (e.g. `.bashrc`) are copied into the volume on first populate and
  then "stick" — after a future `make build` that changes them, `rm` the volume to refresh. It's a
  single shared `claude` user, so sessions/creds are shared by everyone who logs in (that's the point
  of "reuse/resume" — just don't store personal secrets you wouldn't share).
</content>
