#!/usr/bin/env bash
# Warm the selected Geekom alias after native llama-swap startup.
set -eu
curl -fsS --retry 60 --retry-connrefused --retry-delay 5 --max-time 1800 \
 http://127.0.0.1:11434/v1/chat/completions -H 'Content-Type: application/json' \
 -d '{"model":"geekom","messages":[{"role":"user","content":"Reply OK."}],"max_tokens":32,"chat_template_kwargs":{"enable_thinking":false}}' >/dev/null
