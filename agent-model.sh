#!/usr/bin/env bash
# agent-model.sh — the XT's counterpart to main-model.sh: ONE toggle for the Hermes agents'
# model, served by the `agent-llm` container on bigcachy's RX 7900 XT 20GB.
#
#   ./agent-model.sh              fzf MENU of models -> pick -> switch the agents' model
#   ./agent-model.sh <name>       direct switch (muse-glimmer | muse-glimmer-f16)
#   ./agent-model.sh show         active model + what is loaded + VRAM in use
#   ./agent-model.sh list         the registry, current marked
#   ./agent-model.sh config <n>   write the config WITHOUT touching the container
#                                 (first clone / provisioning — nothing is loaded yet)
#
# Regenerates llama-cpp/agent-config.yaml (deterministic, GITIGNORED like config.yaml on
# l-dev-ai — never hand-edit it, edit MODELS/ORDER here) and restarts the container. The
# container has NO -watch-config, so a restart is the only way a change lands; that is fine,
# because /config is a DIRECTORY bind mount, so the restart sees the new file (the
# single-file-mount stale-inode trap in lario-home-infra's notes does not apply here).
#
# WHY A SEPARATE SCRIPT AND NOT main-model.sh WITH A FLAG: the two endpoints are different
# machines, different apply mechanisms (systemd user unit vs docker), different memory
# budgets (105 GiB unified vs 20 GiB VRAM) and different consumers (coding tools vs the
# agents). Sharing code would couple the coder's switch to the agents' — the opposite of
# the 2026-08-30 rebalance, whose point was that the two never move together again.
#
# WHY llama-swap AND NOT BARE llama-server: concurrencyLimit. llama-server has no admission
# control — a request past the last free slot QUEUES SILENTLY, and that silence is
# indistinguishable from a dead provider (the 2026-08-05 outage: a 99% prefix-cache-hit
# call took 640.7s of queue wait and tripped the 600s stale timeout). llama-swap returns
# an immediate HTTP 429 instead (measured 0.0s), which Hermes treats as retryable.
#
# WHAT FITS ON 20 GiB (19.5 usable): a 27B/30B Q4 is ~15-17 GiB of weights, leaving ~2-3 GiB
# for KV + ~1.3 GiB of compute buffers. That rules out the l-dev-ai registry's qwen3.6/3.8
# (KV 64 KiB/token — 3 GiB is under 50k tokens, below Hermes' 64000 floor) and gemma4/
# mistral/minimax outright. Muse Glimmer fits BECAUSE its KV is 13 KiB/token f16 (13 of 52
# layers full attention, the other 39 sliding-window 2048), and q8_0 KV halves that again.
# A model belongs here only if its fit math clears the Hermes floor (64000 + drift buffer
# per slot) — write that math in a comment block above its entry, as main-model.sh does.
#
# TEXT-ONLY IS DELIBERATE on every entry: no --mmproj. The BF16 projector (3.59 GiB) does
# not fit beside Q4 weights, and lario's 2026-08-23 decision is that ALL image work goes to
# the `vision` endpoint on the RTX 5080. Adding a projector here is a decision, not a default.
#
# To add a model: MODELS + ORDER + BASE_ALIASES (all three required — emit_model() expands
# BASE_ALIASES[$1] with no default and aborts under set -u). CONCURRENCY is optional but
# should ALWAYS equal that entry's --parallel; without it llama-swap never rejects.
# Weights: /mnt/xfs/AI_Models is mounted read-only at /models (XFS — never the btrfs root);
# `-hf repo:quant` entries auto-download into /mnt/xfs/AI_Models/llama.cpp-cache.
set -euo pipefail

DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"   # resolve symlink so `agent-model` in PATH works
CONFIG="$DIR/llama-cpp/agent-config.yaml"
STATE="$DIR/.agent-model"
SWAP="http://127.0.0.1:11436"
CONTAINER="agent-llm"
COMPOSE=(docker compose -f "$DIR/docker-compose.yml" -f "$DIR/docker-compose.bigcachy.yml")

# --- Muse Glimmer 30B UD-Q4_K_XL (Meta, 2026-08-10) — the agents' model since 2026-08-30 ---
# Chosen for agentic work (MCP Atlas 75.5 vs qwen3.6's 62.5). Weights 14.81 GiB resident.
#
# Geometry (lario's call, 2026-08-30): 3 slots x 131072 with q8_0 KV cache.
#   weights  UD-Q4_K_XL                    14.81 GiB
#   KV q8_0  393216 tok x 6.5 KiB          2.44 GiB   (13 full-attn layers; the other 39 are
#   SWA q8_0 3 slots x 39 MiB              0.12 GiB    SWA-2048, a fixed cost per slot)
#   buffers  -b 2048 -ub 512              ~1.3  GiB
#   total                                 ~18.7 GiB   -> ~0.8 GiB margin
# -c is the TOTAL pool shared across --parallel slots, so 3 slots serve 131072 each — the
# GGUF's declared context_length and therefore a HARD per-slot ceiling (no rope-scaling
# keys; YaRN by hand is untested). The agents' context_length 126976 = 131072 - 4096 drift
# buffer. Never raise -c without dropping --parallel. q8_0 KV requires -fa on (V-quant needs
# flash attention); fleet precedent: minimax on l-dev-ai runs quantized KV.
#
# MEASURED 2026-08-30 (ROCm image b10689, this exact geometry):
#   resident 17.85 GiB (peak 17.86 under 3 x ~110k concurrent — KV is pre-allocated)
#   decode   34.9 tok/s single-stream; 3-stream ~20 tok/s each, 44.6 aggregate
#            (the Strix Halo baseline this replaced was 13.94 single-stream)
#   prefill  870 -> 674 tok/s from 1.3k to 124k tokens, t ~ n^1.11; a real 123,825-token
#            cold prefill took 183.8s, so the agents' stale timeout 2400 has ~13x margin
#   errors   4th concurrent request -> HTTP 429 in 0.0s; over-ceiling -> typed HTTP 400
#            exceed_context_size_error; SIGKILL of llama-server -> respawn-on-request in 5s
#   quality  q8_0 vs f16 KV A/B at temp 0: 3 of 4 answers byte-identical, 4th equivalent
#   thermals edge 55C / junction 82C / mem 78C at 285W sustained 3-stream — no throttle
#
# --reasoning-budget 2048: Glimmer is a reasoning model with the same empty-answer failure
# as qwen3.6 (budget spent on reasoning_content, content='' at finish_reason=length). The
# system-prompt "Reasoning strength" directive is a preference; this is the server-side
# backstop. Sampling params are the muse block's from main-model.sh.
MUSE_GGUF=/models/gguf/muse-glimmer/Muse-Glimmer-30B-UD-Q4_K_XL.gguf
MUSE_SAMPLING="--cache-ram 0 --reasoning-budget 2048 -b 2048 -ub 512 --temp 1.0 --top-p 0.95 --top-k 64"
MUSE_PARALLEL=3
MUSE_CTX=$(( 131072 * MUSE_PARALLEL ))
# The f16-KV fallback: the geometry the 2026-08-23 plan shipped and the first bring-up
# validated (17.42 GiB resident). Two slots x 98304 — the Hermes floor 64000 + 16384 headroom
# = 80384 still clears it, but the agents' context_length 126976 does NOT: on this entry a
# request above 98304 gets the typed HTTP 400, so lower every live agent's context_length to
# 94208 (98304 - 4096) BEFORE switching here. Keep it registered: if q8_0 KV is ever suspected
# of a quality regression, this is the one-command A/B.
MUSE_F16_PARALLEL=2
MUSE_F16_CTX=$(( 98304 * MUSE_F16_PARALLEL ))

# --- model registry: name -> the "-m/-hf ... + sampling" flags (after the common prefix) ---
declare -A MODELS=(
  [muse-glimmer]="-m $MUSE_GGUF -ngl 999 -c $MUSE_CTX --parallel $MUSE_PARALLEL --cache-type-k q8_0 --cache-type-v q8_0 $MUSE_SAMPLING"
  [muse-glimmer-f16]="-m $MUSE_GGUF -ngl 999 -c $MUSE_F16_CTX --parallel $MUSE_F16_PARALLEL $MUSE_SAMPLING"
)
ORDER=(muse-glimmer muse-glimmer-f16)

# = --parallel of the entry. This is what makes llama-swap REJECT the overflow request
# (HTTP 429, immediately) instead of letting llama-server queue it in silence.
declare -A CONCURRENCY=(
  [muse-glimmer]="$MUSE_PARALLEL"
  [muse-glimmer-f16]="$MUSE_F16_PARALLEL"
)

# explicit per-model aliases (always on that model, regardless of the toggle)
declare -A BASE_ALIASES=(
  [muse-glimmer]='"muse-glimmer-30b-q4"'
  [muse-glimmer-f16]='"muse-glimmer-30b-q4-f16kv"'
)
# consumer aliases that FOLLOW the toggle. `agent` is what every live agent's config.src.yaml
# names and what the opencode `xt` / cline `xt-agent` providers select; `hermes` is the
# historical synonym. NO `main` here: that alias belongs to l-dev-ai's coder endpoint. The
# transitional `main` this endpoint carried during the migration was retired 2026-08-30 once
# all three live agents were confirmed sending `agent` — keeping it would let a misconfigured
# client silently get the agents' model when it meant the coder, and vice versa.
CONSUMER='"agent", "hermes"'

# The image keeps the binary at /app/llama-server — it is NOT on PATH (a bare `llama-server`
# fails with "executable file not found"). No --load-mode here: weights go to VRAM, so the
# host-side mmap default is fine, unlike l-dev-ai's GTT pool.
emit_model() { # $1=name $2=", extra aliases" or ""
  cat <<EOF
  "$1":
    aliases: [${BASE_ALIASES[$1]}$2]
    cmd: |
      /app/llama-server --host :: --port \${PORT} -fa on --jinja ${MODELS[$1]}
    ttl: 0
EOF
  [ -n "${CONCURRENCY[$1]:-}" ] && printf '    concurrencyLimit: %s\n' "${CONCURRENCY[$1]}"
  return 0
}

write_config() { # $1=active model
  local active="$1" m tmp
  tmp="$(mktemp "$CONFIG.XXXXXX")"
  {
    echo "# GENERATED by agent-model.sh — active agent model: $active  (edit MODELS/ORDER in the script)"
    echo "# Never hand-edit: the next \`agent-model <name>\` overwrites this file."
    echo "healthCheckTimeout: 3600"
    echo "logLevel: info"
    echo "models:"
    for m in "${ORDER[@]}"; do
      [ "$m" = "$active" ] && emit_model "$m" ", $CONSUMER" || emit_model "$m" ""
    done
    cat <<EOF
groups:
  # ONE model resident on the 20 GiB card at a time; requesting another member swaps it in.
  "xt":
    swap: true
    exclusive: false
    members: [$(printf '"%s", ' "${ORDER[@]}" | sed 's/, $//')]
EOF
  } > "$tmp"
  mv -f "$tmp" "$CONFIG"
}

known() { printf '%s\n' "${ORDER[@]}" | grep -qx "$1"; }

running_ready() { # $1=model — true when llama-swap reports it loaded and ready
  curl -s -m3 "$SWAP/running" 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if any(m.get('model')=='$1' and m.get('state')=='ready' for m in d.get('running',[])) else 1)" 2>/dev/null
}

switch() { # $1=target — rewrite config, restart the container, warm the model, wait for ready
  known "$1" || { echo "unknown model: $1 (have: ${ORDER[*]})"; exit 1; }
  command -v docker >/dev/null || { echo "docker not found — this runs on the docker host (bigcachy)"; exit 1; }
  echo "agent -> $1"
  write_config "$1"; echo "$1" > "$STATE"
  # A restart fully frees the resident model before the new one loads (no OOM overlap on a
  # 20 GiB card) and re-reads /config from the directory mount. First run on a host creates
  # the container instead.
  if docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "  restarting $CONTAINER (frees the old model first)..."
    docker restart "$CONTAINER" >/dev/null
  else
    echo "  $CONTAINER does not exist yet — creating it (needs COMPOSE_PROFILES=xt in .env)..."
    ( cd "$DIR" && "${COMPOSE[@]}" up -d "$CONTAINER" >/dev/null )
  fi
  # llama-swap loads on the FIRST REQUEST, not at start (ttl 0 = never unload, not preload),
  # so send one — otherwise the container reports healthy with nothing resident and the
  # first agent turn pays the load. Warm in the background; poll /running for ready.
  local i
  for i in $(seq 1 30); do curl -s -m2 "$SWAP/health" >/dev/null 2>&1 && break; sleep 1; done
  curl -s -m 900 "$SWAP/v1/chat/completions" -H 'Content-Type: application/json' \
    -d '{"model":"agent","messages":[{"role":"user","content":"warm"}],"max_tokens":1}' >/dev/null 2>&1 &
  printf "  loading %s " "$1"
  for i in $(seq 1 300); do
    if running_ready "$1"; then echo " ready."; wait; return 0; fi
    printf '.'; sleep 2
  done
  echo " (still loading — watch: docker logs -f $CONTAINER)"; wait
}

show() {
  echo "active agent model: $(cat "$STATE" 2>/dev/null || echo '(unset)')"
  echo "loaded: $(curl -s -m5 "$SWAP/running" 2>/dev/null | python3 -c 'import json,sys;print([m["model"]+":"+m["state"] for m in json.load(sys.stdin).get("running",[])])' 2>/dev/null || echo '(agent-llm unreachable)')"
  local node card
  node="$(sed -n 's/^XT_RENDER_NODE=\/dev\/dri\///p' "$DIR/.env" 2>/dev/null | head -1)"
  card="$(readlink -f "/sys/class/drm/${node:-renderD-none}/device" 2>/dev/null)"
  [ -n "$card" ] && [ -r "$card/mem_info_vram_used" ] \
    && awk '{printf "XT VRAM in use: %.2f GiB\n", $1/1073741824}' "$card/mem_info_vram_used"
  return 0
}

list() {
  local cur; cur=$(cat "$STATE" 2>/dev/null || echo '')
  local m; for m in "${ORDER[@]}"; do [ "$m" = "$cur" ] && echo "* $m  (current)" || echo "  $m"; done
}

menu() {
  command -v fzf >/dev/null || { echo "fzf not found; use: $0 <${ORDER[*]}>"; exit 1; }
  local cur pick; cur=$(cat "$STATE" 2>/dev/null || echo '')
  pick=$(for m in "${ORDER[@]}"; do [ "$m" = "$cur" ] && echo "$m  (current)" || echo "$m"; done \
         | fzf --prompt='agents model (RX 7900 XT) > ' --height=45% --reverse --header='Switch the Hermes agents (and opencode/cline `agent`) to:') || exit 0
  pick=${pick%%  (current)}; pick=$(echo "$pick" | awk '{print $1}')
  [ -n "$pick" ] && { switch "$pick"; echo; read -rp "Press Enter to close..." _; }
}

case "${1:-menu}" in
  menu|"") menu ;;
  show)    show ;;
  list)    list ;;
  config)  [ -n "${2:-}" ] || { echo "usage: $0 config <name>"; exit 1; }
           known "$2" || { echo "unknown model: $2 (have: ${ORDER[*]})"; exit 1; }
           write_config "$2"; echo "$2" > "$STATE"; echo "config written for $2 (container not touched)" ;;
  *)       switch "$1" ;;
esac
