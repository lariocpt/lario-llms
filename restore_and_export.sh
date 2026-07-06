#!/bin/bash

# Target directory on the external drive for Daniel
USB_DIR="/run/media/lario/Lario/AI/flat_models"
mkdir -p "$USB_DIR"

echo "Step 1: Restoring your local machine's cache (using pure Unsloth)..."

# Qwen Models (All Unsloth)
hf download unsloth/Qwen2.5-72B-Instruct-GGUF *Q4_K_M.gguf
hf download unsloth/Qwen2.5-VL-7B-Instruct-GGUF *Q4_K_M.gguf
hf download unsloth/Qwen2.5-VL-7B-Instruct-GGUF *mmproj*
hf download unsloth/Qwen2.5-Coder-32B-Instruct-GGUF *Q4_K_M.gguf

# Gemma Models (All Unsloth)
hf download unsloth/gemma-4-31B-it-GGUF *Q8_0.gguf
hf download unsloth/gemma-3-12b-it-GGUF *Q4_K_M.gguf
hf download unsloth/gemma-3-12b-it-GGUF *mmproj*

echo "Step 2: Copying the real files to Daniel's USB drive..."
# The -L flag ignores the symlinks and copies the real files out of the cache to the USB drive

cp -L /mnt/Shared/models/huggingface/hub/models--unsloth--Qwen2.5-72B-Instruct-GGUF/snapshots/*/*.gguf "$USB_DIR/"
cp -L /mnt/Shared/models/huggingface/hub/models--unsloth--Qwen2.5-VL-7B-Instruct-GGUF/snapshots/*/*.gguf "$USB_DIR/"
cp -L /mnt/Shared/models/huggingface/hub/models--unsloth--Qwen2.5-Coder-32B-Instruct-GGUF/snapshots/*/*.gguf "$USB_DIR/"
cp -L /mnt/Shared/models/huggingface/hub/models--unsloth--gemma-4-31B-it-GGUF/snapshots/*/*.gguf "$USB_DIR/"
cp -L /mnt/Shared/models/huggingface/hub/models--unsloth--gemma-3-12b-it-GGUF/snapshots/*/*.gguf "$USB_DIR/"

echo "Done! Your computer is fixed, and Daniel's USB drive has the real flat files."
