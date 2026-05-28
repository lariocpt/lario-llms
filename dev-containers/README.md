# Dev Containers: Pop!_OS, Ubuntu & Linux Mint

## What they are

Three disposable development environments that share your GPU and LLM stack.
Each container has the same tooling — only the branding differs.

## What's inside

| Tool | What |
|---|---|
| **nvm + Node 24** | JavaScript runtime via nvm |
| **opencode** | Your AI coding assistant, pre-configured to talk to Bifrost |
| **ohmyzsh** | Zsh with plugins and themes |
| **neovim** | Terminal editor |
| **tmux** | Terminal multiplexer |
| **yazi** | Terminal file manager |
| **gram** | Terminal IDE (if available — installs from GitHub releases) |
| **git** | With **push blocked** — clone/pull works, pushes are rejected |
| **ROCm GPU** | Same AMD GPU access as the LLM stack |
| **X11** | GUI apps forward to your host display |

## Quick start

```bash
# Build + run all three
docker compose -f docker-compose.dev.yml up -d --build

# Or just one
docker compose -f docker-compose.dev.yml up -d ubuntu
docker compose -f docker-compose.dev.yml up -d pop
docker compose -f docker-compose.dev.yml up -d mint
```

| Container | Port | Hostname |
|---|---|---|
| `lario-dev-pop` | 8440 | dev-pop |
| `lario-dev-ubuntu` | 8441 | dev-ubuntu |
| `lario-dev-mint` | 8442 | dev-mint |

## Jump in

```bash
docker exec -it lario-dev-ubuntu /bin/zsh
docker exec -it lario-dev-pop /bin/zsh
docker exec -it lario-dev-mint /bin/zsh
```

## Security boundary

The containers are **fully sandboxed by Docker**. The agent has `sudo` and full filesystem access **inside the container** but cannot touch the host OS. The only paths shared with the host are:

| Mount | Mode | What for |
|---|---|---|
| `~/code:/workspace` | read-write | Agent edits your code here |
| `~/.ssh:/home/dev/.ssh` | **read-only** | Git auth — agent can push but can't modify keys |
| `~/.gitconfig:/home/dev/.gitconfig` | read-only | Git identity — prevents tampering |
| `/tmp/.X11-unix` | read-write | GUI forwarding |

**No system paths** (`/etc`, `/var`, `/usr`, `/`, `/dev` beyond GPU) are mounted. The agent cannot modify host files, install system software on the host, or affect anything outside the container.

```bash
git clone git@github.com:your/private-repo.git  # works
git push                                         # works — agent can push code
# but can't touch anything on the host outside ~/code
```

## How it connects to the LLM stack

The dev containers attach to the `lario-net` Docker network (same as Ollama/Bifrost/RAG).
OpenCode inside the container automatically points to `http://bifrost:8080/v1`.

## GUI apps (X11 forwarding)

Make sure X11 access is allowed on the host:
```bash
xhost +local:docker
```

Then GUI apps in the container (neovim GUI, gram IDE windows, etc.) will appear on your host display.

## Stop

```bash
docker compose -f docker-compose.dev.yml down
```
