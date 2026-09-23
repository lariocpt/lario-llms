#!/usr/bin/env bash
# agent-model.sh — the XT's counterpart to main-model.sh: ONE toggle for the Hermes agents'
# model, served by the `agent-llm` container on bigcachy's RX 7900 XT 20GB.
#
#   ./agent-model.sh              fzf MENU of models -> pick -> switch the agents' model
#   ./agent-model.sh <name>       direct switch (muse-glimmer-dflash | muse-glimmer | muse-glimmer-f16 | qwen38-flash)
#   ./agent-model.sh reserved     the active entry's opencode-reserved slots, bare number
#                                 (lario-fleet's agent-bucket cap = slots minus reserved)
#   ./agent-model.sh show         active model + what is loaded + VRAM in use
#   ./agent-model.sh list         the registry, current marked
#   ./agent-model.sh slots        the active entry's --parallel (= its concurrencyLimit), bare
#                                 number — what agents/deploy/lario-fleet.sh derives its cap from
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
# qwen38-flash is the deliberate exception: an MoE whose experts and n-gram table live in
# the 125 GiB of SYSTEM RAM (mmap), with only the non-expert weights + KV + buffers on the
# card — see its block below for the two-sided fit math.
#
# TEXT-ONLY IS DELIBERATE on every entry: no --mmproj. The BF16 projector (3.59 GiB) does
# not fit beside Q4 weights, and lario's 2026-08-23 decision is that ALL image work goes to
# the `vision` endpoint on the RTX 5080. Adding a projector here is a decision, not a default.
#
# To add a model: MODELS + ORDER + BASE_ALIASES (all three required — emit_model() expands
# BASE_ALIASES[$1] with no default and aborts under set -u). CONCURRENCY is optional but
# should ALWAYS equal that entry's --parallel; without it llama-swap never rejects.
# RESERVED is optional (default 0): slots the bucket shares with opencode that lario-fleet
# must not count against the agents.
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
# Three entries share these weights: `muse-glimmer-dflash` (the DEFAULT since 2026-08-31,
# 2 slots + speculative decoding), `muse-glimmer` (3 slots, no drafter — the fallback when
# three concurrent slots matter more than decode speed) and `muse-glimmer-f16` (f16 KV A/B).
#
# Geometry of the plain entry (lario's call, 2026-08-30): 3 slots x 131072 with q8_0 KV.
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

# --- DFlash speculative decoding — the DEFAULT entry since 2026-08-31 (lario's call after
# --- the measurements below) ------------------------------------------------------------
# Muse Glimmer ships a DFlash drafter (unsloth repo, dflash-kquant.gguf, 1.52 GiB): a 5-layer
# block-diffusion companion that proposes 16-token blocks the main model verifies in one
# pass. Its attention is a 2048 sliding window on EVERY layer, so its KV is a small FIXED
# cost per slot that does not grow with context — the reason it can fit at all here.
# Reported: 3.1x decode on an RTX 5090, 1.5-1.8x on Apple M4/M5 Max; a measured DGX-Spark
# recipe (bandwidth-bound like this card) got 2.5-2.8x with ~18-19% per-token acceptance at
# --spec-draft-n-max 15.
#
# Two caveats from that recipe, both honoured below:
#   * Draft KV must stay f16 (-ctkd/-ctvd) — quantized DRAFT KV collapses acceptance. The
#     TARGET's q8_0 KV is a separate setting and is kept.
#   * In llama.cpp DFlash is NOT output-identical: greedy parity failed 0/10 there despite
#     the model card's "identical quality" claim. Treat it as a different sampler; check
#     quality on agent-shaped prompts before making it the default.
# Fit: the 3x131072 q8_0 entry sits at 17.85 GiB resident; the draft needs ~1.5 GiB weights
# + small KV/buffers, which does not fit in the ~1.65 GiB left. So this entry drops to
# 2 slots x 131072 (frees ~0.85 GiB of KV) to keep the agents' 126976 window intact and
# pays with one concurrent slot. The flags follow the published recipe (-md, --spec-type
# draft-dflash, --spec-draft-n-max 15, --spec-draft-ngl all).
#
# MEASURED 2026-08-31 on this card (same script, same prompts as the 3x131072 q8_0 baseline):
#   resident 19.30 GiB idle, 19.47 GiB peak under 2 x ~120k concurrent (card: 19.98 GiB)
#   decode   code 78.1 tok/s (baseline 33.7, 26% acceptance); prose at temp 1.0 38.8
#            (baseline 33.7, 9.6% — the drafter is weak on free prose); deep-context 100k
#            55.2 (baseline 24.9, 22%); 2-stream code aggregate 80.0 (baseline 54.7)
#   agent    a real Hermes turn (reasoning + one tool call, cold cache) 31s vs 53s
#   quality  temp-0 A/B against the non-DFlash answers: 3 of 4 byte-identical, 4th equivalent
#   caveat   a slot decoding while the OTHER slot prefills 120k tokens starves to ~1 tok/s —
#            llama.cpp interleaves the prefill ubatches; the same happens without DFlash.
# Net: ~2x on code/tool-call decode and ~1.7x on a real agent turn, for one fewer slot and
# ~0.5 GiB of VRAM margin instead of ~2.1.
MUSE_DFLASH_GGUF=/models/gguf/muse-glimmer/dflash-kquant.gguf
MUSE_DFLASH_PARALLEL=2
MUSE_DFLASH_CTX=$(( 131072 * MUSE_DFLASH_PARALLEL ))
MUSE_DFLASH_FLAGS="-md $MUSE_DFLASH_GGUF --spec-type draft-dflash --spec-draft-n-max 15 --spec-draft-ngl all -ctkd f16 -ctvd f16"

# --- Qwen3.8-Flash-Next (Qwen, 2026-08-26) — the Qwen4-architecture preview on the XT ---
# 180B total: 125B LM with 6B active per token, a 51B n-gram embedding (a lookup table the
# architecture DESIGNS to live in system RAM via mmap), and 4B MTP. 48 layers =
# 12 x (3 Gated DeltaNet -> MoE, 1 QSA -> MoE): the 36 DeltaNet layers keep a FIXED state
# per slot (~0.11 GiB: 48 V heads x 128x128) instead of a growing KV cache; only the 12 QSA
# layers (2 KV heads x 256 dim) grow with context — ~12 KiB/token q8_0 (~15 with the
# indexer), about half Muse Glimmer's.
#
# WHY IT FITS (unlike qwen3.6/3.8, ruled out in the header): two-sided math.
#   RAM side: 512 experts x 48 layers (120.9B params) + the 51B n-gram table mmap from
#     /mnt/xfs into page cache. bigcachy has 125 GiB; ~21 GiB is baseline (OS, desktop,
#     Docker fleet), so the budget for CPU-resident model weights is ~80 GiB, leaving
#     >= ~24 GiB headroom. UD-Q3_K_XL's CPU portion is ~79 GiB — inside the budget.
#   GPU side: non-expert weights + shared experts + embed/lm-head (~4.5 GiB at Q3) + the
#     FULL KV pool 4 x 131072 at q8_0 (~7.9 GiB) + compute buffers (~1.8 GiB) ~= 14-15 GiB
#     of 19.5 usable.
# Quant UD-Q3_K_XL (83.8 GiB file, unsloth): 88.3% top-1% accuracy in unsloth's KLD table.
#   Rejected: UD-Q4_K_XL (103.7 GiB, 92.3%) pegs the box at ~120/125 GiB — no headroom;
#   UD-IQ4_XS (87.2 GiB, 89.6%) fits but with ~21 GiB headroom and IQ dequant cost on the
#   CPU-heavy path; 5/6/8-bit (147-175 GiB) are neither RAM-feasible nor sensible downloads.
#   Inside every UD quant the n-gram table stays >=4-bit — random-access lookup, unsloth
#   will not go lower on it — so lower bits only buy LM-quality headroom.
#
# Geometry: 4 slots x 131072 = -c 524288, q8_0 KV. The agents' context_length 126976 =
# 131072 - 4096 drift buffer, unchanged from the muse entries. RESERVED=1 below: one slot
# is opencode's (`xt/agent` sessions) — lario-fleet's agent-bucket cap is slots minus
# reserved, so 3 agents hold warm prefixes and the 4th stays free. A 5th concurrent
# request is the instant 429, as ever.
#
# SPEED EXPECTATION (verify at bring-up; not yet measured on this box): decode is
# RAM-bandwidth-bound — ~2.6B active expert params/token ~= 1.3 GiB read at Q3 against
# ~80 GB/s dual-channel DDR5, so plan on roughly 15-30 tok/s single-stream (vs muse's
# 34.9 / 78.1 with DFlash). MTP (1.3-1.7x, unsloth) needs the fork build
# (danielhanchen/llama.cpp:qwen4exp/mtp, upstream PR 28243) — a follow-up, not this entry.
#
# 256k per slot does NOT fit at 4 slots under the headroom rule: 4 x 262144 = 15.7 GiB of
# KV would not fit beside the GPU weights, and --cache-ram would leave ~8 GiB of RAM
# headroom. Measured follow-up, not a day-one entry: 2 x 262144 (KV stays on the GPU) or
# 4 x 262144 + --cache-ram if the headroom is accepted.
#
# Sampling: Qwen3.8 thinking mode (vendor-recommended), temp-0 A/B pending at bring-up.
# --jinja is already in the common prefix and MANDATORY for the Qwen family (rambles past
# stop tokens without it). Text-only on purpose, like every entry here: no --mmproj.
QWEN38F_SAMPLING="--cache-ram 0 --reasoning-budget 2048 -b 2048 -ub 512 --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0"
QWEN38F_PARALLEL=4
QWEN38F_CTX=$(( 131072 * QWEN38F_PARALLEL ))

# --- model registry: name -> the "-m/-hf ... + sampling" flags (after the common prefix) ---
declare -A MODELS=(
  [muse-glimmer]="-m $MUSE_GGUF -ngl 999 -c $MUSE_CTX --parallel $MUSE_PARALLEL --cache-type-k q8_0 --cache-type-v q8_0 $MUSE_SAMPLING"
  [muse-glimmer-f16]="-m $MUSE_GGUF -ngl 999 -c $MUSE_F16_CTX --parallel $MUSE_F16_PARALLEL $MUSE_SAMPLING"
  [muse-glimmer-dflash]="-m $MUSE_GGUF -ngl 999 -c $MUSE_DFLASH_CTX --parallel $MUSE_DFLASH_PARALLEL --cache-type-k q8_0 --cache-type-v q8_0 $MUSE_DFLASH_FLAGS $MUSE_SAMPLING"
  [qwen38-flash]="-hf unsloth/Qwen3.8-Flash-Next-GGUF:UD-Q3_K_XL -ngl 999 -c $QWEN38F_CTX --parallel $QWEN38F_PARALLEL --cache-type-k q8_0 --cache-type-v q8_0 $QWEN38F_SAMPLING"
)
# first = the default / fresh-clone pick: muse-glimmer-dflash, the MEASURED entry.
# qwen38-flash is appended last on purpose — it is registered and switchable, but a fresh
# clone should land on the geometry this card's numbers were taken with.
ORDER=(muse-glimmer-dflash muse-glimmer muse-glimmer-f16 qwen38-flash)

# = --parallel of the entry. This is what makes llama-swap REJECT the overflow request
# (HTTP 429, immediately) instead of letting llama-server queue it in silence.
declare -A CONCURRENCY=(
  [muse-glimmer]="$MUSE_PARALLEL"
  [muse-glimmer-f16]="$MUSE_F16_PARALLEL"
  [muse-glimmer-dflash]="$MUSE_DFLASH_PARALLEL"
  [qwen38-flash]="$QWEN38F_PARALLEL"
)

# Reserved slots per entry: slots the bucket shares with opencode (the `xt/agent` sessions)
# that lario-fleet must NOT count against the agents. lario-fleet's agent-bucket cap is
# `slots` minus `reserved` — the same pattern as the main bucket's LARIO_FLEET_MAIN_RESERVED.
# 0 on the muse entries (their slots are the agents' private budget, as before); 1 on
# qwen38-flash, whose 4th slot is the opencode reservation.
declare -A RESERVED=(
  [muse-glimmer]=0
  [muse-glimmer-f16]=0
  [muse-glimmer-dflash]=0
  [qwen38-flash]=1
)

# explicit per-model aliases (always on that model, regardless of the toggle)
declare -A BASE_ALIASES=(
  [muse-glimmer]='"muse-glimmer-30b-q4"'
  [muse-glimmer-f16]='"muse-glimmer-30b-q4-f16kv"'
  [muse-glimmer-dflash]='"muse-glimmer-30b-q4-dflash"'
  [qwen38-flash]='"qwen38-flash-q3"'
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

# The slot count of the ACTIVE entry, for callers that budget against it (lario-fleet's
# advisory cap = one warm prompt prefix per enabled agent). Reads the state file only —
# never docker — so it is safe and instant from any script. Fails loudly (exit 1, nothing
# on stdout) when no entry is active or the entry declares no limit, so a caller can fall
# back deliberately instead of parsing garbage.
slots() {
  local cur; cur=$(cat "$STATE" 2>/dev/null || true)
  [ -n "$cur" ] && known "$cur" || { echo "no active agent model (run: $0 <name>)" >&2; return 1; }
  [ -n "${CONCURRENCY[$cur]:-}" ] || { echo "$cur declares no concurrencyLimit" >&2; return 1; }
  echo "${CONCURRENCY[$cur]}"
}

# The opencode-reserved slots of the ACTIVE entry — lario-fleet's agent-bucket cap is
# `slots` minus this. Same read-only contract as slots(): state file only, never docker,
# bare number on stdout, loud failure otherwise.
reserved() {
  local cur; cur=$(cat "$STATE" 2>/dev/null || true)
  [ -n "$cur" ] && known "$cur" || { echo "no active agent model (run: $0 <name>)" >&2; return 1; }
  echo "${RESERVED[$cur]:-0}"
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
  slots)   slots ;;
  reserved) reserved ;;
  config)  [ -n "${2:-}" ] || { echo "usage: $0 config <name>"; exit 1; }
           known "$2" || { echo "unknown model: $2 (have: ${ORDER[*]})"; exit 1; }
           write_config "$2"; echo "$2" > "$STATE"; echo "config written for $2 (container not touched)" ;;
  *)       switch "$1" ;;
esac
