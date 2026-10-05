#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$ROOT"
case "$(hostname -s)" in
 bigcachy)
  [[ -f llama-cpp/agent-config.yaml ]] || ./7900xt/7900xt config muse-glimmer-dflash
  [[ -f rtx5080/config/generated.yaml ]] || ./rtx5080/rtx5080 config ocr
  ./intel/install.sh
  install -m 644 rtx5080/systemd/rtx5080.service "$HOME/.config/systemd/user/rtx5080.service"
  systemctl --user daemon-reload
  systemctl --user start rtx5080.service
  docker compose -f docker-compose.yml -f docker-compose.bigcachy.yml -f docker-compose.intel.yml --profile xt up -d chromadb rag_api agent-llm vision bifrost
  ;;
 l-dev-ai) systemctl --user start llama-swap.service ;;
 *) echo 'Model services belong on bigcachy or l-dev-ai' >&2; exit 1 ;;
esac
