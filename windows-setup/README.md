# Windows AI Workstation Setup Guide (Geekom Strix Halo)

Welcome to the comprehensive setup guide for transforming your Geekom Strix Halo into a powerful, local AI workstation. 

This guide will walk you through exactly what to install, where to put the files in this folder, and how to start the system.

## Step 1: Install llama.cpp (The AI Engine)
1. Download the latest `llama.cpp` Windows release with **Vulkan** support from their official GitHub releases page.
2. Extract the downloaded zip file to a permanent location on your C: drive, for example: `C:\llama`
3. Create a folder inside `C:\llama` called `models`.
4. Download the `minimax-m2.7-ud-q3_k_s.gguf` model and place it inside `C:\llama\models\`.
5. **ACTION:** Move the `start-llama-server.bat` file from this setup folder and place it directly into `C:\llama\`.
6. You can now double-click `start-llama-server.bat` anytime to boot up your local AI!

## Step 2: Configure llama-swap (Optimization Configs)
To dynamically switch between models without exceeding your 96GB VRAM (e.g., swapping a fast coder model for the massive MiniMax model), we use `llama-swap`.
1. Download `llama-swap.exe` for Windows and place it in `C:\llama\`.
2. **ACTION:** Move the `config.yaml`, `config-fast.yaml`, and `config-max.yaml` files from this setup folder into `C:\llama\`.
3. *Note:* You can run `llama-swap.exe -config config-fast.yaml` for quick jobs, or point it to `config-max.yaml` when you need the heaviest models.

## Step 3: Install Docker Desktop
1. Download and install **Docker Desktop for Windows**.
2. **CRITICAL:** Ensure you check the box to use **WSL2** (Windows Subsystem for Linux) during installation.
3. Once installed, start Docker Desktop and ensure the engine is running (look for the green whale icon in your system tray).

## Step 4: Run the Vector Database and Bifrost Gateway
The Hermes agent requires a Vector Database (ChromaDB) to remember your engineering documents, and the Bifrost Gateway orchestrates the models.
1. **ACTION:** Create a folder somewhere safe (e.g., `C:\AI-Servers`).
2. **ACTION:** Move the `docker-compose.yml` file from this setup folder into your new `C:\AI-Servers` folder.
3. Open a terminal (Command Prompt or PowerShell) and navigate to that folder:
   ```cmd
   cd C:\AI-Servers
   ```
4. Start the services by running:
   ```cmd
   docker compose up -d
   ```
   *(This will download ChromaDB and Bifrost and start them silently in the background).*

## Step 5: Connect Your Agents
With the servers running, you can now connect your agents (Nanoclaw and Hermes).
1. Your Bifrost gateway is running on `http://localhost:8080`.
2. Your ChromaDB (Vector DB) is running on `http://localhost:8000`.
3. When configuring your Discord bots (for Nanoclaw or Hermes) or your OpenCode VS Code extension, set the API Base URL to `http://localhost:8080/v1` (and you can use anything for the API key, as it routes locally).

You are now fully set up!
