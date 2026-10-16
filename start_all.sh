#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$ROOT"
case "$(hostname -s)" in
 bigcachy)
  [[ -f rtx5080/config/generated.yaml ]] || ./rtx5080/rtx5080 config ocr
  ./intel/install.sh
  install -m 644 rtx5080/systemd/rtx5080.service "$HOME/.config/systemd/user/rtx5080.service"
  systemctl --user daemon-reload
  systemctl --user start rtx5080.service
  . "$ROOT/shared/compose-files.sh"
  lario_compose_files "$ROOT"
  enabled_services="$(docker compose "${LARIO_COMPOSE_FILES[@]}" config --services)"
  model_services=(chromadb rag_api vision)
  # Respect the host's profile opt-in, including temporary physical GPU removal.
  # Explicitly naming agent-llm or passing --profile xt would override that choice.
  if [[ $'\n'"$enabled_services"$'\n' == *$'\nagent-llm\n'* ]]; then
   [[ -f llama-cpp/agent-config.yaml ]] || ./7900xt/7900xt config muse-glimmer-dflash
   model_services+=(agent-llm)
   [[ -f "$HOME/.config/lario-admission/7900xt.active.json" ]] && model_services+=(agent-admission)
  fi
  docker compose "${LARIO_COMPOSE_FILES[@]}" up -d "${model_services[@]}"
  ;;
 l-dev-ai) systemctl --user start llama-swap.service ;;
 *) echo 'Model services belong on bigcachy or l-dev-ai' >&2; exit 1 ;;
esac
