#!/bin/bash
echo "Downloading Max profile models into cache..."
huggingface-cli download bartowski/Qwen2.5-72B-Instruct-GGUF Qwen2.5-72B-Instruct-Q4_K_M.gguf > /dev/null 2>&1 &
huggingface-cli download leafspark/Llama-3.2-11B-Vision-Instruct-GGUF Llama-3.2-11B-Vision-Instruct.Q4_K_M.gguf > /dev/null 2>&1 &
huggingface-cli download leafspark/Llama-3.2-11B-Vision-Instruct-GGUF Llama-3.2-11B-Vision-Instruct-mmproj.f16.gguf > /dev/null 2>&1 &
wait
echo "Downloads completed!"
