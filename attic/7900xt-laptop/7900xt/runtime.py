#!/usr/bin/env python3
"""Run the registered eGPU in rootless Podman; never pull or select an iGPU."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import shared.radeon_runtime as radeon

HARDWARE = '7900xt'
STORE = Path('/mnt/xfs/AI_Models')


def main():
    reg = json.loads((ROOT/HARDWARE/'models.json').read_text())
    if len(sys.argv) != 2 or sys.argv[1] not in ('check', 'run'):
        raise ValueError('use check or run')
    if sys.argv[1] == 'run':
        radeon.run(reg, STORE, HARDWARE)
    radeon.check(reg['aliases'], reg['device_identity'], STORE)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
