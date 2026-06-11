# Dockerized Local AI Setup Guide

This directory contains everything you need to spin up your entire local AI orchestration stack using Docker.

## Architecture Split

To ensure your infrastructure is portable but still takes full advantage of your AMD Strix Halo GPU, the configuration is split into two parts:

### 1. General Configuration (`docker-compose.yml`)
This file contains the universal blueprint for the architecture. It defines the three core containers:
- **`ollama`:** The backend server holding your massive model weights (`llama3.3:70b`, `qwen2.5-coder:32b`, `llama3.2-vision`). It mounts your existing `~/.ollama` folder so you don't have to redownload the models!
- **`bifrost`:** The LLM gateway that routes prompts based on complexity and vision capability.
- **`ml_pipeline`:** The Python container for running Whisper, Flux, and ING's EMM string matching model.

### 2. Machine-Specific Configuration (`docker-compose.override.yml`)
This file is injected automatically by Docker when you run `docker compose up`. It contains all the highly specific AMD ROCm hardware bindings required for your machine:
- It passes your GPU directly into the containers (`/dev/kfd` and `/dev/dri`).
- It forces the architecture compatibility flag (`HSA_OVERRIDE_GFX_VERSION=11.0.2`).
- *If you ever move this stack to an Nvidia machine or a Mac, you simply delete this override file!*

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
- **Ollama API:** OpenCode and other tools should now point to `http://localhost:8080/v1` (which will route down to Ollama on port 11434).
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
We have configured your global host OpenCode to use the local stack. Your config file is populated with:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "bifrost": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Bifrost Gateway",
      "options": {
        "baseURL": "http://localhost:8080/v1"
      },
      "models": {
        "llama3.3:70b": {
          "name": "Llama 3.3 70B (Apex Reasoner)"
        },
        "qwen2.5-coder:32b": {
          "name": "Qwen 2.5 Coder 32B"
        },
        "llama3.2-vision:latest": {
          "name": "Llama Vision 11B"
        }
      }
    }
  },
  "agent": {
    "default": {
      "model": "bifrost/llama3.3:70b"
    }
  }
}
```

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

## 🌐 Local Network Static IP & DNS Setup

To make it easy for all computers in your network to access test servers, SSH, and your AI stack, you can configure a static IP and assign the local domain name `strixly.nuclear.cooking` to this machine.

### Static IP Choices
We use high-range IP addresses to avoid conflicts with your router's automatic DHCP IP range:
* 🔌 **Wired (Ethernet):** `192.168.10.222`
* 📶 **Wi-Fi:** `192.168.10.223`
* **Subnet Mask:** `/24` (`255.255.255.0`)
* **Gateway (Router):** `192.168.10.1`

### DNS Setup: `strixly.nuclear.cooking`
You have two main ways to make `strixly.nuclear.cooking` resolve to this machine:

#### Option A: Public DNS A Record (Highly Recommended & Easiest)
If you own or manage the DNS settings for `nuclear.cooking` (e.g., on Cloudflare, AWS Route 53, Namecheap, etc.):
1. Go to your DNS provider's dashboard.
2. Add an **A Record** pointing `strixly.nuclear.cooking` to `192.168.10.222`.
3. Add an **A Record** pointing `strixly-wifi.nuclear.cooking` to `192.168.10.223` (optional).

*Why this is best:* Every device on your home network will automatically resolve the domain to your local machine without any local DNS server setup or client-side configuration! It also makes setting up local SSL certificates (e.g., via Let's Encrypt) trivial.

#### Option B: Local DNS Server (dnsmasq)
If you prefer to resolve it locally without public DNS:
We have included a `setup_network.sh` script that installs a `dnsmasq` configuration on this machine to intercept requests for `strixly.nuclear.cooking` and serve them locally.
*Note:* Other machines on the network will need to set their DNS server to `192.168.10.222` to resolve the domain.

### 🚀 Automated Network Setup Script

We have created a helper script [setup_network.sh](file:///home/lario/lario-llms/setup_network.sh) in this directory. 

To configure the static IPs and start the local DNS resolver:
1. Make the script executable:
   ```bash
   chmod +x setup_network.sh
   ```
2. Run it with root privileges:
   ```bash
   sudo ./setup_network.sh
   ```

*(This will update NetworkManager connection profiles for "Wired connection 1" and "Lamese 1" to use the static IPs and set up dnsmasq as a local resolver).*

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
