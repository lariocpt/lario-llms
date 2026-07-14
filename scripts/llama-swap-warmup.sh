#!/usr/bin/env bash
# Preload the resident set into llama-swap so the box comes up hot.
# Called (backgrounded) from the llama-swap.service ExecStartPost. Warms the always-on vision
# model + the CURRENT global main (via the `main` alias, which main-model.sh points at the
# active model). Safe to run by hand anytime.
set -u
SWAP="http://127.0.0.1:11434"
for m in qwen3-vl main; do
  curl -s --retry 60 --retry-connrefused --retry-delay 5 -m 1800 \
    "$SWAP/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":1}" \
    >/dev/null 2>&1
done
