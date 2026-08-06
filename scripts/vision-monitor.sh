#!/usr/bin/env bash
# Detect the vision service being broken WITHOUT being the reason it stays loaded.
#
# Why this exists: between 2026-07-27 and 2026-08-01 the vision model failed to load on
# every single request (CUDA OOM on the KV cache) and nothing noticed for five days. The
# container reported "Up (healthy)" the whole time, because the healthcheck inherited from
# ghcr.io/ggml-org/llama.cpp was written for llama-server's own /health, while the entrypoint
# is overridden to llama-swap — a different program that answers 200 on that path no matter
# what state its upstreams are in. 81 failed model starts and 76 failed agent calls went
# unreported.
#
# What can and cannot be checked cheaply:
#   /health      — llama-swap liveness only. Always 200. Useless for this failure.
#   /v1/models   — reads the config; 200 even when the model cannot possibly load.
#   /running     — [] when idle AND [] when broken. Cannot distinguish the two.
#   /metrics     — host CPU/RAM/load telemetry only. No per-model request or error counters.
# So there is no free endpoint that proves the model can serve. The only proof is a real
# inference, and that costs an 8.5GB load which `ttl: 900` in vision-config.yaml deliberately
# avoids holding (the 5080 is shared with rag_api's bge-m3).
#
# Hence two tiers:
#   PASSIVE (every run, free) — scan llama-swap's own log for upstream start failures since
#     the last run. This is what catches the real outage: it fires the first time genuine
#     traffic fails, which in the 2026-07-27 case would have been within minutes instead of
#     five days. Costs nothing and pins nothing.
#   ACTIVE (rate-limited, default 12h) — one real 1x1 image completion, to catch a service
#     that is broken but idle, before an agent hits it. At 12h this loads the model twice a
#     day for the 15 min its ttl keeps it resident (~2% duty cycle), which is why the
#     interval is long and configurable rather than tied to the timer's own cadence.
#
# Exit codes: 0 healthy, 1 unhealthy (systemd records the failure), 2 script/config error.
# Set VISION_ALERT_CMD to route failures somewhere (Discord, ntfy, mail); it receives the
# failure summary on stdin. Left unset deliberately — this repo has no notifier to reuse.

set -uo pipefail

CONTAINER="${VISION_CONTAINER:-vision}"
ENDPOINT="${VISION_ENDPOINT:-http://127.0.0.1:11435}"
MODEL="${VISION_MODEL:-qwen3-vl}"
ACTIVE_PROBE_INTERVAL="${VISION_ACTIVE_PROBE_INTERVAL:-43200}"  # seconds; 0 disables
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/vision-monitor"
LAST_SCAN="$STATE_DIR/last-scan"       # RFC3339 watermark for the passive log scan
LAST_ACTIVE="$STATE_DIR/last-active"   # epoch seconds of the last active probe

mkdir -p "$STATE_DIR" || exit 2

problems=()
note() { printf '%s\n' "$*"; }

# ---------- liveness ----------
if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -q true; then
  problems+=("container '$CONTAINER' is not running")
else
  if ! curl -fsS -m 10 "$ENDPOINT/health" >/dev/null 2>&1; then
    problems+=("llama-swap not answering on $ENDPOINT/health")
  fi
  # Catches the model being renamed or dropped from vision-config.yaml. Cheap, and a
  # genuine failure mode — but note it stays 200 when the model cannot load, which is
  # exactly why it is not sufficient on its own.
  if ! curl -fsS -m 10 "$ENDPOINT/v1/models" 2>/dev/null | grep -q "\"$MODEL\""; then
    problems+=("model '$MODEL' not listed by $ENDPOINT/v1/models")
  fi
fi

# ---------- passive: upstream failures since last run ----------
# Two distinct fingerprints, and catching only the first is how the 2026-08-06 outage
# hid for five days:
#
#   "upstream command exited prematurely"  — llama-server died during STARTUP. The OOM
#                                            outage of 2026-07-27..08-01.
#   "upstream exited unexpectedly"         — llama-server loaded fine, then died mid-request.
#                                            The image-encoder crash of 2026-08-05..08-06.
#
# The second shape is nastier: the model starts, /health and /v1/models both answer 200,
# the container stays green, and only the caller sees a 502. Nothing here noticed, and
# muscledynamix-agent recorded "vision down, waiting on user" for five days while every
# text request through the same endpoint kept succeeding.
since_arg="30m"
if [[ -r "$LAST_SCAN" ]]; then
  saved=$(<"$LAST_SCAN")
  [[ -n "$saved" ]] && since_arg="$saved"
fi
now_rfc3339=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if docker inspect -f '{{.State.Running}}' "$CONTAINER" &>/dev/null; then
  # grep -c exits 1 on no match; || true keeps that from aborting the run.
  starts=$(docker logs "$CONTAINER" --since "$since_arg" 2>&1 \
            | grep -c "exited prematurely" || true)
  starts=${starts:-0}
  if (( starts > 0 )); then
    problems+=("$starts upstream start failure(s) since $since_arg — model is failing to load")
  fi

  # Runtime deaths. Reported separately from start failures because the fix is a different
  # one: a start failure means it cannot allocate at load, a runtime death means it ran out
  # mid-request — for images, the mtmd encoder batch (--mtmd-batch-max-tokens).
  runtime=$(docker logs "$CONTAINER" --since "$since_arg" 2>&1 \
            | grep -c "exited unexpectedly" || true)
  runtime=${runtime:-0}
  if (( runtime > 0 )); then
    problems+=("$runtime upstream runtime crash(es) since $since_arg — model loads but dies mid-request (image encoder?)")
  fi

  if (( starts > 0 || runtime > 0 )); then
    note "--- recent llama-swap errors ---"
    docker logs "$CONTAINER" --since "$since_arg" 2>&1 \
      | grep -iE "exited prematurely|exited unexpectedly|out of memory|failed to allocate|cudaMalloc" \
      | tail -5
  fi
fi
printf '%s' "$now_rfc3339" > "$LAST_SCAN"

# ---------- active: real inference, rate-limited ----------
run_active=0
if (( ACTIVE_PROBE_INTERVAL > 0 )) && (( ${#problems[@]} == 0 )); then
  now_epoch=$(date +%s)
  last=0
  [[ -r "$LAST_ACTIVE" ]] && last=$(<"$LAST_ACTIVE") && last=${last:-0}
  if (( now_epoch - last >= ACTIVE_PROBE_INTERVAL )); then
    run_active=1
  fi
fi

if (( run_active == 1 )); then
  # The probe image must be BIG. This used to send a 1x1 px PNG, on the reasoning that it
  # was "the smallest input that still exercises the multimodal projector path". That was
  # wrong, and it is why this script reported healthy throughout the 2026-08-06 outage:
  # measured on that broken config, 1x1 and 0.30 MP both answered fine while 1.9 MP and up
  # segfaulted the server every time. The encoder allocation scales with PIXELS, so a tiny
  # image proves only that the projector is wired, never that it can allocate.
  #
  # 1536x1536 = 2.4 MP sits above that observed cliff. Solid colour keeps it ~9KB on the
  # wire while still costing full-size preprocessing, because image tokens come from
  # dimensions, not file size.
  px=$(python3 -c "
import base64,io
from PIL import Image
b=io.BytesIO(); Image.new('RGB',(1536,1536),(96,120,160)).save(b,'PNG',optimize=True)
print(base64.b64encode(b.getvalue()).decode())" 2>/dev/null)

  if [[ -z "$px" ]]; then
    # Deliberately a problem, not a silent skip. A probe that cannot build its own input
    # proves nothing, and "no news" from this script is read as "vision is fine".
    problems+=("active probe could not generate its test image (need python3 + Pillow) — probe did NOT run")
  else
    body=$(printf '{"model":"%s","max_tokens":1,"messages":[{"role":"user","content":[{"type":"text","text":"ok"},{"type":"image_url","image_url":{"url":"data:image/png;base64,%s"}}]}]}' "$MODEL" "$px")
    # Generous timeout: a cold start pays a model load before it answers.
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 300 \
             -X POST "$ENDPOINT/v1/chat/completions" \
             -H 'Content-Type: application/json' -d "$body" 2>/dev/null)
    if [[ "$code" != "200" ]]; then
      problems+=("active image probe failed (HTTP ${code:-none}) — model cannot serve images")
    else
      date +%s > "$LAST_ACTIVE"
    fi
  fi
fi

# ---------- report ----------
if (( ${#problems[@]} > 0 )); then
  summary="vision monitor FAILED at $now_rfc3339"$'\n'
  for p in "${problems[@]}"; do summary+="  - $p"$'\n'; done
  note "$summary"
  if [[ -n "${VISION_ALERT_CMD:-}" ]]; then
    printf '%s' "$summary" | eval "$VISION_ALERT_CMD" || note "(alert command failed)"
  fi
  exit 1
fi

note "vision ok at $now_rfc3339 (active probe: $( ((run_active==1)) && echo run || echo skipped ))"
exit 0
