#!/usr/bin/env bash
# Detect the agents' model backend being broken WITHOUT being the reason it stays loaded.
#
# Why this exists: agent-llm inherits exactly the blind spot that hid the vision outage of
# 2026-07-27..08-01 for five days. Its healthcheck is `curl /health && curl /v1/models`, and
# GOTCHAS.md #8 spells out that both answer 200 no matter what state llama-swap's upstreams
# are in — the container reports "Up (healthy)" through a model that cannot load at all.
# scripts/vision-monitor.sh is the pattern; this is the same idea with one endpoint's worth
# of difference, noted below.
#
# What is CHEAPER to check here than on vision:
#   agent-llm runs `ttl: 0` — the model is meant to be resident permanently, not swapped in
#   per request. So `/running` being empty is a REAL failure signal on this service, where on
#   vision it is ambiguous (idle and broken both look like []). That makes the common case
#   detectable for free, and the active probe a backstop rather than the primary check.
#
# What is RISKIER here than on vision:
#   the DFlash entry sits at ~19.5 GiB of the card's 19.98 GiB (agent-model.sh records the
#   measurement). There is ~0.5 GiB of margin, so an allocation failure on load is a live
#   possibility rather than a theoretical one, and it is scanned for by name below.
#
# Exit codes: 0 healthy, 1 unhealthy (systemd records the failure), 2 script/config error.
# Set AGENT_LLM_ALERT_CMD to route failures somewhere; it receives the summary on stdin.
# Left unset deliberately — this repo has no notifier to reuse.

set -uo pipefail

CONTAINER="${AGENT_LLM_CONTAINER:-agent-llm}"
ENDPOINT="${AGENT_LLM_ENDPOINT:-http://127.0.0.1:11436}"
MODEL="${AGENT_LLM_MODEL:-agent}"
ACTIVE_PROBE_INTERVAL="${AGENT_LLM_ACTIVE_PROBE_INTERVAL:-3600}"  # seconds; 0 disables
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/agent-llm-monitor"
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

  # Catches a config that no longer parses or lists anything. Deliberately NOT a check for
  # `$MODEL`: llama-swap's /v1/models returns model NAMES only — muse-glimmer, -dflash, -f16 —
  # and never the aliases, so grepping it for `agent` fails 100% of the time on a healthy
  # service. (This script's first run did exactly that.) The only thing that proves the alias
  # resolves is sending it, which is what the active probe below does.
  if ! curl -fsS -m 10 "$ENDPOINT/v1/models" 2>/dev/null | grep -q '"id"'; then
    problems+=("$ENDPOINT/v1/models listed no models — config missing or unparseable")
  fi

  # The check vision cannot make. ttl: 0 means the active entry should be resident from the
  # moment llama-swap starts it and never unload, so an empty /running here means the upstream
  # died or never came up — not that nobody has asked for it lately.
  running=$(curl -fsS -m 10 "$ENDPOINT/running" 2>/dev/null)
  if [[ -z "$running" ]]; then
    problems+=("$ENDPOINT/running did not answer")
  elif ! grep -q '"state":"ready"' <<<"$running"; then
    problems+=("no upstream in state=ready — with ttl: 0 the model should always be resident")
  fi
fi

# ---------- passive: upstream failures since last run ----------
# Same two fingerprints as vision-monitor, for the same reason — catching only the first is
# how the 2026-08-06 outage hid:
#   "exited prematurely"   — llama-server died during STARTUP (here: most likely the ~0.5 GiB
#                            VRAM margin, or the draft model failing to allocate).
#   "exited unexpectedly"  — loaded fine, then died mid-request.
since_arg="30m"
if [[ -r "$LAST_SCAN" ]]; then
  saved=$(<"$LAST_SCAN")
  [[ -n "$saved" ]] && since_arg="$saved"
fi
now_rfc3339=$(date -u +%Y-%m-%dT%H:%M:%SZ)

if docker inspect -f '{{.State.Running}}' "$CONTAINER" &>/dev/null; then
  starts=$(docker logs "$CONTAINER" --since "$since_arg" 2>&1 | grep -c "exited prematurely" || true)
  starts=${starts:-0}
  if (( starts > 0 )); then
    problems+=("$starts upstream start failure(s) since $since_arg — model is failing to load")
  fi

  runtime=$(docker logs "$CONTAINER" --since "$since_arg" 2>&1 | grep -c "exited unexpectedly" || true)
  runtime=${runtime:-0}
  if (( runtime > 0 )); then
    problems+=("$runtime upstream runtime crash(es) since $since_arg — model loads but dies mid-request")
  fi

  if (( starts > 0 || runtime > 0 )); then
    note "--- recent llama-swap errors ---"
    docker logs "$CONTAINER" --since "$since_arg" 2>&1 \
      | grep -iE "exited prematurely|exited unexpectedly|out of memory|failed to allocate|hipMalloc|ggml_backend" \
      | tail -5
  fi
fi
printf '%s' "$now_rfc3339" > "$LAST_SCAN"

# ---------- active: real inference, rate-limited ----------
# Cheaper than vision's equivalent: ttl: 0 keeps this model resident anyway, so the probe
# pays for decode only and pins nothing that was not already pinned. It is still rate-limited,
# because it takes a slot — and there are only 2 under the DFlash entry, so a probe firing
# during real agent traffic costs half the fleet's concurrency for its duration.
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
  # This probe carries two jobs, not one. It proves the weights are loaded and the sampler
  # runs — and, because it addresses the service by ALIAS, it is also the only check here
  # that proves `$MODEL` still resolves to something. An alias broken by a bad regenerate
  # therefore surfaces within ACTIVE_PROBE_INTERVAL rather than immediately; that is the
  # price of llama-swap not advertising aliases anywhere, and an hour beats five days.
  #
  # max_tokens is 1 because what is being proven is liveness, not answer quality. Generous
  # timeout regardless: a cold start pays a 14.8 GiB load plus the drafter before answering.
  body=$(printf '{"model":"%s","max_tokens":1,"messages":[{"role":"user","content":"ok"}]}' "$MODEL")
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 300 \
           -X POST "$ENDPOINT/v1/chat/completions" \
           -H 'Content-Type: application/json' -d "$body" 2>/dev/null)
  if [[ "$code" != "200" ]]; then
    problems+=("active completion probe failed (HTTP ${code:-none}) — model cannot serve")
  else
    date +%s > "$LAST_ACTIVE"
  fi
fi

# ---------- report ----------
if (( ${#problems[@]} > 0 )); then
  summary="agent-llm monitor FAILED at $now_rfc3339"$'\n'
  for p in "${problems[@]}"; do summary+="  - $p"$'\n'; done
  note "$summary"
  if [[ -n "${AGENT_LLM_ALERT_CMD:-}" ]]; then
    printf '%s' "$summary" | eval "$AGENT_LLM_ALERT_CMD" || note "(alert command failed)"
  fi
  exit 1
fi

note "agent-llm ok at $now_rfc3339 (active probe: $( ((run_active==1)) && echo run || echo skipped ))"
exit 0
