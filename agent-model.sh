#!/usr/bin/env bash
# Compatibility entrypoint; hardware registry owns model configuration.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
exec "$ROOT/7900xt/7900xt" "$@"
