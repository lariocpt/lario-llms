#!/usr/bin/env bash
# main-model.sh — ONE global toggle for the whole fleet.
# Points every consumer/agent alias (main, orchestrator, qwen-routing, generalist, coder,
# smart, ...) at a single chosen big model, so ALL Hermes agents + OpenCode/Cline switch
# together. No smart/embedding routing.
#
#   ./main-model.sh              fzf MENU of models -> pick -> switch the whole fleet
#   ./main-model.sh <name>       direct switch (minimax|mistral|qwen3.6|gemma4|muse-glimmer|
#                                               muse-glimmer-q8|muse-glimmer-fast)
#   ./main-model.sh show         current active model + what's loaded
#
# Regenerates llama-cpp/config.yaml (deterministic) and llama-swap hot-reloads (-watch-config).
# NO STANDALONE VISION MODEL HERE (removed 2026-07-26). Qwen3-VL used to be served as
# `visual`/`vision`/`image`, but this box is for the big text models — its 124GB unified pool
# is the scarce resource. Vision belongs on bigcachy's RTX 5080 (16GB), where an 8B VL model
# fits with room to spare and does not compete with a 70-88GB main model.
#
# That rule is about a SEPARATE vision service, not about multimodality. The main models keep
# their OWN projectors (qwen3.6 931MB, muse-glimmer 3.85GB) because an agent reasoning over a
# screenshot mid-task cannot be served by a model on another box. Note the 8060S iGPU is slow
# at IMAGE ENCODING specifically — that cost is only paid on requests that carry an image, so
# it does not affect text throughput. Bulk image work still belongs on bigcachy.
#
# To add a model: MODELS + ORDER + BASE_ALIASES. All three are REQUIRED — emit_model()
# expands ${BASE_ALIASES[$1]} with no `:-` default, so a model missing there aborts the whole
# script under `set -u`. (CONCURRENCY is genuinely optional; it is guarded.)
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
# 122880 gives each slot a 16384-token buffer over the 106496 agents request. That buffer is
# needed because the client's own token accounting undercounts (tool schemas, chat template): a
# request Hermes believed fit in 65536 arrived as 67292 and was rejected outright, with
# compression never getting a chance to run. Keep the 16384 gap whenever either side moves.
#
# RAISED 81920 -> 122880 on 2026-08-10, paid for by cutting QWEN36_PARALLEL 12 -> 8. The total
# KV pool (CTX * QWEN36_PARALLEL = 983040) is UNCHANGED, so this costs no memory — it is the
# same cache reshaped from many small windows into fewer large ones. The slot budget was sized
# for 5 live agents and only 2 are up; see QWEN36_PARALLEL.
#
# Cost at 122880 (qwen3.6 KV is exactly 64 KiB/token f16 — derivation under QWEN36_PARALLEL):
#   qwen3.6  8 slots x 122880 = 983040 tok = 60.0 GiB KV + 17.3 weights+mmproj = ~79.6 of 105
#   minimax  default slots, q4_0 KV 69.75 KiB/token, on 87 GiB of weights — the tight one.
# If minimax OOMs, give it its own smaller -c in MODELS rather than dropping CTX globally.
CTX=122880

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
# KV COST IS EXACTLY 64 KiB/token at f16. Derived 2026-08-10 from the GGUF metadata, which
# settles a number that had been estimated three different ways (256, ~70, ~66.7):
#
#   qwen35.block_count            = 64
#   qwen35.full_attention_interval = 4    <- only every 4th layer has a real KV cache
#   qwen35.attention.head_count_kv = 4
#   qwen35.attention.key_length / .value_length = 256 / 256
#
#   16 attention layers x 4 kv_heads x (256 + 256) x 2 bytes = 65536 B = 64.00 KiB/token
#
# The other 48 blocks are SSM/recurrent: constant-size state, INDEPENDENT of context length.
# That is why context is cheap on this model and why the old 256 KiB figure was 4x too high —
# it was this same sum run over all 64 layers instead of the 16 that actually cache.
#
# Useful constants: 1 GiB of KV = 16384 tokens. One 122880-token slot = 7.50 GiB.
# Checked against the live box at 12 x 81920: 60.00 GiB KV + 17.27 weights+mmproj = 77.27,
# measured GTT 80.73 — the 3.46 GiB residual is recurrent state + compute buffers, ~0.29/slot.
#
# RAISED 6 -> 10 on 2026-08-05. The six-slot budget assumed ONE session per agent ("4 agents
# plus opencode and cline"). That assumption does not hold: a single Hermes agent opens a
# session per gateway conversation, and timbuk2-repo-knowledge alone ran 4-6 concurrently.
# Measured demand in 10-minute windows on 2026-08-05 00:00-03:30, while the fleet was wedged:
#     01:20   7 sessions   timbuk2x4, pikaboox2, muscledynamixx1
#     01:40   6 sessions   timbuk2x3, pikaboox2, muscledynamixx1
#     03:20   6 sessions   timbuk2x6
# (timbuk2 and pikaboo were removed from the fleet 2026-08-07 — the measurement stands as
# the reason for the current budget; do not try to reconcile these names with `docker ps`.)
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
# CUT 12 -> 8 on 2026-08-10, to buy context. The 12-slot budget assumed 5 live agents; only
# TWO gateway agents are actually up (muscledynamix-agent, lario-local-linux-agent) with five
# in agents/.fleet-disabled/. Real demand is 2 x 2 sessions + opencode + cline = 6 slots
# against 12 provisioned, so half the KV cache was reserved for agents that do not run.
#
# Budget now: 3 live agents x 2 sessions = 6, + opencode + cline = 8. Exactly 8 slots.
# Today that leaves 2 spare, which absorbs one delegation burst (delegation.max_concurrent_
# children is 2, and is NOT counted in this budget — one session delegating twice claims 3).
#
# The trade is exact and memory-neutral, because -c is a TOTAL pool (see QWEN36_CTX below):
#   before  12 slots x  81920 = 983040 tokens = 60.0 GiB KV  ->  agents got  65536
#   after    8 slots x 122880 = 983040 tokens = 60.0 GiB KV  ->  agents get 106496  (+62.5%)
# Resident falls slightly, to ~79.6 GiB of 105, because there are 4 fewer recurrent states.
#
# What this costs: fewer slots means prefixes are evicted sooner, and an evicted prefill is
# now LARGER. Prefill is superlinear (see the measurements above), so at 106496 the cold case
# extrapolates to ~1660s. The agents' local_stream_stale_timeout was raised 1200 -> 2400 in
# the same change. Do not raise CTX further without re-measuring that curve — memory is not
# the binding constraint here, prefill time is. Memory would allow 4 x 262144 (the model's
# entire trained window) at ~85 GiB; prefill would make it unusable.
#
# Re-measure GTT after any change here before going further. This number has been wrong
# by 4x once already (see the KV derivation above), and the failure mode is a hard OOM on
# model load, not a graceful degradation.
# lario-fleet's MAX_ACTIVE moves with this: 8 slots - 2 (opencode, cline) = 6, / 2 = 3.
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
QWEN36_PARALLEL=8
# CRITICAL: llama-server's -c is the TOTAL context pool, SHARED across --parallel slots — it is
# NOT per-slot. Passing -c 122880 --parallel 8 would give each agent 122880/8 = 15360 tokens,
# and a 21k-token agent prompt is then rejected outright:
#   "request (43907 tokens) exceeds the available context size (15360 tokens)"
# So the total must be scaled by the slot count to give every slot the full CTX.
#   8 slots x 122880 = 983040 tokens x 64 KiB/token (f16) = 60.0 GiB KV, + 17.3 GiB weights.
#
# This multiplication IS the slots-for-context trade. Hold the product at 983040 and you can
# move freely along it at zero memory cost: 12x81920, 10x98304, 8x122880, 6x163840, 4x245760.
# Only pass --parallel explicitly (as qwen3.6 does) if you want that split — with -np absent
# llama.cpp auto-picks slots AND enables a unified KV buffer, where every slot reports the
# full -c instead. That is why minimax/mistral/gemma4 leave it off and still get 81920 each.
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
# (muscledynamix uses exactly that; the high-reasoning agents deliberately do not).
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
# --- Muse Glimmer 30B (Meta, released 2026-08-10) ----------------------------------------
# Registered 2026-08-11 as a second big option alongside qwen3.6. DENSE 30B = 28B text
# decoder + a 2B perception encoder shipped as a separate mmproj.
#
# WHY BOTH: Glimmer wins AGENTIC work decisively (MCP Atlas 75.5 vs qwen3.6's 62.5, plus
# general tool use, search, instruction following) and loses NARROWLY on coding/execution
# (SWE-Bench Verified 76.0 vs 77.2, TerminalBench, OSWorld). Glimmer is the better agent,
# qwen3.6 the better coder. Neither replaces the other — that is why both stay in ORDER.
#
# KV IS CHEAP HERE: 13 KiB/token, ~5x cheaper than qwen3.6's 64 KiB. Derived 2026-08-11
# from the GGUF metadata, same method as the qwen3.6 block above:
#     muse-glimmer.block_count                      = 52
#     muse-glimmer.attention.sliding_window_pattern = 4     <- every 4th layer is full attention
#     muse-glimmer.attention.head_count_kv          = 2
#     muse-glimmer.attention.key_length/.value_length = 128 / 128
#     muse-glimmer.attention.sliding_window         = 2048
#
#     52 / 4 = 13 full-attention layers x 2 kv_heads x (128 + 128) x 2 bytes
#            = 13312 B = 13.00 KiB/token
#
# The other 39 layers are sliding-window, CAPPED at 2048 tokens, so they cost a FIXED
# ~78 MiB per slot no matter how long the context is. 1 GiB of KV = ~80600 tokens.
#
# Because KV is this cheap, each slot gets the model's full NATIVE 131072 window rather than
# the global CTX=122880 that the memory-bound models share, and it still fits easily.
# Predicted vs MEASURED resident (GTT), 2026-08-11 AT 8 SLOTS — the KV derivation checks out
# to within ~2 GiB on all three, which is what makes the 24-slot projection below trustworthy:
#     BF16  51.9 weights + 3.6 mmproj + 13.0 KV + 0.6 SWA = ~69 predicted, 71 measured
#     Q8    30.1 weights + 3.6 mmproj + 13.0 KV + 0.6 SWA = ~47 predicted, 49 measured
#     Q4    14.8 weights + 3.6 mmproj + 13.0 KV + 0.6 SWA = ~32 predicted, 33 measured
#
# At the CURRENT 20 slots (KV 32.5 + SWA 1.5, i.e. 34.0 of per-slot cost):
#     Q4    14.8 weights + 3.6 mmproj + 34.0 = ~53 GiB of 105   <- the active default
#     Q8    30.1 weights + 3.6 mmproj + 34.0 = ~68 GiB of 105
#     BF16  51.9 weights + 3.6 mmproj + 34.0 = ~90 GiB of 105   <- too tight to be safe
# So 20 slots is affordable on Q4 and Q8 but NOT on BF16 — which is why BF16 has its own
# MUSE_BF16_PARALLEL below rather than a comment telling you to remember. At 12 slots BF16 is
# 51.9 + 3.6 + 20.4 = ~76 GiB, comfortably under the pool.
#
# SPEED IS PURELY BANDWIDTH-BOUND — measured 2026-08-11 on build 10367, identical method
# (3 x 200-token generations through llama-swap, `Reasoning strength: low`):
#     BF16  55.7 GB weights   4.05 tok/s   71 GiB resident
#     Q8    32.3 GB weights   7.21 tok/s   49 GiB resident
#     Q4    15.9 GB weights  13.94 tok/s   33 GiB resident
# Scale Q4 by weight size and you PREDICT 6.86 (Q8) and 3.98 (BF16); measured 7.21 and 4.05.
# Decode here is therefore purely bandwidth-bound, and every quant has a HEALTHY Vulkan path
# on this build. Do not go looking for a broken kernel — pick the quant by the tok/s you need.
#
# NOTE this specifically CLEARS UD-Q8_K_XL of the pure-Q8_0 penalty measured for qwen3.6 on
# build 10027 (1.7x slower than its weight ratio, "no fast q8_0 path at all"). Q8_K_XL came in
# slightly BETTER than proportional here, so that warning does not generalise to this quant on
# build 10367. It says nothing about pure Q8_0, which was not retested.
#
# qwen3.6 UD-Q4_K_XL re-measured on build 10367 with the SAME script for comparison:
#     qwen3.6  17.6 GB weights  11.93 tok/s   80 GiB resident
# (It was ~10 tok/s on build 10027, so the rebuild made qwen3.6 ~19% FASTER. That doubles as
# this fleet's validation of build 10367 for the pre-existing models — see GOTCHAS #11.)
#
# So against the model this fleet actually ran on:
#     Muse Q4    FASTER (13.94 vs 11.93) and 47 GiB lighter
#     Muse Q8    40% slower (7.21 vs 11.93) but 31 GiB lighter
#     Muse BF16  3x slower (4.05 vs 11.93) — at 4 tok/s an 8192-token answer takes ~34 min and
#                prefill scales the same way, which runs past the agents' 2400s
#                local_stream_stale_timeout. That is the 2026-08-05 stall shape. Avoid for agents.
#
# NOTE the resident figures are NOT comparable as "model size": qwen3.6's 80 GiB is KV-DOMINATED
# (60 GiB cache vs 17.3 GiB weights) because its KV is 64 KiB/token. Muse is WEIGHT-dominated —
# even BF16 spends only 13 GiB on cache. That is why unquantized Muse (71 GiB) fits in LESS than
# quantized qwen3.6 (80 GiB), and why BF16 qwen3.6 is impossible here (~54 GB weights + 60 GiB KV
# would exceed the 105 GiB pool).
# 131072 is a HARD CEILING, not a tuning knob. The GGUF declares context_length = 131072 and
# ships NO rope-scaling keys at all (only rope.freq_base = 500000). Unsloth's docs claim a
# 262144 maximum, but reaching it means enabling YaRN by hand — untested on this model, and
# a quality risk that would land on every agent at once. Do not raise this without measuring.
MUSE_CTX_PER_SLOT=131072
# RAISED 8 -> 20 on 2026-08-12, alongside max_concurrent_sessions 2 -> 3 on the agent side.
# Slots are the cheap axis on this model: at 13 KiB/token a slot costs 1.70 GiB (1.625 KV +
# 0.076 SWA) against qwen3.6's 7.50 GiB, so 2.5x the eviction headroom costs 20 GiB and still
# lands at ~53 of 105 — far under the 80 GiB qwen3.6 occupied.
#
# Eviction, not raw speed, was the root cause of the 2026-08-05 outage (see QWEN36_PARALLEL):
# an evicted prefix pays a full cold prefill, and that is what tripped the stale detector. The
# old 8-slot budget (3 live agents x 2 sessions + opencode + cline) had ZERO margin for
# delegation bursts, which are NOT counted in it — one session delegating twice claims 3 slots.
#
# Budget at 20, with the agents now at 3 sessions each:
#     3 live agents x 3 sessions = 9,  + opencode + cline = 11 baseline
#     9 spare, which covers 4 concurrent delegation bursts (max_concurrent_children: 2)
#
# Spend headroom on SLOTS, not on context: slots cost only memory, while context costs prefill
# time, which is superlinear and is the actual binding constraint here (agents/CLAUDE.md).
# lario-fleet's MAX_ACTIVE moves with this: 20 - 2 (opencode, cline) = 18, / 2 = 9.
MUSE_PARALLEL=20
# Same TOTAL-pool rule as QWEN36_CTX: -c is shared across --parallel slots, NOT per-slot.
MUSE_CTX=$(( MUSE_CTX_PER_SLOT * MUSE_PARALLEL ))

# BF16 carries 37 GiB more weight than Q4, so it cannot afford 24 slots (~97 of 105 GiB, an
# OOM at load — the failure mode here is a hard abort, not graceful degradation). It gets its
# own slot count so that switching to it is safe WITHOUT remembering to edit anything.
MUSE_BF16_PARALLEL=12
MUSE_BF16_CTX=$(( MUSE_CTX_PER_SLOT * MUSE_BF16_PARALLEL ))

# Vision projector. FIXED path — downloaded with `hf download --local-dir`, so unlike
# QWEN36_MMPROJ there is no snapshot commit-hash to glob past. Guarded LOUDLY on purpose:
# the ${VAR:+--mmproj ...} idiom SILENTLY drops the flag when the file is missing, which
# disables vision with no error anywhere. Warn at config-generation time instead.
MUSE_MMPROJ=/mnt/AI_Models/gguf/muse-glimmer/mmproj-Muse-Glimmer-30B-BF16.gguf
[ -f "$MUSE_MMPROJ" ] || { echo "WARN: muse-glimmer mmproj missing ($MUSE_MMPROJ) — vision disabled" >&2; MUSE_MMPROJ=""; }

# Thinking budget. Glimmer is a REASONING model and hits the SAME empty-answer failure as
# qwen3.6 — verified 2026-08-11 on the smoke test: max_tokens=64 returned content='' with
# finish_reason=length, the whole budget spent on reasoning_content.
#
# Its DOCUMENTED control is a system-prompt directive ("Reasoning strength: low|medium|high|
# xhigh"), NOT a CLI flag — and "low" still emitted 298 chars of reasoning. So the system
# prompt is a preference, not a guarantee; --reasoning-budget is the server-side backstop.
# Keep both. Do not delete this in favour of the system-prompt setting.
MUSE_THINK_BUDGET=2048

# --- model registry: name -> the "-m/-hf ... + sampling" flags (after the common prefix) ---
declare -A MODELS=(
  [minimax]="-m /mnt/AI_Models/gguf/minimax/UD-Q3_K_S/MiniMax-M2.7-UD-Q3_K_S-00001-of-00003.gguf -ngl 999 -c $CTX -b 2048 -ub 512 --cache-type-k q4_0 --cache-type-v q4_0 --temp 1.0 --top-p 0.95 --min-p 0.01 --top-k 40"
  [mistral]="-m /mnt/AI_Models/gguf/mistral3/Q4_K_M/Mistral-Medium-3.5-128B-Q4_K_M-00001-of-00003.gguf -ngl 999 -c $CTX --temp 0.7 --top-p 0.8"
  [qwen3.6]="-hf unsloth/Qwen3.6-27B-GGUF:UD-Q4_K_XL ${QWEN36_MMPROJ:+--mmproj $QWEN36_MMPROJ} -ngl 999 -c $QWEN36_CTX --parallel $QWEN36_PARALLEL --cache-reuse 256 --cache-ram 0 --reasoning-budget $QWEN36_THINK_BUDGET -b 2048 -ub 512 --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0"
  [gemma4]="-hf unsloth/gemma-4-31B-it-GGUF:Q4_K_M -ngl 999 -c $CTX --temp 1.0 --top-p 0.95 --top-k 64"
  # BF16 (unquantized, 55.7 GB in two shards) — the quality-first primary. Sharded, so it
  # uses the explicit -m <first-shard> form like minimax/mistral, not -hf.
  [muse-glimmer]="-m /mnt/AI_Models/gguf/muse-glimmer/BF16/Muse-Glimmer-30B-BF16-00001-of-00002.gguf ${MUSE_MMPROJ:+--mmproj $MUSE_MMPROJ} -ngl 999 -c $MUSE_BF16_CTX --parallel $MUSE_BF16_PARALLEL --cache-reuse 256 --cache-ram 0 --reasoning-budget $MUSE_THINK_BUDGET -b 2048 -ub 512 --temp 1.0 --top-p 0.95 --top-k 64"
  # UD-Q8_K_XL (32.3 GB) — near-lossless middle option. NOTE this is a K-quant MIX, not the
  # pure Q8_0 that was measured 1.7x slower and reverted for qwen3.6 on build 10027; that
  # result does not automatically carry over to this quant on build 10367.
  [muse-glimmer-q8]="-hf unsloth/Muse-Glimmer-30B-GGUF:UD-Q8_K_XL ${MUSE_MMPROJ:+--mmproj $MUSE_MMPROJ} -ngl 999 -c $MUSE_CTX --parallel $MUSE_PARALLEL --cache-reuse 256 --cache-ram 0 --reasoning-budget $MUSE_THINK_BUDGET -b 2048 -ub 512 --temp 1.0 --top-p 0.95 --top-k 64"
  # UD-Q4_K_XL (15.9 GB) — the speed option. Single file, so -hf auto-download applies.
  # Measured 13.94 tok/s on 2026-08-11 (build 10367); FASTER than the ~10 tok/s qwen3.6
  # baseline the agent fleet was tuned against.
  [muse-glimmer-fast]="-hf unsloth/Muse-Glimmer-30B-GGUF:UD-Q4_K_XL ${MUSE_MMPROJ:+--mmproj $MUSE_MMPROJ} -ngl 999 -c $MUSE_CTX --parallel $MUSE_PARALLEL --cache-reuse 256 --cache-ram 0 --reasoning-budget $MUSE_THINK_BUDGET -b 2048 -ub 512 --temp 1.0 --top-p 0.95 --top-k 64"
)
ORDER=(minimax mistral qwen3.6 gemma4 muse-glimmer muse-glimmer-q8 muse-glimmer-fast)

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
  [muse-glimmer]="$MUSE_BF16_PARALLEL"
  [muse-glimmer-q8]="$MUSE_PARALLEL"
  [muse-glimmer-fast]="$MUSE_PARALLEL"
)

# explicit per-model aliases (always on that model, regardless of the toggle)
declare -A BASE_ALIASES=(
  [minimax]='"minimax-m2.7", "ollama/minimax"'
  [mistral]='"mistral-medium-3.5", "ollama/mistral"'
  [qwen3.6]='"qwen-3.6", "ollama/qwen3.6"'
  [gemma4]='"gemma-4", "ollama/gemma4"'
  [muse-glimmer]='"muse-glimmer-30b", "ollama/muse-glimmer"'
  [muse-glimmer-q8]='"muse-glimmer-30b-q8", "ollama/muse-glimmer-q8"'
  [muse-glimmer-fast]='"muse-glimmer-30b-q4", "ollama/muse-glimmer-fast"'
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
