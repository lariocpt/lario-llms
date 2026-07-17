#!/usr/bin/env bash
# Install/refresh the native llama-swap systemd USER service on Fedora.
#
# Improvements over the original unit:
#   - RequiresMountsFor=/mnt/AI_Models /mnt/Shared  (never start before the model/config drives)
#   - network-online.target ordering
#   - ROCBLAS_USE_HIPBLASLT=1 (only matters if a model runs on the ROCm build; harmless otherwise)
#   - ExecStartPost preloads the default resident set (minimax + qwen3-vl) in the BACKGROUND so
#     the box comes up hot without blocking the unit.
#
# Idempotent: safe to re-run. Requires ~/.local/bin/llama-swap and the config to already exist.
set -euo pipefail

BIN="$HOME/.local/bin/llama-swap"
CONFIG="/mnt/Shared/personal/lario-llms/llama-cpp/config.yaml"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT="$UNIT_DIR/llama-swap.service"

[ -x "$BIN" ] || { echo "missing $BIN — install llama-swap first"; exit 1; }
[ -f "$CONFIG" ] || { echo "missing $CONFIG"; exit 1; }
mkdir -p "$UNIT_DIR"

cat > "$UNIT" <<EOF
[Unit]
Description=llama-swap model proxy (native)
After=network-online.target
Wants=network-online.target
RequiresMountsFor=/mnt/AI_Models /mnt/Shared

[Service]
Type=simple
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin
Environment=HF_HOME=/mnt/AI_Models/huggingface
Environment=ROCBLAS_USE_HIPBLASLT=1
ExecStart=%h/.local/bin/llama-swap -config ${CONFIG} -listen :11434 -watch-config
# Preload the default resident set (qwen3-vl + minimax) in the BACKGROUND — don't block the unit.
ExecStartPost=/usr/bin/bash -c '/mnt/Shared/personal/lario-llms/scripts/llama-swap-warmup.sh &'
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

loginctl enable-linger "$USER" >/dev/null 2>&1 || true
systemctl --user daemon-reload
systemctl --user enable --now llama-swap.service
echo "llama-swap unit installed. Status:"
systemctl --user --no-pager status llama-swap.service | head -6 || true
