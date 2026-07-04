#!/bin/bash

MODE=$1

if [ -z "$MODE" ]; then
    echo "Usage: ./swap-config.sh [fast|max]"
    exit 1
fi

if [ "$MODE" == "fast" ]; then
    cp config-fast.yaml config.yaml
    echo "Swapped to FAST configuration (Qwen + Gemma)."
elif [ "$MODE" == "max" ]; then
    cp config-max.yaml config.yaml
    echo "Swapped to MAX CAPACITY configuration (MiniMax + Llama Vision)."
else
    echo "Unknown mode: $MODE. Use 'fast' or 'max'."
    exit 1
fi

echo "llama-swap will hot-reload the configuration automatically."
