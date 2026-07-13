#!/usr/bin/env bash
# smart-use.sh — flip the `smart` router's TEXT target between the two big models.
#
#   ./smart-use.sh              show current target + what's loaded
#   ./smart-use.sh minimax      text -> MiniMax-M2.7 (default; co-resident with vision, no swap)
#   ./smart-use.sh mistral      text -> Mistral Medium 3.5 (deliberate swap: unloads MiniMax)
#
# Images ALWAYS route to qwen3-vl (always resident) regardless of this setting. The router
# reads text-target.txt per request, so the change is live — no llama-swap reload needed.
# We then warm up the new target so the (one-time) model swap happens now, with visible logs.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET_FILE="$DIR/smart-router/text-target.txt"
SWAP_URL="http://127.0.0.1:11434"

current() { cat "$TARGET_FILE" 2>/dev/null || echo minimax; }

case "${1:-status}" in
  minimax|mistral)
    echo "$1" > "$TARGET_FILE"
    echo "smart text target -> $1"
    echo "warming up $1 (this triggers the swap if needed)..."
    curl -s -m 1800 "$SWAP_URL/v1/chat/completions" \
      -H 'Content-Type: application/json' \
      -d "{\"model\":\"$1\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}" \
      >/dev/null && echo "  $1 is loaded and ready." || echo "  warmup call failed — check: journalctl --user -u llama-swap -f"
    ;;
  status)
    echo "current smart text target: $(current)"
    echo "loaded models:"; curl -s -m 5 "$SWAP_URL/running" 2>/dev/null || echo "  (llama-swap not reachable)"
    ;;
  *)
    echo "usage: $0 [minimax|mistral|status]"; exit 1 ;;
esac
