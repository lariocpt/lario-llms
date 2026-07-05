# Windows AI Workstation Setup Guide (Geekom Strix Halo)

Welcome to the comprehensive setup guide for transforming your Geekom Strix Halo into a powerful, local AI workstation. 

This guide provides **exact, step-by-step instructions** so you can get everything running with zero guesswork.

---

## Part 1: Install the AI Engine (llama.cpp & llama-swap)
We are going to use `llama.cpp` to run the models on your AMD iGPU, and `llama-swap` to automatically orchestrate and switch between them.

**Step 1: Download llama.cpp**
1. Go to this exact URL: [llama.cpp Windows Vulkan Release](https://github.com/ggerganov/llama.cpp/releases/latest)
2. Scroll down to the "Assets" section and download the file named: `llama-bXXXX-bin-win-vulkan-x64.zip`
3. Open the downloaded zip file and extract the entire folder to your C: drive so that the path looks exactly like this: `C:\llama`

**Step 2: Install the AI Models (from External Drive)**
To save you days of downloading massive files, all the required models have been provided on an external drive. These include:
- **MiniMax-M2.7 (87 GB MoE)** - *The usable heavy reasoner that fits fully in 96GB VRAM.*
- **Llama-3.2-11B-Vision** - *For OCR, documents, and diagrams.*
- **Qwen 2.5 72B** - *The heavyweight reasoner "Main Guy". (~42GB VRAM)*
- **Gemma 4 31B BF16** - *Excellent speed and quality balance. (~62 GB VRAM)*
- **Qwen 3.6 27B** - *Faster MTP architecture, incredibly fast coder.*
- **Qwen2.5-VL 7B** - *Vision model for OCR / documents / diagrams / multimodal math.*
- **Gemma-3 12B** - *Vision model for general VQA / chart understanding / captioning.*

To install them so the system recognizes them instantly:
1. Open your File Explorer, go to your `C:\llama` folder, and create a new folder named `models`.
2. Copy all of the `.gguf` files from the external drive directly into `C:\llama\models\`.
*(By putting the files here, the AI engine will instantly recognize them and won't try to pull them from the internet!)*

**Step 3: Install llama-swap (The Orchestrator)**
Because you want your agents to seamlessly switch between different models (like a fast coder vs a heavy reasoner), you need an orchestrator called `llama-swap`.
1. Go to the [llama-swap GitHub page](https://github.com/mxyng/llama-swap/releases/latest) and download the `.exe` for Windows.
2. Place the `llama-swap.exe` file directly inside your `C:\llama\` folder.
3. *Important:* Right-click `llama-swap.exe`, select **Properties**, and if there is an **"Unblock"** checkbox at the bottom of the General tab, check it and hit Apply.

**Step 4: Add Your Startup Scripts**
1. Open the zip file you received containing this guide.
2. Drag and drop the `config.yaml`, `config-fast.yaml`, `config-max.yaml`, and `start-ai.bat` files into `C:\llama\`.

*(Now, you can just double-click that `start-ai.bat` file anytime you want to turn on the AI! It will automatically detect the models you copied to your cache and start serving them!)*

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

## Part 4: Connect Your Agents!
Everything is now running locally on your machine.
- Your Bifrost gateway is running at: `http://localhost:8080/v1`
- Your ChromaDB (Agent Memory) is running at: `http://localhost:8000`

Whenever you set up an AI agent, tell it to use a "Custom OpenAI API" and set the URL to `http://localhost:8080/v1`. You can put "1234" as the API key, since it's all running safely on your own computer.

---

## Part 5: Agent Configurations (Hermes and Nanoclaw)
Included in this folder is an `agents` directory. This contains the exact configurations for your personal agents.

**1. Daniels-Work-Specialist (Hermes)**:
This agent is pre-configured in your `docker-compose.yml`. When you run Docker, Hermes boots up automatically! 

*What is Discord and why use it?*
[Discord](https://discord.com/) is a free, popular chat application. We use it here because it provides a perfect chat window for you to talk to your AI agent from your computer or phone.

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
- This is your fast, per-session coder agent. Even though you aren't a coder, you will use Nanoclaw to automatically write and run scripts that process your engineering spreadsheets and PDFs!
- Nanoclaw lives inside a code editor interface called VS Code.

*How to Install and Configure VS Code & Cline:*
1. **Download VS Code:** Go to [code.visualstudio.com](https://code.visualstudio.com/) and download the free Windows installer. Run the installer and accept the defaults.
2. **Install the Cline Extension:** 
   - Open VS Code. 
   - On the far left sidebar, click the "Extensions" icon (it looks like 4 square blocks).
   - Search for **"Cline"** in the search bar and click the blue **Install** button.
3. **Connect Cline to your local AI:**
   - Go back to your `C:\llama` or `C:\AI-Servers` folder where you extracted this guide.
   - Double-click the `setup-editor.bat` file.
   - *This script will instantly copy all the pre-configured API settings to the right hidden folders for you automatically!*
4. **Use Nanoclaw:** You can now type in the Cline chat window. Simply tell Nanoclaw what you want it to do (e.g., "Write a python script to read all the PDFs in C:\MyDocs and extract the test values"). It will write the code and run it right on your computer!

---

## Part 6: Python and Agent Tooling
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
pip install pandas numpy openpyxl torch torchvision torchaudio PyPDF2 sentence-transformers chromadb
```

**3. Using the Custom Tooling:**
- Included in this folder is a `tools` directory containing a custom `ingest_docs.py` script. 
- You can run this script to instantly feed any folder of PDFs, Excel spreadsheets, or text files directly into Hermes's Vector Database memory!
- Example: `python tools/ingest_docs.py --repo-path C:\MyEngineeringDocs`
- You can also ask **Nanoclaw** in your code editor to write more Python scripts for you to process your data. Over time, you will build a custom library of "tools" specifically tailored to process your physical engineering workflows.

**4. Sharing Tools with Each Other:**
- Because these custom tools are just standard `.py` text files, sharing them between you and your nephew is incredibly easy! 
- If you ask Nanoclaw to code a new tool (for instance, a tool to parse a proprietary engineering test format), simply take that new `.py` file and send it to your nephew via email, Discord, or a flash drive.
- He can just save it into his own `tools` folder on his computer, and instantly start using it with his own agents!

---

## Part 7: Manually Downloading New Models
If you ever want to download new models yourself instead of copying them from a USB drive, you can use the HuggingFace Command Line tool directly!

**1. Install the HuggingFace tool:**
Open your Command Prompt and type:
```cmd
pip install -U "huggingface_hub[cli]"
```

**2. Download the Models:**
Navigate to your models folder first:
```cmd
cd C:\llama\models
```
Then, you can download any of the models by copying and pasting these exact commands into your terminal:

*Qwen Models:*
```cmd
hf download unsloth/Qwen2.5-72B-Instruct-GGUF *Q4_K_M.gguf --local-dir .
hf download unsloth/Qwen2.5-VL-7B-Instruct-GGUF *Q4_K_M.gguf --local-dir .
hf download unsloth/Qwen2.5-VL-7B-Instruct-GGUF *mmproj* --local-dir .
hf download unsloth/Qwen2.5-Coder-32B-Instruct-GGUF *Q4_K_M.gguf --local-dir .
```

*Gemma Models:*
```cmd
hf download unsloth/gemma-4-31B-it-GGUF *Q8_0.gguf --local-dir .
hf download unsloth/gemma-3-12b-it-GGUF *Q4_K_M.gguf --local-dir .
hf download unsloth/gemma-3-12b-it-GGUF *mmproj* --local-dir .
```

*Heavy Reasoner (MiniMax):*
```cmd
hf download unsloth/MiniMax-M2.7-GGUF *ud-q3_k_s* --local-dir .
```

*Embedding Model (BAAI bge-m3):*
*(Note: This is used by the Vector Database, not llama.cpp, so it should be saved in its own folder)*
```cmd
hf download BAAI/bge-m3 --local-dir .\bge-m3
```
