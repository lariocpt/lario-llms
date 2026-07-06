# Dockerized Local AI Setup Guide

This directory contains everything you need to spin up your entire local AI orchestration stack using Docker.

## Architecture Split & Configurations

To ensure your infrastructure is portable but still takes full advantage of your hardware, the configuration is split into dynamic profiles:

### 1. General Configuration (`docker-compose.yml`)
This file contains the universal blueprint for the architecture. It defines the core containers:
- **`llamacpp`:** The backend server holding your massive model weights (`qwen-2.5-72b`, `gemma4`, `llama-3.2-11b-vision`). It mounts your existing `/models/gguf` folder so you don't have to redownload the models!
- **`bifrost`:** The intelligent LLM gateway. It intercepts requests for the `"smart"` model and dynamically routes prompts to the Coder (Qwen), Visual (Llama), or Generalist (Gemma). It also defaults agent requests to `"qwen-routing"`.
- **`ml_pipeline`:** The Python container for running Whisper, Flux, and ING's EMM string matching model.

### 2. Fast vs Max Profiles (`llama-cpp/swap-config.sh`)
Your models are split into two hardware-specific profiles that you can hot-swap instantly without restarting the Docker containers:
- **Fast Profile (`./swap-config.sh fast`)**: Loads Qwen 3.6 27B and Gemma 4 31B BF16 for rapid, multi-agent workflows.
- **Max Profile (`./swap-config.sh max`)**: Loads the massive Qwen 2.5 72B "Main Guy" alongside Llama 3.2 11B Vision for heavy reasoning tasks (utilizing massive VRAM pools).

*Note: All models listen to abstract aliases like `"qwen-routing"` or `"smart"`, so your frontend tools never need to be reconfigured when underlying weights change!*

### 3. Machine-Specific Configuration (`docker-compose.override.yml`)
This file is injected automatically by Docker when you run `docker compose up`. It contains all the highly specific AMD ROCm hardware bindings required for your machine. 
*If you ever move this stack to an Nvidia machine, a Mac, or Windows WSL2, you simply delete this override file!*

## 🪟 Windows Installation (WSL2 / Docker Desktop)

If you are installing this on **Windows**, you do not need the AMD Linux overrides.
1. Install **Docker Desktop for Windows** and enable **WSL2 integration**.
2. Install **Git Bash** or use **WSL2 Ubuntu** as your terminal.
3. Clone this repository inside your WSL2 environment.
4. **Delete** the `docker-compose.override.yml` file (since Windows handles GPU acceleration through Docker Desktop natively differently than native Linux ROCm).
5. Run the standard `./start_all.sh` from a WSL2 terminal.

## 🚀 Host Environment Setup (Installation)

Before starting the containers, you need to configure your host machine's environment variables. This prevents host-level tools (like Python scripts or the HF CLI) from downloading massive 30GB models into your root OS partition instead of your dedicated XFS drive.

We have created an automated bash install script to configure this for you:
```bash
chmod +x install_host_env.sh
./install_host_env.sh
```
This script will safely inject `export HF_HOME=/mnt/AI_Models/huggingface` into your `~/.zshrc` and `~/.bashrc` profiles.

## How to Start Everything

1. Open your terminal and navigate to this folder:
   ```bash
   cd ~/lario-llms
   ```
2. Run the startup script:
   ```bash
   chmod +x start_all.sh
   ./start_all.sh
   ```

## Using the Stack

- **Bifrost Routing UI:** Open `http://localhost:8080` in your browser.
- **Local LLM API:** OpenCode and other tools should now point to `http://localhost:8080/v1` (which will route down to llamacpp on port 11434).
- **Running Python ML Scripts:** To generate an image or transcribe audio, you need to execute commands *inside* the ML container:
  ```bash
  docker exec -it ml_pipeline /bin/bash
  ```
  *(Once inside, you can run `python generate_image.py` or use Whisper!)*

## 🖥️ Graphical headed Dev Containers (noVNC Desktops)

Your Pop!_OS Cosmic, Ubuntu, and Linux Mint environments run headed XFCE4 desktop environments accessible directly via VNC inside your web browser. 

Thanks to our integrated **Nginx Reverse Proxy container**, you do **not** need to type port numbers! The containers resolve cleanly on your host at default HTTP port 80:
- 🌌 **Pop!_OS Cosmic:** [http://poposcosmic.lario.local](http://poposcosmic.lario.local)
- 🧡 **Ubuntu:** [http://ubuntu.lario.local](http://ubuntu.lario.local)
- 🌿 **Linux Mint:** [http://mint.lario.local](http://mint.lario.local)

*Simply navigate directly to these domains in your web browser, click "Connect", and double-click the pre-built desktop launchers to start coding with Palot and Open Design offline!*

## 🌐 OpenCode Local Configuration (Free & Offline)

To completely bypass "free usage expired" limits or cloud token constraints, both your host machine and your dev containers are configured to use your local **Bifrost Gateway** as a custom provider.

### Host Configuration (`~/.config/opencode/opencode.jsonc`)
We have configured your global host OpenCode to use the local stack. **CRITICAL ARCHITECTURE NOTE:** OpenCode's internal model router parses the provider from the string (e.g. `provider/model`) and *strips* the prefix before sending it to the provider block. However, Bifrost Gateway (built on AI SDK) *requires* the prefix to route upstream. To bypass this Catch-22, we use a "triple-key mapping" technique by mapping our models to built-in provider blocks like `openai` and `ollama`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openai": {
      "name": "llama.cpp (local, direct)",
      "options": {
        "baseURL": "http://127.0.0.1:11434/v1",
        "apiKey": "dummy"
      },
      "models": {
        "openai/qwen-routing": { "name": "backend match" },
        "openai/openai/qwen-routing": { "name": "Qwen Fast Coder (27B)" },
        "openai/gemma4": { "name": "backend match" },
        "openai/openai/gemma4": { "name": "Gemma-4 Generalist (31B)" }
      }
    },
    "ollama": {
      "name": "Bifrost Gateway",
      "options": {
        "baseURL": "http://localhost:8080/v1",
        "apiKey": "bifrost"
      },
      "models": {
        "ollama/smart": { "name": "backend match" },
        "ollama/ollama/smart": { "name": "Smart Router" }
      }
    }
  }
}
```
*Note: Make sure `auth.json` contains dummy keys for both `openai` and `ollama` so OpenCode doesn't block instantiation!*

### Cline / Claude Dev Configuration
When using Cline or the `saoudrizwan.claude-dev` VS Code extension with Bifrost, you must configure it as an OpenAI-compatible provider pointing to `http://localhost:8080/v1`. 
**CRITICAL:** Because Bifrost is an AI SDK gateway, you *must* prepend the upstream provider to your model ID. For example, to use the `smart` routing or `gemma4`, set the model ID to `ollama/smart` or `ollama/gemma4`. If you just use `smart`, Bifrost will reject the request with `provider is required in model field`.

### Dev Containers Configuration
All three dev containers (Pop!_OS, Ubuntu, Mint) come prebuilt with this exact same local gateway configuration pointing internally to `http://bifrost:8080/v1`.

### 🖥️ Headed Display & GUI Applications (X11 Forwarding)
The containers are fully configured to run graphical GUI applications "headed" (meaning their windows will open directly on your host machine's desktop!).
- **How it works:** When `./start_all.sh` runs, it automatically grants local Docker containers permission to connect to your host's graphical X11 display using `xhost +local:docker`.
- **How to test:** 
  1. Open a shell inside one of your dev containers (e.g. `docker exec -it lario-dev-ubuntu /bin/zsh`).
  2. Run a GUI test application like `x11apps` or `xeyes` or standard graphical editors:
     ```bash
     xeyes &
     ```
  3. The graphical window will pop up instantly on your main Pop!_OS desktop!

### Sharing OpenCode Web with a Friend
To let your friend connect over your Wi-Fi, run the following on your host machine:
```bash
opencode web --port 4096 --hostname 0.0.0.0
```
Your friend can then access your design engine at `http://192.168.10.90:4096`!

---
## 💾 Dual-OS Shared exFAT Model Storage (Windows & Linux)

If you dual-boot between Linux (for development/AI) and Windows (for gaming/other uses), you can share a single copy of your model weights across both operating systems to save hundreds of gigabytes of disk space.

* **On Linux (Docker):** Runs inside Docker with full AMD GPU passthrough.
* **On Windows (Native):** Runs natively with full AMD GPU acceleration (since Docker on Windows doesn't support AMD passthrough).
* **The Shared Bridge:** Both systems read/write from a shared exFAT partition.

For a detailed walkthrough on setting up the exFAT partition, configure auto-mount on boot in Linux, configure Windows environment variables, and secure external access via Tailscale, check the guide:
👉 **[Shared exFAT Setup Guide](file:///home/lario/.gemini/antigravity-cli/brain/8773d0a1-762b-4e68-9f82-d78e4cf51dc4/shared_exfat_setup.md)**

---

## 🎨 Desktop Integration & Dock Shortcuts (Open Design & Palot)

You can run both **Open Design** and **Palot** locally alongside your main AI orchestration stack, and add them directly to your system's application launcher and dock.

### 1. Open Design

**Open Design** is an open-source design agent engine that generates beautiful frontend components and prototypes offline.

* **Run/Install instructions:**
  Ensure you have Node.js ~24 and pnpm installed, then run:
  ```bash
  cd ~/open-design
  corepack enable
  pnpm install
  pnpm tools-dev run web
  ```
  This will start the dev server, accessible at `http://localhost:7456`.

### 2. Palot (Desktop GUI)

**Palot** is the visual Electron desktop environment for managing your offline OpenCode agent sessions.

* **Development mode (Run from source):**
  Ensure you have Bun 1.3.8+ installed, then run:
  ```bash
  cd ~/palot
  bun install
  cd apps/desktop
  bun run dev
  ```

* **Production Packaging (Pack to a system `.deb` package):**
  If you want to compile and install it permanently on your host:
  ```bash
  cd ~/palot
  bun install
  cd apps/desktop
  bun run package:linux
  sudo apt install ./release/Palot-*.deb
  ```

---

### 🖥️ Pinning Applications to Your Host Dock

To make Open Design and Palot show up in your Pop!_OS / Linux application menu and dock, we have created an automated launcher configuration script: `create_dock_shortcuts.sh`.

#### Automated Shortcut Creator
To generate `.desktop` launchers automatically, run:
```bash
cd ~/lario-llms
./create_dock_shortcuts.sh
```

#### What this script does
It creates Linux Desktop Entry files (`.desktop`) inside `~/.local/share/applications/`:

1. **`open-design.desktop`**: Starts the open-design server in a terminal window (so you can view build logs) using the official `docs/assets/logo.png` icon.
2. **`palot-dev.desktop`**: Launches the Palot desktop application in dev mode (`bun run dev`) directly on your host desktop, using its official branded icon.

After running the script, search for **"Open Design"** or **"Palot (Dev)"** in your desktop application launcher, click to run, and choose **"Add to Favorites"** / **"Pin to Dock"**!

---

## 🆘 Troubleshooting & Boot Recovery (EFI / GRUB)

If you are expanding your EFI system partition or dual-booting and get stuck at a GRUB command line prompt or lose your Windows boot option, we have created a dedicated recovery guide:
👉 **[EFI Resizing & GRUB Boot Recovery Guide](file:///home/lario/.gemini/antigravity-cli/brain/8773d0a1-762b-4e68-9f82-d78e4cf51dc4/efi_resize_and_recovery.md)**

It covers:
* How to manually boot your Linux kernel directly from the `grub>` command prompt.
* How to chroot and reinstall GRUB using a Live Linux USB.
* How to recover the Windows Boot Manager using `bcdboot` if it gets wiped from the partition.

---

## 🛠️ Local Terminal Tools & Custom Presets

We have configured custom shell integrations and file handling rules for daily productivity.

### ⏰ Terminal Clock (`tuime`)
The TUI clock [tuime](file:///home/lario/.local/bin/tuime) is configured with aliases in your [.zshrc](file:///home/lario/.zshrc) for various colorful, bright, and screensaver presets:
* **`clock-candy`**: A colorful clock with random, bright candy-like colors.
* **`clock-bright`**: A super bright clock using the Chrome font with candy colors.
* **`clock-3d`**: A futuristic clock utilizing a custom cyan/magenta color gradient and 3D font.
* **`clock-ss`**: Runs the clock in screensaver mode (exits on any key press instead of requiring `q`).
* **`clock-candy-ss`**: Candy color clock in screensaver mode.
* **`clock-bright-ss`**: Super bright Chrome font clock in screensaver mode.
* **`clock-3d-ss`**: Cyan/magenta 3D gradient clock in screensaver mode.

### 📊 CSV Viewer (`xan`)
The Rust-based CSV viewer/processor [xan](file:///home/lario/.local/bin/xan) is configured as the default handler for all CSV files (`*.csv` and `text/csv` mime types) inside the [yazi](file:///home/lario/.config/yazi/yazi.toml) terminal file manager:
* Files are automatically opened with paginated viewer mode: `xan view -p`.
* To run it manually from any terminal, run: `xan view <filename.csv>`.

### 🔑 Env File Manager (`lazyenv`)
The TUI environment variable manager [lazyenv](file:///home/lario/.local/bin/lazyenv) is configured as the default handler for all `.env` files (`*.env`) inside the [yazi](file:///home/lario/.config/yazi/yazi.toml) terminal file manager:
* Opening a `.env` file automatically scans its parent directory and opens `lazyenv` so you can view, edit, and compare all `.env` files in that folder.
* To run it manually from any terminal, run: `lazyenv <directory_path>`.
