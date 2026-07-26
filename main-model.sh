#!/usr/bin/env bash
# main-model.sh — ONE global toggle for the whole fleet.
# Points every consumer/agent alias (main, orchestrator, qwen-routing, generalist, coder,
# smart, ...) at a single chosen big model, so ALL Hermes agents + OpenCode/Cline switch
# together. No smart/embedding routing.
#
#   ./main-model.sh              fzf MENU of models -> pick -> switch the whole fleet
#   ./main-model.sh <name>       direct switch (minimax|mistral|qwen3.6|gemma4)
#   ./main-model.sh show         current active model + what's loaded
#
# Regenerates llama-cpp/config.yaml (deterministic) and llama-swap hot-reloads (-watch-config).
# NO VISION MODEL HERE (removed 2026-07-26). Qwen3-VL used to be served as `visual`/`vision`/
# `image`, but this box is for the big text models — its 124GB unified pool is the scarce
# resource. Vision belongs on bigcachy's RTX 5080 (16GB), where an 8B VL model fits with
# room to spare and does not compete with a 70-88GB main model.
# To add a model: one line in MODELS + ORDER.
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"   # resolve symlink so `main-model` in PATH works
CONFIG="$DIR/llama-cpp/config.yaml"
STATE="$DIR/.main-model"
SWAP="http://127.0.0.1:11434"
# Every menu model serves this. It MUST be >= the agents' config.src.yaml context_length,
# which is 65536 (Hermes' 64K minimum). It sat at 32768 while the fleet, bifrost, chromadb
# and the RAG containers all shared this box: the agents asked for 64K and silently only
# ever got 32K. The 2026-07 move took those containers to big-cachy, so the KV cache can
# now actually cover what the agents request.
#
# Cost, MiniMax-M2.7 (62 layers, 8 KV heads, 128 head-dim; q4_0 KV = 69.75 KiB/token):
#   4 slots x 65536 = 262144 tokens ~= 18.7 GB KV   (was 9.4 GB at 32768)
# Measured headroom after the move: ~28 GiB available. If `free -h` here trends toward
# zero under load, step down to 49152 (14.0 GB) rather than all the way back to 32768.
CTX=65536

# Qwen3.6 is MULTIMODAL. The vision projector is a separate file that `-hf` does NOT
# auto-load — it must be passed with --mmproj or images are silently ignored. Resolved by
# glob because the HF snapshot dir is a commit hash that changes on re-download.
QWEN36_MMPROJ="$(ls -1 /mnt/AI_Models/huggingface/hub/models--unsloth--Qwen3.6-27B-GGUF/snapshots/*/mmproj-BF16.gguf 2>/dev/null | head -1)"

# Parallel slots. Each slot holds ONE cached prompt prefix; when an agent's prefix is evicted
# it pays a full cold prefill (~100s for a 21k-token agent prompt at ~210 tok/s). With 9 Hermes
# agents + opencode + cline sharing 4 slots, that eviction was constant — the real cause of the
# "agents take minutes" problem, not raw model speed.
#
# Only qwen3.6 gets a high count: slots cost KV cache, and KV must fit beside the weights in
# the ~105 GiB GPU pool. At q4_0 (72 KiB/token) 12 x 65536 = ~54 GiB, + 17 GiB weights = ~71 GiB.
#
# Q8_0 was tried and REVERTED 2026-07-26. It fits (27 GiB weights -> ~82 GiB total) but is
# ~1.7x slower on both decode (2.8 vs 4.7 tok/s) and prefill (112s vs 67s on a 21k prompt),
# which is just the weight-bandwidth ratio 26.6/16.4 on a memory-bound box. Its warm-cache
# path was far worse still (42-57s vs 4.7s) for reasons never established. An Unsloth
# dynamic Q4 is within ~1% of Q8 on quality, so the trade is not worth it here.
# The file is kept at /mnt/AI_Models/gguf/qwen3.6/Qwen3.6-27B-Q8_0.gguf if a future
# ROCm/HIP build (rather than this Vulkan one) changes the arithmetic.
# minimax (87 GiB) and mistral (70 GiB) have no room for more than the default 4 — that is the
# trade you accept when you switch to them.
QWEN36_PARALLEL=12
# CRITICAL: llama-server's -c is the TOTAL context pool, SHARED across --parallel slots — it is
# NOT per-slot. Passing -c 65536 --parallel 12 gives each agent 65536/12 = 5632 tokens, and a
# 21k-token agent prompt is then rejected outright:
#   "request (43907 tokens) exceeds the available context size (5632 tokens)"
# So the total must be scaled by the slot count to give every slot the full CTX.
#   12 slots x 65536 = 786432 tokens x 72 KiB/token (q4_0) = ~54 GiB KV, + 17 GiB weights.
QWEN36_CTX=$(( CTX * QWEN36_PARALLEL ))


# --- model registry: name -> the "-m/-hf ... + sampling" flags (after the common prefix) ---
declare -A MODELS=(
  [minimax]="-m /mnt/AI_Models/gguf/minimax/UD-Q3_K_S/MiniMax-M2.7-UD-Q3_K_S-00001-of-00003.gguf -ngl 999 -c $CTX -b 2048 -ub 512 --cache-type-k q4_0 --cache-type-v q4_0 --temp 1.0 --top-p 0.95 --min-p 0.01 --top-k 40"
  [mistral]="-m /mnt/AI_Models/gguf/mistral3/Q4_K_M/Mistral-Medium-3.5-128B-Q4_K_M-00001-of-00003.gguf -ngl 999 -c $CTX --temp 0.7 --top-p 0.8"
  [qwen3.6]="-hf unsloth/Qwen3.6-27B-GGUF:UD-Q4_K_XL ${QWEN36_MMPROJ:+--mmproj $QWEN36_MMPROJ} -ngl 999 -c $QWEN36_CTX --parallel $QWEN36_PARALLEL -b 2048 -ub 512 --cache-type-k q4_0 --cache-type-v q4_0 --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0"
  [gemma4]="-hf unsloth/gemma-4-31B-it-GGUF:Q4_K_M -ngl 999 -c $CTX --temp 1.0 --top-p 0.95 --top-k 64"
)
ORDER=(minimax mistral qwen3.6 gemma4)

# explicit per-model aliases (always on that model, regardless of the toggle)
declare -A BASE_ALIASES=(
  [minimax]='"minimax-m2.7", "ollama/minimax"'
  [mistral]='"mistral-medium-3.5", "ollama/mistral"'
  [qwen3.6]='"qwen-3.6", "ollama/qwen3.6"'
  [gemma4]='"gemma-4", "ollama/gemma4"'
)
# consumer/agent aliases that FOLLOW the toggle (land on the active model)
CONSUMER='"main", "orchestrator", "qwen-routing", "custom/ollama/orchestrator", "ollama/orchestrator", "generalist", "coder", "agent", "hermes", "smart", "ollama/smart", "ollama/generalist"'

emit_model() { # $1=name $2=", extra aliases" or ""
  cat <<EOF
  "$1":
    aliases: [${BASE_ALIASES[$1]}$2]
    cmd: |
      llama-server --host :: --port \${PORT} -fa on --jinja --no-mmap ${MODELS[$1]}
    ttl: 0
EOF
}

write_config() { # $1=active model
  local active="$1" m
  {
    echo "# GENERATED by main-model.sh — active main model: $active  (edit MODELS/ORDER in the script)"
    echo "healthCheckTimeout: 3600"
    echo "logLevel: info"
    echo "models:"
    for m in "${ORDER[@]}"; do
      [ "$m" = "$active" ] && emit_model "$m" ", $CONSUMER" || emit_model "$m" ""
    done
    cat <<EOF
groups:
  # ONE big "main" model resident at a time.
  "big":
    swap: true
    exclusive: false
    members: [$(printf '"%s", ' "${ORDER[@]}" | sed 's/, $//')]
EOF
  } > "$CONFIG"
}

switch() { # $1=target — clean swap: free the old model, rewrite config, restart, wait for ready
  printf '%s\n' "${ORDER[@]}" | grep -qx "$1" || { echo "unknown model: $1 (have: ${ORDER[*]})"; exit 1; }
  echo "main -> $1"
  # 1) rewrite config so the new model is the active `main`
  write_config "$1"; echo "$1" > "$STATE"
  # 2) restart llama-swap: this FULLY frees the currently-loaded model before the new one loads,
  #    which avoids the transient OOM when swapping between two big models (both briefly resident).
  echo "  restarting llama-swap (frees the old model first — no OOM overlap)..."
  systemctl --user restart llama-swap.service 2>/dev/null \
    || { echo "  ! could not restart llama-swap (user service). Config is set; it will apply on next start."; return 1; }
  # 3) the unit's ExecStartPost warms `main` (=$1); wait for it to become ready
  printf "  loading %s " "$1"
  local i
  for i in $(seq 1 300); do
    if curl -s -m3 "$SWAP/running" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if any(m.get('model')=='$1' and m.get('state')=='ready' for m in d.get('running',[])) else 1)" 2>/dev/null; then
      echo " ready."; return 0
    fi
    printf '.'; sleep 2
  done
  echo " (still loading — watch: journalctl --user -u llama-swap -f)"
}

show() {
  echo "active main model: $(cat "$STATE" 2>/dev/null || echo '(unset)')"
  echo "loaded: $(curl -s -m5 "$SWAP/running" 2>/dev/null | python3 -c 'import json,sys;print([m["model"] for m in json.load(sys.stdin).get("running",[])])' 2>/dev/null || echo '(llama-swap unreachable)')"
}

menu() {
  command -v fzf >/dev/null || { echo "fzf not found; use: $0 <${ORDER[*]}>"; exit 1; }
  local cur pick; cur=$(cat "$STATE" 2>/dev/null || echo '')
  pick=$(for m in "${ORDER[@]}"; do [ "$m" = "$cur" ] && echo "$m  (current)" || echo "$m"; done \
         | fzf --prompt='global main model > ' --height=45% --reverse --header='Switch the whole Hermes fleet + local tools to:') || exit 0
  pick=${pick%%  (current)}; pick=$(echo "$pick" | awk '{print $1}')
  [ -n "$pick" ] && { switch "$pick"; echo; read -rp "Press Enter to close..." _; }
}

case "${1:-menu}" in
  menu|"") menu ;;
  show)    show ;;
  config)  # rewrite config WITHOUT restarting llama-swap. Intended for machine-setup,
           # when NOTHING is loaded yet.
           #
           # NOT safe while a big model is resident — verified 2026-07-26. Removing a model
           # from the config and letting -watch-config hot-reload it left llama-swap
           # convinced the running upstream had died ("group: running mistral exited:
           # upstream command exited prematurely") while the llama-server process was still
           # very much alive and holding 103 GB. Every request then 500'd until the service
           # was restarted. If a model is loaded, use `main-model.sh <name>` instead — it
           # restarts cleanly.
           [ -n "${2:-}" ] || { echo "usage: $0 config <name>"; exit 1; }
           printf '%s\n' "${ORDER[@]}" | grep -qx "$2" || { echo "unknown model: $2 (have: ${ORDER[*]})"; exit 1; }
           write_config "$2"; echo "$2" > "$STATE"; echo "config written for $2 (no restart)" ;;
  *)       switch "$1" ;;
esac
