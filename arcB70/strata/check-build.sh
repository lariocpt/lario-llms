#!/usr/bin/env bash
# Run a bounded isolated smoke once the private source build is ready.
set -euo pipefail
strata_private_build=/home/lario/.local/share/strata/build/4b9e05a2a806a3fe24f7b2560d98626c37dade35-b70
strata_repo=/home/lario/Projects/personal/lario-llms
for ((strata_wait=0; strata_wait<120; strata_wait++)); do
    if [[ -f "$strata_private_build/.complete" ]]; then
        exec systemd-run --user --scope --collect --unit=b70-strata-source-256k-3 \
            --property=MemoryMax=88G --property=MemorySwapMax=0 \
            timeout --signal=TERM --kill-after=30s 900s \
            /home/lario/.local/share/strata/venv/bin/python \
            "$strata_repo/arcB70/strata/smoke.py" \
            --engine "$strata_private_build/strata" --context 262144 --slots 3 \
            --rounds 2 --output "$strata_repo/research/benchmarks/20261027-b70-flash/source-256k-3"
    fi
    sleep 5
done
echo 'Private source build did not complete within ten minutes' >&2
exit 1
