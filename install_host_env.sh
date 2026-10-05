#!/usr/bin/env bash
# Client configuration is owned by machine-setup; never inject legacy providers here.
set -euo pipefail
SETUP="$HOME/Projects/personal/machine-setup/setup.sh"
[[ -x "$SETUP" ]] || { echo "machine-setup/setup.sh is required" >&2; exit 1; }
exec "$SETUP" --agents "$@"
