#!/bin/bash
# install_host_env.sh
# Safely configures host environment variables for lario-llms

echo "🚀 Starting lario-llms host environment installation..."

# Define the target cache directory
HF_TARGET="/mnt/AI_Models/huggingface"

# Ensure the destination directory exists
if [ -d "/mnt/AI_Models" ]; then
    echo "✅ /mnt/AI_Models partition found."
    sudo mkdir -p "$HF_TARGET"
    sudo chown -R $USER:$USER "$HF_TARGET"
else
    echo "⚠️ Warning: /mnt/AI_Models not found! Please ensure your XFS partition is mounted."
    echo "The HF_HOME variable will still be set, but the directory doesn't exist yet."
fi

# Function to safely inject exports
inject_export() {
    local shell_rc="$1"
    local export_line="export HF_HOME=$HF_TARGET"
    
    if [ -f "$shell_rc" ]; then
        if grep -q "export HF_HOME" "$shell_rc"; then
            echo "⏭️  $shell_rc already contains HF_HOME. Skipping."
        else
            echo "" >> "$shell_rc"
            echo "# Added by lario-llms install script" >> "$shell_rc"
            echo "$export_line" >> "$shell_rc"
            echo "✅ Injected HF_HOME into $shell_rc"
        fi
    fi
}

# Inject into common profiles
inject_export "$HOME/.zshrc"
inject_export "$HOME/.bashrc"

echo "🎉 Installation complete!"
echo "👉 Please run 'source ~/.zshrc' or restart your terminal to apply the changes."
