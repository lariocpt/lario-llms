#!/bin/bash

# 1. Restore the blobs to your local machine's HuggingFace cache
echo "Restoring 88GB MiniMax blobs from external drive to local cache..."
mkdir -p ~/.cache/huggingface/hub/models--unsloth--MiniMax-M2.7-GGUF/blobs
mv /run/media/lario/Lario/AI/models/huggingface/hub/models--unsloth--MiniMax-M2.7-GGUF/blobs/* ~/.cache/huggingface/hub/models--unsloth--MiniMax-M2.7-GGUF/blobs/

# 2. Tell HuggingFace to rebuild the symlinks using the blobs we just restored
echo "Rebuilding HuggingFace symlinks..."
hf download unsloth/MiniMax-M2.7-GGUF --include "*ud-q3_k_s*"

# 3. Now copy them back to the USB drive cleanly (without symlinks)
echo "Exporting clean, flat files back to external drive..."
mkdir -p /run/media/lario/Lario/AI/flat_models

# Export MiniMax
cp -L ~/.cache/huggingface/hub/models--unsloth--MiniMax-M2.7-GGUF/snapshots/*/*.gguf /run/media/lario/Lario/AI/flat_models/

# Download the remaining missing models directly to the USB drive as flat files
echo "Downloading missing models directly to USB..."
hf download bartowski/Llama-3.2-11B-Vision-Instruct-GGUF Llama-3.2-11B-Vision-Instruct-Q8_0.gguf --local-dir /run/media/lario/Lario/AI/flat_models
hf download bartowski/Qwen2.5-72B-Instruct-GGUF Qwen2.5-72B-Instruct-Q4_K_M.gguf --local-dir /run/media/lario/Lario/AI/flat_models
hf download unsloth/gemma-4-31B-it-GGUF gemma-4-31b-it-q8_0.gguf --local-dir /run/media/lario/Lario/AI/flat_models

echo "Done! You now have a flat_models folder with real files. No symlinks involved!"
