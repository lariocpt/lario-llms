# Manual / Unscripted Configuration Guide

> **🛑 STOP: DO NOT USE THIS GUIDE FOR NORMAL SETUP 🛑**
> This document is strictly for technical curiosity, troubleshooting, or cases where your computer's security permissions block the automated `.bat` scripts from running. 
> 
> Under normal circumstances, you should just double-click `setup-editor.bat` and let the computer do all of this for you automatically!

---

If the `setup-editor.bat` script fails, or if you simply want to know how the AI connects to your code editor under the hood, here are the exact manual steps to configure the API connections yourself.

## 1. Manually Configuring the Cline Extension (VS Code)

Cline connects to your local Bifrost Gateway using an standard OpenAI-compatible API format.

1. Open VS Code.
2. Click the **Cline icon** on your left sidebar to open its chat window.
3. Click the **Gear icon** (Settings) at the top right of the Cline window.
4. Scroll down to "API Provider" and change the dropdown to **OpenAI Compatible**.
5. Fill in the fields exactly as follows:
   - **Base URL:** `http://localhost:8080/v1`
   - **API Key:** `1234`
   - **Model ID:** `smart`
6. Close the settings window. Cline is now connected!

*Technical Note: Under the hood, this modifies a hidden configuration file located at `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_api_settings.json`.*

## 2. Manually Configuring OpenCode (VS Code)

OpenCode is another powerful code editor extension. It requires a raw JSON configuration file to know how to talk to your local models.

1. Open your File Explorer.
2. Go to your user profile folder (e.g., `C:\Users\Daniel`).
3. If it doesn't exist, create a folder named exactly `.config`.
4. Inside the `.config` folder, create a folder named exactly `opencode`.
5. Inside the `opencode` folder, create a text file named `opencode.jsonc`.
6. Open `opencode.jsonc` in Notepad and paste the following exactly:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "bifrost": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Bifrost Gateway",
      "options": {
        "baseURL": "http://localhost:8080/v1",
        "timeout": 300000,
        "chunkTimeout": 30000
      },
      "models": {
        "smart": { "name": "Smart Router (Auto-selects best model)" },
        "qwen-routing": { "name": "Qwen Routing / Coder" },
        "gemma4": { "name": "Gemma-4 31B" }
      }
    }
  },
  "agent": {
    "default": {
      "model": "bifrost/smart"
    }
  }
}
```
7. Save the file. OpenCode will now route requests directly to your local Bifrost Gateway!


