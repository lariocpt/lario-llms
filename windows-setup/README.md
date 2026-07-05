# Windows AI Workstation Setup Guide (Geekom Strix Halo)

Welcome to the comprehensive setup guide for transforming your Geekom Strix Halo into a powerful, local AI workstation. 

This guide provides **exact, step-by-step instructions** so you can get everything running with zero guesswork.

---

## Part 1: Install the AI Engine (llama.cpp)
We are going to use `llama.cpp` because it can run the models directly on your AMD iGPU using Vulkan.

**Step 1: Download llama.cpp**
1. Go to this exact URL: [llama.cpp Windows Vulkan Release](https://github.com/ggerganov/llama.cpp/releases/latest)
2. Scroll down to the "Assets" section and download the file named: `llama-bXXXX-bin-win-vulkan-x64.zip`
3. Open the downloaded zip file and extract the entire folder to your C: drive so that the path looks exactly like this: `C:\llama`

**Step 2: Download the AI Models**
1. Open your File Explorer, go to `C:\llama`, and create a new folder inside it called `models`.
2. Below is the list of highly-optimized models for your Geekom Strix Halo. Click the links to go to their HuggingFace pages, click the "Files" tab, and download the `.gguf` file to your new `C:\llama\models\` folder.

- **MiniMax-M2.7 (87 GB MoE)** - *The usable heavy reasoner that fits fully in 96GB VRAM.*
  - **Link:** [MiniMax-M2.7 UD-Q3_K_S](https://huggingface.co/bartowski/MiniMax-Text-01-GGUF/tree/main) 
  - **File to download:** `minimax-text-01-ud-q3_k_s.gguf`
- **Llama-3.2-11B-Vision** - *For OCR, documents, and diagrams.*
  - **Link:** [Llama-3.2-11B-Vision-Instruct GGUF](https://huggingface.co/bartowski/Llama-3.2-11B-Vision-Instruct-GGUF/tree/main)
- **Qwen 2.5 72B** - *The heavyweight reasoner "Main Guy". (~42GB VRAM)*
  - **Link:** [Qwen2.5-72B-Instruct GGUF](https://huggingface.co/bartowski/Qwen2.5-72B-Instruct-GGUF/tree/main)
- **Gemma 4 31B BF16** - *Excellent speed and quality balance. (~62 GB VRAM)*
  - **Link:** [Gemma-4-31B-it GGUF](https://huggingface.co/unsloth/gemma-4-31B-it-GGUF/tree/main) *(Note: Search for BF16 or Q8 depending on space)*
- **Qwen 3.6 27B** - *Faster MTP architecture, incredibly fast coder.*
  - **Link:** [Qwen3.6-27B GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF/tree/main)
- **Qwen2.5-VL 7B** - *Vision model for OCR / documents / diagrams / multimodal math.*
  - **Link:** [Qwen2.5-VL-7B-Instruct GGUF](https://huggingface.co/unsloth/Qwen2.5-VL-7B-Instruct-GGUF/tree/main)
- **Gemma-3 12B** - *Vision model for general VQA / chart understanding / captioning.*
  - **Link:** [Gemma-3-12b-it GGUF](https://huggingface.co/unsloth/gemma-3-12b-it-GGUF/tree/main)

*(Note: These downloads are massive. Be sure to put all downloaded `.gguf` files directly into `C:\llama\models\`)*

**Step 3: Add Your Startup Scripts**
1. Open the zip file you received containing this guide.
2. Inside, you will see a file named `start-llama-server.bat`. 
3. Drag and drop `start-llama-server.bat` directly into `C:\llama\`.
*(Now, you can just double-click that `.bat` file anytime you want to turn on the AI!)*

---

## Part 2: Install Docker Desktop
Docker is required to run the Bifrost Gateway and ChromaDB (the Vector Database that gives your agents a memory).

1. Go to this exact URL: [Docker Desktop Download](https://www.docker.com/products/docker-desktop/)
2. Click **Download for Windows**.
3. Run the installer. **CRITICAL:** When asked, ensure the box next to **"Use WSL 2 instead of Hyper-V"** is CHECKED.
4. Finish the installation and restart your computer if it asks you to.
5. After restarting, open the "Docker Desktop" application from your start menu. Accept the terms. Leave it running (you should see a green whale icon in the bottom-right corner of your screen).

---

## Part 3: Run the Vector Database and Bifrost Gateway
Now that Docker is running, we need to start the background servers.

1. Open your File Explorer and go to your `C:\` drive. Create a new folder there named `AI-Servers`.
2. Open the zip file containing this guide again. 
3. Drag and drop the `docker-compose.yml` file from the zip into `C:\AI-Servers\`.
4. Open the Windows **Command Prompt** (Press the Windows Key, type `cmd`, and hit Enter).
5. Copy and paste the following commands exactly, pressing Enter after each one:

```cmd
cd C:\AI-Servers
docker compose up -d
```
*(You will see it downloading several components. Wait for it to say "Started" or "Running").*

---

## Part 4: Configure Optimization (llama-swap)
If you want to use multiple models (like a fast coder vs the massive MiniMax), your nephew uses a tool called `llama-swap`.

1. Go to the [llama-swap GitHub page](https://github.com/mxyng/llama-swap/releases/latest) and download the `.exe` for Windows.
2. Place the `llama-swap.exe` file inside your `C:\llama\` folder.
3. Open the zip file containing this guide one last time.
4. Drag and drop the `config.yaml`, `config-fast.yaml`, and `config-max.yaml` files into `C:\llama\`.
5. To run the swap server, open Command Prompt and run:
```cmd
cd C:\llama
llama-swap.exe -config config-fast.yaml
```

---

## Part 5: Connect Your Agents!
Everything is now running locally on your machine.
- Your Bifrost gateway is running at: `http://localhost:8080/v1`
- Your ChromaDB (Agent Memory) is running at: `http://localhost:8000`

Whenever you set up an agent in OpenCode, Cline, or Discord, tell it to use a "Custom OpenAI API" and set the URL to `http://localhost:8080/v1`. You can put "1234" as the API key, since it's all running safely on your own computer.

---

## Part 6: Agent Configurations (Hermes and Nanoclaw)
Included in this folder is an `agents` directory. This contains the exact configurations for your personal agents.

**1. Daniels-Work-Specialist (Hermes)**:
This agent is pre-configured in your `docker-compose.yml`. When you run Docker, Hermes boots up automatically! 

*What is Discord and why use it?*
[Discord](https://discord.com/) is a free, popular chat application (similar to Microsoft Teams or Slack). We use it here because it provides a perfect, familiar chat window for you to talk to your AI agent, send it files, and read its replies from your computer or phone.

*How to connect your Agent to Discord:*
1. Download [Discord](https://discord.com/download) and create a free account if you don't have one. Create a basic empty "Server" for yourself.
2. Go to your `C:\AI-Servers\agents\Daniels-Work-Specialist` folder (assuming you moved it there).
3. Rename the `.env.example` file to exactly `.env` (with a dot at the start).
4. Open `.env` in Notepad.
5. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create a New Application.
6. Go to the "Bot" tab, turn on all three "Privileged Gateway Intents" (Presence, Server Members, Message Content), and click "Reset Token" to get your Bot Token.
7. Paste the Token, Application ID, and Public Key into your `.env` file.
8. Restart your Docker containers (open Command Prompt, go to `C:\AI-Servers`, run `docker compose down` then `docker compose up -d`). You can now invite the bot to your Discord server and talk to it!

*How to teach it:*
- You can edit `SOUL.md` in that folder to change Hermes's behavior or give it specific instructions on how to handle your engineering documents.

**2. General-Helper (Nanoclaw)**:
- This is your fast, per-session coder agent. 
- You can use the configuration files found in `agents\General-Helper` as the base for any OpenCode or Cline sessions when you need quick scripts written. You don't need a Discord bot for this one—it lives in your code editor!

---

## Part 7: Python and Agent Tooling
Because you are working with engineering data (spreadsheets, tests, and physical documents), your agents (especially Nanoclaw) will need tools to process this data. They do this by writing and running Python scripts.

**1. Install Python:**
1. Go to [Python.org Downloads](https://www.python.org/downloads/windows/).
2. Download the latest Python 3 installer for Windows.
3. **CRITICAL:** When you run the installer, check the box at the very bottom that says **"Add python.exe to PATH"** before clicking Install.

**2. Install Essential Data Science Libraries:**
Once Python is installed, you need to give your agents the standard libraries they use to crunch numbers, read spreadsheets, and run machine learning tasks.
1. Open Command Prompt.
2. Run the following command to install the necessary libraries:
```cmd
pip install pandas numpy openpyxl torch torchvision torchaudio
```
*(Note: `pandas` and `openpyxl` allow the agents to read and modify your Excel files. `torch` (PyTorch) is a machine learning framework they might use for complex data modeling).*

**3. Building Tools for Your Host:**
- As an engineer, you don't need to write the code yourself! 
- When you have a specific task (e.g., "I need a tool that takes all PDFs in a folder and extracts the test results into an Excel spreadsheet"), open up your code editor and ask **Nanoclaw** to write that Python script for you.
- Nanoclaw will write the script and run it using the Python installation you just set up. Over time, you will build a custom library of "tools" specifically tailored to process your physical engineering documents and workflows.
