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
# PER-SLOT context. Note llama-server's -c is the TOTAL pool: for qwen3.6 the launch line
# passes QWEN36_CTX = CTX * QWEN36_PARALLEL, so CTX is what one slot actually gets.
#
# It MUST be > the agents' config.src.yaml context_length, which is pinned at 65536 by a HARD
# FLOOR inside Hermes: below 64000 an agent refuses to start at all — "Model main has a context
# window of N tokens, which is below the minimum 64000 required by Hermes Agent". Lowering the
# agents to 49152 to buy margin was tried on 2026-07-29 and broke every agent's init, so the
# margin has to come from THIS side.
#
# WARNING, replacing the old note here: it advised "step down to 49152 if memory is tight".
# That reads as safe and is not. 49152 on the SERVER silently truncates agents that ask for
# 65536; 49152 on the CLIENT is below Hermes' floor and bricks it. If memory is ever tight,
# cut QWEN36_PARALLEL or the per-model -c — never take this below 65536.
#
# 81920 gives each slot a 16384-token buffer over what agents request. That buffer is needed
# because the client's own token accounting undercounts (tool schemas, chat template): a
# request Hermes believed fit in 65536 arrived as 67292 and was rejected outright, with
# compression never getting a chance to run.
#
# Cost at 81920 (qwen3.6 KV measured at ~70 KiB/token f16 — see QWEN36_PARALLEL):
#   qwen3.6 12 slots x 81920 = 983040 tok ~= 63 GiB KV + 19 weights = ~81 GiB of 105
#   minimax  default slots, q4_0 KV 69.75 KiB/token, on 87 GiB of weights — the tight one.
# If minimax OOMs, give it its own smaller -c in MODELS rather than dropping CTX globally.
CTX=81920

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
# the ~105 GiB GPU pool.
#
# CORRECTED 2026-07-29 — the old note here claimed "KV is 256 KiB/token at f16, so 5 x 65536
# = ~80 GiB, + 17 GiB weights" i.e. ~98 GiB resident. MEASURED on the box with 5 slots live,
# amdgpu GTT reported 40 GiB used of 105 — 17 GiB weights + 0.9 mmproj leaves ~22 GiB of KV
# for 327680 tokens, so real cost is ~70 KiB/token, a 3.6x OVERESTIMATE. The slot budget was
# far more conservative than the hardware needs. Do not re-copy the 256 figure forward.
#
# RAISED 6 -> 10 on 2026-08-05. The six-slot budget assumed ONE session per agent ("4 agents
# plus opencode and cline"). That assumption does not hold: a single Hermes agent opens a
# session per gateway conversation, and timbuk2-repo-knowledge alone ran 4-6 concurrently.
# Measured demand in 10-minute windows on 2026-08-05 00:00-03:30, while the fleet was wedged:
#     01:20   7 sessions   timbuk2x4, pikaboox2, muscledynamixx1
#     01:40   6 sessions   timbuk2x3, pikaboox2, muscledynamixx1
#     03:20   6 sessions   timbuk2x6
# Against 6 slots — of which 2 were meant to be opencode's and cline's — that is permanent
# eviction, and an evicted agent pays a FULL cold prefill at its real working size (50-60k),
# not the 21k the benchmarks used. Prefill is superlinear, measured 2026-08-05 on an idle box:
#     23207 tok   100.0s   (232 tok/s)
#     72905 tok   723.4s   (101 tok/s)
# So a 50-60k cold prefill is 400-600s, which straddles Hermes' stale-stream threshold; the
# stream is killed just short of finishing and the retry starts from zero. That is the whole
# 2026-08-05 outage. The agents are ALSO capped at max_concurrent_sessions: 2 each so this
# budget cannot be blown again from the client side — both halves are needed.
#
# Budget: 5 live agents x 2 sessions = 10, + opencode + cline = 12. Exactly 12 slots.
#
# KV cost is now measured directly rather than estimated. At 10 slots the box reported
# 71 GiB GTT resident; minus ~18.9 GiB of weights + mmproj that is 52.1 GiB of KV across
# 819200 tokens = 66.7 KiB/token — close to the 70 KiB/token figure derived on 2026-07-29,
# so that estimate is confirmed, not merely reused. At 12 slots:
#   12 x 81920 = 983040 tokens x 66.7 KiB = ~63 GiB KV + ~19 weights = ~81 GiB of 105.
# Roughly 24 GiB of headroom. 14 slots would still fit (~92 GiB) but leaves only ~13 —
# too thin to absorb minimax/mistral, which carry 87 and 70 GiB of weights on their own.
#
# Re-measure GTT after any change here before going further. This number has been wrong
# by 3.6x once already (see the 2026-07-29 correction above), and the failure mode is a
# hard OOM on model load, not a graceful degradation.
# lario-fleet's MAX_ACTIVE was raised 3 -> 4 to match.
#
# KV type measured 2026-07-26 (21k-token prompt / 100-token generation):
#     f16   5 slots   cold 68.0s   warm  3.0s   decode 10.0 tok/s   <- chosen
#     q4_0 12 slots   cold 66.6s   warm  4.7s   decode  4.7 tok/s
#     q8_0 10 slots   cold 120.1s  warm 60.7s   decode  1.6 tok/s
#
# f16 is BOTH the highest-fidelity option and the fastest — quantised KV costs a dequant
# on every attention op, and this Vulkan build has no fast q8_0 path at all (the same
# collapse showed up with Q8_0 *weights*, which is why those were reverted too). Do not
# "optimise" this back to a quantised KV to buy slots: it trades quality for slots you do
# not use, and loses speed doing it.
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

# Thinking budget. qwen3.6 is a REASONING model: it emits ALL `reasoning_content` before
# any `content`, and llama-server's --reasoning-budget defaults to -1 (UNRESTRICTED).
# Unbounded, it can spend an agent's entire max_tokens (8192) thinking and return
# finish_reason=length with content='' — an empty answer indistinguishable from a dead
# provider. At ~11 tok/s that is also ~12 minutes of total silence, which trips Hermes'
# stale-stream detector ("no response received for 6 consecutive stale attempts").
# That is what hung pikaboo for 7880s on a 7k-token prompt (2026-07-28) — note the
# prompt was TINY, so this is not a context-pressure failure and raising -c does not fix it.
#
# 2048 leaves generous room to think while guaranteeing ~6k tokens remain for the answer.
# Do NOT set 0 here — that kills thinking for every consumer at once. Per-agent opt-out
# belongs in the agent's own config.src.yaml, via
#   custom_providers[].extra_body.chat_template_kwargs.enable_thinking: false
# (muscledynamix + pikaboo use exactly that; the high-reasoning agents deliberately do not).
#
# `reasoning_effort` does NOT work on this model — verified silently ignored, 594 chars of
# reasoning still emitted with effort: "none". Several agent configs set it and comment that
# it is "worth the extra reasoning"; they are not getting what that says. Use this budget.
QWEN36_THINK_BUDGET=2048


# qwen3.6 gets --cache-reuse: exact-prefix caching already works (verified 2026-08-05 — the
# same 23k prompt went 100.0s cold -> 0.1s warm, 23203/23207 tokens cached), but Hermes places
# its VOLATILE system-prompt tier (memory snapshot, user profile, timestamp) at the end of the
# system prompt, i.e. in the MIDDLE of the full prompt, ahead of the conversation. Any change
# there invalidates every token after it under strict prefix matching. --cache-reuse lets the
# server skip past a short divergence and keep the tail, which is exactly that shape.
# 256 is the chunk threshold, not a memory cost. Drop the flag first if prefill ever
# misbehaves — it is the only change here with a correctness surface.
#
# --cache-ram 0 is what makes keeping --cache-reuse safe. llama-server has a SECOND,
# separate cache: the host-RAM prompt cache (`-cram`, default **8192 MiB — on unless you
# turn it off**), which checkpoints a slot's KV state when that slot is reassigned to a
# different prompt. On this build it ABORTS:
#
#   ggml_abort <- ggml_backend_tensor_get <- llama_context::state_seq_get_data
#               <- server_slot::prompt_save(server_prompt_cache&)
#
# Adding --cache-reuse on 2026-08-05 16:49 changed which slot gets picked and how often a
# prompt is saved, and turned that latent abort into a constant one: the journal covers
# from 2026-07-31 with ZERO "upstream exited unexpectedly", then 13 SIGABRTs in the five
# hours after the flag landed, first at 17:00:49. The llama.cpp binary never changed
# (build 10027, 2026-07-15).
#
# Hermes' auto-COMPACTION is the reliable trigger: it presents a brand-new prompt prefix,
# which is exactly the evict-and-save path. Crash times matched compression attempts in
# the agent logs to the second. From the agent side this is invisible — llama-swap reports
# a 502, or the client just times out — so it reads as "compaction hangs", not "the server
# died". See agents/CLAUDE.md.
#
# 0 disables prompt_save outright while leaving --cache-reuse's in-slot KV shifting alone;
# the two are independent caches. If a future build ever needs the host cache back, verify
# with a summarisation-shaped request (~3k tokens, no max_tokens) before trusting it.
#
# --- model registry: name -> the "-m/-hf ... + sampling" flags (after the common prefix) ---
declare -A MODELS=(
  [minimax]="-m /mnt/AI_Models/gguf/minimax/UD-Q3_K_S/MiniMax-M2.7-UD-Q3_K_S-00001-of-00003.gguf -ngl 999 -c $CTX -b 2048 -ub 512 --cache-type-k q4_0 --cache-type-v q4_0 --temp 1.0 --top-p 0.95 --min-p 0.01 --top-k 40"
  [mistral]="-m /mnt/AI_Models/gguf/mistral3/Q4_K_M/Mistral-Medium-3.5-128B-Q4_K_M-00001-of-00003.gguf -ngl 999 -c $CTX --temp 0.7 --top-p 0.8"
  [qwen3.6]="-hf unsloth/Qwen3.6-27B-GGUF:UD-Q4_K_XL ${QWEN36_MMPROJ:+--mmproj $QWEN36_MMPROJ} -ngl 999 -c $QWEN36_CTX --parallel $QWEN36_PARALLEL --cache-reuse 256 --cache-ram 0 --reasoning-budget $QWEN36_THINK_BUDGET -b 2048 -ub 512 --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0"
  [gemma4]="-hf unsloth/gemma-4-31B-it-GGUF:Q4_K_M -ngl 999 -c $CTX --temp 1.0 --top-p 0.95 --top-k 64"
)
ORDER=(minimax mistral qwen3.6 gemma4)

# Admission control: refuse work rather than silently queue it.
#
# llama-swap's concurrencyLimit caps in-flight requests PER MODEL and returns an error
# past it. Set to the slot count, so a request either gets a slot immediately or is
# rejected — llama-server never builds an internal queue.
#
# This is the fix for the failure mode behind the 2026-08-05 outage. llama.cpp emits
# nothing while a request waits for a slot, and that silence is indistinguishable from a
# dead provider, so every client's stale detector eventually kills the stream. The logs
# are unambiguous: muscledynamix call #43 had a 99% prefix-cache hit — ~642 tokens left
# to prefill — and still took 640.7s. That was almost entirely queue wait, and it is what
# tripped a 600s stale timeout. An immediate error is strictly better: Hermes treats it as
# retryable and backs off, instead of burning the full stale timeout and latching its
# give-up breaker.
#
# NOT a per-client cap. llama-swap cannot tell opencode from cline from an agent — they
# all resolve the `main` alias to this one model instance, and aliases share it. Neither
# opencode nor cline exposes a client-side concurrency setting (checked: no such key in
# opencode.json or its CLI, none in cline's providers.json). Their share of the budget is
# a RESERVATION, not an enforced limit — see QWEN36_PARALLEL. This limit is what stops any
# one of them from turning overuse into a fleet-wide stall.
declare -A CONCURRENCY=(
  [qwen3.6]="$QWEN36_PARALLEL"
)

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
  # Only emitted for models that declare one (see CONCURRENCY) — the others keep
  # llama-swap's default of unlimited.
  [ -n "${CONCURRENCY[$1]:-}" ] && printf '    concurrencyLimit: %s\n' "${CONCURRENCY[$1]}"
  return 0
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
