#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
[[ $(hostname -s) == bigcachy ]] || { echo 'Intel services belong on bigcachy' >&2; exit 1; }
[[ $(findmnt -n -o FSTYPE -T /mnt/xfs/AI_Models) == xfs ]] || { echo 'XFS model mount missing' >&2; exit 1; }
mkdir -p "$HOME/.config/systemd/user"
install -m 644 "$ROOT/intel/systemd/lario-intel@.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
if (( $# == 0 )); then set -- embedding asr translation tts; fi
for service in "$@"; do
  systemctl --user enable --now "lario-intel@$service.service"
done
