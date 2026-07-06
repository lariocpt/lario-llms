#!/bin/bash

# Target directory on the external drive
TARGET_DIR="/run/media/lario/Lario/AI/flat_models"

# Create the target directory if it doesn't exist
mkdir -p "$TARGET_DIR"

echo "Downloading models directly to $TARGET_DIR..."

# Qwen Models
echo "Downloading Qwen 2.5 72B..."
hf download bartowski/Qwen2.5-72B-Instruct-GGUF Qwen2.5-72B-Instruct-Q4_K_M.gguf --local-dir "$TARGET_DIR"

echo "Downloading Qwen 2.5 VL (Vision)..."
hf download unsloth/Qwen2.5-VL-7B-Instruct-GGUF *Q4_K_M.gguf --local-dir "$TARGET_DIR"
hf download unsloth/Qwen2.5-VL-7B-Instruct-GGUF *mmproj* --local-dir "$TARGET_DIR"

echo "Downloading Qwen Fast Coder (Qwen2.5 Coder 32B or 27B variant)..."
hf download unsloth/Qwen2.5-Coder-32B-Instruct-GGUF *Q4_K_M.gguf --local-dir "$TARGET_DIR"

# Gemma Models
echo "Downloading Gemma 4 31B..."
hf download unsloth/gemma-4-31B-it-GGUF *Q8_0.gguf --local-dir "$TARGET_DIR"

echo "Downloading Gemma 3 12B Vision..."
hf download unsloth/gemma-3-12b-it-GGUF *Q4_K_M.gguf --local-dir "$TARGET_DIR"
hf download unsloth/gemma-3-12b-it-GGUF *mmproj* --local-dir "$TARGET_DIR"

echo "All downloads complete! The files are cleanly stored in $TARGET_DIR."
