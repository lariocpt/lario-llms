#!/usr/bin/env bash
# The owner controller selects the authenticated private backend after admission
# activation. Warming the public port without its consumer key would then fail.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
exec "$ROOT/geekom/geekom" warm
