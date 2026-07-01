# 🧠 The AI Machine — lario-llms

An orchestrated AI stack running on your AMD Strix Halo machine. Four layers that together make this a full-stack local AI workstation.

---

## Layer 1 — LLM Hub (llama.cpp + Bifrost)

**What it does:** Serves and routes language models. Migrated from Ollama to **llama.cpp + llama-swap**
(GPU via ROCm on the Strix Halo iGPU). Details: [`../llama-cpp/README.md`](../llama-cpp/README.md).

| Service | What | Port |
|---|---|---|
| **llamacpp** | LLM backend — llama-swap → `llama-server`, on-demand model swap, OpenAI `/v1` (network alias `ollama`) | `11434` |
| **bifrost** | Smart gateway — routes prompts based on complexity | `8080` |

**Served models** (`curl -s localhost:11434/v1/models`): `minimax-m2` (agentic default), `qwen3-coder:30b`,
`llama3.3:70b`, `meditron`/`meditron:70b`, `translategemma`, `llama3.2-vision` (text), `mistral-medium-3.5`,
plus `gemma4`/`glm-4.7-flash` *(currently broken on this build — see llama-cpp/README.md)*.

Tune/add models by editing [`../llama-cpp/config.yaml`](../llama-cpp/config.yaml) (live-reloaded);
pull new GGUFs with `llama cli -hf <repo>:<quant>`.

### Clients
Reach models via **Bifrost** (`:8080`, auto-routes by prompt) **or** **llama.cpp directly** (`:11434/v1`,
pins a specific model — Bifrost's catch-all rule otherwise rewrites the requested model).

| Client | How it's wired | Default model |
|---|---|---|
| `llama` (host CLI) | wrapper → `docker exec llamacpp llama-<tool>` | — |
| OpenCode (host) | `~/.config/opencode/opencode.jsonc` — `llama-cpp` + `bifrost` providers | `llama-cpp/qwen3-coder:30b` |
| Cline (CLI + VS Code) | `~/.cline/data/settings/providers.json` + extension `settings.json` → `:11434/v1` | `qwen3-coder:30b` |
| Agents (`/mnt/Shared/personal/agents`) | Hermes → `llamacpp:11434/v1` direct; Nanoclaw → Bifrost | `minimax-m2` |

---

## Layer 2 — RAG Pipeline (ChromaDB + rag_api)

**What it does:** Lets you upload documents and query them with LLM-powered retrieval-augmented generation.

| Service | What | Port |
|---|---|---|
| **chromadb** | Vector database — stores document embeddings | `8000` |
| **rag_api** | RAG server — embed query → search Chroma → prompt LLM via Bifrost | `8100` |

**Ingest a document:**
```bash
curl -X POST http://localhost:8100/ingest \
  -H "Content-Type: application/json" \
  -d '{"documents": ["Your document text here..."], "collection": "notes"}'
```

**Ask a question with RAG:**
```bash
curl -X POST http://localhost:8100/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What does this say about my notes?", "collection": "notes"}'
```

RAG automatically embeds using BGE-M3 (sentence-transformers), retrieves top-5 chunks, augments the prompt, and sends to gemma4 via Bifrost.

**Suggested use cases:**
- Index research papers / reference documents → query with command-r
- Index code documentation → query with qwen3-coder
- Index your notes, journals, project specs

---

## Layer 3 — ML Pipeline (ml_pipeline)

**What it does:** Python environment for ML tasks — image generation, speech transcription, embeddings.

| Tool | What it does |
|---|---|
| **Whisper** | Speech-to-text (audio → transcript) |
| **Flux.1-schnell** | Image generation (text → image) |
| **BGE-M3** | Text embeddings for semantic search |
| **EMM** | Entity matching / fuzzy string matching |

Jump in:
```bash
docker exec -it ml_pipeline /bin/bash
python /app/scripts/generate_image.py --prompt "your prompt"
```

---

## Layer 4 — Open Design (Design Agent)

**What it is:** Open Design is the open-source alternative to Anthropic's Claude Design. It turns your local coding-agent CLI (OpenCode, Claude Code, Codex, etc.) into a design engine. You describe what you want and it generates HTML/CSS artifacts — landing pages, decks, social cards, prototypes — rendered in a sandboxed iframe, editable in place.

- **217 skills** (SKILL.md bundles) — drop a folder, add a design capability
- **149 design systems** (DESIGN.md) — Linear, Stripe, Apple, Notion, etc.
- **16 CLI adapters** — auto-detects OpenCode, Claude Code, Codex, Cursor, Gemini, etc.
- **BYOK proxy** — no CLI? Paste any OpenAI-compatible URL + key
- **Apache-2.0** — fully open source
- **Local-first** — SQLite, no cloud dependency

### Installation

Requires **Node ~24** and **pnpm 10.33.x**.

```bash
# Inside any of your dev containers, or on host:
git clone https://github.com/nexu-io/open-design.git
cd open-design
corepack enable
pnpm install
pnpm tools-dev run web
```

Open the URL printed by `tools-dev` (typically `http://localhost:7456`). The Welcome dialog auto-detects OpenCode on your PATH.

### Docker deployment (headless)

```bash
cd open-design/deploy
OPEN_DESIGN_IMAGE=docker.io/vanjayak/open-design:latest docker compose pull
OPEN_DESIGN_IMAGE=docker.io/vanjayak/open-design:latest docker compose up -d --no-build
# → http://127.0.0.1:7456
```

### How it fits

Open Design uses **OpenCode** (which you already have installed in your dev containers) as the design engine. OpenCode is configured to speak to **Bifrost**, which routes to your local **llama.cpp** models. So a prompt in Open Design → OpenCode → Bifrost → llama.cpp → design artifact, all local, all on your Strix Halo.

---

## Layer 5 — Palot (Desktop GUI for OpenCode)

**What it is:** Palot is an open-source Electron app that wraps OpenCode in a visual desktop interface. Think of it as a desktop IDE for your AI coding agent — multi-project workspace, real-time diff review, scheduled automations, and migration from Claude Code / Cursor.

- **Multi-project workspace** — manage AI sessions across all projects in one window
- **Visual diff panel** — see every file change with syntax-highlighted diffs, leave line-level comments
- **Scheduled agent runs** — RRule-based recurring tasks with human-in-the-loop review
- **Migration wizard** — import config + history from Claude Code and Cursor
- **mDNS discovery** — auto-detect remote/headless OpenCode servers on your network
- **System tray + command palette** — always available, `Cmd+K` to search
- **MIT license** — fully open source

### Installation

**Prerequisites:** [Bun](https://bun.sh) 1.3.8+ and OpenCode CLI installed.

```bash
# Clone and build from source
git clone https://github.com/itswendell/palot.git
cd palot
bun install
cd apps/desktop && bun run dev
```

**Or download a release** from [github.com/itswendell/palot/releases](https://github.com/itswendell/palot/releases) — AppImage/DEB/RPM for Linux, DMG for macOS, NSIS for Windows.

### 🖥️ Desktop Integration (Add to Dock)

To easily launch both **Open Design** and **Palot** from your system's application launcher or pin them to your Dock, use the automation script in the repository root:
```bash
cd ~/lario-llms
./create_dock_shortcuts.sh
```
This generates `.desktop` files in `~/.local/share/applications/` so you can launch them with a single click and keep them in your dock!

### How it fits

Palot is the **desktop face** of the whole stack. It manages OpenCode, which speaks to Bifrost, which routes to your local llama.cpp models (minimax-m2, qwen3-coder, etc.) backed by RAG. You get a visual IDE experience for coding agents — all local, all on your Strix Halo.

---


## 🖥️ Dev Containers (Pop!_OS, Ubuntu, Mint)

Three disposable development environments with full AI stack access:

| Container | Port | FLAVOR |
|---|---|---|
| `lario-dev-pop` | `8440` | Pop!_OS Cosmic |
| `lario-dev-ubuntu` | `8441` | Ubuntu 24.04 |
| `lario-dev-mint` | `8442` | Linux Mint |

**Each includes:**
- fnm + Node 24, ohmyzsh, neovim, tmux, yazi (with doxx & mdfried), splashboard, herdr, pik, zenith, harlequin, opencode, gram (terminal IDE)
- X11 forwarding for GUI apps
- ROCm GPU passthrough (same as your LLM stack)
- SSH keys mounted read-only — full git access (clone, push, PR), but keys can't be stolen
- Fully Docker-sandboxed — agent has `sudo` inside container, **zero access to host OS or files**
- OpenCode pre-configured to speak to Bifrost
- Shared `~/code` workspace mounted at `/workspace`

```bash
cd dev-containers
docker compose -f docker-compose.dev.yml up -d <distro>
```

---

## 🚀 One Command to Start Everything

```bash
./start_all.sh
```

This brings up: llama.cpp → Bifrost → ChromaDB → RAG API → ML Pipeline.

Then spin up dev containers or Open Design as needed.

### Quick Reference

```
Bifrost Gateway:  http://localhost:8080     ← AI router
llama.cpp API:    http://localhost:11434    ← raw LLM (llama-swap, OpenAI /v1)
ChromaDB:         http://localhost:8000     ← vector store
RAG API:          http://localhost:8100     ← RAG queries
Open Design:      http://localhost:7456     ← design agent
Palot (dev):      bun run dev              ← desktop GUI for OpenCode
Dev-Pop:          http://localhost:8440     ← Pop dev container
Dev-Ubuntu:       http://localhost:8441     ← Ubuntu dev container
Dev-Mint:         http://localhost:8442     ← Mint dev container
```

### Model Quick-Reference

Served via llama.cpp/llama-swap (`llama-cpp/config.yaml`). Pull new GGUFs with `llama cli -hf <repo>:<quant>`.

| Model id | Model | Notes |
|---|---|---|
| `minimax-m2` | MiniMax-M2.7 (230B MoE) | agentic default, ~15 tok/s |
| `qwen3-coder:30b` | Qwen3 Coder 30B | strong code, ~75 tok/s |
| `llama3.3:70b` | Llama 3.3 70B | general heavy lifter |
| `meditron:70b` | Meditron 70B | top medical LLM |
| `mistral-medium-3.5` | Mistral Medium 3.5 128B | dense, slowest |
