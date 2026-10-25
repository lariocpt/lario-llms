#!/usr/bin/env bash
# Compatibility entrypoint; hardware registry owns model configuration.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
exec "$ROOT/geekom7900xt/geekom7900xt" "$@"
