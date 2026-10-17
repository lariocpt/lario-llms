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
  if [[ $'\n'"$enabled_services"$'\n' == *$'\nradeon-forwarder\n'* ]]; then
   model_services+=(radeon-forwarder)
  fi
  docker compose "${LARIO_COMPOSE_FILES[@]}" up -d "${model_services[@]}"
  ;;
 l-dev-ai) systemctl --user start llama-swap.service ;;
 cachyos-mini-mobile) systemctl --user start lario-admission@7900xt.service 7900xt.service ;;
 *) echo 'Unknown model host' >&2; exit 1 ;;
esac
