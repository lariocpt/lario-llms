# Lario LLMs Session & Progress Tracker

This document tracks our ongoing tasks, fixes, and architecture decisions so that context is strictly preserved across sessions, docker restarts, or if the assistant (me) is rebooted.

## Current Tasks & Status

### 1. JSON Tool Formatting Fix (Local LLMs)
- **Status:** ✅ Applied (via Antigravity `.agy/rules/json_fix.md`).
- **Does it require a Cline restart?** 
  - Yes and No. If you use **Cline** directly, it does NOT read `.agy/rules` (Antigravity's rule folder). Cline reads from a `.clinerules` file in the root of your workspace (`~/code/...`). 
  - If you use **Claude Code**, it uses custom instructions usually in a `.claude.md` file.
  - **Action Item:** We need to copy this JSON escaping rule into a `.clinerules` file in your primary project repo so Cline sees it natively. I will generate this for you in our next steps.

### 2. Cline Session Persistence across Docker Rebuilds
- **Status:** 🚧 Pending implementation in `docker-compose.dev.yml`.
- **The Problem:** Your `docker-compose.dev.yml` currently mounts `~/code`, `~/.ssh`, etc., but does *not* persist the internal VS Code server directory where extensions save their data. When you rebuild `t2-container` (or `lario-dev-ubuntu`), the internal `~/.vscode-server` directory is wiped, destroying Cline's memory and chat history!
- **The Fix:** We need to add a named volume or bind mount for the VS Code server data in `docker-compose.dev.yml`. 
  - Example: `- vscode-server-data:/home/dev/.vscode-server`
  - This ensures that even if the container is entirely destroyed and rebuilt from scratch, Cline will wake up, read the volume, and instantly resume your previous conversations.

### 3. Agent Configuration Standardization
- **Status:** 📝 Planning.
- **The Problem:** You have multiple agents (Cline, Antigravity, Claude Code, OpenCode).
- **The Fix:** Each agent has a designated configuration file where rules must be explicitly placed for that specific agent to read them.
  - **Antigravity:** `.agy/rules/`
  - **Cline:** `.clinerules`
  - **Claude Code:** `.claude.md` (or custom instructions via CLI)
  - **Aider:** `.aider.conf.yml` or `.aider.model.settings.yml`

## Next Steps

1. Create a `.clinerules` file with the JSON escaping fix.
2. Update `/mnt/Shared/personal/lario-llms/dev-containers/docker-compose.dev.yml` to include a persistent volume for `/home/dev/.vscode-server` so your Cline history survives container rebuilds.
