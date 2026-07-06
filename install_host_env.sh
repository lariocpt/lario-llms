#!/bin/bash
# install_host_env.sh
# Safely configures host environment variables, UI integrations, and optimization maps for lario-llms

echo "🚀 Starting lario-llms host environment & integrations installation..."

# 1. HuggingFace Cache Configuration
echo "📁 Configuring XFS HuggingFace Cache..."
HF_TARGET="/mnt/AI_Models/huggingface"

if [ -d "/mnt/AI_Models" ]; then
    sudo mkdir -p "$HF_TARGET"
    sudo chown -R $USER:$USER "$HF_TARGET"
    echo "✅ /mnt/AI_Models partition verified and HF_TARGET created."
else
    echo "⚠️ Warning: /mnt/AI_Models not found! HF_HOME will be set, but the drive is missing."
fi

inject_export() {
    local shell_rc="$1"
    local export_line="export HF_HOME=$HF_TARGET"
    
    if [ -f "$shell_rc" ]; then
        # Inject HF_HOME
        if grep -q "export HF_HOME" "$shell_rc"; then
            echo "⏭️  $shell_rc already contains HF_HOME."
        else
            echo "" >> "$shell_rc"
            echo "# Added by lario-llms install script" >> "$shell_rc"
            echo "$export_line" >> "$shell_rc"
            echo "✅ Injected HF_HOME into $shell_rc"
        fi
        
        # Inject AMD ROCm optimization overrides
        if ! grep -q "export HSA_OVERRIDE_GFX_VERSION" "$shell_rc"; then
            echo "export HSA_OVERRIDE_GFX_VERSION=11.0.2" >> "$shell_rc"
            echo "✅ Injected HSA_OVERRIDE_GFX_VERSION=11.0.2 into $shell_rc"
        fi
    fi
}

inject_export "$HOME/.zshrc"
inject_export "$HOME/.bashrc"

# 2. OpenCode Triple-Key Configuration
echo "💻 Configuring OpenCode Triple-Key provider mapping..."
OPENCODE_DIR="$HOME/.config/opencode"
# Some systems use opencode.jsonc, some use opencode.json
OPENCODE_FILE="$OPENCODE_DIR/opencode.json"
mkdir -p "$OPENCODE_DIR"

if [ ! -f "$OPENCODE_FILE" ]; then
    echo "📝 Creating new OpenCode config..."
    cat << 'EOF' > "$OPENCODE_FILE"
{
  "provider": {}
}
EOF
fi

if command -v jq &> /dev/null; then
    # Inject the double-prefix triple-key maps directly into the JSON
    jq '.provider.openai = {
      "name": "llama.cpp (local, direct)",
      "options": { "baseURL": "http://127.0.0.1:11434/v1", "apiKey": "dummy" },
      "models": {
        "openai/openai/qwen-routing": { "name": "Qwen Fast Coder (27B)" },
        "openai/openai/gemma4": { "name": "Gemma-4 Generalist (31B)" }
      }
    } | .provider.ollama = {
      "name": "Bifrost Gateway",
      "options": { "baseURL": "http://localhost:8080/v1", "apiKey": "bifrost" },
      "models": {
        "ollama/ollama/smart": { "name": "Smart Router" }
      }
    }' "$OPENCODE_FILE" > "${OPENCODE_FILE}.tmp" && mv "${OPENCODE_FILE}.tmp" "$OPENCODE_FILE"
    echo "✅ OpenCode configuration injected."
else
    echo "⚠️ jq not found. Skipping OpenCode JSON injection. (sudo dnf install jq)"
fi

# 3. VS Code / Cline Configuration (settings.json)
echo "🧩 Configuring VS Code for Cline / Claude Dev..."
VSCODE_DIR="$HOME/.config/Code/User"
VSCODE_FILE="$VSCODE_DIR/settings.json"
if [ -f "$VSCODE_FILE" ] && command -v jq &> /dev/null; then
    # Injects the OpenAI compatible endpoint pointing to Bifrost Gateway
    jq '."cline.customModel" = "ollama/smart" | ."cline.customProvider" = "openai" | ."cline.customBaseUrl" = "http://localhost:8080/v1" | ."cline.customApiKey" = "bifrost"' "$VSCODE_FILE" > "${VSCODE_FILE}.tmp" && mv "${VSCODE_FILE}.tmp" "$VSCODE_FILE"
    echo "✅ VS Code Cline configuration injected."
else
    echo "⏭️  VS Code settings.json not found or jq missing. Skipping Cline configuration."
fi

# 4. Bifrost & llama-swap Map Validations
echo "🌉 Validating Bifrost & optimization maps..."
BIFROST_DIR="$(pwd)/bifrost"
LLAMA_SWAP_DIR="$(pwd)/llama-cpp"

if [ ! -d "$BIFROST_DIR" ]; then
    echo "📁 Creating Bifrost data directory..."
    mkdir -p "$BIFROST_DIR"
fi

if [ -f "$LLAMA_SWAP_DIR/config.yaml" ]; then
    echo "✅ llama-swap optimization map found (config.yaml)."
else
    echo "⚠️ llama-swap optimization map (config.yaml) is missing! The stack won't start correctly."
fi

echo "🎉 Installation & Integration complete!"
echo "👉 Please run 'source ~/.zshrc' or restart your terminal to apply the AMD and HF variables."
