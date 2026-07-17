#!/usr/bin/env bash
# Stage the validated host llama.cpp build + Ollama's ROCm runtime + llama-swap into vendor/,
# then build the self-contained `lario/llamacpp` image. vendor/ is gitignored (~3 GB).
set -euo pipefail
cd "$(dirname "$0")"

SRC_LLAMA="${LLAMA_DIR:-$HOME/.local/bin/llama-b9842}"
SRC_ROCM="${ROCM_DIR:-$HOME/.local/lib/ollama/rocm}"
SWAP_URL="${LLAMA_SWAP_URL:-https://github.com/mostlygeek/llama-swap/releases/download/v233/llama-swap_233_linux_amd64.tar.gz}"
IMAGE="${IMAGE:-lario/llamacpp:latest}"

[ -x "$SRC_LLAMA/llama-server" ] || { echo "ERROR: $SRC_LLAMA/llama-server not found"; exit 1; }
[ -e "$SRC_ROCM/libamdhip64.so.7" ] || { echo "ERROR: $SRC_ROCM ROCm libs not found"; exit 1; }

echo ">> Staging vendor/ (llama.cpp + ROCm; ~3 GB)…"
rm -rf vendor && mkdir -p vendor
cp -a "$SRC_LLAMA" vendor/llama
cp -a "$SRC_ROCM"  vendor/rocm

echo ">> Fetching llama-swap…"
tmp="$(mktemp -d)"
curl -fsSL "$SWAP_URL" -o "$tmp/swap.tgz"
tar -xzf "$tmp/swap.tgz" -C "$tmp"
cp "$(find "$tmp" -type f -name llama-swap | head -1)" vendor/llama-swap
chmod +x vendor/llama-swap
rm -rf "$tmp"
echo ">> llama-swap flags:"; ./vendor/llama-swap --help 2>&1 | head -20 || true

echo ">> Building $IMAGE…"
docker build -t "$IMAGE" .
echo ">> Done: $IMAGE"
