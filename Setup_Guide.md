# Dockerized Local AI Setup Guide

This directory contains everything you need to spin up your entire local AI orchestration stack using Docker.

## Architecture Split

To ensure your infrastructure is portable but still takes full advantage of your AMD Strix Halo GPU, the configuration is split into two parts:

### 1. General Configuration (`docker-compose.yml`)
This file contains the universal blueprint for the architecture. It defines the three core containers:
- **`ollama`:** The backend server holding your massive model weights (`gemma4`, `qwen3-coder:30b`, `llama3.2-vision`). It mounts your existing `~/.ollama` folder so you don't have to redownload the models!
- **`bifrost`:** The LLM gateway that routes prompts based on complexity.
- **`ml_pipeline`:** The Python container for running Whisper, Flux, and ING's EMM string matching model.

### 2. Machine-Specific Configuration (`docker-compose.override.yml`)
This file is injected automatically by Docker when you run `docker compose up`. It contains all the highly specific AMD ROCm hardware bindings required for your machine:
- It passes your GPU directly into the containers (`/dev/kfd` and `/dev/dri`).
- It forces the architecture compatibility flag (`HSA_OVERRIDE_GFX_VERSION=11.0.2`).
- *If you ever move this stack to an Nvidia machine or a Mac, you simply delete this override file!*

## How to Start Everything

1. Open your terminal and navigate to this folder:
   ```bash
   cd ~/Documents/localai
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
