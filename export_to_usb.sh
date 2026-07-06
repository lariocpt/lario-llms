#!/bin/bash

# Target directory on the external drive for Daniel
USB_DIR="/run/media/lario/Lario/AI/flat_models"
CACHE_DIR="/mnt/Shared/models/huggingface/hub"

echo "Creating target directory on USB..."
mkdir -p "$USB_DIR"
mkdir -p "$USB_DIR/bge-m3"

echo "======================================================"
echo "Exporting models to USB... (This will take some time)"
echo "======================================================"

# Qwen Models
echo "-> Copying Qwen 2.5 72B..."
rsync -ahL --info=progress2 "$CACHE_DIR/models--bartowski--Qwen2.5-72B-Instruct-GGUF/snapshots/"*/*.gguf "$USB_DIR/"

echo "-> Copying Qwen 2.5 VL (Vision)..."
rsync -ahL --info=progress2 "$CACHE_DIR/models--unsloth--Qwen2.5-VL-7B-Instruct-GGUF/snapshots/"*/*Q4_K_M.gguf "$USB_DIR/"
# Renaming Qwen mmproj to avoid collision
rsync -ahL --info=progress2 "$CACHE_DIR/models--unsloth--Qwen2.5-VL-7B-Instruct-GGUF/snapshots/"*/*mmproj*.gguf "$USB_DIR/Qwen2.5-VL-7B-Instruct-mmproj-F16.gguf"

echo "-> Copying Qwen 2.5 Coder 32B..."
rsync -ahL --info=progress2 "$CACHE_DIR/models--unsloth--Qwen2.5-Coder-32B-Instruct-GGUF/snapshots/"*/*.gguf "$USB_DIR/"

# Gemma Models
echo "-> Copying Gemma 4 31B..."
rsync -ahL --info=progress2 "$CACHE_DIR/models--unsloth--gemma-4-31B-it-GGUF/snapshots/"*/*.gguf "$USB_DIR/"

echo "-> Copying Gemma 3 12B Vision..."
rsync -ahL --info=progress2 "$CACHE_DIR/models--unsloth--gemma-3-12b-it-GGUF/snapshots/"*/*Q4_K_M.gguf "$USB_DIR/"
# Renaming Gemma mmproj to avoid collision
rsync -ahL --info=progress2 "$CACHE_DIR/models--unsloth--gemma-3-12b-it-GGUF/snapshots/"*/*mmproj*.gguf "$USB_DIR/gemma-3-12b-it-mmproj-F16.gguf"

# Llama Models
echo "-> Copying Llama 3.2 11B Vision..."
rsync -ahL --info=progress2 "$CACHE_DIR/models--leafspark--Llama-3.2-11B-Vision-Instruct-GGUF/snapshots/"*/*Q4_K_M.gguf "$USB_DIR/"
rsync -ahL --info=progress2 "$CACHE_DIR/models--leafspark--Llama-3.2-11B-Vision-Instruct-GGUF/snapshots/"*/*mmproj*.gguf "$USB_DIR/Llama-3.2-11B-Vision-Instruct-mmproj.f16.gguf"

# MiniMax
echo "-> Copying MiniMax M2.7 (Heavy)..."
rsync -ahL --info=progress2 "$CACHE_DIR/models--unsloth--MiniMax-M2.7-GGUF/snapshots/"*/*.gguf "$USB_DIR/"

# BGE-M3 Embedding
echo "-> Copying BGE-M3 (Embedding)..."
rsync -ahL --info=progress2 "$CACHE_DIR/models--BAAI--bge-m3/snapshots/"*/ "$USB_DIR/bge-m3/"

echo "======================================================"
echo "Export Complete! Daniel's USB drive is perfectly prepped."
