#!/usr/bin/env python3
"""Run the registered eGPU in rootless Podman; never pull or select an iGPU.

Geekom placement of the physical RX 7900 XT through the spare M.2 NVMe slot.
Store and identity come from the placement manifest and the generated registry.
"""
import json
import sys
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import shared.radeon_runtime as radeon

HARDWARE = 'geekom7900xt'


def main():
    placement = json.loads((ROOT/HARDWARE/'placement.json').read_text())
    reg = json.loads((ROOT/HARDWARE/'models.json').read_text())
    if len(sys.argv) != 2 or sys.argv[1] not in ('check', 'run'):
        raise ValueError('use check or run')
    if socket.gethostname().split('.')[0] != reg['host']:
        raise RuntimeError('wrong Radeon owner host')
    store = Path(placement['model_store'])
    if sys.argv[1] == 'run':
        radeon.run(reg, store, HARDWARE)
    radeon.check(reg['aliases'], reg['device_identity'], store)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
