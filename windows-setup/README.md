# Windows AI Workstation Setup Guide (Geekom Strix Halo)

Welcome to the comprehensive setup guide for transforming your Geekom Strix Halo into a powerful, local AI workstation. This machine is uniquely capable because its memory architecture allows dedicating an enormous 96GB of RAM as VRAM, meaning it can run some of the most powerful AI models entirely locally, without needing an external graphics card.

## Overview
This guide covers:
1. **Configuration and Setup of Local LLMs**: How to get large, highly capable AI models running on your hardware.
2. **Configuration of the Bifrost Gateway**: A central hub that routes all AI traffic. This allows you to speak to specific "agents" (like a coder or a visual expert) directly, while also letting a main orchestrator model intelligently route tasks to the right specialized model behind the scenes, managing memory efficiently.
3. **Setting up Autonomous Agents**: Explaining the concepts of different agents (like Nanoclaw and Hermes) and how they can learn your specific workflows and help automate tasks.

---

## Required Software Installation

To get started, you will need to download and install the following software on your Windows machine:

1. **Docker Desktop for Windows**: Essential for running isolated, containerized applications (like the Bifrost gateway, your vector database, and the agents). Ensure WSL2 (Windows Subsystem for Linux) is enabled during installation.
2. **Python 3.11+**: Required for various AI tooling and scripts. Make sure to check the box to "Add Python to PATH" during installation.
3. **llama.cpp (Windows Release)**: The core engine for running our large models. Download the latest Windows release with **Vulkan** support (since we are using the AMD iGPU).
4. **ChromaDB (Dockerized)**: A Vector Database (RAG DB) used by agents to store and retrieve knowledge. We will run this via Docker (see the `docker-compose.yml` included in this folder).
5. **Git for Windows**: Necessary for cloning repositories and allowing coding agents to manage code.
6. **AMD Adrenalin Software / Geekom Specific Drivers**: Ensure your GPU drivers are fully up to date to get the most compute performance out of the Strix Halo iGPU.
7. **Cline / OpenCode**: VS Code extensions/harnesses that allow coding agents to write and edit code directly in your editor.
8. **Discord**: Used as the primary chat interface to converse with your Hermes and Nanoclaw agents.

---

## Model List, Downloads, and Installation

Here are the specific models curated for your 96GB VRAM setup. You can download these in `.gguf` format from HuggingFace (e.g., via the `huggingface-cli` or manually).

1. **MiniMax-M2.7 UD-Q3_K_S** (87 GB MoE, 62 layers / 256 experts)
   - *Role*: The usable heavy reasoner.
   - *Notes*: Fits FULLY in 96 GB VRAM. All layers can be offloaded to the GPU. Do NOT use `--n-cpu-moe`. Expect ~18 tokens/sec on the iGPU.
2. **Llama-3.2-11B-Vision**
   - *Role*: OCR, document, and diagram analysis.
3. **Qwen 2.5 72B** (~42GB VRAM)
   - *Role*: The heavyweight reasoner "Main Guy".
4. **Gemma 4 31B BF16** (~62 GB VRAM)
   - *Role*: Excellent speed and quality balance.
5. **Qwen 3.6 27B**
   - *Role*: Faster MTP architecture, incredibly fast coder.
6. **Qwen2.5-VL 7B**
   - *Role*: Vision model for OCR, documents, diagrams, and multimodal math.
7. **Gemma-3 12B**
   - *Role*: Vision model for general Visual Question Answering (VQA), chart understanding, and captioning.

### llama.cpp Configuration

To run these painlessly out of the gate using your AMD iGPU on Windows, you will use the Vulkan backend of `llama.cpp`. 

In this folder, you will find a `start-llama-server.bat` script. Here is the exact `llama.cpp` configuration for running the massive **MiniMax-M2.7** model fully on your GPU:

```bat
llama-server.exe ^
  -m "models\minimax-m2.7-ud-q3_k_s.gguf" ^
  -c 8192 ^
  -ngl 99 ^
  --host 0.0.0.0 ^
  --port 11434
```
*(Explanation: `-ngl 99` forces all layers to the GPU, `-c 8192` sets the context window, and `--port 11434` mimics the standard Ollama API port so other tools can connect easily).*

---

## The Bifrost Gateway and Prompt Orchestration

When you have a 96GB VRAM pool, you can't load the 87GB MiniMax model *and* the Qwen 72B model at the same time. Prompting a dormant agent might try to load its model into RAM, exceeding your limit and crashing the system.

**The Solution:** The Bifrost Gateway.

Bifrost sits between your chat interface (Discord/OpenCode) and the `llama.cpp` instances. 
- It acts as an **orchestrator**. 
- I have configured the gateway to intercept your prompts and intelligently route them to the most suitable agent for what is being asked.
- It manages a "fast" and "max" mode. It actively swaps out models in `llama.cpp` (e.g., swapping a visual model for a coding model) to ensure you never exceed memory usage while always getting the best model for the task.
- Yes, the local LLMs can analyze images through this gateway, automatically routing image requests to Qwen2.5-VL or Llama-3.2-Vision.

---

## Agents: Nanoclaw vs. Hermes

Daniel, since you are an engineer (and not primarily a coder) looking to automate physical documents, spreadsheets, and tests, you will be interacting with **Agents**. Agents are more than just raw AI models; they have memory, instructions, and tools.

### Models vs. Agents
- **A Model** (like Qwen or MiniMax) is just the brain. It answers questions but has no memory of past sessions, no tools, and no identity.
- **An Agent** uses the model's brain but adds a specific role (persona), a workspace (access to your files), tools (ability to run code or search the web), and persistent memory (saving knowledge for the future).

### Nanoclaw vs. Hermes
1. **Nanoclaw (The General Helper / Coder)**: 
   - Nanoclaw is an agent optimized for execution and coding. It is designed to be highly configurable, spawn quickly for a specific session, and use tools to get a job done fast. 
   - *Example*: You might configure a Nanoclaw agent to write a specific python script to parse a spreadsheet.

2. **Hermes ("Daniel's Work Specialist")**:
   - Hermes is a long-lived, natively self-improving agent. 
   - It is designed to act as a deep knowledge specialist. As Hermes works, it builds a persistent "Knowledge Base" of references, learning your specific work over time. 
   - *Example*: A Hermes agent can be assigned to read through all your physical document scans, spreadsheets, and engineering tests, documenting common practices and organizing them. The next time you ask a question, Hermes remembers the context from its long-term memory.

### Should you set up a Vector DB?
**Yes, absolutely.** For Hermes to learn your work and improve, it requires a Vector Database (like ChromaDB). The vector database is what allows Hermes to take thousands of pages of your engineering documents, store them, and instantly "remember" the exact relevant paragraph when you ask a question weeks later. (A Docker configuration for this is included below).

---

## Getting Started

1. Place the included `docker-compose.yml` and `start-llama-server.bat` files in your dedicated AI directory.
2. Run `start-llama-server.bat` to boot your local model.
3. Open a terminal in the folder and run `docker compose up -d` to start your Vector DB and Bifrost gateway.
4. You can now connect your Discord bots or OpenCode extensions directly to Bifrost!
