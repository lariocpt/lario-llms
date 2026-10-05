#!/usr/bin/env bash
# Monitor the selected RTX profile without switching it or reserving GPU memory.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
exec python3 "$ROOT/rtx5080/monitor.py"
